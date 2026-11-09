"""
Reddit post scheduler module.
Coordinates scraping Reddit subreddits for new videos, downloading them via yt-dlp,
inspecting the Telegram channel's existing schedule, and scheduling 3 videos per day
starting at midnight without captions using Telegram's native scheduling.
"""
import os
import shutil
import asyncio
import logging
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from telethon.errors import (
    FloodWaitError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    RPCError
)

from src.config import (
    DEFAULT_REDDIT_SUBREDDITS,
    DEFAULT_REDDIT_CHECK_INTERVAL_SECONDS,
    DEFAULT_REDDIT_POSTS_PER_DAY,
    DEFAULT_REDDIT_DAILY_SLOTS,
    REDDIT_PENDING_DIR,
    REDDIT_SCHEDULED_DIR,
    MIN_SCHEDULE_DELAY_SECONDS,
    DATE_FORMAT_DISPLAY,
    logger
)
from src.reddit_feed import (
    fetch_subreddit_posts,
    load_seen_posts,
    save_seen_posts,
    filter_new_posts
)
from src.reddit_downloader import (
    download_reddit_videos,
    get_pending_videos
)
from src.post_scheduler import list_scheduled_posts
from src.video_optimizer import optimize_video_for_upload, cleanup_temp_file


def get_channel_schedule_summary(scheduled_posts: List[Dict[str, Any]]) -> Dict[date, List[datetime]]:
    """
    Group scheduled posts by local calendar date.

    Args:
        scheduled_posts: List of scheduled posts from list_scheduled_posts()

    Returns:
        Dict[date, List[datetime]]: Mapping from date to list of scheduled datetimes
    """
    grouped = defaultdict(list)
    for p in scheduled_posts:
        dt = p.get('date')
        if isinstance(dt, datetime):
            local_dt = dt.astimezone()
            grouped[local_dt.date()].append(local_dt)

    # Sort datetimes for each day
    for d in grouped:
        grouped[d].sort()

    return grouped


def calculate_available_slots(
    existing_schedule: Dict[date, List[datetime]],
    count_needed: int,
    start_date: Optional[date] = None,
    daily_slots: Optional[List[Tuple[int, int]]] = None,
    posts_per_day: int = DEFAULT_REDDIT_POSTS_PER_DAY,
    now_dt: Optional[datetime] = None
) -> List[datetime]:
    """
    Find the next available scheduling slot datetimes for videos.
    Starts at midnight (00:00).
    If a day already has scheduled posts reaching the daily quota, moves forward to later days.

    Args:
        existing_schedule: Dict of date -> list of scheduled datetimes in channel
        count_needed: Number of video slots needed
        start_date: Earliest date to begin scheduling (defaults to tomorrow)
        daily_slots: List of (hour, minute) tuples for daily slots (default: 00:00, 08:00, 16:00)
        posts_per_day: Max videos per calendar day (default: 3)
        now_dt: Baseline datetime for 'now' check

    Returns:
        List[datetime]: List of future datetimes for scheduling the new videos
    """
    if count_needed <= 0:
        return []

    slots_def = daily_slots or DEFAULT_REDDIT_DAILY_SLOTS
    now = now_dt or datetime.now().astimezone()
    local_tz = now.tzinfo

    # Earliest candidate day: tomorrow if not explicitly provided
    if start_date is None:
        candidate_day = now.date() + timedelta(days=1)
    else:
        candidate_day = max(start_date, now.date())

    available_slots: List[datetime] = []

    while len(available_slots) < count_needed:
        existing_on_day = existing_schedule.get(candidate_day, [])

        # If day is already full (has posts_per_day or more), move forward to next day
        if len(existing_on_day) >= posts_per_day:
            candidate_day += timedelta(days=1)
            continue

        # Check each predefined daily slot for this day
        for hour, minute in slots_def:
            slot_dt = datetime(
                candidate_day.year,
                candidate_day.month,
                candidate_day.day,
                hour,
                minute,
                0,
                tzinfo=local_tz
            )

            # Slot must be in the future
            if slot_dt <= now + timedelta(seconds=MIN_SCHEDULE_DELAY_SECONDS):
                continue

            # Check if this slot conflicts with an existing post (within 45 minutes)
            is_occupied = any(
                abs((slot_dt - ex).total_seconds()) < 45 * 60
                for ex in existing_on_day
            )

            if not is_occupied:
                available_slots.append(slot_dt)
                existing_on_day.append(slot_dt)

                if len(available_slots) >= count_needed:
                    break

                # If this day now reached posts_per_day, stop filling this day
                if len(existing_on_day) >= posts_per_day:
                    break

        candidate_day += timedelta(days=1)

    return available_slots


async def schedule_video_file(
    client: Any,
    entity: Any,
    video_path: str,
    schedule_time: datetime
) -> Tuple[bool, Optional[str]]:
    """
    Upload and schedule a video to Telegram without caption.
    Automatically applies 720p optimization via FFmpeg for videos/GIFs > 5MB.

    Args:
        client: Telethon client
        entity: Channel entity or ID
        video_path: Local path to the video file
        schedule_time: Target scheduled datetime

    Returns:
        Tuple[bool, Optional[str]]: (Success, error message if any)
    """
    if not os.path.exists(video_path):
        return False, f"File not found: {video_path}"

    upload_path, is_temp = optimize_video_for_upload(video_path)
    try:
        try:
            await client.send_file(
                entity,
                file=upload_path,
                caption=None,  # No caption per user request
                schedule=schedule_time,
                supports_streaming=True
            )
        except FloodWaitError as e:
            logger.warning(f"Telegram flood wait of {e.seconds}s encountered.")
            await asyncio.sleep(e.seconds)
            await client.send_file(
                entity,
                file=upload_path,
                caption=None,
                schedule=schedule_time,
                supports_streaming=True
            )

        # If upload succeeded and the file was optimized, replace the pending file
        # with the optimized 720p version so the scheduled folder gets the 720p version
        if is_temp and os.path.exists(upload_path):
            try:
                shutil.move(upload_path, video_path)
                is_temp = False
            except Exception as move_err:
                logger.warning(f"Could not replace pending video with optimized version: {move_err}")

        return True, None
    except (ChatAdminRequiredError, ChatWriteForbiddenError) as e:
        err = f"Permission error posting to channel: {e}"
        logger.error(err)
        return False, err
    except Exception as e:
        err = f"Failed scheduling video {video_path}: {e}"
        logger.error(err)
        return False, err
    finally:
        if is_temp:
            cleanup_temp_file(upload_path)


async def run_reddit_automation_once(
    client: Any,
    db: dict,
    db_path: str,
    subreddits: Optional[List[str]] = None,
    channel_entity: Any = None
) -> Dict[str, Any]:
    """
    Execute a single check-and-schedule cycle:
    1. Resolve target channel
    2. Check Reddit subreddits for new posts
    3. Filter against seen posts and download new videos
    4. Inspect channel schedule
    5. Schedule pending videos for 3 slots/day starting at midnight
    6. Move scheduled videos to archive

    Returns:
        Dict[str, Any]: Execution summary
    """
    active_channel = channel_entity or db.get('active_channel')
    if not active_channel:
        logger.error("No active channel selected in database.")
        return {'success': False, 'error': 'No active channel selected'}

    entity_id = active_channel['id'] if isinstance(active_channel, dict) else active_channel

    try:
        channel_target = await client.get_entity(entity_id)
    except Exception as e:
        logger.warning(f"Could not resolve entity object for {entity_id}: {e}")
        channel_target = entity_id

    summary = {
        'success': True,
        'posts_fetched': 0,
        'new_posts_found': 0,
        'downloaded': 0,
        'scheduled': 0,
        'errors': []
    }

    # Step 1: Fetch posts from Reddit
    subs = subreddits or DEFAULT_REDDIT_SUBREDDITS
    logger.info(f"Checking Reddit for new video posts across: {', '.join(subs)}")
    fetched = fetch_subreddit_posts(subs)
    summary['posts_fetched'] = len(fetched)

    # Step 2: Filter new posts
    seen_ids = load_seen_posts()
    new_posts = filter_new_posts(fetched, seen_ids)
    summary['new_posts_found'] = len(new_posts)
    logger.info(f"Found {len(new_posts)} new video posts to process.")

    # Step 3: Download new videos
    if new_posts:
        video_urls = [p['video_url'] for p in new_posts if p.get('video_url')]
        downloaded_files = download_reddit_videos(video_urls, output_dir=REDDIT_PENDING_DIR)
        summary['downloaded'] = len(downloaded_files)

        # Mark all processed post IDs as seen
        for p in new_posts:
            seen_ids.add(p['id'])
        save_seen_posts(seen_ids)

    # Step 4: Gather all pending videos waiting to be scheduled
    pending_videos = get_pending_videos(REDDIT_PENDING_DIR)
    if not pending_videos:
        logger.info("No pending videos to schedule.")
        return summary

    logger.info(f"{len(pending_videos)} video(s) pending scheduling.")

    # Step 5: Inspect channel schedule
    existing_scheduled = await list_scheduled_posts(client, channel_target)
    schedule_by_day = get_channel_schedule_summary(existing_scheduled)

    logger.info(f"Channel currently has {len(existing_scheduled)} scheduled posts across {len(schedule_by_day)} days.")

    # Step 6: Calculate target slots (3 per day, 00:00, 08:00, 16:00, moving forward for full days)
    slots = calculate_available_slots(
        existing_schedule=schedule_by_day,
        count_needed=len(pending_videos),
        daily_slots=DEFAULT_REDDIT_DAILY_SLOTS,
        posts_per_day=DEFAULT_REDDIT_POSTS_PER_DAY
    )

    # Step 7: Schedule each video into its slot
    os.makedirs(REDDIT_SCHEDULED_DIR, exist_ok=True)

    for video_path, slot_dt in zip(pending_videos, slots):
        success, err = await schedule_video_file(
            client=client,
            entity=channel_target,
            video_path=video_path,
            schedule_time=slot_dt
        )

        if success:
            summary['scheduled'] += 1
            filename = os.path.basename(video_path)
            logger.info(f"Scheduled '{filename}' for {slot_dt.strftime('%Y-%m-%d %H:%M:%S')}")

            # Move to scheduled folder
            dest_path = os.path.join(REDDIT_SCHEDULED_DIR, filename)
            if os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(video_path, dest_path)

            # Short delay between Telegram uploads
            await asyncio.sleep(2)
        else:
            summary['errors'].append(f"{os.path.basename(video_path)}: {err}")

    return summary


async def run_reddit_automation_daemon(
    client: Any,
    db: dict,
    db_path: str,
    interval_seconds: int = DEFAULT_REDDIT_CHECK_INTERVAL_SECONDS,
    stop_event: Optional[asyncio.Event] = None
):
    """
    Run the Reddit-to-Telegram automation loop every N seconds (default: 2 hours).
    Can be gracefully stopped using stop_event.
    """
    logger.info(f"Starting Reddit automation daemon (interval: {interval_seconds // 3600}h).")
    event = stop_event or asyncio.Event()

    while not event.is_set():
        try:
            logger.info("--- Starting Reddit automation check ---")
            res = await run_reddit_automation_once(client, db, db_path)
            logger.info(
                f"Cycle complete: {res.get('new_posts_found', 0)} new posts, "
                f"{res.get('downloaded', 0)} downloaded, {res.get('scheduled', 0)} scheduled."
            )
        except Exception as e:
            logger.error(f"Error during Reddit automation cycle: {e}")

        try:
            logger.info(f"Sleeping for {interval_seconds} seconds until next check...")
            await asyncio.wait_for(event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass  # Normal timeout, proceed to next iteration

    logger.info("Reddit automation daemon stopped.")


async def display_channel_schedule_calendar(client: Any, entity_id: Any):
    """
    Display a clear breakdown of the channel's scheduled posts by date,
    showing filled slots (00:00, 08:00, 16:00) and whether days are full or have openings.
    """
    posts = await list_scheduled_posts(client, entity_id)
    if not posts:
        print("\nNo posts currently scheduled in this channel.")
        now = datetime.now().astimezone()
        tomorrow = now.date() + timedelta(days=1)
        print(f"All slots starting from tomorrow ({tomorrow}) are currently free.")
        return

    grouped = get_channel_schedule_summary(posts)
    print("\n" + "=" * 65)
    print(f"{'Date':<12} | {'Count':<5} | {'Scheduled Times':<25} | {'Status'}")
    print("-" * 65)
    for d in sorted(grouped.keys()):
        times_list = grouped[d]
        times_str = ", ".join(t.strftime("%H:%M") for t in times_list)
        if len(times_list) >= DEFAULT_REDDIT_POSTS_PER_DAY:
            status = "FULL (Will skip)"
        else:
            free = DEFAULT_REDDIT_POSTS_PER_DAY - len(times_list)
            status = f"{free} slot(s) available"
        print(f"{d.isoformat():<12} | {len(times_list):<5} | {times_str:<25} | {status}")
    print("=" * 65)


async def reddit_automation_menu(client: Any, db: dict, db_path: str):
    """Interactive menu for Reddit video automation."""
    active = db.get('active_channel')
    if not active:
        print("\nNo active channel selected! Please select a channel first from the main menu (Option 3).")
        return

    while True:
        print("\n" + "=" * 55)
        print("Reddit Video Automation & Channel Scheduler")
        print(f"Active Channel: {active['title']} (ID: {active['id']})")
        print("Schedule Rule: 3 videos/day starting at midnight (00:00, 08:00, 16:00)")
        print("Caption Rule: No caption (native Telegram scheduling)")
        print("=" * 55)
        print("1. Run check & schedule once now")
        print("2. Start 2-hour automation background loop")
        print("3. Inspect channel schedule & open slots")
        print("4. View pending downloaded videos")
        print("5. View tracked subreddits")
        print("6. Back to main menu")

        choice = input("\nEnter choice (1-6): ").strip()
        if choice == '1':
            print("\nRunning single Reddit check and schedule cycle...")
            res = await run_reddit_automation_once(client, db, db_path)
            print("\nExecution Summary:")
            print(f"- Posts fetched: {res['posts_fetched']}")
            print(f"- New posts found: {res['new_posts_found']}")
            print(f"- Videos downloaded: {res['downloaded']}")
            print(f"- Videos scheduled: {res['scheduled']}")
            if res['errors']:
                print(f"- Errors: {len(res['errors'])}")
                for err in res['errors']:
                    print(f"   * {err}")
        elif choice == '2':
            print("\nStarting 2-hour automation loop.")
            print("Press Ctrl+C to stop the loop and return to the menu.\n")
            stop_event = asyncio.Event()
            try:
                await run_reddit_automation_daemon(client, db, db_path, stop_event=stop_event)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nAutomation loop stopped.")
        elif choice == '3':
            await display_channel_schedule_calendar(client, active['id'])
        elif choice == '4':
            pending = get_pending_videos()
            print(f"\nPending videos waiting in '{REDDIT_PENDING_DIR}': {len(pending)}")
            for p in pending:
                print(f" - {os.path.basename(p)} ({os.path.getsize(p):,} bytes)")
        elif choice == '5':
            print("\nTracked Subreddits:")
            for s in DEFAULT_REDDIT_SUBREDDITS:
                print(f" - {s}")
        elif choice == '6':
            break
        else:
            print("\nInvalid choice!")


def cli_main():
    """CLI entry point for running Reddit automation independently."""
    import argparse
    from dotenv import load_dotenv
    from src.account import AccountContext
    from src.database import load_database, get_legacy_db_path
    from src.client import restore_session

    load_dotenv()
    parser = argparse.ArgumentParser(description="Reddit Video Automation for Telegram Channel")
    parser.add_argument('--once', action='store_true', help="Run one check-and-schedule cycle then exit")
    parser.add_argument('--daemon', action='store_true', help="Run continuously in background (default 2 hours)")
    parser.add_argument('--interval', type=int, default=DEFAULT_REDDIT_CHECK_INTERVAL_SECONDS, help="Check interval in seconds (default: 7200)")
    args = parser.parse_args()

    api_id = os.getenv('API_ID')
    api_hash = os.getenv('API_HASH')
    if not api_id or not api_hash:
        print("Error: API_ID and API_HASH not found in .env file.")
        return

    # Attempt to resolve active account context: check per-account first, then legacy
    account = AccountContext.find_active_account()
    if account:
        db_path = account.database_path
        db = load_database(db_path)
    else:
        db_path = get_legacy_db_path()
        db = load_database(db_path)

    async def run():
        client, phone = await restore_session(db, int(api_id), api_hash, db_path)
        if not client:
            print("No active Telegram session found. Please run 'python main.py' first to log in and select an active channel.")
            return

        AccountContext.set_account(phone)

        if not db.get('active_channel'):
            print(f"No active channel selected for account {phone}. Please run 'python main.py' to select an active channel.")
            return

        try:
            if args.once:
                print("Running single Reddit automation cycle...")
                await run_reddit_automation_once(client, db, db_path)
            else:
                await run_reddit_automation_daemon(client, db, db_path, interval_seconds=args.interval)
        finally:
            await client.disconnect()

    asyncio.run(run())


if __name__ == '__main__':
    cli_main()

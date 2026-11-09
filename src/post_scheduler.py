"""
Post scheduler module.
Allows scheduling and managing text and media posts to Telegram channels.
Supports native Telegram scheduling (cloud-based delivery) and batch scheduling.
"""
import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

from telethon import functions, types
from telethon.errors import (
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    RPCError
)

from src.config import (
    MIN_SCHEDULE_DELAY_SECONDS,
    DEFAULT_BATCH_SCHEDULE_INTERVAL_MINUTES,
    SCHEDULE_MAX_FUTURE_DAYS,
    DEFAULT_DOWNLOADS_DIR,
    DATE_FORMAT_DISPLAY,
    logger
)
from src.database import save_database
from src.video_optimizer import optimize_video_for_upload, cleanup_temp_file

# Supported media extensions for auto-detection
MEDIA_EXTENSIONS = (
    '.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv',
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    '.mp3', '.ogg', '.m4a', '.wav'
)


def parse_schedule_time(
    input_str: str,
    now_dt: Optional[datetime] = None
) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse a user schedule time input string into a future datetime.

    Supported formats:
    - Relative delay: "30m", "+30m", "2h", "+2h", "1d", "+1d", or numeric minutes "45"
    - Time today/tomorrow: "HH:MM" (e.g. "14:30")
    - Full datetime: "YYYY-MM-DD HH:MM" or "YYYY-MM-DD HH:MM:SS"
    - Immediate: "now" or "0"

    Args:
        input_str: Raw input string
        now_dt: Optional baseline datetime (defaults to datetime.now())

    Returns:
        Tuple[Optional[datetime], Optional[str]]: (Parsed datetime or None, error message or None)
    """
    if not input_str:
        return None, "Empty schedule time input"

    text = input_str.strip().lower()
    base = now_dt or datetime.now()

    if text in ('now', '0', 'immediate'):
        return base, None

    # Check relative formats: e.g. +30m, 30m, 2h, 1d, 45 (minutes)
    rel_match = re.match(r'^\+?(\d+)\s*([mhd]?)$', text)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2) or 'm'
        if unit == 'm':
            return base + timedelta(minutes=val), None
        elif unit == 'h':
            return base + timedelta(hours=val), None
        elif unit == 'd':
            return base + timedelta(days=val), None

    # Check time format: HH:MM
    time_match = re.match(r'^(\d{1,2}):(\d{2})$', text)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= base:
                target += timedelta(days=1)
            return target, None
        return None, f"Invalid time values: {text}"

    # Check full datetime formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed, None
        except ValueError:
            pass

    return None, f"Unrecognized format '{input_str}'. Use e.g. '30m', '2h', '18:30', or 'YYYY-MM-DD HH:MM'"


def validate_schedule_time(
    dt: datetime,
    now_dt: Optional[datetime] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate that a scheduled time satisfies Telegram limits.

    Args:
        dt: Candidate schedule datetime
        now_dt: Baseline datetime

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_reason)
    """
    base = now_dt or datetime.now()
    min_time = base + timedelta(seconds=MIN_SCHEDULE_DELAY_SECONDS)
    max_time = base + timedelta(days=SCHEDULE_MAX_FUTURE_DAYS)

    if dt < min_time:
        return False, (
            f"Schedule time must be at least {MIN_SCHEDULE_DELAY_SECONDS}s in the future. "
            f"Provided: {dt.strftime(DATE_FORMAT_DISPLAY)}"
        )

    if dt > max_time:
        return False, f"Schedule time cannot be more than {SCHEDULE_MAX_FUTURE_DAYS} days in the future."

    return True, None


def clean_filename_caption(file_path: str) -> str:
    """
    Generate a clean human-readable caption from a media file path.

    Args:
        file_path: Media file path

    Returns:
        str: Clean caption
    """
    basename = os.path.basename(file_path)
    stem, _ = os.path.splitext(basename)
    # Remove yt-dlp style IDs like "[dQw4w9WgXcQ]"
    cleaned = re.sub(r'\[[a-zA-Z0-9_-]+\]', '', stem)
    # Replace underscores and duplicate spaces
    cleaned = cleaned.replace('_', ' ').strip()
    return cleaned or stem


def find_media_files(folder_path: str) -> List[str]:
    """
    Find all supported media files in a directory.

    Args:
        folder_path: Directory path to scan

    Returns:
        List[str]: Sorted list of full file paths
    """
    if not os.path.isdir(folder_path):
        return []

    files = []
    for root, _, filenames in os.walk(folder_path):
        for name in filenames:
            if name.lower().endswith(MEDIA_EXTENSIONS):
                files.append(os.path.join(root, name))

    files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    return files


async def schedule_text_post(
    client: Any,
    entity: Any,
    text: str,
    schedule_time: Optional[datetime] = None
) -> Any:
    """
    Schedule a text message to be sent to a channel.

    Args:
        client: Telethon client
        entity: Channel/Group entity or ID
        text: Message body text
        schedule_time: Target datetime (None for immediate)

    Returns:
        Message object returned by Telethon
    """
    return await client.send_message(
        entity,
        message=text,
        schedule=schedule_time
    )


async def schedule_media_post(
    client: Any,
    entity: Any,
    file_path: str,
    schedule_time: Optional[datetime] = None,
    caption: Optional[str] = None
) -> Any:
    """
    Schedule a media file (photo/video/document) with optional caption.
    Automatically applies 720p optimization via FFmpeg for videos/GIFs > 5MB.

    Args:
        client: Telethon client
        entity: Channel/Group entity or ID
        file_path: Path to the media file
        schedule_time: Target datetime (None for immediate)
        caption: Optional caption text

    Returns:
        Message object returned by Telethon
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Media file not found: {file_path}")

    upload_path, is_temp = optimize_video_for_upload(file_path)
    try:
        return await client.send_file(
            entity,
            file=upload_path,
            caption=caption,
            schedule=schedule_time,
            supports_streaming=True
        )
    finally:
        if is_temp:
            cleanup_temp_file(upload_path)


async def batch_schedule_media(
    client: Any,
    entity: Any,
    file_paths: List[str],
    start_time: datetime,
    interval_minutes: int = DEFAULT_BATCH_SCHEDULE_INTERVAL_MINUTES,
    caption_mode: str = 'filename',
    custom_caption: Optional[str] = None
) -> Dict[str, Any]:
    """
    Batch schedule multiple media files at regular intervals.

    Args:
        client: Telethon client
        entity: Channel/Group entity
        file_paths: List of file paths to schedule
        start_time: Datetime for the first post
        interval_minutes: Minutes between subsequent posts
        caption_mode: 'filename', 'custom', or 'none'
        custom_caption: Custom text if caption_mode is 'custom'

    Returns:
        Dict[str, Any]: Summary containing total, scheduled, and errors
    """
    scheduled_count = 0
    errors = []
    delta = timedelta(minutes=interval_minutes)

    for i, path in enumerate(file_paths):
        post_time = start_time + (i * delta)

        if caption_mode == 'filename':
            caption = clean_filename_caption(path)
        elif caption_mode == 'custom':
            caption = custom_caption
        else:
            caption = None

        try:
            await schedule_media_post(
                client=client,
                entity=entity,
                file_path=path,
                schedule_time=post_time,
                caption=caption
            )
            scheduled_count += 1
            logger.info(f"Scheduled {os.path.basename(path)} for {post_time.strftime(DATE_FORMAT_DISPLAY)}")
            # Small delay between API calls to avoid rate limits
            await asyncio.sleep(1)
        except FloodWaitError as e:
            logger.warning(f"Flood wait {e.seconds}s encountered while scheduling {path}")
            await asyncio.sleep(e.seconds)
            try:
                await schedule_media_post(client, entity, path, post_time, caption)
                scheduled_count += 1
            except Exception as retry_err:
                errors.append({'file': path, 'error': str(retry_err)})
        except Exception as e:
            logger.error(f"Failed scheduling {path}: {e}")
            errors.append({'file': path, 'error': str(e)})

    return {
        'total': len(file_paths),
        'scheduled': scheduled_count,
        'failed': len(errors),
        'errors': errors
    }


async def list_scheduled_posts(client: Any, entity: Any) -> List[Dict[str, Any]]:
    """
    Retrieve all pending scheduled messages for a channel.

    Args:
        client: Telethon client
        entity: Channel/Group entity or ID

    Returns:
        List[Dict[str, Any]]: List of scheduled post summaries
    """
    results = []
    try:
        async for msg in client.iter_messages(entity, scheduled=True):
            media_type = 'None'
            if msg.media:
                media_type = type(msg.media).__name__.replace('MessageMedia', '')

            results.append({
                'id': msg.id,
                'date': msg.date,
                'date_str': msg.date.strftime(DATE_FORMAT_DISPLAY) if msg.date else 'Unknown',
                'text': msg.raw_text or '',
                'media_type': media_type,
            })
    except Exception as e:
        logger.error(f"Error fetching scheduled messages: {e}")

    return results


async def delete_scheduled_posts(
    client: Any,
    entity: Any,
    message_ids: List[int]
) -> bool:
    """
    Delete scheduled messages from a channel.

    Args:
        client: Telethon client
        entity: Channel/Group entity or ID
        message_ids: IDs of scheduled messages to delete

    Returns:
        bool: True if successful, False otherwise
    """
    if not message_ids:
        return True

    try:
        input_peer = await client.get_input_entity(entity)
        await client(functions.messages.DeleteScheduledMessagesRequest(
            peer=input_peer,
            id=message_ids
        ))
        return True
    except Exception as e:
        logger.error(f"Failed deleting scheduled messages {message_ids}: {e}")
        return False


def record_scheduled_post(
    db: dict,
    db_path: str,
    channel_id: str,
    post_data: dict
):
    """
    Save scheduled post metadata into the local database.

    Args:
        db: Database dictionary
        db_path: Path to database JSON file
        channel_id: Channel ID string
        post_data: Details of the scheduled post
    """
    scheduled_section = db.setdefault('scheduled_posts', {})
    channel_posts = scheduled_section.setdefault(str(channel_id), [])
    channel_posts.append(post_data)
    save_database(db_path, db)


async def post_scheduler_menu(client: Any, db: dict, db_path: str):
    """
    Interactive console menu for scheduled posts.

    Args:
        client: Telethon client
        db: Database dictionary
        db_path: Path to database JSON file
    """
    active = db.get('active_channel')
    if not active:
        print("\nError: No active channel selected!")
        print("Please select a channel first using Option 3 from the main menu.")
        return

    channel_id = active['id']
    print("\n" + "=" * 50)
    print(f"Scheduled Posts Manager")
    print(f"Active Channel: {active.get('title', 'Unknown')} (ID: {channel_id})")
    print("=" * 50)
    print("1. Schedule a text post")
    print("2. Schedule a media post (photo/video from file)")
    print("3. Batch schedule media files from folder (e.g. downloads/)")
    print("4. View scheduled posts in channel")
    print("5. Cancel / Delete a scheduled post")
    print("6. Post immediately (text or media)")
    print("7. Back to main menu")

    choice = input("\nEnter choice (1-7): ").strip()
    if choice == '1':
        await _handle_schedule_text(client, active, db, db_path)
    elif choice == '2':
        await _handle_schedule_media(client, active, db, db_path)
    elif choice == '3':
        await _handle_batch_schedule(client, active, db, db_path)
    elif choice == '4':
        await _handle_list_scheduled(client, active)
    elif choice == '5':
        await _handle_cancel_scheduled(client, active)
    elif choice == '6':
        await _handle_immediate_post(client, active, db, db_path)


def _prompt_schedule_time() -> Optional[datetime]:
    """Prompt the user for schedule time with validation."""
    print("\nEnter schedule time (e.g. '30m', '2h', '18:30', 'YYYY-MM-DD HH:MM'):")
    val = input("Schedule time: ").strip()
    dt, err = parse_schedule_time(val)
    if err or not dt:
        print(f"\nError: {err or 'Invalid schedule time'}")
        return None

    is_valid, val_err = validate_schedule_time(dt)
    if not is_valid:
        print(f"\nError: {val_err}")
        return None

    print(f"Post will be scheduled for: {dt.strftime(DATE_FORMAT_DISPLAY)}")
    return dt


async def _handle_schedule_text(client: Any, active: dict, db: dict, db_path: str):
    """Handle scheduling a text message."""
    print("\nEnter post content (Telegram markdown/entities supported):")
    text = input("Message text: ").strip()
    if not text:
        print("Cannot send an empty message.")
        return

    dt = _prompt_schedule_time()
    if not dt:
        return

    try:
        msg = await schedule_text_post(client, active['id'], text, dt)
        record_scheduled_post(db, db_path, str(active['id']), {
            'id': getattr(msg, 'id', None),
            'type': 'text',
            'content': text[:100],
            'scheduled_date': str(dt),
            'created_at': str(datetime.now())
        })
        print("\nSuccessfully scheduled text post!")
    except (ChatAdminRequiredError, ChatWriteForbiddenError) as e:
        print(f"\nPermission denied: You do not have write/admin rights in this channel ({e}).")
    except Exception as e:
        print(f"\nFailed to schedule post: {e}")


async def _handle_schedule_media(client: Any, active: dict, db: dict, db_path: str):
    """Handle scheduling a media file."""
    file_path = input("\nEnter path to media file: ").strip()
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    caption = input("Enter caption (optional, press Enter to skip): ").strip() or None
    dt = _prompt_schedule_time()
    if not dt:
        return

    try:
        print("\nUploading and scheduling media...")
        msg = await schedule_media_post(client, active['id'], file_path, dt, caption)
        record_scheduled_post(db, db_path, str(active['id']), {
            'id': getattr(msg, 'id', None),
            'type': 'media',
            'file': file_path,
            'caption': caption,
            'scheduled_date': str(dt),
            'created_at': str(datetime.now())
        })
        print("\nSuccessfully scheduled media post!")
    except Exception as e:
        print(f"\nFailed to schedule media post: {e}")


async def _handle_batch_schedule(client: Any, active: dict, db: dict, db_path: str):
    """Handle batch scheduling media files from folder."""
    folder = input(f"\nEnter folder containing media [{DEFAULT_DOWNLOADS_DIR}]: ").strip() or DEFAULT_DOWNLOADS_DIR
    media_files = find_media_files(folder)

    if not media_files:
        print(f"\nNo supported media files found in {folder}.")
        return

    print(f"\nFound {len(media_files)} media file(s) in {folder}.")
    for i, path in enumerate(media_files[:10], 1):
        print(f"  {i}. {os.path.basename(path)}")
    if len(media_files) > 10:
        print(f"  ... and {len(media_files) - 10} more.")

    print("\nSelect start schedule time for the FIRST post:")
    start_time = _prompt_schedule_time()
    if not start_time:
        return

    interval_str = input(f"Enter interval between posts in minutes [{DEFAULT_BATCH_SCHEDULE_INTERVAL_MINUTES}]: ").strip()
    interval = int(interval_str) if interval_str.isdigit() else DEFAULT_BATCH_SCHEDULE_INTERVAL_MINUTES

    print("\nCaption option:")
    print("1. Clean filename as caption")
    print("2. Custom caption for all")
    print("3. No caption")
    caption_choice = input("Enter choice (1-3) [1]: ").strip() or '1'

    caption_mode = 'filename'
    custom_caption = None
    if caption_choice == '2':
        caption_mode = 'custom'
        custom_caption = input("Enter custom caption: ").strip()
    elif caption_choice == '3':
        caption_mode = 'none'

    confirm = input(f"\nReady to schedule {len(media_files)} posts every {interval}m? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Batch scheduling cancelled.")
        return

    print("\nBatch scheduling in progress...")
    result = await batch_schedule_media(
        client=client,
        entity=active['id'],
        file_paths=media_files,
        start_time=start_time,
        interval_minutes=interval,
        caption_mode=caption_mode,
        custom_caption=custom_caption
    )

    print("\n" + "-" * 40)
    print("Batch Scheduling Summary:")
    print(f"  Total Files:     {result['total']}")
    print(f"  Scheduled:       {result['scheduled']}")
    print(f"  Failed:          {result['failed']}")
    if result['errors']:
        print("  Errors:")
        for err in result['errors'][:5]:
            print(f"    - {os.path.basename(err['file'])}: {err['error']}")
    print("-" * 40)


async def _handle_list_scheduled(client: Any, active: dict):
    """List pending scheduled posts."""
    print("\nFetching scheduled posts from Telegram...")
    posts = await list_scheduled_posts(client, active['id'])

    if not posts:
        print("\nNo scheduled posts found in this channel.")
        return

    print(f"\nScheduled Posts ({len(posts)} pending):")
    print("-" * 65)
    for p in posts:
        preview = p['text'].replace('\n', ' ')[:40] if p['text'] else f"[{p['media_type']}]"
        print(f"ID: {p['id']:<8} | Time: {p['date_str']} | Type: {p['media_type']:<8} | {preview}")
    print("-" * 65)


async def _handle_cancel_scheduled(client: Any, active: dict):
    """Cancel / delete a scheduled post."""
    posts = await list_scheduled_posts(client, active['id'])
    if not posts:
        print("\nNo scheduled posts found to cancel.")
        return

    print("\nCurrently scheduled posts:")
    for p in posts:
        snippet = (p['text'] or f"[{p['media_type']}]")[:30]
        print(f"  ID {p['id']}: {p['date_str']} - {snippet}")

    target_id_str = input("\nEnter scheduled message ID to cancel (or 'all' to cancel all, 0 to return): ").strip()
    if target_id_str == '0' or not target_id_str:
        return

    if target_id_str.lower() == 'all':
        confirm = input(f"Are you sure you want to cancel ALL {len(posts)} scheduled posts? (y/N): ").strip().lower()
        if confirm == 'y':
            ids = [p['id'] for p in posts]
            success = await delete_scheduled_posts(client, active['id'], ids)
            if success:
                print(f"\nCancelled {len(ids)} scheduled post(s).")
            else:
                print("\nFailed to cancel some scheduled posts.")
        return

    try:
        msg_id = int(target_id_str)
        success = await delete_scheduled_posts(client, active['id'], [msg_id])
        if success:
            print(f"\nScheduled post #{msg_id} cancelled successfully.")
        else:
            print(f"\nFailed to cancel scheduled post #{msg_id}.")
    except ValueError:
        print("Please enter a valid numeric ID.")


async def _handle_immediate_post(client: Any, active: dict, db: dict, db_path: str):
    """Handle immediate posting (now)."""
    print("\nImmediate Post Options:")
    print("1. Send text post now")
    print("2. Send media post now")
    sub_choice = input("Enter choice (1-2): ").strip()

    if sub_choice == '1':
        text = input("\nEnter message text: ").strip()
        if not text:
            print("Cannot send an empty message.")
            return
        try:
            await schedule_text_post(client, active['id'], text, schedule_time=None)
            print("\nPost published immediately!")
        except Exception as e:
            print(f"\nFailed to send message: {e}")
    elif sub_choice == '2':
        file_path = input("\nEnter path to media file: ").strip()
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return
        caption = input("Enter caption (optional): ").strip() or None
        try:
            print("\nUploading and sending media...")
            await schedule_media_post(client, active['id'], file_path, schedule_time=None, caption=caption)
            print("\nMedia published immediately!")
        except Exception as e:
            print(f"\nFailed to send media: {e}")

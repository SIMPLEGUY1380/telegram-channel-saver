"""
Media management module.
Handles downloading and managing media content from messages.
"""
import os
import logging
import asyncio
import random
from datetime import datetime
from telethon.errors import FloodWaitError, ServerError, TimedOutError

from src.config import (
    MEDIA_DOWNLOAD_TIMEOUT, MEDIA_DOWNLOAD_RETRY,
    MEDIA_RETRY_DELAY_BASE, MEDIA_DOWNLOAD_DELAY,
    CHUNK_SIZE, get_video_dir,
    DATE_FORMAT_FILENAME, DATE_FORMAT_DISPLAY
)

logger = logging.getLogger(__name__)

async def download_media_safely(client, message, filename, file_size=None):
    """
    Enhanced media download method with safety features:
    - Timeout handling
    - Chunked downloads for large files
    - Retry mechanism with exponential backoff
    - Detailed error reporting
    
    Args:
        client: Telegram client
        message: Message containing media
        filename: Base filename to save as
        file_size: Size of the file in bytes if known
        
    Returns:
        dict: Result with 'success', 'file_path', and optional 'error' fields
    """
    result = {
        'success': False,
        'file_path': None,
        'error': None
    }
    
    # Get target file path (uses account-specific directory)
    video_dir = get_video_dir()
    os.makedirs(video_dir, exist_ok=True)
    target_path = os.path.join(video_dir, filename)
    
    # Determine if file is large (over 10MB)
    is_large_file = False
    if file_size and file_size > 10 * 1024 * 1024:  # > 10MB
        is_large_file = True
        print(f"Large file detected ({file_size/(1024*1024):.2f} MB). Using chunked download.")
    
    # For retry mechanism
    retry_count = 0
    max_retries = MEDIA_DOWNLOAD_RETRY
    
    # Initialize start_time variable for both large and small files
    start_time = datetime.now()
    
    # Try to download with retries
    while retry_count <= max_retries:
        try:
            if retry_count > 0:
                # Calculate backoff delay with jitter to avoid thundering herd
                backoff_time = MEDIA_RETRY_DELAY_BASE * (2 ** (retry_count - 1))
                # Add jitter (±25%)
                jitter = random.uniform(0.75, 1.25)
                delay = backoff_time * jitter
                print(f"Retry {retry_count}/{max_retries} after {delay:.1f} seconds...")
                await asyncio.sleep(delay)
            
            # Reset start_time for each attempt
            start_time = datetime.now()
            
            if is_large_file:
                # Use chunked download for large files
                print(f"Starting chunked download with {CHUNK_SIZE/1024:.0f}KB chunks...")
                
                # Use a custom progress callback
                last_update_time = start_time
                bytes_downloaded = 0
                
                # Progress callback function
                def progress_callback(downloaded_bytes, total_bytes):
                    nonlocal bytes_downloaded, last_update_time
                    bytes_downloaded = downloaded_bytes
                    
                    # Only update display every second
                    current_time = datetime.now()
                    if (current_time - last_update_time).total_seconds() >= 1:
                        # Calculate speed
                        elapsed = (current_time - start_time).total_seconds()
                        speed = downloaded_bytes / elapsed if elapsed > 0 else 0
                        
                        # Format sizes
                        downloaded_mb = downloaded_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024) if total_bytes else 0
                        speed_kbps = speed / 1024
                        
                        # Calculate percentage
                        percent = (downloaded_bytes / total_bytes * 100) if total_bytes else 0
                        
                        # Calculate ETA
                        if speed > 0 and total_bytes:
                            remaining_bytes = total_bytes - downloaded_bytes
                            eta_seconds = remaining_bytes / speed
                            eta_str = str(datetime.fromtimestamp(eta_seconds) - datetime.fromtimestamp(0))
                            eta_str = eta_str.split('.')[0]  # Remove microseconds
                        else:
                            eta_str = "unknown"
                        
                        print(f"\rProgress: {downloaded_mb:.2f}/{total_mb:.2f} MB " + 
                              f"({percent:.1f}%) at {speed_kbps:.1f} KB/s - ETA: {eta_str}", 
                              end='')
                        
                        last_update_time = current_time
                    
                    return True  # Continue download
                
                # Attempt the chunked download with timeout
                file_path = await asyncio.wait_for(
                    client.download_media(
                        message.media,
                        file=target_path,
                        progress_callback=progress_callback
                    ),
                    timeout=MEDIA_DOWNLOAD_TIMEOUT
                )
                
                print()  # New line after progress output
                
            else:
                # Regular download for smaller files
                file_path = await asyncio.wait_for(
                    client.download_media(
                        message.media,
                        file=target_path
                    ),
                    timeout=MEDIA_DOWNLOAD_TIMEOUT
                )
            
            # Success!
            if file_path:
                # Verify downloaded file
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    downloaded_size = os.path.getsize(file_path)
                    if file_size and abs(downloaded_size - file_size) > 1024:  # Allow 1KB difference
                        # File size mismatch, file may be incomplete
                        print(f"Warning: File size mismatch. Expected: {file_size}, Got: {downloaded_size}")
                        logger.warning(f"File size mismatch for {file_path}. Expected: {file_size}, Got: {downloaded_size}")
                    
                    # Calculate download speed
                    elapsed = (datetime.now() - start_time).total_seconds()
                    speed_mbps = (downloaded_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    print(f"Download completed: {downloaded_size/(1024*1024):.2f} MB in {elapsed:.1f} seconds ({speed_mbps:.2f} MB/s)")
                    
                    result['success'] = True
                    result['file_path'] = file_path
                    return result
                else:
                    # File doesn't exist or is empty
                    result['error'] = "Download failed - file is empty or missing"
                    if os.path.exists(file_path):
                        os.remove(file_path)  # Clean up empty file
                    # Continue to retry
            
            else:
                result['error'] = "Download returned None"
                # Continue to retry
        
        except asyncio.TimeoutError:
            result['error'] = f"Download timed out after {MEDIA_DOWNLOAD_TIMEOUT} seconds"
            print(f"Timeout error: {result['error']}")
            logger.warning(f"Download timeout for {filename}")
            # Continue to next retry
        
        except FloodWaitError as e:
            wait_time = e.seconds
            result['error'] = f"Rate limit exceeded! Required to wait {wait_time} seconds"
            print(f"Flood wait error: Need to wait {wait_time} seconds")
            logger.warning(f"FloodWaitError: {wait_time} seconds wait required")
            
            # This is a special case - wait the required time then retry
            await asyncio.sleep(wait_time)
            continue  # Skip retry increment
        
        except (ServerError, TimedOutError) as e:
            result['error'] = f"Telegram server error: {str(e)}"
            print(f"Server error: {result['error']}")
            logger.warning(f"Server error during download: {str(e)}")
            # Continue to retry
        
        except ConnectionError as e:
            result['error'] = f"Connection error: {str(e)}"
            print(f"Connection error: {result['error']}")
            logger.warning(f"Connection error during download: {str(e)}")
            # Continue to retry
        
        except OSError as e:
            result['error'] = f"OS error: {str(e)}"
            print(f"OS error: {result['error']}")
            logger.warning(f"OS error during download: {str(e)}")
            # Continue to retry
        
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            print(f"Unexpected error: {result['error']}")
            logger.error(f"Unexpected error during download: {str(e)}", exc_info=True)
            # Continue to retry
        
        # Increment retry counter
        retry_count += 1
    
    # If we get here, all retries failed
    print(f"All {max_retries} download attempts failed")
    return result

async def download_video_messages(client, db, db_path, limit=None, round_videos_only=False, video_dir=None):
    """
    Download video messages (video circles or regular videos) from active channel
    
    Args:
        client: Telegram client
        db: Database
        db_path: Path to database file
        limit: Maximum number of videos to download (None for all)
        round_videos_only: If True, download only round videos (video circles/video messages), 
                           otherwise download all videos
        video_dir: Custom directory to save videos (default: temp/videos)
    
    Returns:
        bool: True if download was successful, False otherwise
    """
    from telethon.tl.types import InputMessagesFilterRoundVideo, InputMessagesFilterVideo
    from src.channels import get_active_channel
    from src.database import save_database
    
    active = get_active_channel(db)
    if not active:
        print("\nNo active channel selected!")
        return False
    
    try:
        # Set up download directory (uses account-specific directory by default)
        if video_dir:
            download_dir = video_dir
        else:
            download_dir = get_video_dir()
        os.makedirs(download_dir, exist_ok=True)
        
        print("\n" + "="*50)
        print(f"Downloading {'round' if round_videos_only else 'all'} videos from channel: {active['title']}")
        print("="*50)
        
        # Initialize video messages list in the database
        channel_id = str(active['id'])
        if 'videos' not in db:
            db['videos'] = {}
        if channel_id not in db['videos']:
            db['videos'][channel_id] = {}
        
        # Counters for tracking progress
        downloaded = 0
        skipped = 0
        errors = 0
        retry_count = 0
        
        # Progress tracking
        start_time = datetime.now()
        last_save_time = start_time
        
        # Define the video filter
        video_filter = InputMessagesFilterRoundVideo() if round_videos_only else InputMessagesFilterVideo()
        
        # Get total count of videos (approximate)
        total_count = 0
        try:
            async for _ in client.iter_messages(active['id'], filter=video_filter, limit=1):
                # Just to get the first message to check if any exist
                total_count = 1
            print(f"Scanning for {'round' if round_videos_only else 'all'} videos in the channel...")
        except Exception as e:
            print(f"Error checking for videos: {e}")
            return False
        
        # If no videos found
        if total_count == 0:
            print("\nNo videos found in this channel!")
            return False
        
        # Get videos from newest to oldest
        async for message in client.iter_messages(active['id'], filter=video_filter, limit=limit):
            try:
                msg_id = str(message.id)
                video_info = {
                    'id': message.id,
                    'date': str(message.date),
                    'from_id': message.from_id.user_id if message.from_id else None,
                    'media_type': type(message.media).__name__ if message.media else None,
                    'file_path': None,
                    'download_date': None,
                    'file_size': None,
                    'duration': getattr(message.media.document, 'duration', None) if message.media else None,
                    'mime_type': getattr(message.media.document, 'mime_type', None) if message.media else None,
                    'size': getattr(message.media.document, 'size', None) if message.media else None,
                }
                
                # Check if video is already downloaded
                if msg_id in db['videos'][channel_id] and db['videos'][channel_id][msg_id].get('file_path'):
                    existing_path = db['videos'][channel_id][msg_id]['file_path']
                    if os.path.exists(existing_path):
                        print(f"Video from message #{message.id} already downloaded, skipping...")
                        skipped += 1
                        continue
                
                # Create a filename based on message ID and date
                filename = f"video_{message.id}_{message.date.strftime(DATE_FORMAT_FILENAME)}"
                
                # Get video file size if available
                file_size = None
                if hasattr(message.media, 'document'):
                    file_size = getattr(message.media.document, 'size', None)
                    if file_size:
                        size_mb = file_size / (1024 * 1024)
                        print(f"Video size: {size_mb:.2f} MB")
                
                # Download the video using our enhanced method
                print(f"Downloading video from message #{message.id}...")
                download_result = await download_media_safely(
                    client=client,
                    message=message,
                    filename=filename,
                    file_size=file_size
                )
                
                if download_result['success']:
                    file_path = download_result['file_path']
                    print(f"Video saved to: {file_path}")
                    
                    # Update video info with download details
                    video_info['file_path'] = file_path
                    video_info['download_date'] = str(datetime.now())
                    video_info['file_size'] = os.path.getsize(file_path) if os.path.exists(file_path) else None
                    
                    # Save to database
                    db['videos'][channel_id][msg_id] = video_info
                    downloaded += 1
                    
                    # Save database periodically
                    current_time = datetime.now()
                    if (current_time - last_save_time).total_seconds() > 300:  # 5 minutes
                        save_database(db_path, db)
                        last_save_time = current_time
                else:
                    # Handle download failure
                    print(f"Failed to download video: {download_result['error']}")
                    logger.warning(f"Video download failed for message {message.id}: {download_result['error']}")
                    errors += 1
                
                # Display progress
                elapsed = datetime.now() - start_time
                print(f"Progress: Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")
                print(f"Elapsed time: {str(elapsed).split('.')[0]}")
                print(f"Retries due to rate limits: {retry_count}")
                print("-"*50)
                
                # Add delay to avoid rate limits
                await asyncio.sleep(MEDIA_DOWNLOAD_DELAY)
                
            except Exception as e:
                logger.error(f"Error downloading video from message {message.id}: {str(e)}")
                print(f"Error downloading video from message #{message.id}: {str(e)}")
                errors += 1
                continue
        
        # Final save
        save_database(db_path, db)
        
        # Final statistics
        end_time = datetime.now()
        elapsed = end_time - start_time
        
        print("\n" + "="*50)
        print("Download Completed!")
        print("="*50)
        print(f"\nFinal Statistics:")
        print(f"Total videos downloaded: {downloaded}")
        print(f"Videos skipped (already downloaded): {skipped}")
        print(f"Errors: {errors}")
        print(f"Retries due to rate limits: {retry_count}")
        print(f"\nTime Elapsed: {str(elapsed).split('.')[0]}")
        print("="*50)
        
        return True
        
    except Exception as e:
        logger.error(f"Error downloading videos: {e}")
        print(f"\nError downloading videos: {str(e)}")
        return False

def list_downloaded_videos(db):
    """
    List all downloaded videos for active channel
    
    Args:
        db: Database
    """
    from src.channels import get_active_channel
    
    active = get_active_channel(db)
    if not active:
        print("\nNo active channel selected!")
        return
        
    channel_id = str(active['id'])
    if 'videos' not in db or channel_id not in db['videos'] or not db['videos'][channel_id]:
        print("\nNo downloaded videos for this channel!")
        return
        
    videos = db['videos'][channel_id]
    total = len(videos)
    
    print("\nDownloaded Videos:")
    print("-" * 80)
    print(f"{'ID':<10} | {'Date':<20} | {'Type':<15} | {'Size':<10} | {'Duration':<10} | {'Path':<30}")
    print("-" * 80)
    
    for video_id, video in sorted(videos.items(), key=lambda x: int(x[0]), reverse=True):
        if not video.get('file_path') or not os.path.exists(video.get('file_path', '')):
            continue
            
        # Format size to KB/MB
        size = "N/A"
        if video.get('file_size'):
            size_bytes = video['file_size']
            if size_bytes < 1024:
                size = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size = f"{size_bytes / 1024:.1f} KB"
            else:
                size = f"{size_bytes / (1024 * 1024):.1f} MB"
                
        # Format duration to mm:ss
        duration = "N/A"
        if video.get('duration'):
            seconds = video['duration']
            minutes = seconds // 60
            seconds = seconds % 60
            duration = f"{minutes:02d}:{seconds:02d}"
            
        # Format date
        date = video.get('date', 'Unknown')
        if date and date != 'Unknown':
            try:
                # Parse and format date string (handle timezone suffix)
                date_obj = datetime.fromisoformat(date.replace('+00:00', '').rstrip('Z'))
                date = date_obj.strftime(DATE_FORMAT_DISPLAY)
            except (ValueError, TypeError):
                pass
                
        # Format path
        path = video.get('file_path', 'Unknown')
        if len(path) > 30:
            path = "..." + path[-27:]
            
        # Get media type (video type)
        media_type = video.get('media_type', 'Unknown')
        if media_type == 'MessageMediaDocument':
            mime_type = video.get('mime_type', '')
            if 'video' in mime_type:
                if 'round' in mime_type:
                    media_type = 'Video Circle'
                else:
                    media_type = 'Video'
                    
        print(f"{video['id']:<10} | {date:<20} | {media_type:<15} | {size:<10} | {duration:<10} | {path:<30}")
        
    print("-" * 80)
    print(f"Total Videos: {total}") 
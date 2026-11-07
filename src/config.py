"""
Configuration settings for the Telegram Channel Saver.
Contains constants and settings used throughout the application.
"""
import os
import logging

# Configure logging
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Date format constants
DATE_FORMAT_WITH_TZ = "%Y-%m-%d %H:%M:%S%z"  # Format with timezone info
DATE_FORMAT_DISPLAY = "%Y-%m-%d %H:%M:%S"  # Display format without timezone
DATE_FORMAT_FILENAME = "%Y%m%d_%H%M%S"  # Safe format for filenames

# Batch size and timing settings
MESSAGES_BATCH_SIZE = 100  # Number of messages to process in one batch
BATCH_DELAY = 2  # Delay between batches in seconds
SAVE_INTERVAL = 300  # Save database every 5 minutes
MAX_RETRIES = 3  # Maximum retries for failed message fetches

# Media download settings
MEDIA_DOWNLOAD_DELAY = 3  # Delay between media downloads in seconds to avoid rate limits
MEDIA_DOWNLOAD_TIMEOUT = 120  # Timeout for media downloads in seconds (2 minutes)
MEDIA_DOWNLOAD_RETRY = 3  # Maximum number of retries for failed media downloads
MEDIA_RETRY_DELAY_BASE = 5  # Base delay for retry backoff in seconds
CHUNK_SIZE = 1024 * 1024  # 1MB chunk size for large downloads

# Link downloader settings (embedded yt-dlp)
DEFAULT_LINKS_FILE = 'links.txt'
DEFAULT_DOWNLOADS_DIR = 'downloads'
DEFAULT_ARCHIVE_FILE = 'downloaded.txt'

# Scheduled posting settings
MIN_SCHEDULE_DELAY_SECONDS = 15  # Minimum future delay for Telegram scheduling
DEFAULT_BATCH_SCHEDULE_INTERVAL_MINUTES = 60  # Default interval between scheduled posts
SCHEDULE_MAX_FUTURE_DAYS = 365  # Telegram API allows up to ~1 year in future

# Directory settings
# Legacy paths (kept for migration compatibility)
LEGACY_TEMP_DIR = 'temp/channel_saver'
LEGACY_VIDEO_DIR = 'temp/videos'
LEGACY_EXPORT_DIR = 'temp/exports'

# New per-account base directory
ACCOUNTS_BASE_DIR = 'temp/accounts'

# Backward compatibility aliases
TEMP_DIR = LEGACY_TEMP_DIR
VIDEO_TEMP_DIR = LEGACY_VIDEO_DIR
EXPORT_DIR = LEGACY_EXPORT_DIR


def get_video_dir() -> str:
    """Get video directory for current account context"""
    from src.account import AccountContext
    ctx = AccountContext.get_current()
    if ctx:
        return ctx.videos_dir
    return LEGACY_VIDEO_DIR


def get_export_dir() -> str:
    """Get export directory for current account context"""
    from src.account import AccountContext
    ctx = AccountContext.get_current()
    if ctx:
        return ctx.exports_dir
    return LEGACY_EXPORT_DIR

# OpenRouter API settings
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "openai/gpt-4o-mini"  # Default model for image analysis
OPENROUTER_TIMEOUT = 30  # Timeout for API requests in seconds

# Create temp directories if they don't exist
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(VIDEO_TEMP_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(DEFAULT_DOWNLOADS_DIR, exist_ok=True)

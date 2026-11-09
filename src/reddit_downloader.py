"""
Reddit video downloader module.
Downloads videos found by the Reddit feed scraper using embedded yt-dlp.
"""
import os
import glob
import logging
from typing import List, Dict, Any, Optional

import yt_dlp

from src.config import (
    REDDIT_PENDING_DIR,
    REDDIT_ARCHIVE_FILE,
    DEFAULT_LINKS_FILE,
    logger
)
from src.post_scheduler import MEDIA_EXTENSIONS

# Supported video extensions for Telegram scheduling
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.mov', '.webm')


def append_links_to_file(urls: List[str], file_path: str = DEFAULT_LINKS_FILE):
    """
    Append URLs to links.txt for records and fallback.
    """
    if not urls:
        return
    existing = set()
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    u = line.strip()
                    if u and not u.startswith('#'):
                        existing.add(u)
        except Exception as e:
            logger.warning(f"Error reading {file_path}: {e}")

    to_add = [u for u in urls if u not in existing]
    if not to_add:
        return

    try:
        with open(file_path, 'a', encoding='utf-8') as f:
            for u in to_add:
                f.write(f"{u}\n")
    except Exception as e:
        logger.error(f"Error appending to {file_path}: {e}")


def get_pending_videos(pending_dir: str = REDDIT_PENDING_DIR) -> List[str]:
    """
    Get all downloaded video files waiting in the pending folder.
    Sorted by modification time (oldest first, so FIFO order).
    """
    if not os.path.exists(pending_dir):
        return []

    files = []
    for f in os.listdir(pending_dir):
        full_path = os.path.join(pending_dir, f)
        if os.path.isfile(full_path):
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                files.append(full_path)

    # Sort FIFO: oldest downloaded first
    files.sort(key=lambda p: os.path.getmtime(p))
    return files


def download_reddit_videos(
    urls: List[str],
    output_dir: str = REDDIT_PENDING_DIR,
    archive_file: str = REDDIT_ARCHIVE_FILE,
    ydl_class: Any = None
) -> List[str]:
    """
    Download video URLs into pending directory using yt-dlp.

    Args:
        urls: List of video URLs (RedGIFs, v.redd.it, etc.)
        output_dir: Folder to store downloaded videos
        archive_file: Archive file path tracking downloaded IDs
        ydl_class: Optional override for testing

    Returns:
        List[str]: Paths to newly downloaded video files
    """
    if not urls:
        return []

    os.makedirs(output_dir, exist_ok=True)
    # Also record in links.txt
    append_links_to_file(urls)

    # Record files existing prior to download
    before_files = set(os.listdir(output_dir))

    ydl_opts = {
        'paths': {'home': output_dir},
        'outtmpl': '%(id)s.%(ext)s',
        'download_archive': archive_file,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'ignoreerrors': True,
        'quiet': True,
        'no_warnings': True,
    }

    downloader = ydl_class or yt_dlp.YoutubeDL

    try:
        with downloader(ydl_opts) as ydl:
            ydl.download(urls)
    except Exception as e:
        logger.error(f"Error during Reddit video download: {e}")

    # Determine newly downloaded files
    after_files = set(os.listdir(output_dir))
    new_files = [
        os.path.join(output_dir, f)
        for f in (after_files - before_files)
        if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
    ]

    logger.info(f"Downloaded {len(new_files)} new videos into {output_dir}")
    return new_files

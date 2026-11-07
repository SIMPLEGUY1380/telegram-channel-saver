"""
Link downloader module.
Downloads videos and clips from URLs using embedded yt-dlp.
Equivalent to: yt-dlp -a links.txt -P "downloads" --download-archive "downloaded.txt" --ignore-errors
"""
import os
import logging
from typing import List, Optional, Callable, Dict, Any
from urllib.parse import urlparse

import yt_dlp

from src.config import (
    DEFAULT_LINKS_FILE,
    DEFAULT_DOWNLOADS_DIR,
    DEFAULT_ARCHIVE_FILE,
    logger
)


def clean_url(line: str) -> Optional[str]:
    """
    Clean and validate a URL from a line of text.

    Args:
        line: Raw line text

    Returns:
        Optional[str]: Cleaned URL or None if invalid/comment/empty
    """
    if not line:
        return None

    cleaned = line.strip()
    if not cleaned or cleaned.startswith('#'):
        return None

    # Strip inline comments if separated by whitespace
    if ' #' in cleaned:
        cleaned = cleaned.split(' #', 1)[0].strip()

    parsed = urlparse(cleaned)
    if parsed.scheme in ('http', 'https', 'ftp') and parsed.netloc:
        return cleaned

    return None


def parse_links_file(file_path: str) -> List[str]:
    """
    Read URLs from a links file, ignoring empty lines and comments.

    Args:
        file_path: Path to text file containing links

    Returns:
        List[str]: List of valid URLs

    Raises:
        FileNotFoundError: If the file does not exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Links file not found: {file_path}")

    urls = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            url = clean_url(line)
            if url:
                urls.append(url)

    return urls


def get_archive_entries(archive_file: str = DEFAULT_ARCHIVE_FILE) -> List[str]:
    """
    Read recorded video IDs from download archive.

    Args:
        archive_file: Path to archive file

    Returns:
        List[str]: List of archive entry strings
    """
    if not os.path.exists(archive_file):
        return []

    entries = []
    try:
        with open(archive_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    entries.append(stripped)
    except OSError as e:
        logger.warning(f"Could not read archive file {archive_file}: {e}")

    return entries


def get_ydl_options(
    output_dir: str = DEFAULT_DOWNLOADS_DIR,
    archive_file: str = DEFAULT_ARCHIVE_FILE,
    ignore_errors: bool = True,
    quiet: bool = False,
    progress_hook: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Build yt-dlp configuration options matching CLI flags.

    Args:
        output_dir: Output folder for downloaded files (-P)
        archive_file: File recording downloaded IDs (--download-archive)
        ignore_errors: Whether to continue on errors (--ignore-errors)
        quiet: Suppress extra logging
        progress_hook: Optional callback for download progress

    Returns:
        Dict[str, Any]: Options dictionary for YoutubeDL
    """
    os.makedirs(output_dir, exist_ok=True)

    options: Dict[str, Any] = {
        'paths': {'home': output_dir},
        'download_archive': archive_file,
        'ignoreerrors': ignore_errors,
        'outtmpl': os.path.join(output_dir, '%(title)s [%(id)s].%(ext)s'),
        'no_warnings': False,
        'quiet': quiet,
    }

    if progress_hook:
        options['progress_hooks'] = [progress_hook]

    return options


def download_urls(
    urls: List[str],
    output_dir: str = DEFAULT_DOWNLOADS_DIR,
    archive_file: str = DEFAULT_ARCHIVE_FILE,
    ignore_errors: bool = True,
    progress_hook: Optional[Callable] = None,
    ydl_class: Any = None
) -> Dict[str, Any]:
    """
    Download video/clip media from a list of URLs using embedded yt-dlp.

    Args:
        urls: List of video URLs
        output_dir: Destination directory
        archive_file: Archive file path
        ignore_errors: Continue on download errors
        progress_hook: Progress callback
        ydl_class: YoutubeDL class override (for testing)

    Returns:
        Dict[str, Any]: Summary containing total, status, and output directory
    """
    if not urls:
        return {
            'success': True,
            'total': 0,
            'new_downloads': 0,
            'output_dir': output_dir,
            'archive_file': archive_file,
            'error': None
        }

    opts = get_ydl_options(
        output_dir=output_dir,
        archive_file=archive_file,
        ignore_errors=ignore_errors,
        progress_hook=progress_hook
    )

    downloader = ydl_class or yt_dlp.YoutubeDL
    initial_archive_count = len(get_archive_entries(archive_file))

    try:
        with downloader(opts) as ydl:
            exit_code = ydl.download(urls)

        final_archive_count = len(get_archive_entries(archive_file))
        new_downloads = max(0, final_archive_count - initial_archive_count)

        return {
            'success': exit_code == 0 or ignore_errors,
            'total': len(urls),
            'new_downloads': new_downloads,
            'output_dir': output_dir,
            'archive_file': archive_file,
            'error': None
        }
    except Exception as e:
        logger.error(f"Error during video download: {e}")
        return {
            'success': False,
            'total': len(urls),
            'new_downloads': 0,
            'output_dir': output_dir,
            'archive_file': archive_file,
            'error': str(e)
        }


def download_from_file(
    file_path: str = DEFAULT_LINKS_FILE,
    output_dir: str = DEFAULT_DOWNLOADS_DIR,
    archive_file: str = DEFAULT_ARCHIVE_FILE,
    ignore_errors: bool = True,
    ydl_class: Any = None
) -> Dict[str, Any]:
    """
    Download videos from URLs listed in a text file.

    Args:
        file_path: Path to links file
        output_dir: Destination directory
        archive_file: Archive file path
        ignore_errors: Continue on errors
        ydl_class: YoutubeDL class override

    Returns:
        Dict[str, Any]: Download operation summary
    """
    try:
        urls = parse_links_file(file_path)
    except FileNotFoundError as e:
        return {
            'success': False,
            'total': 0,
            'new_downloads': 0,
            'output_dir': output_dir,
            'archive_file': archive_file,
            'error': str(e)
        }

    return download_urls(
        urls=urls,
        output_dir=output_dir,
        archive_file=archive_file,
        ignore_errors=ignore_errors,
        ydl_class=ydl_class
    )


def interactive_download_links():
    """Interactive console UI for downloading clips via yt-dlp."""
    print("\n" + "=" * 50)
    print("Video/Clip Downloader (embedded yt-dlp)")
    print("=" * 50)
    print("1. Download from links file (e.g. links.txt)")
    print("2. Download a single URL")
    print("3. View download archive (downloaded.txt)")
    print("4. Back to main menu")

    choice = input("\nEnter choice (1-4): ").strip()
    if choice == '1':
        _handle_file_download()
    elif choice == '2':
        _handle_single_url_download()
    elif choice == '3':
        _handle_view_archive()


def _handle_file_download():
    """Handle interactive file download workflow."""
    default_prompt = f" [{DEFAULT_LINKS_FILE}]"
    file_path = input(f"\nEnter links file path{default_prompt}: ").strip() or DEFAULT_LINKS_FILE

    if not os.path.exists(file_path):
        print(f"\nError: File not found: {file_path}")
        create = input(f"Would you like to create an empty '{file_path}'? (y/N): ").strip().lower()
        if create == 'y':
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# Add one video/clip link per line:\n")
            print(f"Created '{file_path}'. Please add links to it and run this option again.")
        return

    output_dir = input(f"Enter download directory [{DEFAULT_DOWNLOADS_DIR}]: ").strip() or DEFAULT_DOWNLOADS_DIR
    archive_file = input(f"Enter archive file [{DEFAULT_ARCHIVE_FILE}]: ").strip() or DEFAULT_ARCHIVE_FILE

    print(f"\nReading links from {file_path}...")
    try:
        urls = parse_links_file(file_path)
        print(f"Found {len(urls)} valid URL(s). Starting download...")
        result = download_urls(urls, output_dir=output_dir, archive_file=archive_file)
        _print_download_summary(result)
    except Exception as e:
        print(f"\nDownload failed: {e}")


def _handle_single_url_download():
    """Handle single URL download workflow."""
    url = input("\nEnter video URL: ").strip()
    cleaned = clean_url(url)
    if not cleaned:
        print("\nInvalid URL format.")
        return

    output_dir = input(f"Enter download directory [{DEFAULT_DOWNLOADS_DIR}]: ").strip() or DEFAULT_DOWNLOADS_DIR
    archive_file = input(f"Enter archive file [{DEFAULT_ARCHIVE_FILE}]: ").strip() or DEFAULT_ARCHIVE_FILE

    print(f"\nDownloading: {cleaned}")
    result = download_urls([cleaned], output_dir=output_dir, archive_file=archive_file)
    _print_download_summary(result)


def _handle_view_archive():
    """Display entries currently in download archive."""
    archive_file = input(f"\nEnter archive file [{DEFAULT_ARCHIVE_FILE}]: ").strip() or DEFAULT_ARCHIVE_FILE
    entries = get_archive_entries(archive_file)
    print(f"\nDownload Archive ({archive_file}): {len(entries)} item(s) recorded")
    print("-" * 50)
    for i, entry in enumerate(entries[-20:], 1):
        print(f"{i:2d}. {entry}")
    if len(entries) > 20:
        print(f"... and {len(entries) - 20} older items.")


def _print_download_summary(result: Dict[str, Any]):
    """Print download execution summary."""
    print("\n" + "-" * 40)
    print("Download Summary:")
    print(f"  Total URLs:      {result.get('total', 0)}")
    print(f"  New Downloads:   {result.get('new_downloads', 0)}")
    print(f"  Output Folder:   {result.get('output_dir')}")
    print(f"  Archive File:    {result.get('archive_file')}")
    if result.get('error'):
        print(f"  Errors:          {result.get('error')}")
    else:
        print("  Status:          Completed successfully")
    print("-" * 40)

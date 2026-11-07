"""
Unit tests for src/link_downloader.py
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.link_downloader import (
    clean_url,
    parse_links_file,
    get_archive_entries,
    get_ydl_options,
    download_urls,
    download_from_file
)


class DummyYoutubeDL:
    """Mock YoutubeDL class for testing."""
    last_instance = None

    def __init__(self, params):
        self.params = params
        self.downloaded_urls = []
        DummyYoutubeDL.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def download(self, urls):
        self.downloaded_urls.extend(urls)
        # Simulate writing to archive file if specified
        archive_path = self.params.get('download_archive')
        if archive_path:
            with open(archive_path, 'a', encoding='utf-8') as f:
                for url in urls:
                    f.write(f"dummy {url}\n")
        return 0


class TestLinkDownloader(unittest.TestCase):
    """Test suite for link downloader functions."""

    def test_clean_url_valid(self):
        """Test valid URLs are parsed and preserved."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertEqual(clean_url(url), url)

        http_url = "http://example.com/video.mp4"
        self.assertEqual(clean_url(http_url), http_url)

    def test_clean_url_comments_and_whitespace(self):
        """Test comment lines and inline comments are handled."""
        self.assertIsNone(clean_url("# This is a comment"))
        self.assertIsNone(clean_url("   # Indented comment"))
        self.assertIsNone(clean_url(""))
        self.assertIsNone(clean_url("   \n\t  "))
        self.assertIsNone(clean_url("not a url at all"))

        # Inline comment
        with_comment = "https://youtube.com/watch?v=123 # Great clip"
        self.assertEqual(clean_url(with_comment), "https://youtube.com/watch?v=123")

    def test_parse_links_file(self):
        """Test parsing URLs from file."""
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as f:
            f.write("# Header comment\n")
            f.write("https://example.com/clip1.mp4\n")
            f.write("\n")
            f.write("  # middle comment\n")
            f.write("https://example.com/clip2.mp4 # inline comment\n")
            f.write("invalid_text_line\n")
            temp_path = f.name

        try:
            urls = parse_links_file(temp_path)
            self.assertEqual(len(urls), 2)
            self.assertEqual(urls[0], "https://example.com/clip1.mp4")
            self.assertEqual(urls[1], "https://example.com/clip2.mp4")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_parse_links_file_not_found(self):
        """Test FileNotFoundError is raised for non-existent file."""
        with self.assertRaises(FileNotFoundError):
            parse_links_file("non_existent_file_xyz_123.txt")

    def test_get_ydl_options(self):
        """Test YoutubeDL options builder matches required CLI parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = os.path.join(temp_dir, "archive.txt")
            downloads = os.path.join(temp_dir, "downloads")

            opts = get_ydl_options(
                output_dir=downloads,
                archive_file=archive,
                ignore_errors=True,
                quiet=True
            )

            self.assertEqual(opts['paths']['home'], downloads)
            self.assertEqual(opts['download_archive'], archive)
            self.assertTrue(opts['ignoreerrors'])
            self.assertTrue(opts['quiet'])
            self.assertTrue(os.path.exists(downloads))

    def test_download_urls_empty(self):
        """Test downloading with empty URL list."""
        result = download_urls([])
        self.assertTrue(result['success'])
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['new_downloads'], 0)

    def test_download_urls_with_dummy_ydl(self):
        """Test downloading calls YoutubeDL and tracks downloads."""
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = os.path.join(temp_dir, "downloaded.txt")
            downloads = os.path.join(temp_dir, "downloads")
            urls = ["https://example.com/1", "https://example.com/2"]

            result = download_urls(
                urls=urls,
                output_dir=downloads,
                archive_file=archive,
                ignore_errors=True,
                ydl_class=DummyYoutubeDL
            )

            self.assertTrue(result['success'])
            self.assertEqual(result['total'], 2)
            self.assertEqual(result['new_downloads'], 2)
            self.assertEqual(len(get_archive_entries(archive)), 2)

    def test_download_from_file_integration(self):
        """Test end-to-end download from file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            links_file = os.path.join(temp_dir, "links.txt")
            archive = os.path.join(temp_dir, "downloaded.txt")
            downloads = os.path.join(temp_dir, "downloads")

            with open(links_file, 'w', encoding='utf-8') as f:
                f.write("https://example.com/video1\n")
                f.write("https://example.com/video2\n")

            result = download_from_file(
                file_path=links_file,
                output_dir=downloads,
                archive_file=archive,
                ignore_errors=True,
                ydl_class=DummyYoutubeDL
            )

            self.assertTrue(result['success'])
            self.assertEqual(result['total'], 2)
            self.assertEqual(result['new_downloads'], 2)

    def test_download_from_file_missing(self):
        """Test download from missing file reports failure gracefully."""
        result = download_from_file("missing_links_test.txt")
        self.assertFalse(result['success'])
        self.assertIn("not found", result['error'].lower())


if __name__ == '__main__':
    unittest.main()

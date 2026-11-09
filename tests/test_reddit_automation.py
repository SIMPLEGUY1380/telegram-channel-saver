"""
Unit tests for Reddit video automation and scheduling.
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, date, time, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from src.reddit_feed import (
    normalize_subreddit,
    extract_video_url,
    parse_atom_entries,
    filter_new_posts,
    load_seen_posts,
    save_seen_posts
)
from src.reddit_downloader import (
    get_pending_videos,
    append_links_to_file
)
from src.reddit_scheduler import (
    get_channel_schedule_summary,
    calculate_available_slots,
    schedule_video_file,
    run_reddit_automation_once
)


class TestRedditFeed(unittest.TestCase):
    """Test Reddit feed parsing and normalization."""

    def test_normalize_subreddit(self):
        self.assertEqual(normalize_subreddit('https://www.reddit.com/r/tits/'), 'tits')
        self.assertEqual(normalize_subreddit('https://reddit.com/r/boobs'), 'boobs')
        self.assertEqual(normalize_subreddit('r/amazingtits'), 'amazingtits')
        self.assertEqual(normalize_subreddit('BestTits/'), 'BestTits')
        self.assertEqual(normalize_subreddit('B_Cups'), 'B_Cups')
        self.assertEqual(normalize_subreddit(''), '')

    def test_extract_video_url(self):
        # RedGIFs
        html1 = '<p><a href="https://redgifs.com/watch/cookedimpassionedkoala">[link]</a></p>'
        self.assertEqual(extract_video_url(html1), 'https://redgifs.com/watch/cookedimpassionedkoala')

        # v.redd.it
        html2 = '<span><a href="https://v.redd.it/abc123456">[link]</a></span>'
        self.assertEqual(extract_video_url(html2), 'https://v.redd.it/abc123456')

        # Static photo - should return None
        html3 = '<p><a href="https://i.redd.it/photo123.jpg">[link]</a></p>'
        self.assertIsNone(extract_video_url(html3))

        # Imgur gifv converted to mp4
        html4 = '<a href="https://i.imgur.com/sample.gifv">link</a>'
        self.assertEqual(extract_video_url(html4), 'https://i.imgur.com/sample.mp4')

    def test_parse_atom_entries(self):
        atom_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>t3_post123</id>
            <title>Video Post Title</title>
            <link href="https://reddit.com/r/tits/comments/post123"/>
            <content type="html">&lt;a href="https://redgifs.com/watch/mytestvideo"&gt;link&lt;/a&gt;</content>
            <updated>2026-11-07T10:00:00+00:00</updated>
          </entry>
          <entry>
            <id>t3_photo456</id>
            <title>Photo Post</title>
            <link href="https://reddit.com/r/tits/comments/photo456"/>
            <content type="html">&lt;a href="https://i.redd.it/photo.jpg"&gt;link&lt;/a&gt;</content>
          </entry>
        </feed>"""

        posts = parse_atom_entries(atom_xml)
        # Should only parse the video post, skipping the photo
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]['id'], 'post123')
        self.assertEqual(posts[0]['title'], 'Video Post Title')
        self.assertEqual(posts[0]['video_url'], 'https://redgifs.com/watch/mytestvideo')

    def test_filter_new_posts(self):
        posts = [
            {'id': 'p1', 'title': 'Post 1'},
            {'id': 'p2', 'title': 'Post 2'},
            {'id': 'p3', 'title': 'Post 3'}
        ]
        seen = {'p1', 'p3'}
        new_posts = filter_new_posts(posts, seen)
        self.assertEqual(len(new_posts), 1)
        self.assertEqual(new_posts[0]['id'], 'p2')


class TestRedditSchedulerSlots(unittest.TestCase):
    """Test channel inspection and scheduling slot calculations."""

    def setUp(self):
        # Fixed baseline time: 2026-11-07 10:00:00 UTC
        self.now = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)
        self.tomorrow = date(2026, 11, 8)

    def test_empty_schedule_allocates_midnight_and_eight_and_sixteen(self):
        """When schedule is empty, allocate 3 slots starting at midnight tomorrow."""
        existing = {}
        slots = calculate_available_slots(
            existing_schedule=existing,
            count_needed=3,
            start_date=self.tomorrow,
            now_dt=self.now
        )
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0], datetime(2026, 11, 8, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(slots[1], datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(slots[2], datetime(2026, 11, 8, 16, 0, 0, tzinfo=timezone.utc))

    def test_full_day_moves_forward_to_next_day(self):
        """If a day already has 3 posts scheduled, move forward to the following day."""
        existing = {
            self.tomorrow: [
                datetime(2026, 11, 8, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 8, 16, 0, 0, tzinfo=timezone.utc),
            ]
        }
        slots = calculate_available_slots(
            existing_schedule=existing,
            count_needed=3,
            start_date=self.tomorrow,
            now_dt=self.now
        )
        self.assertEqual(len(slots), 3)
        # All slots should be on Nov 9
        self.assertEqual(slots[0].date(), date(2026, 11, 9))
        self.assertEqual(slots[0], datetime(2026, 11, 9, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(slots[1], datetime(2026, 11, 9, 8, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(slots[2], datetime(2026, 11, 9, 16, 0, 0, tzinfo=timezone.utc))

    def test_partially_full_day_fills_remaining_slots_and_advances(self):
        """If a day has 1 post scheduled, fill the remaining 2 slots and advance for remaining."""
        existing = {
            self.tomorrow: [
                datetime(2026, 11, 8, 0, 0, 0, tzinfo=timezone.utc)  # midnight already taken
            ]
        }
        slots = calculate_available_slots(
            existing_schedule=existing,
            count_needed=3,
            start_date=self.tomorrow,
            now_dt=self.now
        )
        self.assertEqual(len(slots), 3)
        # First 2 slots go to Nov 8 at 08:00 and 16:00
        self.assertEqual(slots[0], datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(slots[1], datetime(2026, 11, 8, 16, 0, 0, tzinfo=timezone.utc))
        # 3rd slot advances to Nov 9 at 00:00 (midnight)
        self.assertEqual(slots[2], datetime(2026, 11, 9, 0, 0, 0, tzinfo=timezone.utc))

    def test_multiple_full_days_moves_forward_to_first_open_day(self):
        """If Nov 8 and Nov 9 are both full, jump to Nov 10."""
        existing = {
            date(2026, 11, 8): [
                datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc),
            ],
            date(2026, 11, 9): [
                datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc),
            ]
        }
        slots = calculate_available_slots(
            existing_schedule=existing,
            count_needed=2,
            start_date=self.tomorrow,
            now_dt=self.now
        )
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0], datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(slots[1], datetime(2026, 11, 10, 8, 0, 0, tzinfo=timezone.utc))


class TestRedditAutomationExecution(unittest.IsolatedAsyncioTestCase):
    """Test full execution cycle with mock Telethon client and yt-dlp."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.pending_dir = os.path.join(self.test_dir, 'pending')
        self.scheduled_dir = os.path.join(self.test_dir, 'scheduled')
        os.makedirs(self.pending_dir, exist_ok=True)
        os.makedirs(self.scheduled_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch('src.reddit_scheduler.REDDIT_PENDING_DIR')
    @patch('src.reddit_scheduler.REDDIT_SCHEDULED_DIR')
    async def test_run_reddit_automation_once(self, mock_sched_dir, mock_pend_dir):
        mock_pend_dir.__str__.return_value = self.pending_dir
        mock_sched_dir.__str__.return_value = self.scheduled_dir

        # Create 2 dummy video files in pending
        v1 = os.path.join(self.pending_dir, 'vid1.mp4')
        v2 = os.path.join(self.pending_dir, 'vid2.mp4')
        with open(v1, 'wb') as f: f.write(b'video1')
        with open(v2, 'wb') as f: f.write(b'video2')

        # Mock telethon client
        client = AsyncMock()
        client.send_file = AsyncMock()
        client.iter_messages = MagicMock()

        # Mock no existing scheduled messages
        async def mock_iter(*args, **kwargs):
            if False: yield None
        client.iter_messages.return_value = mock_iter()

        db = {'active_channel': {'id': -100999, 'title': 'Test Channel'}}

        with patch('src.reddit_scheduler.fetch_subreddit_posts', return_value=[]), \
             patch('src.reddit_scheduler.REDDIT_PENDING_DIR', self.pending_dir), \
             patch('src.reddit_scheduler.REDDIT_SCHEDULED_DIR', self.scheduled_dir):

            res = await run_reddit_automation_once(client, db, 'test_db.json')

            self.assertTrue(res['success'])
            self.assertEqual(res['scheduled'], 2)
            self.assertEqual(client.send_file.call_count, 2)

            # Check that caption is None (no caption)
            first_call_kwargs = client.send_file.call_args_list[0].kwargs
            self.assertIsNone(first_call_kwargs['caption'])

            # Verify files were moved to scheduled
            self.assertFalse(os.path.exists(v1))
            self.assertFalse(os.path.exists(v2))
            self.assertTrue(os.path.exists(os.path.join(self.scheduled_dir, 'vid1.mp4')))
            self.assertTrue(os.path.exists(os.path.join(self.scheduled_dir, 'vid2.mp4')))

    async def test_schedule_video_file_over_5mb(self):
        """Test that schedule_video_file uses 720p optimized video and replaces original."""
        client = AsyncMock()
        client.send_file = AsyncMock()
        sched_time = datetime(2026, 11, 9, 8, 0, 0)

        v_orig = os.path.join(self.pending_dir, 'heavy.mp4')
        with open(v_orig, 'wb') as f:
            f.write(b"heavy_original_bytes")

        v_opt = os.path.join(self.pending_dir, 'heavy_opt.mp4')
        with open(v_opt, 'wb') as f:
            f.write(b"optimized_720p_bytes")

        with patch('src.reddit_scheduler.optimize_video_for_upload', return_value=(v_opt, True)):
            success, err = await schedule_video_file(client, "12345", v_orig, sched_time)
            self.assertTrue(success)
            self.assertIsNone(err)

            # send_file called with optimized file and supports_streaming=True
            client.send_file.assert_awaited_once_with(
                "12345",
                file=v_opt,
                caption=None,
                schedule=sched_time,
                supports_streaming=True
            )

            # Original pending path was replaced with the optimized 720p content
            self.assertTrue(os.path.exists(v_orig))
            with open(v_orig, 'rb') as f:
                content = f.read()
            self.assertEqual(content, b"optimized_720p_bytes")
            self.assertFalse(os.path.exists(v_opt))


if __name__ == '__main__':
    unittest.main()

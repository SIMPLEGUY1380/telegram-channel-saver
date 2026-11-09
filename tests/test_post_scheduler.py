"""
Unit tests for src/post_scheduler.py
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.post_scheduler import (
    parse_schedule_time,
    validate_schedule_time,
    clean_filename_caption,
    find_media_files,
    schedule_text_post,
    schedule_media_post,
    batch_schedule_media,
    delete_scheduled_posts,
    record_scheduled_post
)


class TestPostScheduler(unittest.TestCase):
    """Test suite for post scheduler functions."""

    def setUp(self):
        self.fixed_now = datetime(2026, 11, 7, 12, 0, 0)

    def test_parse_schedule_time_relative_minutes(self):
        """Test relative minutes parsing."""
        dt, err = parse_schedule_time("30m", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now + timedelta(minutes=30))

        dt, err = parse_schedule_time("+45m", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now + timedelta(minutes=45))

        # Bare number defaults to minutes
        dt, err = parse_schedule_time("15", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now + timedelta(minutes=15))

    def test_parse_schedule_time_relative_hours_and_days(self):
        """Test relative hours and days."""
        dt, err = parse_schedule_time("2h", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now + timedelta(hours=2))

        dt, err = parse_schedule_time("1d", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now + timedelta(days=1))

    def test_parse_schedule_time_hh_mm(self):
        """Test HH:MM parsing."""
        # 14:30 is in the afternoon, after 12:00 -> today
        dt, err = parse_schedule_time("14:30", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, datetime(2026, 11, 7, 14, 30, 0))

        # 09:30 is in the morning, before 12:00 -> tomorrow
        dt, err = parse_schedule_time("09:30", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, datetime(2026, 11, 8, 9, 30, 0))

    def test_parse_schedule_time_absolute_datetime(self):
        """Test absolute YYYY-MM-DD HH:MM parsing."""
        dt, err = parse_schedule_time("2026-12-25 18:00", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, datetime(2026, 12, 25, 18, 0, 0))

    def test_parse_schedule_time_immediate(self):
        """Test immediate schedule keyword."""
        dt, err = parse_schedule_time("now", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now)

        dt, err = parse_schedule_time("0", now_dt=self.fixed_now)
        self.assertIsNone(err)
        self.assertEqual(dt, self.fixed_now)

    def test_parse_schedule_time_invalid(self):
        """Test invalid inputs return error."""
        dt, err = parse_schedule_time("", now_dt=self.fixed_now)
        self.assertIsNotNone(err)
        self.assertIsNone(dt)

        dt, err = parse_schedule_time("invalid_random_string", now_dt=self.fixed_now)
        self.assertIsNotNone(err)
        self.assertIsNone(dt)

    def test_validate_schedule_time(self):
        """Test schedule limits validation."""
        # Less than 15 seconds in future -> invalid
        too_soon = self.fixed_now + timedelta(seconds=5)
        is_valid, err = validate_schedule_time(too_soon, now_dt=self.fixed_now)
        self.assertFalse(is_valid)
        self.assertIn("at least 15s", err)

        # 30 minutes in future -> valid
        valid_dt = self.fixed_now + timedelta(minutes=30)
        is_valid, err = validate_schedule_time(valid_dt, now_dt=self.fixed_now)
        self.assertTrue(is_valid)
        self.assertIsNone(err)

        # > 365 days -> invalid
        too_far = self.fixed_now + timedelta(days=370)
        is_valid, err = validate_schedule_time(too_far, now_dt=self.fixed_now)
        self.assertFalse(is_valid)
        self.assertIn("365 days", err)

    def test_clean_filename_caption(self):
        """Test generating clean captions from filenames."""
        name = "My_Awesome_Video [dQw4w9WgXcQ].mp4"
        cleaned = clean_filename_caption(name)
        self.assertEqual(cleaned, "My Awesome Video")

        simple = "simple_post.mov"
        self.assertEqual(clean_filename_caption(simple), "simple post")

    def test_find_media_files(self):
        """Test finding media files in a directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file1 = os.path.join(temp_dir, "clip1.mp4")
            file2 = os.path.join(temp_dir, "photo.jpg")
            file3 = os.path.join(temp_dir, "doc.txt")
            file4 = os.path.join(temp_dir, "audio.mp3")

            for p in (file1, file2, file3, file4):
                with open(p, 'w') as f:
                    f.write("content")

            found = find_media_files(temp_dir)
            basenames = [os.path.basename(p) for p in found]

            self.assertIn("clip1.mp4", basenames)
            self.assertIn("photo.jpg", basenames)
            self.assertIn("audio.mp3", basenames)
            self.assertNotIn("doc.txt", basenames)

    async def _async_test_schedule_text(self):
        """Async test for scheduling text post."""
        client = AsyncMock()
        client.send_message = AsyncMock(return_value=MagicMock(id=101))
        sched_time = self.fixed_now + timedelta(hours=1)

        result = await schedule_text_post(client, "12345", "Test message", sched_time)
        self.assertEqual(result.id, 101)
        client.send_message.assert_awaited_once_with(
            "12345",
            message="Test message",
            schedule=sched_time
        )

    def test_schedule_text_post(self):
        """Synchronous wrapper for schedule text test."""
        import asyncio
        asyncio.run(self._async_test_schedule_text())

    async def _async_test_batch_schedule_media(self):
        """Async test for batch scheduling media files."""
        client = AsyncMock()
        client.send_file = AsyncMock(return_value=MagicMock(id=202))

        with tempfile.TemporaryDirectory() as temp_dir:
            f1 = os.path.join(temp_dir, "v1.mp4")
            f2 = os.path.join(temp_dir, "v2.mp4")
            for f in (f1, f2):
                with open(f, 'w') as fp:
                    fp.write("dummy")

            start = self.fixed_now + timedelta(hours=1)
            result = await batch_schedule_media(
                client=client,
                entity="12345",
                file_paths=[f1, f2],
                start_time=start,
                interval_minutes=30,
                caption_mode="filename"
            )

            self.assertEqual(result['total'], 2)
            self.assertEqual(result['scheduled'], 2)
            self.assertEqual(client.send_file.await_count, 2)

    def test_batch_schedule_media(self):
        """Synchronous wrapper for batch schedule test."""
        import asyncio
        asyncio.run(self._async_test_batch_schedule_media())

    async def _async_test_schedule_media_post_over_5mb(self):
        """Async test for scheduling media post over 5MB triggering optimization."""
        client = AsyncMock()
        client.send_file = AsyncMock(return_value=MagicMock(id=303))
        sched_time = self.fixed_now + timedelta(hours=2)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as orig_f:
            orig_path = orig_f.name
            orig_f.write(b"data")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as opt_f:
            opt_path = opt_f.name
            opt_f.write(b"opt_data")

        with patch('src.post_scheduler.optimize_video_for_upload', return_value=(opt_path, True)):
            try:
                res = await schedule_media_post(client, "12345", orig_path, sched_time, caption="test")
                self.assertEqual(res.id, 303)
                client.send_file.assert_awaited_once_with(
                    "12345",
                    file=opt_path,
                    caption="test",
                    schedule=sched_time,
                    supports_streaming=True
                )
                # Verify temporary optimized file is cleaned up
                self.assertFalse(os.path.exists(opt_path))
            finally:
                if os.path.exists(orig_path):
                    os.remove(orig_path)
                if os.path.exists(opt_path):
                    os.remove(opt_path)

    def test_schedule_media_post_over_5mb(self):
        """Synchronous wrapper for schedule media over 5MB test."""
        import asyncio
        asyncio.run(self._async_test_schedule_media_post_over_5mb())

    def test_record_scheduled_post(self):
        """Test database recording of scheduled posts."""
        db = {}
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            db_path = f.name

        try:
            record_scheduled_post(db, db_path, "123456", {
                'id': 1,
                'type': 'text',
                'scheduled_date': '2026-11-07 14:00:00'
            })

            self.assertIn('scheduled_posts', db)
            self.assertIn('123456', db['scheduled_posts'])
            self.assertEqual(len(db['scheduled_posts']['123456']), 1)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == '__main__':
    unittest.main()

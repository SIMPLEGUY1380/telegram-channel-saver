"""
Unit tests for src/video_optimizer.py
"""
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from src.video_optimizer import (
    is_optimizable_media,
    check_ffmpeg_available,
    should_optimize_media,
    build_scale_filter,
    optimize_video_to_720,
    optimize_video_for_upload,
    cleanup_temp_file,
    OPTIMIZABLE_MEDIA_EXTENSIONS
)


class TestVideoOptimizer(unittest.TestCase):
    """Test suite for video optimization and quality logic."""

    def test_is_optimizable_media(self):
        """Test detection of video and gif extensions."""
        self.assertTrue(is_optimizable_media("video.mp4"))
        self.assertTrue(is_optimizable_media("clip.MOV"))
        self.assertTrue(is_optimizable_media("anim.gif"))
        self.assertTrue(is_optimizable_media("movie.webm"))
        self.assertTrue(is_optimizable_media("sample.mkv"))

        self.assertFalse(is_optimizable_media("image.jpg"))
        self.assertFalse(is_optimizable_media("photo.png"))
        self.assertFalse(is_optimizable_media("audio.mp3"))
        self.assertFalse(is_optimizable_media("doc.pdf"))
        self.assertFalse(is_optimizable_media(""))
        self.assertFalse(is_optimizable_media(None))

    def test_should_optimize_media(self):
        """Test threshold check for 5MB limit."""
        threshold = 5 * 1024 * 1024  # 5MB

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            small_path = f.name
            f.write(b"x" * 1024)  # 1 KB

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            large_path = f.name
            # Seek and write 1 byte at 5MB + 10 bytes to create a sparse file quickly
            f.seek(threshold + 10)
            f.write(b"1")

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            txt_path = f.name
            f.seek(threshold + 10)
            f.write(b"1")

        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            large_gif = f.name
            f.seek(threshold + 10)
            f.write(b"1")

        try:
            # Small video under 5MB -> False
            self.assertFalse(should_optimize_media(small_path, threshold_bytes=threshold))

            # Large video over 5MB -> True
            self.assertTrue(should_optimize_media(large_path, threshold_bytes=threshold))

            # Large non-video -> False
            self.assertFalse(should_optimize_media(txt_path, threshold_bytes=threshold))

            # Large GIF over 5MB -> True
            self.assertTrue(should_optimize_media(large_gif, threshold_bytes=threshold))

            # Non-existent file -> False
            self.assertFalse(should_optimize_media("non_existent_file.mp4", threshold_bytes=threshold))
        finally:
            for p in (small_path, large_path, txt_path, large_gif):
                if os.path.exists(p):
                    os.remove(p)

    def test_build_scale_filter(self):
        """Test FFmpeg scale filter syntax."""
        flt = build_scale_filter(720)
        self.assertIn("720", flt)
        self.assertIn("iw", flt)
        self.assertIn("ih", flt)
        self.assertIn("trunc(iw/2)*2", flt)
        self.assertIn("trunc(ih/2)*2", flt)

    @patch('src.video_optimizer.check_ffmpeg_available', return_value=False)
    def test_optimize_video_to_720_ffmpeg_missing(self, mock_ffmpeg):
        """Test behavior when FFmpeg is not installed."""
        result = optimize_video_to_720("test.mp4")
        self.assertIsNone(result)

    @patch('src.video_optimizer.check_ffmpeg_available', return_value=True)
    @patch('subprocess.run')
    def test_optimize_video_to_720_success(self, mock_run, mock_ffmpeg):
        """Test successful FFmpeg optimization."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as in_f:
            in_path = in_f.name
            in_f.write(b"source" * 1000)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out_f:
            out_path = out_f.name
            out_f.write(b"opt" * 500)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        try:
            res = optimize_video_to_720(in_path, output_path=out_path)
            self.assertEqual(res, out_path)
            self.assertTrue(mock_run.called)
        finally:
            cleanup_temp_file(in_path)
            cleanup_temp_file(out_path)

    @patch('src.video_optimizer.check_ffmpeg_available', return_value=True)
    @patch('subprocess.run')
    def test_optimize_video_to_720_failure(self, mock_run, mock_ffmpeg):
        """Test FFmpeg optimization failure handling."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as in_f:
            in_path = in_f.name
            in_f.write(b"data")

        out_path = in_path + "_out.mp4"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Encoding error")

        try:
            res = optimize_video_to_720(in_path, output_path=out_path)
            self.assertIsNone(res)
            self.assertFalse(os.path.exists(out_path))
        finally:
            cleanup_temp_file(in_path)
            cleanup_temp_file(out_path)

    def test_optimize_video_for_upload_under_threshold(self):
        """Files under threshold should not be optimized."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"small")
            f_path = f.name

        try:
            path_to_send, is_temp = optimize_video_for_upload(f_path, threshold_bytes=5 * 1024 * 1024)
            self.assertEqual(path_to_send, f_path)
            self.assertFalse(is_temp)
        finally:
            cleanup_temp_file(f_path)

    @patch('src.video_optimizer.optimize_video_to_720')
    def test_optimize_video_for_upload_over_threshold(self, mock_opt):
        """Files over threshold should be optimized and marked as temporary."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.seek(6 * 1024 * 1024)
            f.write(b"1")
            large_path = f.name

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as opt_f:
            opt_path = opt_f.name
            opt_f.write(b"optimized")

        mock_opt.return_value = opt_path

        try:
            path_to_send, is_temp = optimize_video_for_upload(large_path, threshold_bytes=5 * 1024 * 1024)
            self.assertEqual(path_to_send, opt_path)
            self.assertTrue(is_temp)
        finally:
            cleanup_temp_file(large_path)
            cleanup_temp_file(opt_path)

    def test_cleanup_temp_file(self):
        """Test safe removal of temporary files."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            t_path = f.name
            f.write(b"test")

        self.assertTrue(os.path.exists(t_path))
        cleanup_temp_file(t_path)
        self.assertFalse(os.path.exists(t_path))

        # Should not raise on non-existent file
        cleanup_temp_file("non_existent.tmp")
        cleanup_temp_file(None)


if __name__ == '__main__':
    unittest.main()

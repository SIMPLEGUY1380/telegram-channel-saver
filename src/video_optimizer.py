"""
Video and GIF optimizer module.
Provides upload-level FFmpeg optimization for media files exceeding size thresholds (e.g. > 5MB).
Scales content down to 720p (preserving aspect ratio) using H.264/AAC with faststart for streaming.
"""
import os
import shutil
import uuid
import logging
import subprocess
from typing import Tuple, Optional

from src.config import (
    VIDEO_QUALITY_THRESHOLD_BYTES,
    VIDEO_TARGET_RESOLUTION,
    FFMPEG_CRF,
    FFMPEG_PRESET,
    OPTIMIZED_TEMP_DIR,
    logger
)

# Supported video and animation formats for FFmpeg processing
OPTIMIZABLE_MEDIA_EXTENSIONS = (
    '.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv', '.gif'
)


def is_optimizable_media(file_path: str) -> bool:
    """
    Check if a file has an extension matching optimizable video or GIF formats.

    Args:
        file_path: Path to the media file

    Returns:
        bool: True if file is a supported video/GIF, False otherwise
    """
    if not file_path:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in OPTIMIZABLE_MEDIA_EXTENSIONS


def check_ffmpeg_available() -> bool:
    """
    Check if the ffmpeg executable is available in system PATH.

    Returns:
        bool: True if ffmpeg command exists, False otherwise
    """
    return shutil.which('ffmpeg') is not None


def should_optimize_media(
    file_path: str,
    threshold_bytes: int = VIDEO_QUALITY_THRESHOLD_BYTES
) -> bool:
    """
    Determine if a media file should be optimized before upload.
    Files qualify if they exist, are supported videos/GIFs, and exceed threshold_bytes.

    Args:
        file_path: Path to the media file
        threshold_bytes: Size threshold in bytes (default: 5MB)

    Returns:
        bool: True if the file should be scaled/compressed, False otherwise
    """
    if not file_path or not os.path.isfile(file_path):
        return False

    if not is_optimizable_media(file_path):
        return False

    try:
        file_size = os.path.getsize(file_path)
        return file_size > threshold_bytes
    except OSError as e:
        logger.warning(f"Could not check size of {file_path}: {e}")
        return False


def build_scale_filter(target_res: int = VIDEO_TARGET_RESOLUTION) -> str:
    """
    Construct an FFmpeg video filter graph to scale content to target_res (e.g. 720p).
    - Preserves aspect ratio:
        * Landscape (iw >= ih): scales height to min(target_res, ih), width adjusts automatically (-2).
        * Portrait (iw < ih): scales width to min(target_res, iw), height adjusts automatically (-2).
    - Ensures dimensions are always even integers (trunc(iw/2)*2) as required by libx264/yuv420p.
    - Avoids upscaling files that are already lower than target_res.

    Args:
        target_res: Target resolution limit (default: 720)

    Returns:
        str: FFmpeg vf filter string
    """
    return (
        f"scale='w=if(gte(iw,ih),-2,min({target_res},iw)):"
        f"h=if(gte(iw,ih),min({target_res},ih),-2)',"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )


def optimize_video_to_720(
    file_path: str,
    output_path: Optional[str] = None,
    target_res: int = VIDEO_TARGET_RESOLUTION,
    crf: int = FFMPEG_CRF,
    preset: str = FFMPEG_PRESET
) -> Optional[str]:
    """
    Transcode and downscale a video or GIF to 720p MP4 using FFmpeg.
    Uses libx264 (yuv420p) and AAC audio with +faststart for immediate Telegram streaming.

    Args:
        file_path: Source file path
        output_path: Optional destination path. If None, auto-generated in OPTIMIZED_TEMP_DIR.
        target_res: Target bounding resolution (default: 720)
        crf: Constant Rate Factor quality parameter (default: 23)
        preset: FFmpeg x264 preset (default: 'fast')

    Returns:
        Optional[str]: Path to the generated optimized file, or None if transcoding failed
    """
    if not check_ffmpeg_available():
        logger.warning("FFmpeg executable not found in PATH. Skipping quality optimization.")
        return None

    os.makedirs(OPTIMIZED_TEMP_DIR, exist_ok=True)
    if not output_path:
        stem = os.path.splitext(os.path.basename(file_path))[0]
        uid = uuid.uuid4().hex[:8]
        output_path = os.path.join(OPTIMIZED_TEMP_DIR, f"opt_{uid}_{stem}.mp4")

    scale_filter = build_scale_filter(target_res)

    cmd = [
        'ffmpeg', '-y',
        '-i', file_path,
        '-map', '0:v:0',
        '-map', '0:a?',
        '-vf', scale_filter,
        '-c:v', 'libx264',
        '-crf', str(crf),
        '-preset', preset,
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        output_path
    ]

    try:
        orig_size = os.path.getsize(file_path)
        logger.info(
            f"Optimizing '{os.path.basename(file_path)}' ({orig_size / (1024 * 1024):.2f}MB > 5MB) "
            f"to {target_res}p..."
        )

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

        if result.returncode != 0:
            logger.error(
                f"FFmpeg failed (exit code {result.returncode}) while optimizing {file_path}:\n"
                f"{result.stderr[-500:] if result.stderr else 'No error output'}"
            )
            cleanup_temp_file(output_path)
            return None

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error(f"FFmpeg did not produce a valid output file at {output_path}")
            cleanup_temp_file(output_path)
            return None

        new_size = os.path.getsize(output_path)
        reduction = ((orig_size - new_size) / orig_size) * 100 if orig_size > 0 else 0
        logger.info(
            f"Successfully optimized '{os.path.basename(file_path)}' -> {target_res}p: "
            f"{orig_size / (1024 * 1024):.2f}MB to {new_size / (1024 * 1024):.2f}MB "
            f"({reduction:.1f}% reduction)"
        )
        return output_path

    except Exception as e:
        logger.error(f"Unexpected error during video optimization of {file_path}: {e}")
        cleanup_temp_file(output_path)
        return None


def optimize_video_for_upload(
    file_path: str,
    threshold_bytes: int = VIDEO_QUALITY_THRESHOLD_BYTES,
    target_res: int = VIDEO_TARGET_RESOLUTION
) -> Tuple[str, bool]:
    """
    Prepare a media file for upload to Telegram.
    If the file is a video or GIF exceeding threshold_bytes (>5MB), it is transcoded to 720p.
    Files under 5MB or non-video files are returned as-is without quality change.

    Args:
        file_path: Original media file path
        threshold_bytes: Threshold above which optimization triggers (default: 5MB)
        target_res: Target resolution (default: 720)

    Returns:
        Tuple[str, bool]: (path_to_upload, is_temporary_file)
            - If optimized: (temp_optimized_path, True)
            - If skipped or failed: (original_file_path, False)
    """
    if not should_optimize_media(file_path, threshold_bytes=threshold_bytes):
        return file_path, False

    optimized_path = optimize_video_to_720(file_path, target_res=target_res)
    if optimized_path and os.path.exists(optimized_path):
        return optimized_path, True

    # Fallback to original file if optimization failed
    logger.warning(f"Proceeding with original file '{os.path.basename(file_path)}' without quality change.")
    return file_path, False


def cleanup_temp_file(file_path: Optional[str]):
    """
    Safely delete a temporary file if it exists.

    Args:
        file_path: Path to file to delete
    """
    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError as e:
            logger.warning(f"Could not remove temporary file {file_path}: {e}")

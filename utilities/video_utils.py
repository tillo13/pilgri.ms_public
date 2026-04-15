"""
Video utilities for Pilgrims - MP4 to GIF conversion and video processing
"""

import subprocess
import tempfile
import requests
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

def download_video(url: str, output_path: str) -> bool:
    """Download video from URL to local path"""
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(response.content)
        logger.info(f"Downloaded video to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        return False


def mp4_to_gif(mp4_path: str, gif_path: str, fps: int = 10, width: int = 480) -> bool:
    """
    Convert MP4 to GIF using ffmpeg

    Args:
        mp4_path: Path to input MP4 file
        gif_path: Path for output GIF file
        fps: Frames per second for GIF (lower = smaller file)
        width: Width in pixels (height auto-scaled)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Two-pass approach for better quality GIFs:
        # 1. Generate palette from video
        # 2. Use palette to create GIF

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as palette_file:
            palette_path = palette_file.name

        # Pass 1: Generate palette
        palette_cmd = [
            'ffmpeg', '-y', '-i', mp4_path,
            '-vf', f'fps={fps},scale={width}:-1:flags=lanczos,palettegen=stats_mode=diff',
            palette_path
        ]

        result = subprocess.run(palette_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Palette generation failed: {result.stderr}")
            return False

        # Pass 2: Create GIF using palette
        gif_cmd = [
            'ffmpeg', '-y', '-i', mp4_path, '-i', palette_path,
            '-lavfi', f'fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle',
            gif_path
        ]

        result = subprocess.run(gif_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"GIF creation failed: {result.stderr}")
            return False

        # Clean up palette
        os.unlink(palette_path)

        # Log file sizes
        mp4_size = os.path.getsize(mp4_path) / (1024 * 1024)
        gif_size = os.path.getsize(gif_path) / (1024 * 1024)
        logger.info(f"Converted {mp4_path} ({mp4_size:.2f}MB) -> {gif_path} ({gif_size:.2f}MB)")

        return True

    except Exception as e:
        logger.error(f"MP4 to GIF conversion failed: {e}")
        return False


def mp4_url_to_gif(video_url: str, output_gif_path: str, fps: int = 10, width: int = 480) -> bool:
    """
    Download MP4 from URL and convert to GIF

    Args:
        video_url: URL of MP4 video
        output_gif_path: Path for output GIF
        fps: Frames per second
        width: Width in pixels

    Returns:
        True if successful
    """
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if not download_video(video_url, tmp_path):
            return False

        return mp4_to_gif(tmp_path, output_gif_path, fps, width)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def process_video_for_email(video_url: str, save_dir: str, filename_base: str, fps: int = 10, width: int = 400):
    """
    Process a video URL for email use:
    1. Download MP4
    2. Convert to GIF
    3. Save both to specified directory

    Args:
        video_url: Replicate video URL
        save_dir: Directory to save files (e.g., 'static/files/video')
        filename_base: Base filename without extension (e.g., 'commander_discovery_123')
        fps: GIF frames per second
        width: GIF width in pixels

    Returns:
        dict with 'mp4_path', 'gif_path', 'mp4_size_mb', 'gif_size_mb' or None on failure
    """
    # Ensure directory exists
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    mp4_path = os.path.join(save_dir, f"{filename_base}.mp4")
    gif_path = os.path.join(save_dir, f"{filename_base}.gif")

    # Download MP4
    if not download_video(video_url, mp4_path):
        return None

    # Convert to GIF
    if not mp4_to_gif(mp4_path, gif_path, fps, width):
        return None

    return {
        'mp4_path': mp4_path,
        'gif_path': gif_path,
        'mp4_size_mb': os.path.getsize(mp4_path) / (1024 * 1024),
        'gif_size_mb': os.path.getsize(gif_path) / (1024 * 1024),
    }


def extract_thumbnail(mp4_path: str, output_path: str, timestamp: str = "00:00:02", width: int = 480, add_play_button: bool = True) -> bool:
    """
    Extract a single frame from an MP4 as a JPEG thumbnail, optionally with a centered play button overlay.

    Args:
        mp4_path: Path to input MP4 file
        output_path: Path for output JPEG file
        timestamp: Time to extract frame from (default 2 seconds in)
        width: Width of thumbnail (height auto-scaled)
        add_play_button: If True, composite a play button in the center (email-compatible)

    Returns:
        True if successful, False otherwise
    """
    try:
        # First extract the raw frame
        temp_frame = output_path + '.temp.jpg' if add_play_button else output_path

        cmd = [
            'ffmpeg', '-y', '-ss', timestamp, '-i', mp4_path,
            '-vframes', '1', '-vf', f'scale={width}:-1',
            '-q:v', '2',  # High quality JPEG
            temp_frame
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Thumbnail extraction failed: {result.stderr}")
            return False

        # Add play button overlay using PIL if requested
        if add_play_button:
            try:
                from PIL import Image, ImageDraw

                # Open the extracted frame
                img = Image.open(temp_frame)
                img_width, img_height = img.size

                # Create a transparent overlay for the play button
                overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                # Calculate center
                center_x = img_width // 2
                center_y = img_height // 2

                # Draw circle (play button background) - purple to match branding
                circle_radius = min(img_width, img_height) // 8  # Proportional to image
                circle_radius = max(35, min(circle_radius, 50))  # Clamp between 35-50px

                # Semi-transparent purple circle
                draw.ellipse(
                    [center_x - circle_radius, center_y - circle_radius,
                     center_x + circle_radius, center_y + circle_radius],
                    fill=(155, 89, 182, 230)  # #9b59b6 with alpha
                )

                # Draw triangle (play icon) - white
                triangle_size = circle_radius * 0.6
                # Offset slightly right to visually center the play triangle
                offset_x = triangle_size * 0.15
                triangle_points = [
                    (center_x - triangle_size * 0.4 + offset_x, center_y - triangle_size * 0.6),  # Top left
                    (center_x - triangle_size * 0.4 + offset_x, center_y + triangle_size * 0.6),  # Bottom left
                    (center_x + triangle_size * 0.6 + offset_x, center_y),  # Right point
                ]
                draw.polygon(triangle_points, fill=(255, 255, 255, 255))

                # Composite the overlay onto the original image
                img = img.convert('RGBA')
                img = Image.alpha_composite(img, overlay)

                # Convert back to RGB for JPEG and save
                img = img.convert('RGB')
                img.save(output_path, 'JPEG', quality=90)

                # Clean up temp file
                os.unlink(temp_frame)

                logger.info(f"Added play button overlay to thumbnail")

            except ImportError:
                logger.warning("PIL not available, saving thumbnail without play button")
                os.rename(temp_frame, output_path)
            except Exception as e:
                logger.warning(f"Failed to add play button, using raw thumbnail: {e}")
                if os.path.exists(temp_frame):
                    os.rename(temp_frame, output_path)

        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Extracted thumbnail: {output_path} ({size_kb:.1f}KB)")
        return True

    except Exception as e:
        logger.error(f"Thumbnail extraction failed: {e}")
        return False


def upload_video_to_gcs(mp4_path: str, user_id: int, video_type: str = "discovery") -> str:
    """
    Upload an MP4 video to GCS and return the public URL.

    Args:
        mp4_path: Local path to MP4 file
        user_id: User ID for naming
        video_type: Type of video (e.g., 'discovery', 'expedition')

    Returns:
        Public GCS URL or None on failure
    """
    try:
        from google.cloud import storage
        import time as time_module

        GCP_PROJECT_ID = "galactica-character-game"
        BUCKET_NAME = "galactica-pilgrim-assets"

        # Generate unique filename
        timestamp = int(time_module.time())
        blob_name = f"videos/{video_type}_{user_id}_{timestamp}.mp4"

        # Read file
        with open(mp4_path, 'rb') as f:
            file_data = f.read()

        # Upload to GCS (bucket has uniform access, so files are public via IAM policy)
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(file_data, content_type='video/mp4')

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
        logger.info(f"Uploaded video to GCS: {public_url}")
        return public_url

    except Exception as e:
        logger.error(f"GCS upload failed: {e}")
        return None


def upload_thumbnail_to_gcs(jpg_path: str, user_id: int, video_type: str = "discovery") -> str:
    """
    Upload a JPEG thumbnail to GCS and return the public URL.
    """
    try:
        from google.cloud import storage
        import time as time_module

        GCP_PROJECT_ID = "galactica-character-game"
        BUCKET_NAME = "galactica-pilgrim-assets"

        timestamp = int(time_module.time())
        blob_name = f"videos/thumb_{video_type}_{user_id}_{timestamp}.jpg"

        with open(jpg_path, 'rb') as f:
            file_data = f.read()

        # Upload to GCS (bucket has uniform access, so files are public via IAM policy)
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(file_data, content_type='image/jpeg')

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
        logger.info(f"Uploaded thumbnail to GCS: {public_url}")
        return public_url

    except Exception as e:
        logger.error(f"GCS thumbnail upload failed: {e}")
        return None


def get_user_video_data(user_id: int, commander_name: str = None):
    """
    Get video data for a user's FOMO email.

    AUTO-GENERATES a video if user doesn't have one - video is REQUIRED for all FOMO emails.

    Returns dict with thumbnail_url, video_url, captain_name — or None on failure.
    """
    from typing import Optional, Dict
    from utilities.postgres.core import db_cursor
    from utilities.depot_utils import get_latest_character_image
    from utilities.replicate_utils import FluxGenerator, animate_character_video

    with db_cursor() as cur:
        cur.execute("""
            SELECT gcs_url, commander_name
            FROM pilgrim.replicate_assets
            WHERE user_id = %s AND asset_type = 'character_video' AND is_deleted = false
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        row = cur.fetchone()

    if not row or not row.get('gcs_url'):
        logger.info(f"No video found for user {user_id} - auto-generating...")
        try:
            character_url, asset_id = get_latest_character_image(user_id)
            logger.info(f"Found commander image for user {user_id}: {character_url}")

            flux = FluxGenerator()
            video_url = animate_character_video(character_url, flux, user_id=user_id, asset_id=asset_id)

            if not video_url:
                logger.error(f"Failed to auto-generate video for user {user_id}")
                return None

            logger.info(f"Auto-generated video for user {user_id}: {video_url}")

            with db_cursor() as cur:
                cur.execute("""
                    SELECT commander_name FROM pilgrim.replicate_assets
                    WHERE id = %s
                """, (asset_id,))
                img_row = cur.fetchone()

            row = {
                'gcs_url': video_url,
                'commander_name': img_row.get('commander_name') if img_row else None
            }

        except Exception as e:
            logger.error(f"Failed to auto-generate video for user {user_id}: {e}")
            return None

    video_url = row['gcs_url']
    captain_name = commander_name or row.get('commander_name') or 'Captain'

    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_video:
            tmp_video_path = tmp_video.name

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_thumb:
            tmp_thumb_path = tmp_thumb.name

        if not download_video(video_url, tmp_video_path):
            logger.warning(f"Failed to download video for user {user_id}")
            return None

        if not extract_thumbnail(tmp_video_path, tmp_thumb_path, timestamp="00:00:02", width=480, add_play_button=True):
            logger.warning(f"Failed to extract thumbnail for user {user_id}")
            return None

        thumbnail_url = upload_thumbnail_to_gcs(tmp_thumb_path, user_id, video_type="fomo")

        if os.path.exists(tmp_video_path):
            os.unlink(tmp_video_path)
        if os.path.exists(tmp_thumb_path):
            os.unlink(tmp_thumb_path)

        if not thumbnail_url:
            logger.warning(f"Failed to upload thumbnail for user {user_id}")
            return None

        logger.info(f"Generated video thumbnail for user {user_id}: {thumbnail_url}")

        return {
            'thumbnail_url': thumbnail_url,
            'video_url': video_url,
            'captain_name': captain_name
        }

    except Exception as e:
        logger.error(f"Error generating video data for user {user_id}: {e}")
        return None

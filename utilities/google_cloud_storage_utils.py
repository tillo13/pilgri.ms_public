"""
Google Cloud Storage utilities for Galactica Pilgrims
Saves Replicate-generated images/videos to persistent GCS storage
"""
from google.cloud import storage
import requests
import logging
from datetime import datetime
import time
from io import BytesIO

logger = logging.getLogger(__name__)

# GCS Configuration
GCP_PROJECT_ID = "galactica-character-game"
BUCKET_NAME = "galactica-pilgrim-assets"

def upload_blob_from_url(source_url, destination_blob_name, content_type='image/png', max_retries=3):
    """
    Download from Replicate URL and upload to GCS with retry logic
    
    Args:
        source_url: Replicate URL (temporary, expires in ~24 hours)
        destination_blob_name: Path in GCS (e.g., 'characters/user123_12345.png')
        content_type: MIME type ('image/png', 'video/mp4', etc.)
        max_retries: Number of retry attempts
        
    Returns:
        Public GCS URL (permanent) or None if failed
    """
    import time as time_module
    
    for attempt in range(max_retries):
        download_start = time_module.time()
        try:
            logger.info(f"[{content_type}] Downloading from Replicate (attempt {attempt + 1}/{max_retries}): {source_url[:50]}...")
            
            # Download from Replicate with timeout
            response = requests.get(source_url, timeout=120)  # Increased timeout for videos
            response.raise_for_status()
            file_data = response.content
            
            download_time = time_module.time() - download_start
            file_size_mb = len(file_data) / (1024 * 1024)
            logger.info(f"[{content_type}] Downloaded {len(file_data):,} bytes ({file_size_mb:.2f} MB) in {download_time:.2f}s")
            
            upload_start = time_module.time()
            logger.info(f"[{content_type}] Starting GCS upload: {destination_blob_name}")
            
            # Upload to GCS
            storage_client = storage.Client(project=GCP_PROJECT_ID)
            bucket = storage_client.bucket(BUCKET_NAME)
            blob = bucket.blob(destination_blob_name)
            
            # Cache for 7 days (images are immutable — timestamped filenames)
            blob.cache_control = 'public, max-age=604800'
            blob.upload_from_string(
                file_data,
                content_type=content_type,
                predefined_acl=None,
                timeout=180  # 3 minute timeout for large files
            )
            
            upload_time = time_module.time() - upload_start
            logger.info(f"[{content_type}] GCS upload completed in {upload_time:.2f}s")
            
            # For uniform bucket-level access, files are public via bucket IAM policy
            public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"
            
            total_time = time_module.time() - download_start
            logger.info(f"✅ [{content_type}] TOTAL TIME: {total_time:.2f}s | URL: {public_url}")
            return public_url
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[{content_type}] Download error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"[{content_type}] Retrying in {wait_time}s...")
                time_module.sleep(wait_time)
            
        except Exception as e:
            logger.error(f"[{content_type}] GCS upload error (attempt {attempt + 1}): {e}")
            import traceback
            logger.error(f"[{content_type}] Traceback: {traceback.format_exc()}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"[{content_type}] Retrying in {wait_time}s...")
                time_module.sleep(wait_time)
    
    logger.error(f"[{content_type}] ❌ FAILED to save after {max_retries} attempts")
    return None


def create_thumbnail(image_data, max_width=400, quality=85):
    """
    Create a thumbnail from image data using Pillow.

    Args:
        image_data: Raw image bytes
        max_width: Maximum width for thumbnail (maintains aspect ratio)
        quality: JPEG quality (1-100)

    Returns:
        Thumbnail image bytes or None if failed
    """
    try:
        from PIL import Image

        # Open image from bytes
        img = Image.open(BytesIO(image_data))

        # Calculate new dimensions maintaining aspect ratio
        width, height = img.size
        if width <= max_width:
            # Already small enough
            return None

        ratio = max_width / width
        new_height = int(height * ratio)

        # Resize with high quality
        img_resized = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        # Convert to RGB if needed (for JPEG)
        if img_resized.mode in ('RGBA', 'P'):
            img_resized = img_resized.convert('RGB')

        # Save to bytes
        output = BytesIO()
        img_resized.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)

        return output.read()

    except ImportError:
        logger.warning("Pillow not installed, cannot create thumbnail")
        return None
    except Exception as e:
        logger.error(f"Error creating thumbnail: {e}")
        return None


def upload_blob_from_url_with_thumbnail(source_url, destination_blob_name, content_type='image/png',
                                        thumbnail_width=400, max_retries=3):
    """
    Download from URL, create thumbnail, and upload both to GCS.

    Args:
        source_url: Source image URL
        destination_blob_name: Path in GCS for full image
        content_type: MIME type
        thumbnail_width: Width for thumbnail
        max_retries: Number of retry attempts

    Returns:
        Dict with 'url' (full image) and 'thumbnail_url' (smaller version)
    """
    import time as time_module

    for attempt in range(max_retries):
        try:
            logger.info(f"Downloading image for thumbnail processing (attempt {attempt + 1})...")

            # Download image
            response = requests.get(source_url, timeout=120)
            response.raise_for_status()
            image_data = response.content

            file_size_kb = len(image_data) / 1024
            logger.info(f"Downloaded {file_size_kb:.1f} KB image")

            # Upload full image
            storage_client = storage.Client(project=GCP_PROJECT_ID)
            bucket = storage_client.bucket(BUCKET_NAME)

            blob = bucket.blob(destination_blob_name)
            blob.cache_control = 'public, max-age=604800'
            blob.upload_from_string(image_data, content_type=content_type, timeout=180)
            full_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"
            logger.info(f"Uploaded full image: {full_url}")

            # Create and upload thumbnail
            thumbnail_data = create_thumbnail(image_data, max_width=thumbnail_width)
            thumbnail_url = None

            if thumbnail_data:
                # Generate thumbnail blob name
                thumb_blob_name = destination_blob_name.replace('.png', '_thumb.jpg').replace('.jpg', '_thumb.jpg')
                if '_thumb_thumb' in thumb_blob_name:
                    thumb_blob_name = thumb_blob_name.replace('_thumb_thumb', '_thumb')

                thumb_blob = bucket.blob(thumb_blob_name)
                thumb_blob.cache_control = 'public, max-age=604800'
                thumb_blob.upload_from_string(thumbnail_data, content_type='image/jpeg', timeout=60)
                thumbnail_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{thumb_blob_name}"

                thumb_size_kb = len(thumbnail_data) / 1024
                logger.info(f"Uploaded thumbnail ({thumb_size_kb:.1f} KB): {thumbnail_url}")

            return {
                'url': full_url,
                'thumbnail_url': thumbnail_url
            }

        except Exception as e:
            logger.error(f"Error uploading with thumbnail (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time_module.sleep(2 ** attempt)

    return None


def save_character_image(replicate_url, user_id=None, commander_stats=None, commander_name=None):
    """
    Save character image from Replicate to GCS and record in database
    
    Args:
        replicate_url: Temporary Replicate URL
        user_id: User ID for organizing files (None for guest users)
        commander_stats: Dict with stats for this NEW commander
        commander_name: Optional display name
        
    Returns:
        dict with gcs_url, blob_name, asset_id
    """
    from utilities.postgres_utils import create_replicate_asset
    
    timestamp = int(datetime.now().timestamp())
    user_prefix = f"user{user_id}_" if user_id else "guest_"
    blob_name = f"characters/{user_prefix}{timestamp}.png"
    
    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')
    
    # Save to database WITH STATS
    asset_id = None
    if gcs_url:
        asset_id = create_replicate_asset(
            user_id=user_id,
            asset_type='character_image',
            replicate_url=replicate_url,
            gcs_url=gcs_url,
            gcs_blob_name=blob_name,
            is_original=True,
            replicate_model='black-forest-labs/flux-kontext-pro',
            content_type='image/png',
            commander_stats=commander_stats,  # ✅ SAVE STATS HERE
            commander_name=commander_name
        )
    
    return {
        'gcs_url': gcs_url if gcs_url else replicate_url,
        'blob_name': blob_name,
        'asset_id': asset_id
    }


def save_edited_image(replicate_url, user_id=None, edit_number=1, parent_asset_id=None, prompt=None):
    """
    Save edited character image from Replicate to GCS and record in database

    Args:
        replicate_url: Temporary Replicate URL
        user_id: User ID for organizing files
        edit_number: Which edit iteration this is
        parent_asset_id: ID of the parent asset
        prompt: Edit prompt used

    Returns:
        dict with gcs_url, blob_name, asset_id
    """
    from utilities.postgres_utils import create_replicate_asset, db_cursor

    timestamp = int(datetime.now().timestamp())
    user_prefix = f"user{user_id}_" if user_id else "guest_"
    blob_name = f"characters/{user_prefix}{timestamp}_edit{edit_number}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    # Get commander_name from parent asset to preserve it
    parent_commander_name = None
    if parent_asset_id:
        try:
            with db_cursor() as cur:
                cur.execute("""
                    SELECT commander_name FROM pilgrim.replicate_assets
                    WHERE id = %s AND is_deleted = false
                """, (parent_asset_id,))
                row = cur.fetchone()
                if row:
                    parent_commander_name = row.get('commander_name')
        except Exception as e:
            logger.warning(f"Could not get parent commander_name: {e}")

    # Save to database
    asset_id = None
    if gcs_url:
        asset_id = create_replicate_asset(
            user_id=user_id,
            asset_type='edited_image',
            replicate_url=replicate_url,
            gcs_url=gcs_url,
            gcs_blob_name=blob_name,
            prompt_used=prompt,
            edit_number=edit_number,
            parent_asset_id=parent_asset_id,
            replicate_model='black-forest-labs/flux-kontext-pro',
            content_type='image/png',
            commander_name=parent_commander_name  # Preserve commander name from parent
        )

    return {
        'gcs_url': gcs_url if gcs_url else replicate_url,
        'blob_name': blob_name,
        'asset_id': asset_id
    }

def save_character_video(replicate_url, user_id=None, character_asset_id=None):
    """
    Save character video from Replicate to GCS and record in database
    """
    from utilities.postgres_utils import create_replicate_asset
    import time as time_module
    
    start_time = time_module.time()
    logger.info(f"🎬 Starting video save process for user {user_id}")
    
    timestamp = int(datetime.now().timestamp())
    user_prefix = f"user{user_id}_" if user_id else "guest_"
    blob_name = f"videos/{user_prefix}{timestamp}.mp4"
    
    logger.info(f"🎬 Blob name: {blob_name}")
    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'video/mp4')
    
    if not gcs_url:
        logger.error(f"🎬 ❌ Video GCS upload failed, skipping database save")
        return {
            'gcs_url': replicate_url,
            'blob_name': blob_name,
            'asset_id': None
        }
    
    # Save to database
    logger.info(f"🎬 Saving to database...")
    db_start = time_module.time()
    
    asset_id = create_replicate_asset(
        user_id=user_id,
        asset_type='character_video',
        replicate_url=replicate_url,
        gcs_url=gcs_url,
        gcs_blob_name=blob_name,
        parent_asset_id=character_asset_id,
        replicate_model='wan-video/wan-2.2-i2v-fast',
        content_type='video/mp4'
    )
    
    db_time = time_module.time() - db_start
    total_time = time_module.time() - start_time
    
    logger.info(f"🎬 Database save completed in {db_time:.2f}s")
    logger.info(f"🎬 ✅ TOTAL VIDEO PROCESS TIME: {total_time:.2f}s | Asset ID: {asset_id}")
    
    return {
        'gcs_url': gcs_url,
        'blob_name': blob_name,
        'asset_id': asset_id
    }
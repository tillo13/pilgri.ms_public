##############################################################################
# FLUX IMAGE GENERATION - MANDATORY PROMPT PATTERN
##############################################################################
#
# ALL image generation MUST follow this exact pattern:
#
# "Cartoon video game item with bold outlines and stylized proportions:
#  [ITEM DESCRIPTION], isolated on red Martian terrain, vibrant colors
#  with reds and oranges reflecting Mars atmosphere, video game asset style"
#
# CRITICAL LORE REQUIREMENT:
# Items must look BUILT FROM MARTIAN MATERIALS - rocks, clay, crystals.
# NOT metallic Earth technology. Think: cobbled together from Mars terrain.
#
# KEY AESTHETIC PRINCIPLES:
# - ASYMMETRICAL & IMPERFECT: Mismatched parts, one side bulkier than other
# - Body: reddish-brown rocky Martian materials, clay-like textures
# - Accents: small subtle blue-purple crystal nodes (Sepolia shards) in crevices
# - Wheels/parts: compressed Martian stone, different sizes, irregular shapes
# - Overall: looks cobbled together from foreign alien materials not meant
#   for machinery - improvised, weathered, ancient geological appearance
#
# Example (rover level 3 - APPROVED STYLE):
# "Cartoon video game item with bold outlines and stylized proportions:
#  asymmetrical six-wheeled Mars rover with mismatched wheels of different
#  sizes carved from compressed Martian stone, body made of irregularly
#  stacked sedimentary rock slabs and iron-clay chunks fitted together
#  imperfectly, one side bulkier than the other, lopsided crystalline
#  sensor array on top like natural quartz formations, segmented stone
#  robotic arm with uneven rocky joints, weathered cracked surfaces showing
#  ancient geological layers, subtle small blue-purple Sepolia crystal nodes
#  embedded unevenly in crevices, looks cobbled together from foreign alien
#  terrain materials not meant for machinery, deep rusty red and burnt
#  orange color palette with dust weathering, isolated on red Martian
#  terrain, vibrant colors with reds and oranges reflecting Mars atmosphere,
#  video game asset style"
#
# TWO-STEP PROCESS FOR NEW ITEMS:
# 1. Send existing approved image to Claude Haiku to describe it in detail
# 2. Ask Claude to create upgraded prompt preserving that aesthetic
#
# USE KONTEXT FOR PROGRESSIVE UPGRADES - chained edits compound beautifully!
# Lv1→Lv10 progression shows gradual Mars material evolution with crystals.
# See tools/test_kontext_progression.py for working examples.
#
##############################################################################

##############################################################################
# IMPORTS
##############################################################################

import os
import replicate
import base64
import logging
import time
import requests
from PIL import Image, ImageOps
from io import BytesIO
from google.cloud import secretmanager
from dotenv import load_dotenv
from config import (
    PROJECT_ID, FLUX_MODEL, WAN_VIDEO_MODEL, REPLICATE_TOKEN_ID,
    STANDALONE_CARTOON_PROMPT, VIDEO_ANIMATION_PROMPT,
    MAX_SPEED, MIN_FRAMES, LOW_RESOLUTION, FAST_SAMPLE_SHIFT, STANDARD_FPS,
    MAX_RETRIES, RETRY_DELAY, BACKOFF_MULTIPLIER
)

# Load .env file for local development
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

##############################################################################
# SECRET MANAGEMENT
##############################################################################

_secrets_cache = {}
_sm_client = None

def get_secret(secret_id, project_id=None):
    env_value = os.getenv(secret_id)
    if env_value:
        return env_value
    project = project_id or PROJECT_ID
    cache_key = f"{project}:{secret_id}"
    if cache_key in _secrets_cache:
        return _secrets_cache[cache_key]
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    response = _sm_client.access_secret_version(request={"name": name})
    val = response.payload.data.decode('UTF-8')
    _secrets_cache[cache_key] = val
    return val

##############################################################################
# FLUX GENERATOR CLASS
##############################################################################

class FluxGenerator:
    def __init__(self, token_secret_id=None, project_id=None):
        logger.info("Initializing FluxGenerator...")
        self.project_id = project_id or PROJECT_ID
        token_id = token_secret_id or REPLICATE_TOKEN_ID
        token = get_secret(token_id, self.project_id)
        self.client = replicate.Client(api_token=token)
        logger.info("FluxGenerator initialized successfully")
    
    def _retry_api_call(self, operation_name, api_call_func):
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"{operation_name} - Attempt {attempt + 1}/{MAX_RETRIES}")
                result = api_call_func()
                logger.info(f"{operation_name} succeeded")
                return result
            except Exception as e:
                last_error = e
                error_msg = str(e)
                if "unauthorized" in error_msg.lower() or "invalid" in error_msg.lower():
                    break
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY * (BACKOFF_MULTIPLIER ** attempt)
                    time.sleep(delay)
        raise last_error
    
    def _fix_exif_orientation(self, image_data):
        try:
            img = Image.open(BytesIO(image_data))
            corrected_img = ImageOps.exif_transpose(img)
            img_bytes = BytesIO()
            corrected_img.save(img_bytes, format='PNG')
            return img_bytes.getvalue()
        except Exception as e:
            logger.error(f"EXIF fix failed: {e}")
            return image_data
    
    def process_image(self, image_data, custom_prompt=None, model=None):
        logger.info("Starting image processing...")
        prompt = custom_prompt or STANDALONE_CARTOON_PROMPT
        flux_model = model or FLUX_MODEL
        
        def _do_process_image():
            corrected_data = self._fix_exif_orientation(image_data)
            image_b64 = base64.b64encode(corrected_data).decode('utf-8')
            data_uri = f"data:image/png;base64,{image_b64}"
            output = self.client.run(flux_model, input={'input_image': data_uri, 'prompt': prompt})
            return output[0] if isinstance(output, list) else str(output)
        
        result_url = self._retry_api_call("Image Processing", _do_process_image)
        logger.info(f"Image processing completed: {result_url}")
        return result_url
    
    def edit_image(self, image_url, edit_prompt, model=None):
        logger.info(f"Starting image editing: {edit_prompt}")
        flux_model = model or FLUX_MODEL

        def _do_edit_image():
            # Download and fix EXIF orientation before editing
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()

            corrected_data = self._fix_exif_orientation(response.content)
            image_b64 = base64.b64encode(corrected_data).decode('utf-8')
            data_uri = f"data:image/png;base64,{image_b64}"

            output = self.client.run(flux_model, input={'input_image': data_uri, 'prompt': edit_prompt})
            return output[0] if isinstance(output, list) else str(output)

        result_url = self._retry_api_call("Image Editing", _do_edit_image)
        logger.info(f"Image editing completed: {result_url}")
        return result_url

    def kontext_edit(self, image_url, edit_prompt, output_format="png"):
        """
        Use Flux Kontext Pro to edit an existing image based on a text prompt.
        Perfect for progressive upgrades - same base image with modifications.

        Args:
            image_url: URL of the source image to modify
            edit_prompt: Text description of the change to make
            output_format: 'png' or 'jpg'

        Returns:
            URL of the edited image from Replicate
        """
        logger.info(f"Starting Kontext edit: {edit_prompt[:50]}...")

        def _do_kontext_edit():
            output = self.client.run(
                "black-forest-labs/flux-kontext-pro",
                input={
                    "prompt": edit_prompt,
                    "input_image": image_url,
                    "output_format": output_format
                }
            )
            # Kontext returns a FileOutput object, get the URL
            if hasattr(output, 'url'):
                return output.url
            return str(output)

        result_url = self._retry_api_call("Kontext Edit", _do_kontext_edit)
        logger.info(f"Kontext edit completed: {result_url}")
        return result_url

    def nano_banana_edit(self, prompt, image_urls=None, resolution="2K", aspect_ratio="4:3",
                         output_format="png", safety_filter_level="block_only_high"):
        """
        Use Google's Nano Banana Pro for premium quality image generation/editing.

        ⚠️  PRICING WARNING: $0.15-0.30 per image - use sparingly for high-value outputs!

        This model excels at:
        - Character consistency across multiple reference images
        - High-quality scene generation with specific subjects
        - Taking up to 14 input images for multi-reference generation

        Args:
            prompt: Text description of the image to generate
            image_urls: Optional list of image URLs (up to 14) for reference/editing
            resolution: "1K", "2K", or "4K" (default "2K")
            aspect_ratio: Ratio like "4:3", "16:9", "1:1", "3:4", "9:16" (default "4:3")
            output_format: "png" or "jpg" (default "png")
            safety_filter_level: "block_only_high", "block_medium_and_above",
                                 "block_low_and_above", "block_none" (default "block_only_high")

        Returns:
            URL of the generated image from Replicate

        Example:
            # Generate ARIA in a new scene using reference images
            result = generator.nano_banana_edit(
                prompt="ARIA the holographic AI companion taking a selfie on Mars...",
                image_urls=["https://storage.../aria_base.png"],
                resolution="2K",
                aspect_ratio="4:3"
            )
        """
        logger.info(f"Starting Nano Banana Pro generation: {prompt[:50]}...")
        logger.info(f"⚠️  Premium model - $0.15-0.30 cost per image")

        def _do_nano_banana():
            input_params = {
                "prompt": prompt,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "output_format": output_format,
                "safety_filter_level": safety_filter_level
            }

            # Add image inputs if provided
            if image_urls:
                input_params["image_input"] = image_urls
                logger.info(f"Using {len(image_urls)} reference image(s)")

            output = self.client.run(
                "google/nano-banana-pro",
                input=input_params
            )

            # Handle various output formats
            if isinstance(output, list) and len(output) > 0:
                return str(output[0])
            elif hasattr(output, 'url'):
                return output.url
            return str(output)

        result_url = self._retry_api_call("Nano Banana Pro", _do_nano_banana)
        logger.info(f"Nano Banana Pro completed: {result_url}")
        return result_url

    def animate_character(self, image_url, custom_prompt=None, model=None, last_image=None, **animation_settings):
        """
        Animate a character image into video
        
        Args:
            image_url: URL of the image to animate
            custom_prompt: Custom prompt for animation (optional)
            model: Video model to use (optional)
            last_image: URL of last frame from previous video for smooth transitions (optional)
            **animation_settings: Additional animation parameters
        """
        prompt = custom_prompt or VIDEO_ANIMATION_PROMPT
        video_model = model or WAN_VIDEO_MODEL
        settings = {
            "go_fast": animation_settings.get("go_fast", MAX_SPEED),
            "num_frames": animation_settings.get("num_frames", MIN_FRAMES),
            "resolution": animation_settings.get("resolution", LOW_RESOLUTION),
            "sample_shift": animation_settings.get("sample_shift", FAST_SAMPLE_SHIFT),
            "frames_per_second": animation_settings.get("frames_per_second", STANDARD_FPS)
        }
        
        # Add last_image parameter if provided
        if last_image:
            settings["last_image"] = last_image
            logger.info(f"   🔗 Using last_image for smooth transition")
        
        def _do_animate_character():
            output = self.client.run(video_model, input={"image": image_url, "prompt": prompt, **settings})
            return str(output)
        
        result_url = self._retry_api_call("Character Animation", _do_animate_character)
        logger.info(f"Character animation completed: {result_url}")
        return result_url
    
    # Backward compatibility
    def animate_dancing(self, image_url, custom_prompt=None):
        return self.animate_character(image_url, custom_prompt)

##############################################################################
# IMAGE/VIDEO PROCESSING HELPERS (moved from loader.py)
##############################################################################

def process_uploaded_image(image_file, flux_generator):
    """Process uploaded image, save to GCS, create new commander with fresh stats."""
    from flask import session
    from utilities.depot_utils import generate_commander_stats
    from utilities.google_cloud_storage_utils import save_character_image

    stats = generate_commander_stats()
    result_url = flux_generator.process_image(image_file.read())

    user_id = session.get('user_id')
    result = save_character_image(result_url, user_id, commander_stats=stats, commander_name=None)

    session['current_asset_id'] = result['asset_id']
    session['edit_count'] = 0
    return {'image_url': result['gcs_url'], 'stats': stats}

def edit_character_image(image_url, edit_prompt, flux_generator):
    """Apply edit to character image, save to GCS with provenance."""
    from flask import session
    from utilities.google_cloud_storage_utils import save_edited_image

    result_url = flux_generator.edit_image(image_url, edit_prompt)

    user_id = session.get('user_id')
    parent_id = session.get('current_asset_id')
    edit_count = session.get('edit_count', 0) + 1
    session['edit_count'] = edit_count

    result = save_edited_image(result_url, user_id=user_id, edit_number=edit_count,
                               parent_asset_id=parent_id, prompt=edit_prompt)
    session['current_asset_id'] = result['asset_id']
    return result['gcs_url']

def animate_character_video(character_url, flux_generator, user_id=None, asset_id=None):
    """Create animation from character image, save to GCS (thread-safe - no session access)."""
    from utilities.google_cloud_storage_utils import save_character_video

    logger.info(f"Starting video animation for {character_url}")
    video_url = flux_generator.animate_character(character_url)
    logger.info(f"Replicate returned: {video_url}")

    result = save_character_video(video_url, user_id=user_id, character_asset_id=asset_id)
    logger.info(f"GCS save completed: {result['gcs_url']}")
    return result['gcs_url']
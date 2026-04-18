##############################################################################
# REPLICATE API CLIENTS - all generation/analysis through Replicate lives here
##############################################################################
#
# FluxGenerator: Flux image edit, Kontext progressive edit, Nano Banana Pro,
#                Wan video animation. Despite the name, handles ALL image/video
#                generation models we run through Replicate (not just Flux).
#
# VisionAnalyzer: LLaVA-13B vision model for image analysis.
#
# IMAGE PROMPT PATTERN (mandatory for all item generation):
#
#   "Cartoon video game item with bold outlines and stylized proportions:
#    [ITEM DESCRIPTION], isolated on red Martian terrain, vibrant colors
#    with reds and oranges reflecting Mars atmosphere, video game asset style"
#
# Items MUST look built from Martian materials (rocks, clay, crystals) — not
# metallic Earth tech. Asymmetrical, weathered, subtle Sepolia crystal accents.
# See tools/test_kontext_progression.py for approved Lv1→Lv10 examples.
##############################################################################

import os
import base64
import logging
import time
import replicate
import requests
from io import BytesIO
from PIL import Image, ImageOps
from google.cloud import secretmanager
from dotenv import load_dotenv

from config import (
    PROJECT_ID, FLUX_MODEL, WAN_VIDEO_MODEL, REPLICATE_TOKEN_ID,
    STANDALONE_CARTOON_PROMPT, VIDEO_ANIMATION_PROMPT,
    MAX_SPEED, MIN_FRAMES, LOW_RESOLUTION, FAST_SAMPLE_SHIFT, STANDARD_FPS,
    MAX_RETRIES, RETRY_DELAY, BACKOFF_MULTIPLIER,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SECRETS
# ---------------------------------------------------------------------------

_secrets_cache = {}
_sm_client = None


def get_secret(secret_id, project_id=None):
    """Retrieve secret from env var or Google Cloud Secret Manager (cached)."""
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


# ---------------------------------------------------------------------------
# FLUX / KONTEXT / NANO BANANA / WAN VIDEO
# ---------------------------------------------------------------------------

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
        """Flux Kontext Pro — text-prompted edit of an existing image URL."""
        logger.info(f"Starting Kontext edit: {edit_prompt[:50]}...")

        def _do_kontext_edit():
            output = self.client.run(
                "black-forest-labs/flux-kontext-pro",
                input={
                    "prompt": edit_prompt,
                    "input_image": image_url,
                    "output_format": output_format,
                },
            )
            if hasattr(output, 'url'):
                return output.url
            return str(output)

        result_url = self._retry_api_call("Kontext Edit", _do_kontext_edit)
        logger.info(f"Kontext edit completed: {result_url}")
        return result_url

    def flux2_pro_edit(self, prompt, image_urls=None, aspect_ratio="1:1",
                        resolution="1 MP", output_format="png", safety_tolerance=2):
        """Flux 2 Pro — accepts up to 8 reference images for multi-ref editing
        + character consistency. Same Replicate client as kontext."""
        logger.info(f"Starting Flux 2 Pro: {prompt[:50]}... refs={len(image_urls or [])}")

        def _do_flux2():
            input_params = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_format": output_format,
                "safety_tolerance": safety_tolerance,
            }
            if image_urls:
                input_params["input_images"] = list(image_urls)[:8]
            output = self.client.run("black-forest-labs/flux-2-pro", input=input_params)
            if isinstance(output, list) and output:
                first = output[0]
                return first.url if hasattr(first, 'url') else str(first)
            if hasattr(output, 'url'):
                return output.url
            return str(output)

        result_url = self._retry_api_call("Flux 2 Pro", _do_flux2)
        logger.info(f"Flux 2 Pro completed: {result_url}")
        return result_url

    def nano_banana_edit(self, prompt, image_urls=None, resolution="2K", aspect_ratio="4:3",
                         output_format="png", safety_filter_level="block_only_high"):
        """
        Google Nano Banana Pro — premium generation/editing, $0.15-0.30/image.
        Accepts up to 14 reference images for character consistency.
        """
        logger.info(f"Starting Nano Banana Pro generation: {prompt[:50]}...")
        logger.info("⚠️  Premium model - $0.15-0.30 cost per image")

        def _do_nano_banana():
            input_params = {
                "prompt": prompt,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "output_format": output_format,
                "safety_filter_level": safety_filter_level,
            }
            if image_urls:
                input_params["image_input"] = image_urls
                logger.info(f"Using {len(image_urls)} reference image(s)")

            output = self.client.run("google/nano-banana-pro", input=input_params)

            if isinstance(output, list) and len(output) > 0:
                return str(output[0])
            elif hasattr(output, 'url'):
                return output.url
            return str(output)

        result_url = self._retry_api_call("Nano Banana Pro", _do_nano_banana)
        logger.info(f"Nano Banana Pro completed: {result_url}")
        return result_url

    def animate_character(self, image_url, custom_prompt=None, model=None, last_image=None, **animation_settings):
        """Animate character image into video (Wan). last_image enables smooth chaining."""
        prompt = custom_prompt or VIDEO_ANIMATION_PROMPT
        video_model = model or WAN_VIDEO_MODEL
        settings = {
            "go_fast": animation_settings.get("go_fast", MAX_SPEED),
            "num_frames": animation_settings.get("num_frames", MIN_FRAMES),
            "resolution": animation_settings.get("resolution", LOW_RESOLUTION),
            "sample_shift": animation_settings.get("sample_shift", FAST_SAMPLE_SHIFT),
            "frames_per_second": animation_settings.get("frames_per_second", STANDARD_FPS),
        }
        if last_image:
            settings["last_image"] = last_image
            logger.info("   🔗 Using last_image for smooth transition")

        def _do_animate_character():
            output = self.client.run(video_model, input={"image": image_url, "prompt": prompt, **settings})
            return str(output)

        result_url = self._retry_api_call("Character Animation", _do_animate_character)
        logger.info(f"Character animation completed: {result_url}")
        return result_url

    def animate_dancing(self, image_url, custom_prompt=None):
        return self.animate_character(image_url, custom_prompt)


# ---------------------------------------------------------------------------
# HIGH-LEVEL HELPERS (GCS-backed uploads / edits / videos)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# VISION ANALYSIS (LLaVA)
# ---------------------------------------------------------------------------

class VisionAnalyzer:
    """Generic image analysis using LLaVA-13B vision model."""

    def __init__(self, token_secret_id=None, project_id=None):
        logger.info("Initializing VisionAnalyzer...")
        self.project_id = project_id or PROJECT_ID
        token_id = token_secret_id or REPLICATE_TOKEN_ID
        token = get_secret(token_id, self.project_id)
        self.client = replicate.Client(api_token=token)
        self.model = "yorickvp/llava-13b:80537f9eead1a5bfa72d5ac6ea6414379be41d4d4f6679fd776e9535d1eb58bb"
        logger.info("VisionAnalyzer initialized successfully")

    def analyze(self, image_url, prompt, temperature=0.2, max_tokens=1024):
        """Run a custom prompt against LLaVA for the given image URL."""
        logger.info("Analyzing image with LLaVA...")
        try:
            output = self.client.run(
                self.model,
                input={
                    "image": image_url,
                    "prompt": prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": 1,
                },
            )
            response = ""
            for item in output:
                response += str(item)
            result = response.strip()
            logger.info(f"Generated response ({len(result)} chars)")
            return result
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            raise

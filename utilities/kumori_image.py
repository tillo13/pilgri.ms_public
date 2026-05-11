"""Galactica → kumori.ai free-tier image stack.

Thin wrapper over the vendored `utilities/kumori_api_client/`. Exposes a small,
opinionated surface for Galactica's image-gen needs:

  - kumori_klein_edit()      — multi-ref image edit via Cloudflare flux-2-klein-4b
  - kumori_describe()        — vision LLM (image-to-text)
  - kumori_llm_chat()        — text LLM with backend fallback chain

All three return Python bytes / strings — no Replicate-style temp URLs to chase.
Size constraints for Klein come from kumori/shared/.../SIZES.md (multiples of 16,
≤4 MP). This module documents the recommended sizes in PRESETS.

Init at app boot:
    from utilities.kumori_image import init_kumori
    init_kumori(get_secret)  # uses PILGRIMS_KUMORI_API_KEY from Secret Manager
"""

import base64
import logging
import time
from io import BytesIO
from typing import List, Optional, Tuple, Dict, Any

from utilities.kumori_api_client import (
    init as _kc_init,
    imggen_edit as _kc_imggen_edit,
    imggen_generate as _kc_imggen_generate,
    describe_image as _kc_describe,
    llm_chat_resilient as _kc_llm_chat_resilient,
    KumoriAPIError,
)
from utilities.kumori_api_client.client import set_request_log, _redact_b64  # type: ignore

logger = logging.getLogger(__name__)

# ─── Klein 4B size presets (per SIZES.md in kumori/shared) ────────────────────
# Multiples of 16; total ≤ 4 MP. Anything else is silently snapped DOWN to
# the nearest multiple of 16, which can produce surprising output dimensions.

PRESETS = {
    'aria_journal':       (1024, 768),   # 4:3 — matches /aria-album cards
    'square_hero':        (1024, 1024),  # 1:1 — catalog / icon
    'captain_portrait':   (768, 1024),   # 3:4 — vertical portrait
    'phone_splash':       (720, 1280),   # 9:16 — phone vertical
    'wide_cinematic':     (2048, 1024),  # 2:1 — wide hero
    'premium_share':      (2048, 2048),  # 4 MP — max quality, ~7s render
    'thumbnail':          (512, 384),    # quick previews
}

# Default LLM backend chain — STRONGEST first. Used for prompt synthesis and
# caption rewriting where instruction-following + prose quality matter.
# Ranked by capability for structured creative tasks:
#   openrouter-hermes      → Hermes 3 Llama 3.1 405B (the biggest free model)
#   mistral-mistral-large  → Mistral Large (top Mistral tier)
#   sambanova-meta-llama   → Llama 3.3 70B on SambaNova (very fast)
#   github-llama-70b       → Llama 3.3 70B (GitHub Models, reliable)
#   openrouter-nemotron    → NVIDIA Nemotron 120B
#   github-gpt4nano        → GPT-4.1 nano (small but solid for fallback)
#   mistral-medium         → final fallback
DEFAULT_LLM_BACKENDS = [
    'openrouter-hermes',
    'mistral-mistral-large-latest',
    'sambanova-meta-llama-3.3-70b-instruct',
    'github-llama-70b',
    'openrouter-nemotron-120b',
    'github-gpt4nano',
    'mistral-medium',
]

_initialized = False


def init_kumori(get_secret_fn=None, api_key_name: str = 'PILGRIMS_KUMORI_API_KEY'):
    """Call once at app boot. Wires the vendored client to Secret Manager."""
    global _initialized
    _kc_init(get_secret_fn=get_secret_fn, api_key_name=api_key_name)
    _initialized = True
    logger.info(f"✅ kumori_image initialized (key={api_key_name})")


def _snap16(n: int) -> int:
    """Floor-snap to multiple of 16 — matches Klein's silent rounding."""
    return max(16, (n // 16) * 16)


def validate_klein_size(width: int, height: int) -> Tuple[int, int]:
    """Snap to multiple-of-16 + cap to 4 MP. Returns (w, h) Klein will actually
    use. Logs a warning if the input had to be adjusted."""
    w = _snap16(width)
    h = _snap16(height)
    if w * h > 4 * 1024 * 1024:
        # Scale both down proportionally to fit 4 MP
        import math
        scale = math.sqrt(4 * 1024 * 1024 / (w * h))
        w = _snap16(int(w * scale))
        h = _snap16(int(h * scale))
        logger.warning(f"klein size scaled to fit 4 MP: {width}x{height} -> {w}x{h}")
    elif (w, h) != (width, height):
        logger.info(f"klein size snapped to multiple-of-16: {width}x{height} -> {w}x{h}")
    return w, h


def _pack_image_url_or_bytes(image_url_or_bytes, max_long_side: int = 1024) -> str:
    """Coerce a URL or raw bytes into a base64 JPEG payload at ≤max_long_side."""
    from PIL import Image
    import urllib.request
    if isinstance(image_url_or_bytes, (bytes, bytearray)):
        raw = bytes(image_url_or_bytes)
    elif isinstance(image_url_or_bytes, str):
        if image_url_or_bytes.startswith(('http://', 'https://')):
            raw = urllib.request.urlopen(image_url_or_bytes, timeout=30).read()
        elif image_url_or_bytes.startswith('data:image'):
            _, b64 = image_url_or_bytes.split(',', 1)
            return b64
        else:
            with open(image_url_or_bytes, 'rb') as f:
                raw = f.read()
    else:
        raise TypeError(f"unsupported image input type: {type(image_url_or_bytes)}")
    im = Image.open(BytesIO(raw)).convert('RGB')
    if max(im.size) > max_long_side:
        im.thumbnail((max_long_side, max_long_side), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, 'JPEG', quality=88, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def kumori_klein_edit(prompt: str, target_image, reference_images: Optional[List] = None,
                     preset: Optional[str] = None, width: int = 1024, height: int = 1024,
                     app_name: str = 'galactica', character: str = '',
                     ref_filename: str = '', debug: bool = False) -> Dict[str, Any]:
    """Render an image via Cloudflare flux-2-klein-4b.

    target_image / reference_images: each can be a URL, file path, or raw bytes.
    Up to 3 reference images (target + 3 refs = 4 total — Klein's hard cap).

    Returns {ok, image_bytes, provider, ms, used_size:(w,h), [upstream_calls]}
    on success. When debug=True, the response includes the upstream HTTP calls
    kumori made to Cloudflare so the caller can see the raw payloads.
    """
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}; valid: {list(PRESETS)}")
        width, height = PRESETS[preset]
    width, height = validate_klein_size(width, height)
    target_b64 = _pack_image_url_or_bytes(target_image)
    refs_b64 = [_pack_image_url_or_bytes(r) for r in (reference_images or [])]
    t0 = time.time()
    res = _kc_imggen_edit(prompt=prompt, target_image_b64=target_b64,
                          reference_images_b64=refs_b64, width=width, height=height,
                          app_name=app_name, character=character or 'anon',
                          ref_filename=ref_filename or 'ref', debug=debug)
    ms = int((time.time() - t0) * 1000)
    if not res.get('ok'):
        raise KumoriAPIError(f"klein edit failed: {res.get('error')}", payload=res)
    image_bytes = base64.b64decode(res['image_b64'])
    out = {
        'ok': True,
        'image_bytes': image_bytes,
        'provider': res.get('provider'),
        'ms': res.get('ms') or ms,
        'used_size': (width, height),
    }
    if debug and res.get('_debug'):
        out['upstream_calls'] = res['_debug'].get('upstream_calls', [])
    return out


def kumori_describe(image_url_or_bytes, prompt: str = "Describe this image briefly.") -> Tuple[str, str]:
    """Vision LLM → text. Returns (description_text, backend_used)."""
    if isinstance(image_url_or_bytes, (bytes, bytearray)):
        b64 = base64.b64encode(bytes(image_url_or_bytes)).decode()
        res = _kc_describe(image_b64=b64, prompt=prompt, mime='image/jpeg')
    elif isinstance(image_url_or_bytes, str) and image_url_or_bytes.startswith(('http://', 'https://')):
        res = _kc_describe(image_url=image_url_or_bytes, prompt=prompt)
    else:
        # treat as local path
        with open(image_url_or_bytes, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        res = _kc_describe(image_b64=b64, prompt=prompt, mime='image/jpeg')
    return (res.get('text') or '').strip(), res.get('backend', '?')


def kumori_llm_chat(system: str, user_prompt: str, *,
                    backends: Optional[List[str]] = None,
                    max_tokens: int = 700, temperature: float = 0.4,
                    min_chars: int = 80, debug: bool = False) -> Tuple[str, str, List[dict], Optional[Dict[str, Any]]]:
    """LLM with server-side backend fallback. Returns
    (text, winning_backend, attempt_log, debug_info_or_None).

    When debug=True, debug_info has {upstream_calls: [...]} listing every
    HTTP call kumori made to LLM provider APIs (Groq, Mistral, GitHub Models, etc.)
    with full request/response payloads."""
    chain = backends or DEFAULT_LLM_BACKENDS
    messages = [{"role": "user", "content": user_prompt}]
    text, backend, attempts, debug_info = _kc_llm_chat_resilient(
        backends=chain, messages=messages, max_tokens=max_tokens,
        temperature=temperature, system=system, min_chars=min_chars,
        debug=debug,
    )
    return text or '', backend or '?', attempts or [], debug_info

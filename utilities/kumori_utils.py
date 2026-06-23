"""Galactica → kumori.ai free-tier stack (image + text + describe).

Thin wrapper over the vendored `utilities/kumori_api_client/`. Single home for
every kumori-routed call Galactica makes. Future video / TTS / music fold in
here as new top-level functions — keep the surface narrow and opinionated:

  - kumori_klein_edit()         — image edit; kumori cascades HF→CF server-side
  - kumori_klein_generate()     — text→image (no reference); kumori cascades
  - kumori_describe()           — vision LLM (image-to-text)
  - kumori_llm_chat()           — text LLM with backend fallback chain

All return Python bytes / strings — no Replicate-style temp URLs to chase.
Size constraints for Klein come from kumori/shared/.../SIZES.md (multiples of 16,
≤4 MP). This module documents the recommended sizes in PRESETS.

Init at app boot:
    from utilities.kumori_utils import init_kumori
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
    logger.info(f"✅ kumori_utils initialized (key={api_key_name})")


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
                     ref_filename: str = '', debug: bool = False,
                     feature: Optional[str] = None, verbiage: Optional[str] = None,
                     caller_user_id: Optional[int] = None,
                     tags: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Render an image via kumori's edit router.

    Since 2026-05-16 kumori cascades server-side across the full edit stack
    (HF Qwen-2511 → HF Kontext-Dev → HF Qwen-2511-fast → CF Klein → CF Klein-2),
    skipping rungs in daily-cap cooldown. Caller passes prompt+images and
    kumori picks the best available rung. No client-side ladder needed.

    target_image / reference_images: each can be a URL, file path, or raw bytes.
    Up to 3 reference images supported across all rungs.

    Attribution kwargs (logged to kumori_api_usage per call):
      feature='aria_journal.render' etc, verbiage=prompt-or-label,
      caller_user_id=end-user, tags=arbitrary JSONB.

    Returns {ok, image_bytes, provider, ms, used_size, ladder_trace,
             [upstream_calls]}. ladder_trace lists every rung kumori tried
     ([{provider, ok, ms, error_code, skipped_reason}, ...]).
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
                          ref_filename=ref_filename or 'ref', debug=debug,
                          feature=feature, verbiage=verbiage,
                          caller_user_id=caller_user_id, tags=tags)
    ms = int((time.time() - t0) * 1000)
    if not res.get('ok'):
        raise KumoriAPIError(f"kumori edit failed: {res.get('error')}", payload=res)
    out = {
        'ok': True,
        'image_bytes': base64.b64decode(res['image_b64']),
        'provider': res.get('provider'),
        'ms': res.get('ms') or ms,
        'used_size': (width, height),
        'ladder_trace': res.get('ladder_trace', []),
    }
    if debug and res.get('_debug'):
        out['upstream_calls'] = res['_debug'].get('upstream_calls', [])
    return out


def kumori_klein_generate(prompt: str, *, preset: Optional[str] = None,
                          width: int = 1024, height: int = 1024,
                          feature: Optional[str] = None, verbiage: Optional[str] = None,
                          caller_user_id: Optional[int] = None,
                          tags: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Text→image via kumori. No reference images. kumori cascades server-side
    across the free-tier generate stack (CF + HF + Pollinations + Horde rungs).

    Returns {ok, image_bytes, provider, ms, used_size, ladder_trace}.
    Raises KumoriAPIError on full-ladder failure.
    """
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}; valid: {list(PRESETS)}")
        width, height = PRESETS[preset]
    width, height = validate_klein_size(width, height)
    t0 = time.time()
    res = _kc_imggen_generate(prompt=prompt, width=width, height=height,
                              feature=feature, verbiage=verbiage,
                              caller_user_id=caller_user_id, tags=tags)
    ms = int((time.time() - t0) * 1000)
    if not res.get('ok'):
        raise KumoriAPIError(f"kumori generate failed: {res.get('error')}", payload=res)
    return {
        'ok': True,
        'image_bytes': base64.b64decode(res['image_b64']),
        'provider': res.get('provider'),
        'ms': res.get('ms') or ms,
        'used_size': (width, height),
        'ladder_trace': res.get('ladder_trace', []),
    }


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


def kumori_llm_chat_messages(system: str, messages: List[Dict[str, str]], *,
                             backends: Optional[List[str]] = None,
                             max_tokens: int = 700, temperature: float = 0.4,
                             min_chars: int = 1, debug: bool = False) -> Tuple[str, str, List[dict], Optional[Dict[str, Any]]]:
    """Multi-turn variant of kumori_llm_chat. Pass a full role/content message
    list (conversation history + current turn) so chat features keep context,
    instead of collapsing to a single prompt. Returns
    (text, winning_backend, attempt_log, debug_info_or_None).

    min_chars defaults to 1 (not 80) because a short valid chat reply
    ("Acknowledged, Captain.") must not count as a backend failure."""
    chain = backends or DEFAULT_LLM_BACKENDS
    text, backend, attempts, debug_info = _kc_llm_chat_resilient(
        backends=chain, messages=messages, max_tokens=max_tokens,
        temperature=temperature, system=system, min_chars=min_chars,
        debug=debug, app_name='galactica',
    )
    return text or '', backend or '?', attempts or [], debug_info

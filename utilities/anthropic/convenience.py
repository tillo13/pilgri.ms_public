"""Convenience functions around ClaudeClient — create_client, stream_response, etc.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import base64
from typing import List, Dict, Any, Iterator

from utilities.anthropic.pricing import CLAUDE_MODELS
from utilities.anthropic.client import ClaudeClient, _get_anthropic_api_key


def create_client(api_key: str = None, model: str = None) -> ClaudeClient:
    """
    Create a Claude client with sensible defaults.

    Args:
        api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var, then Secret Manager)
        model: Model to use (defaults to Sonnet 3.5)

    Returns:
        Configured ClaudeClient instance
    """
    api_key = _get_anthropic_api_key(api_key)

    if not model:
        # #1493: was a "sonnet-3.5" key -> the retired Sonnet 3.5 alias. Now current Sonnet.
        model = CLAUDE_MODELS.get("sonnet-4.6", "claude-sonnet-4-6")

    return ClaudeClient(
        api_key=api_key,
        model=model,
        enable_beta_features=True
    )


def stream_response(prompt: str,
                   api_key: str = None,
                   model: str = None,
                   system_prompt: str = None) -> Iterator[str]:
    """Stream a response from Claude for a simple prompt."""
    client = create_client(api_key, model)

    messages = [{"role": "user", "content": prompt}]

    for event in client.stream_chat(messages, system=system_prompt):
        if event["type"] == "delta" and "text" in event:
            yield event["text"]


def chat_with_history(messages: List[Dict[str, str]],
                     api_key: str = None,
                     model: str = None) -> str:
    """Chat with Claude using conversation history."""
    client = create_client(api_key, model)
    return client.chat(messages, max_tokens=1024, temperature=1.0)


# =====================================================
# LEGACY FUNCTIONS - For backward compatibility
# =====================================================

def get_available_models(api_key: str) -> Dict[str, Dict]:
    """Get information about available Claude models."""
    return CLAUDE_MODELS


def get_latest_model(api_key: str, model_family: str = "claude-3-5") -> str:
    """Get the latest available Claude model from a specific family."""
    if "claude-4" in model_family:
        return CLAUDE_MODELS.get("sonnet-4", "claude-sonnet-4-20250514")
    elif "claude-3-7" in model_family:
        return CLAUDE_MODELS.get("sonnet-3.7", "claude-3-7-sonnet-20250219")
    else:
        return CLAUDE_MODELS.get("sonnet-3.5", "claude-3-5-sonnet-latest")


def generate_text(prompt: str, api_key: str, model: str, max_tokens: int, temperature: float, auto_discover: bool = False) -> str:
    """Generate text response from Claude based on a prompt."""
    client = ClaudeClient(api_key=api_key, model=model)
    return client.generate_text(prompt=prompt, max_tokens=max_tokens, temperature=temperature)


def process_image(image_path: str, prompt: str, api_key: str, model: str, max_tokens: int, temperature: float, auto_discover: bool = False) -> str:
    """Process an image with Claude and generate a text response."""
    client = ClaudeClient(api_key=api_key, model=model)

    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    media_type = client._get_media_type(image_path)

    return client.process_image_base64(
        image_data=base64_image,
        media_type=media_type,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature
    )


def chat(messages: List[Dict[str, Any]], api_key: str, model: str, max_tokens: int, temperature: float, auto_discover: bool = False) -> str:
    """Conduct a multi-turn chat conversation with Claude."""
    client = ClaudeClient(api_key=api_key, model=model)
    return client.chat(messages=messages, max_tokens=max_tokens, temperature=temperature)

"""ClaudeClient — Anthropic SDK wrapper with streaming, image, web search.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import os
import base64
import logging
import time
from typing import List, Dict, Any, Iterator
from utilities.anthropic_logger import new_client

from utilities.anthropic.pricing import (
    CLAUDE_MODELS,
    WEB_SEARCH_TOOL_VERSION,
    log_api_usage,
    get_model_pricing,
    sampling_kwargs,
)

logger = logging.getLogger("claude_utils")


def _get_anthropic_api_key(api_key: str = None) -> str:
    """Get Anthropic API key from argument, env, or Secret Manager."""
    if api_key:
        return api_key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    try:
        from utilities.google_auth_utils import get_secret
        api_key = get_secret("KUMORI_ANTHROPIC_API_KEY", project_id="kumori-404602")
        if api_key:
            return api_key
    except Exception:
        pass
    raise ValueError("No Anthropic API key available")


class ClaudeClient:
    def __init__(self,
                api_key: str,
                model: str = None,
                enable_beta_features: bool = True):
        """
        Initialize the Claude client.

        Args:
            api_key: Anthropic API key
            model: Claude model to use (defaults to latest Sonnet)
            enable_beta_features: Enable beta features like web search
        """
        if not api_key:
            raise ValueError("No API key provided")

        # #1493: default to current Sonnet if no model specified. Was a "sonnet-3.5"
        # key (not in catalog) -> the retired Sonnet 3.5 alias — a hard-error time bomb
        # once Anthropic decommissions it.
        if not model:
            model = CLAUDE_MODELS.get("sonnet-4.6", "claude-sonnet-4-6")

        # Warn about slow models
        if "claude-opus-4-20250514" in model:
            logger.warning(f"Model {model} has ~35s response time - consider using opus-4.1 or sonnet models instead")

        # Store configuration
        self.api_key = api_key
        self.model = model
        self.enable_beta_features = enable_beta_features

        # Initialize Anthropic client with appropriate timeout
        # Use longer timeout for Opus 4 original, standard for others
        timeout = 60.0 if "claude-opus-4-20250514" in model else 30.0

        self.client = new_client(timeout=timeout, # Dynamic timeout based on model
            max_retries=2)

        logger.info(f"Initialized Claude client with model: {self.model} (timeout: {timeout}s)")
        if enable_beta_features:
            logger.debug("Web search capabilities available (no beta headers required)")

    def _log_tokens(self, method: str, response: Any, duration_ms: int = None,
                    feature: str = None, user_id: str = None):
        """Log token usage, ACCURATE cost estimation, and API usage tracking.

        `feature` overrides the method name for kumori_api_usage tagging.
        `user_id` should be the auth user when available, or a sentinel like
        'system:galactica_cron' for background jobs — so every row is attributed.
        """
        if hasattr(response, 'usage'):
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_tokens = input_tokens + output_tokens

            # Get accurate model-specific pricing
            model_pricing = get_model_pricing(self.model)
            input_cost = input_tokens * model_pricing['input']
            output_cost = output_tokens * model_pricing['output']
            total_cost = input_cost + output_cost

            logger.info(
                f"{method} | Model: {self.model} | "
                f"Tokens: {input_tokens}→{output_tokens} (Total: {total_tokens}) | "
                f"Cost: ${total_cost:.6f}"
            )

            log_api_usage(
                model=self.model,
                usage=response.usage,
                feature=feature or method,
                streaming=False,
                duration_ms=duration_ms,
                user_id=user_id,
            )

    def _get_media_type(self, file_path: str) -> str:
        """Determine media type from file extension."""
        extension = file_path.lower().split('.')[-1]
        media_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        return media_types.get(extension, 'application/octet-stream')

    def _samp(self, temperature=None, top_p=None, top_k=None):
        """Sampling kwargs for this client's model — see sampling_kwargs()."""
        return sampling_kwargs(self.model, temperature, top_p, top_k)

    def generate_text(self,
                     prompt: str,
                     max_tokens: int = 1024,
                     temperature: float = 1.0,
                     user_id: str = None,
                     feature: str = None) -> str:
        """
        Generate text response from Claude.
        """
        try:
            start_time = time.time()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                **self._samp(temperature),
                messages=[{"role": "user", "content": prompt}]
            )

            elapsed_time = time.time() - start_time
            response_text = message.content[0].text

            self._log_tokens("generate_text", message, duration_ms=int(elapsed_time * 1000),
                             feature=feature, user_id=user_id)
            logger.info(f"Text generation completed in {elapsed_time:.2f}s")

            return response_text

        except Exception as e:
            logger.error(f"Error generating text response: {str(e)}")
            raise

    def process_image(self,
                     image_path: str,
                     prompt: str,
                     max_tokens: int = 1024,
                     temperature: float = 1.0) -> str:
        """Process an image file with Claude and generate a text response."""
        try:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file not found: {image_path}")

            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")

            return self.process_image_base64(
                image_data=base64_image,
                media_type=self._get_media_type(image_path),
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )

        except Exception as e:
            logger.error(f"Error processing image file: {str(e)}")
            raise

    def process_image_url(self,
                         image_url: str,
                         prompt: str,
                         max_tokens: int = 1024,
                         user_id: str = None,
                         feature: str = None,
                         temperature: float = 1.0) -> str:
        """Process an image from a URL with Claude and generate a text response."""
        try:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": image_url
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]

            start_time = time.time()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                **self._samp(temperature),
                messages=[{"role": "user", "content": content}]
            )

            elapsed_time = time.time() - start_time
            response_text = message.content[0].text

            self._log_tokens("process_image_url", message, duration_ms=int(elapsed_time * 1000),
                             feature=feature, user_id=user_id)
            logger.info(f"Image URL processing completed in {elapsed_time:.2f}s")

            return response_text

        except Exception as e:
            logger.error(f"Error processing image URL: {str(e)}")
            raise

    def process_image_base64(self,
                            image_data: str,
                            media_type: str,
                            prompt: str,
                            max_tokens: int = 1024,
                            temperature: float = 1.0,
                            user_id: str = None,
                            feature: str = None) -> str:
        """Process a base64-encoded image with Claude."""
        try:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]

            start_time = time.time()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                **self._samp(temperature),
                messages=[{"role": "user", "content": content}]
            )

            elapsed_time = time.time() - start_time
            response_text = message.content[0].text

            self._log_tokens("process_image_base64", message, duration_ms=int(elapsed_time * 1000),
                             feature=feature, user_id=user_id)
            logger.info(f"Base64 image processing completed in {elapsed_time:.2f}s")

            return response_text

        except Exception as e:
            logger.error(f"Error processing base64 image: {str(e)}")
            raise

    def chat(self,
            messages: List[Dict[str, Any]],
            max_tokens: int = 1024,
            temperature: float = 1.0,
            system: str = None,
            user_id: str = None,
            feature: str = None) -> str:
        """Conduct a multi-turn chat conversation with Claude."""
        try:
            for msg in messages:
                if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                    raise ValueError("Invalid message format. Each message must have 'role' and 'content' keys.")
                if msg['role'] not in ['user', 'assistant']:
                    raise ValueError("Message role must be either 'user' or 'assistant'.")

            params = {
                "model": self.model,
                "max_tokens": max_tokens,
                **self._samp(temperature),
                "messages": messages
            }

            if system:
                params["system"] = system

            start_time = time.time()

            message = self.client.messages.create(**params)

            elapsed_time = time.time() - start_time
            response_text = message.content[0].text

            self._log_tokens("chat", message, duration_ms=int(elapsed_time * 1000),
                             feature=feature, user_id=user_id)
            logger.info(f"Chat completed in {elapsed_time:.2f}s | Messages: {len(messages)}")

            return response_text

        except Exception as e:
            logger.error(f"Error in chat conversation: {str(e)}")
            raise

    def stream_chat(self,
                   messages: List[Dict[str, Any]],
                   max_tokens: int = 1024,
                   temperature: float = 1.0,
                   system: str = None,
                   enable_web_search: bool = False,
                   user_id: str = None,
                   feature: str = None) -> Iterator[Dict[str, Any]]:
        """Stream a chat conversation with Claude - OPTIMIZED with clear web search logging."""
        try:
            params = {
                "model": self.model,
                "max_tokens": max_tokens,
                **self._samp(temperature),
                "messages": messages
            }

            if system:
                params["system"] = system

            if enable_web_search:
                web_search_added = self.configure_web_search_tools(params)
                if web_search_added:
                    logger.info(f"🌐 Web search tools configured for {self.model}")
                else:
                    logger.info(f"💬 Using knowledge base mode for {self.model}")

            logger.debug(f"Starting streaming chat with model {self.model}")

            total_input_tokens = 0
            total_output_tokens = 0
            start_time = time.time()

            with self.client.messages.stream(**params) as stream:
                for event in stream:
                    if not hasattr(event, 'type'):
                        continue

                    if event.type == 'message_start':
                        total_input_tokens = event.message.usage.input_tokens
                        logger.debug(f"Stream started - Input tokens: {total_input_tokens}")

                        yield {
                            "type": "start",
                            "message_id": event.message.id,
                            "model": event.message.model
                        }

                    elif event.type == 'content_block_start':
                        if (hasattr(event, 'content_block') and
                            hasattr(event.content_block, 'type') and
                            event.content_block.type == 'server_tool_use' and
                            hasattr(event.content_block, 'name') and
                            event.content_block.name == 'web_search'):

                            logger.info("🌐 Claude is searching the web for current information...")

                            yield {
                                "type": "web_search_start"
                            }

                    elif event.type == 'content_block_delta':
                        if hasattr(event, 'delta'):

                            if hasattr(event.delta, 'type'):

                                if event.delta.type == 'text_delta':
                                    yield {
                                        "type": "delta",
                                        "text": event.delta.text
                                    }

                                elif event.delta.type == 'input_json_delta':
                                    yield {
                                        "type": "web_search_query",
                                        "text": event.delta.partial_json if hasattr(event.delta, 'partial_json') else ''
                                    }

                                elif event.delta.type == 'thinking':
                                    yield {
                                        "type": "thinking",
                                        "text": event.delta.text if hasattr(event.delta, 'text') else ''
                                    }

                            elif hasattr(event.delta, 'text'):
                                yield {
                                    "type": "delta",
                                    "text": event.delta.text
                                }

                    elif event.type == 'message_delta':
                        if hasattr(event, 'usage'):
                            total_output_tokens = event.usage.output_tokens

                    elif event.type == 'message_stop':
                        elapsed_time = time.time() - start_time

                        # Bug #1477 (Andy 2026-05-14 P1): kumori anthropic_leak_detector
                        # flagged $258/mo unaccounted spend on sonnet-4-5 because this
                        # block USED TO log a hand-built {input_tokens, output_tokens}
                        # dict — which drops cache_creation_input_tokens (~42k/hr),
                        # cache_read_input_tokens (~64k/hr), thinking_tokens, and
                        # server_tool_use entirely. log_api_usage reads all of those
                        # via getattr off a real SDK usage object. The SDK exposes
                        # the complete usage on stream.get_final_message().usage at
                        # exit time. Use that instead of the partial event-loop counters.
                        try:
                            final_usage = stream.get_final_message().usage
                            total_input_tokens = getattr(final_usage, 'input_tokens', total_input_tokens)
                            total_output_tokens = getattr(final_usage, 'output_tokens', total_output_tokens)
                        except Exception as _e:
                            # Defensive fallback — never break the user-facing stream
                            # because the post-stream usage read failed. The partial
                            # counters from the event loop still get logged.
                            logger.warning(f"stream_chat: get_final_message() failed, logging partial usage: {_e}")
                            final_usage = {'input_tokens': total_input_tokens, 'output_tokens': total_output_tokens}

                        total_tokens = total_input_tokens + total_output_tokens
                        model_pricing = get_model_pricing(self.model)
                        total_cost = (total_input_tokens * model_pricing['input']) + (total_output_tokens * model_pricing['output'])

                        logger.info(
                            f"stream_chat | Model: {self.model} | "
                            f"Tokens: {total_input_tokens}→{total_output_tokens} (Total: {total_tokens}) | "
                            f"Cost: ${total_cost:.6f} | "
                            f"Time: {elapsed_time:.2f}s"
                        )

                        log_api_usage(
                            model=self.model,
                            usage=final_usage,
                            feature=feature or 'stream_chat',
                            streaming=True,
                            duration_ms=int(elapsed_time * 1000),
                            user_id=user_id,
                        )

                        yield {
                            "type": "stop",
                            "stop_reason": event.message.stop_reason if hasattr(event, 'message') else None
                        }
                        break

        except Exception as e:
            logger.error(f"Error in streaming chat: {str(e)}")
            yield {
                "type": "error",
                "error": str(e)
            }

    def configure_web_search_tools(self, params):
        """Configure web search tools with detailed informative logging (no more red X warnings)."""

        unsupported_prefixes = [
            'claude-2',
            'claude-instant',
        ]

        model_supported = not any(prefix in self.model for prefix in unsupported_prefixes)

        if model_supported:
            params["tools"] = [{
                "type": WEB_SEARCH_TOOL_VERSION,
            }]
            logger.debug(f"Added {WEB_SEARCH_TOOL_VERSION} tool to request parameters")
            return True
        else:
            logger.debug(f"Model {self.model} will use training knowledge (web search not available)")
            return False

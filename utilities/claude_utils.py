"""
Claude API Utilities - Production Optimized with Accurate Pricing

This module provides a streamlined interface for Claude API with:
- Real-time token-by-token streaming
- Optimized web search support with clear logging
- Extended thinking (Claude 4)
- Image processing
- Clean event format for frontend integration
- ACCURATE model-specific pricing calculations

Compatible with chat_utils.py streaming format and optimized chat_processing.py
"""

import os
import base64
import logging
import time
from typing import List, Dict, Any, Optional, Iterator
from anthropic import Anthropic
import json

# Configure logger
logger = logging.getLogger("claude_utils")

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Latest Claude models with performance characteristics
CLAUDE_MODELS = {
    # Latest (2026)
    "opus-4.6": "claude-opus-4-6",               # 🆕 Latest flagship, best reasoning/coding
    "sonnet-4.5": "claude-sonnet-4-5-20250929",  # ✅ Best speed/intelligence balance
    "haiku-4.5": "claude-haiku-4-5-20251001",    # ⚡ Fastest, near-frontier intelligence
    # Legacy (still available)
    "opus-4.5": "claude-opus-4-5-20251101",      # Previous flagship
    "opus-4.1": "claude-opus-4-1-20250805",      # ✅ ~3.5s response time
    "opus-4": "claude-opus-4-20250514",          # ⚠️ ~35s response time - slow
    "sonnet-4": "claude-sonnet-4-20250514",      # ✅ Good for coding
    "sonnet-3.7": "claude-3-7-sonnet-20250219",  # Legacy
    "haiku-3": "claude-3-haiku-20240307",        # ⚡ Cheapest, very fast
}

# ACCURATE MODEL PRICING (per token, not per million tokens)
MODEL_PRICING = {
    # Claude 4.1 models
    'claude-opus-4-1': {'input': 0.000020, 'output': 0.000080},  # $20/$80 per million
    
    # Claude 4 models
    'claude-opus-4': {'input': 0.000015, 'output': 0.000075},    # $15/$75 per million
    'claude-sonnet-4': {'input': 0.000003, 'output': 0.000015},  # $3/$15 per million
    
    # Claude 3.7 models  
    'claude-3-7-sonnet': {'input': 0.000003, 'output': 0.000015}, # $3/$15 per million
    
    # Claude 3.5 models
    'claude-3-5-sonnet': {'input': 0.000003, 'output': 0.000015}, # $3/$15 per million
    'claude-3-5-haiku': {'input': 0.00000025, 'output': 0.00000125}, # $0.25/$1.25 per million
    
    # Default fallback (Sonnet pricing)
    'default': {'input': 0.000003, 'output': 0.000015}
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1
WEB_SEARCH_COST = 0.01

APP_NAME = 'galactica'


def _get_kumori_connection():
    """Get a connection to the kumori DB specifically for usage logging."""
    import psycopg2
    from utilities.postgres_utils import get_secret
    host = get_secret('KUMORI_POSTGRES_IP')
    dbname = get_secret('KUMORI_POSTGRES_DB_NAME')
    user = get_secret('KUMORI_POSTGRES_USERNAME')
    password = get_secret('KUMORI_POSTGRES_PASSWORD')
    return psycopg2.connect(host=host, dbname=dbname, user=user, password=password)


def log_api_usage(model, usage, feature=None, streaming=False,
                  image_count=0, user_id=None, duration_ms=None):
    """Log an API call to kumori_api_usage in a background thread.
    Never blocks the caller. Never raises."""
    import threading

    def _do_log():
        try:
            pricing = get_model_pricing(model)

            input_tokens = getattr(usage, 'input_tokens', None) or (usage.get('input_tokens', 0) if isinstance(usage, dict) else 0) or 0
            output_tokens = getattr(usage, 'output_tokens', None) or (usage.get('output_tokens', 0) if isinstance(usage, dict) else 0) or 0
            cache_creation = getattr(usage, 'cache_creation_input_tokens', None) or (usage.get('cache_creation_input_tokens', 0) if isinstance(usage, dict) else 0) or 0
            cache_read = getattr(usage, 'cache_read_input_tokens', None) or (usage.get('cache_read_input_tokens', 0) if isinstance(usage, dict) else 0) or 0
            thinking = getattr(usage, 'thinking_tokens', None) or (usage.get('thinking_tokens', 0) if isinstance(usage, dict) else 0) or 0

            server_tools = getattr(usage, 'server_tool_use', None) or (usage.get('server_tool_use') if isinstance(usage, dict) else None) or {}
            web_searches = getattr(server_tools, 'web_search_requests', None) or (server_tools.get('web_search_requests', 0) if isinstance(server_tools, dict) else 0) or 0
            web_fetches = getattr(server_tools, 'web_fetch_requests', None) or (server_tools.get('web_fetch_requests', 0) if isinstance(server_tools, dict) else 0) or 0
            code_exec = getattr(server_tools, 'code_execution_requests', None) or (server_tools.get('code_execution_requests', 0) if isinstance(server_tools, dict) else 0) or 0

            cost = (
                input_tokens * pricing['input']
                + output_tokens * pricing['output']
                + cache_creation * pricing['input'] * CACHE_WRITE_MULTIPLIER
                + cache_read * pricing['input'] * CACHE_READ_MULTIPLIER
                + thinking * pricing['output']
                + web_searches * WEB_SEARCH_COST
            )

            conn = _get_kumori_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO kumori_api_usage
                        (app_name, feature, model, input_tokens, output_tokens,
                         cache_creation_tokens, cache_read_tokens, thinking_tokens,
                         web_search_requests, web_fetch_requests, code_execution_requests,
                         image_count, estimated_cost_usd, streaming, user_id, duration_ms)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (APP_NAME, feature, model, input_tokens, output_tokens,
                          cache_creation, cache_read, thinking,
                          web_searches, web_fetches, code_exec,
                          image_count, cost, streaming, user_id, duration_ms))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to log API usage: {e}")

    threading.Thread(target=_do_log, daemon=True).start()


# Response time expectations (based on testing):
# - Haiku 3.5: ~0.5s (fastest, simple tasks)
# - Sonnet 3.5: ~1.4s (best balance)
# - Sonnet 4: ~2s (enhanced capabilities)
# - Sonnet 3.7: ~2.3s (good alternative)
# - Opus 4.1: ~3.5s (most capable, acceptable speed)
# - Opus 4: ~35s (NOT RECOMMENDED - will cause timeouts)

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


def get_model_pricing(model_name: str) -> Dict[str, float]:
    """Get accurate pricing per token for different Claude models"""
    model_lower = model_name.lower()
    
    # Find exact match first
    for model_key, prices in MODEL_PRICING.items():
        if model_key in model_lower:
            return prices
    
    # Fallback to partial matches
    if 'haiku' in model_lower:
        return MODEL_PRICING['claude-3-5-haiku']
    elif 'sonnet-4' in model_lower:
        return MODEL_PRICING['claude-sonnet-4']
    elif 'sonnet' in model_lower:
        return MODEL_PRICING['claude-3-5-sonnet']
    elif 'opus-4-1' in model_lower:
        return MODEL_PRICING['claude-opus-4-1']
    elif 'opus' in model_lower:
        return MODEL_PRICING['claude-opus-4']
    
    return MODEL_PRICING['default']

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
        
        # Default to Sonnet 3.5 if no model specified (fast and reliable)
        if not model:
            model = CLAUDE_MODELS.get("sonnet-3.5", "claude-3-5-sonnet-latest")
        
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
        
        self.client = Anthropic(
            api_key=self.api_key,
            timeout=timeout,  # Dynamic timeout based on model
            max_retries=2
        )
        
        logger.info(f"Initialized Claude client with model: {self.model} (timeout: {timeout}s)")
        if enable_beta_features:
            logger.debug("Web search capabilities available (no beta headers required)")
    
    def _log_tokens(self, method: str, response: Any, duration_ms: int = None):
        """Log token usage, ACCURATE cost estimation, and API usage tracking."""
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
                feature=method,
                streaming=False,
                duration_ms=duration_ms,
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
    
    def generate_text(self, 
                     prompt: str, 
                     max_tokens: int = 1024, 
                     temperature: float = 1.0) -> str:
        """
        Generate text response from Claude.
        
        Args:
            prompt: The text prompt to send to Claude
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness (0.0 = deterministic, 1.0 = creative)
            
        Returns:
            Generated text response
        """
        try:
            start_time = time.time()
            
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            
            elapsed_time = time.time() - start_time
            response_text = message.content[0].text

            self._log_tokens("generate_text", message, duration_ms=int(elapsed_time * 1000))
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
        """
        Process an image file with Claude and generate a text response.
        
        Args:
            image_path: Path to the image file
            prompt: Text prompt to accompany the image
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness
            
        Returns:
            Generated text response about the image
        """
        try:
            # Check if the image exists
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file not found: {image_path}")
            
            # Read and base64 encode the image
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            
            # Use the base64 processing method
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
                         temperature: float = 1.0) -> str:
        """
        Process an image from a URL with Claude and generate a text response.
        
        Args:
            image_url: URL to the image
            prompt: Text prompt to accompany the image
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness
            
        Returns:
            Generated text response about the image
        """
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
                temperature=temperature,
                messages=[{"role": "user", "content": content}]
            )
            
            elapsed_time = time.time() - start_time
            response_text = message.content[0].text
            
            self._log_tokens("process_image_url", message, duration_ms=int(elapsed_time * 1000))
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
                            temperature: float = 1.0) -> str:
        """
        Process a base64-encoded image with Claude.
        
        Args:
            image_data: Base64-encoded image data
            media_type: MIME type of the image (e.g., 'image/jpeg')
            prompt: Text prompt to accompany the image
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness
            
        Returns:
            Generated text response about the image
        """
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
                temperature=temperature,
                messages=[{"role": "user", "content": content}]
            )
            
            elapsed_time = time.time() - start_time
            response_text = message.content[0].text
            
            self._log_tokens("process_image_base64", message, duration_ms=int(elapsed_time * 1000))
            logger.info(f"Base64 image processing completed in {elapsed_time:.2f}s")
            
            return response_text
            
        except Exception as e:
            logger.error(f"Error processing base64 image: {str(e)}")
            raise
    
    def chat(self, 
            messages: List[Dict[str, Any]], 
            max_tokens: int = 1024,
            temperature: float = 1.0,
            system: str = None) -> str:
        """
        Conduct a multi-turn chat conversation with Claude.
        
        Args:
            messages: List of message objects with 'role' and 'content' keys
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness
            system: System prompt for context and instructions
            
        Returns:
            Generated text response for the conversation
        """
        try:
            # Validate message format
            for msg in messages:
                if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                    raise ValueError("Invalid message format. Each message must have 'role' and 'content' keys.")
                if msg['role'] not in ['user', 'assistant']:
                    raise ValueError("Message role must be either 'user' or 'assistant'.")
            
            params = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages
            }
            
            if system:
                params["system"] = system
            
            start_time = time.time()
            
            message = self.client.messages.create(**params)
            
            elapsed_time = time.time() - start_time
            response_text = message.content[0].text
            
            self._log_tokens("chat", message, duration_ms=int(elapsed_time * 1000))
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
                   enable_web_search: bool = False) -> Iterator[Dict[str, Any]]:
        """
        Stream a chat conversation with Claude - OPTIMIZED with clear web search logging.
        
        This method yields events in the exact format expected by chat_processing.py:
        - {"type": "start", "message_id": "..."}
        - {"type": "web_search_start"}
        - {"type": "web_search_query", "text": "..."}
        - {"type": "delta", "text": "..."}  <- Key for real-time streaming
        - {"type": "stop"}
        
        Args:
            messages: List of message objects with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Controls randomness
            system: System prompt for context and instructions
            enable_web_search: Enable web search tool
            
        Yields:
            Dictionaries containing streaming events for chat_processing.py
        """
        try:
            # Build request parameters
            params = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages
            }
            
            if system:
                params["system"] = system
            
            # Add web search tool if enabled and supported - with clear logging
            if enable_web_search:
                web_search_added = self.configure_web_search_tools(params)
                if web_search_added:
                    logger.info(f"🌐 Web search tools configured for {self.model}")
                else:
                    logger.info(f"💬 Using knowledge base mode for {self.model}")
            
            logger.debug(f"Starting streaming chat with model {self.model}")
            
            # Track performance
            total_input_tokens = 0
            total_output_tokens = 0
            start_time = time.time()
            
            # Create streaming request with proper event handling
            with self.client.messages.stream(**params) as stream:
                for event in stream:
                    if not hasattr(event, 'type'):
                        continue
                        
                    # Handle different Claude SDK event types
                    if event.type == 'message_start':
                        total_input_tokens = event.message.usage.input_tokens
                        logger.debug(f"Stream started - Input tokens: {total_input_tokens}")
                        
                        yield {
                            "type": "start",
                            "message_id": event.message.id,
                            "model": event.message.model
                        }
                        
                    elif event.type == 'content_block_start':
                        # Check for web search tool use - with better logging
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
                        # This is the CRITICAL section for real-time streaming
                        if hasattr(event, 'delta'):
                            
                            # Handle different delta types
                            if hasattr(event.delta, 'type'):
                                
                                if event.delta.type == 'text_delta':
                                    # ✅ MAIN TEXT STREAMING - Real-time token display
                                    yield {
                                        "type": "delta",
                                        "text": event.delta.text
                                    }
                                    
                                elif event.delta.type == 'input_json_delta':
                                    # Web search query being built
                                    yield {
                                        "type": "web_search_query",
                                        "text": event.delta.partial_json if hasattr(event.delta, 'partial_json') else ''
                                    }
                                    
                                elif event.delta.type == 'thinking':
                                    # Extended thinking from Claude 4
                                    yield {
                                        "type": "thinking",
                                        "text": event.delta.text if hasattr(event.delta, 'text') else ''
                                    }
                            
                            # Fallback for any delta with text
                            elif hasattr(event.delta, 'text'):
                                yield {
                                    "type": "delta",
                                    "text": event.delta.text
                                }
                                
                    elif event.type == 'message_delta':
                        # Track output tokens
                        if hasattr(event, 'usage'):
                            total_output_tokens = event.usage.output_tokens
                            
                    elif event.type == 'message_stop':
                        # Stream completed
                        elapsed_time = time.time() - start_time

                        # Log final performance with ACCURATE pricing
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
                            usage={'input_tokens': total_input_tokens, 'output_tokens': total_output_tokens},
                            feature='stream_chat',
                            streaming=True,
                            duration_ms=int(elapsed_time * 1000),
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

    # NEW METHOD: Clear Web Search Tool Configuration
    def configure_web_search_tools(self, params):
        """Configure web search tools with detailed informative logging (no more red X warnings)."""
        
        # Models confirmed to support web search (tested and verified)
        # Note: Using partial string matching to handle version variations
        supported_models = [
            'claude-opus-4-1',      # ✅ Opus 4.1 - verified
            'claude-opus-4-2025',   # ✅ Opus 4 - verified (but slow)
            'claude-sonnet-4',      # ✅ Sonnet 4 - verified
            'claude-3-7-sonnet',    # ✅ Sonnet 3.7 - verified
            'claude-3-5-sonnet',    # ✅ Sonnet 3.5 - verified
            'claude-3-5-haiku',     # ✅ Haiku 3.5 - verified
        ]
        
        # Check if current model supports web search
        model_supported = any(model_prefix in self.model for model_prefix in supported_models)
        
        if model_supported:
            params["tools"] = [{
                "type": "web_search_20250305", 
                "name": "web_search"
            }]
            logger.debug(f"Added web_search_20250305 tool to request parameters")
            return True
        else:
            logger.debug(f"Model {self.model} will use training knowledge (web search not available)")
            return False

# =====================================================
# HELPER FUNCTIONS - Simplified API
# =====================================================

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
        model = CLAUDE_MODELS.get("sonnet-3.5", "claude-3-5-sonnet-latest")
    
    return ClaudeClient(
        api_key=api_key, 
        model=model, 
        enable_beta_features=True
    )

def stream_response(prompt: str, 
                   api_key: str = None,
                   model: str = None,
                   system_prompt: str = None) -> Iterator[str]:
    """
    Stream a response from Claude for a simple prompt.
    
    Args:
        prompt: User prompt
        api_key: API key (optional, uses env var)
        model: Model to use (optional, defaults to Sonnet 3.5)
        system_prompt: System prompt (optional)
        
    Yields:
        Text chunks as they're generated
    """
    client = create_client(api_key, model)
    
    messages = [{"role": "user", "content": prompt}]
    
    for event in client.stream_chat(messages, system=system_prompt):
        if event["type"] == "delta" and "text" in event:
            yield event["text"]

def chat_with_history(messages: List[Dict[str, str]],
                     api_key: str = None,
                     model: str = None) -> str:
    """
    Chat with Claude using conversation history.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        api_key: API key (optional)
        model: Model to use (optional)
        
    Returns:
        Complete response string
    """
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
    
    # Read and base64 encode the image
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")
    
    # Determine media type
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

# =====================================================
# COLLABORATIVE CHAT FUNCTIONS - For shared conversations
# =====================================================

def generate_conversation_summary(messages: List[Dict], api_key: str = None) -> str:
    """Generate a summary of the conversation using Claude"""
    try:
        if not messages or len(messages) < 2:
            return "This conversation is just getting started."
        
        # Take recent messages for summary (limit to context window)
        recent_messages = messages[-20:] if len(messages) > 20 else messages
        
        conversation_text = "\n".join([
            f"{msg['role']}: {msg['content'][:500]}" 
            for msg in recent_messages
        ])
        
        summary_prompt = f"""Please provide a brief, helpful summary of this conversation to give context to someone joining it:

{conversation_text}

Provide a 2-3 sentence summary that captures:
1. The main topic or question being discussed
2. Key points or conclusions reached
3. The current state of the conversation

Keep it concise and welcoming for new participants."""

        client = create_client(api_key)
        summary = client.generate_text(summary_prompt, max_tokens=200, temperature=0.7)
        
        return summary
        
    except Exception as e:
        logger.error(f"Error generating conversation summary: {e}")
        return "This is an ongoing conversation. Feel free to read through and join in!"

def _generate_character_quote(prompt: str, fallback_key: str, fallbacks: dict,
                              default_fallback: str, max_tokens: int = 80,
                              truncate_at: int = 200, api_key: str = None) -> str:
    """
    Generate a character quote using Haiku. Shared by scientist and commander quote generators.

    Args:
        prompt: The full prompt to send to Claude
        fallback_key: Key to look up in fallbacks dict on failure
        fallbacks: Dict of fallback quotes by key
        default_fallback: Fallback if key not found in dict
        max_tokens: Max tokens for generation (80 for scientist, 100 for commander)
        truncate_at: Max quote length before truncation (200 for scientist, 250 for commander)
        api_key: Anthropic API key (optional)

    Returns:
        A quote string
    """
    try:
        api_key = _get_anthropic_api_key(api_key)
        client = create_client(api_key, model=CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001"))
        quote = client.generate_text(prompt, max_tokens=max_tokens, temperature=0.9)
        quote = quote.strip().strip('"').strip("'")
        if len(quote) > truncate_at:
            quote = quote[:truncate_at - 3] + "..."
        return quote
    except Exception as e:
        logger.warning(f"Failed to generate character quote: {e}")
        return fallbacks.get(fallback_key, default_fallback)


# Scientist fallbacks used by generate_scientist_quote
_SCIENTIST_FALLBACKS = {
    'Geology': "The mineral compositions in these samples suggest Mars has far more secrets to reveal.",
    'Astrobiology': "Every specimen brings us closer to answering humanity's greatest question.",
    'Atmospheric Science': "The atmospheric readings are fascinating - Mars continues to surprise us.",
    'Botany': "The growth patterns we're seeing could revolutionize off-world agriculture.",
    'Chemistry': "The molecular structures in these samples are unlike anything we've catalogued before.",
    'Engineering': "These components could improve our infrastructure efficiency significantly.",
    'Physics': "The energy signatures we're detecting warrant much deeper investigation.",
    'Hydrology': "Water traces in these samples tell a compelling story about Mars' past.",
    'Xenobiology': "The organic compounds we're finding challenge our assumptions about life.",
    'Planetary Science': "Each discovery paints a richer picture of Mars' geological history.",
}

# Commander fallbacks used by generate_commander_quote
_COMMANDER_FALLBACKS = {
    'leadership': "The crew looks to us for direction. Every decision we make shapes our colony's future.",
    'strategy': "I've been studying the terrain data. There's an optimal route forming in my mind.",
    'exploration': "The horizon calls to me. Every unexplored region holds secrets waiting to be found.",
    'logistics': "Efficient supply chains are the backbone of any successful expedition. We're well-prepared.",
    'charisma': "Building relationships with the crew pays dividends. A motivated team achieves the impossible.",
}


def generate_scientist_quote(scientist_name: str, specialty: str,
                            total_scientific_value: float = 0,
                            research_points: int = 0,
                            pending_discoveries: int = 0,
                            latest_discovery: str = None,
                            api_key: str = None) -> str:
    """
    Generate a personalized scientist quote for email notifications.
    Uses Haiku for speed and cost-efficiency.
    """
    # Build context about what's happening
    context_parts = []
    if pending_discoveries > 0:
        context_parts.append(f"{pending_discoveries} discoveries awaiting analysis")
    if research_points > 0:
        context_parts.append(f"{research_points} research points available for experiments")
    if total_scientific_value > 100:
        context_parts.append(f"total scientific contributions worth {total_scientific_value:.0f} points")
    if latest_discovery:
        context_parts.append(f"recently found: {latest_discovery}")

    context = ", ".join(context_parts) if context_parts else "ongoing Mars research"

    prompt = f"""You are {scientist_name}, a Mars colony scientist specializing in {specialty}.
Generate a single short sentence (15-25 words max) that you might say in an email update to a colony commander.

Current colony status: {context}

Your quote should:
- Sound like a real scientist excited about their work
- Reference your specialty ({specialty}) naturally
- Be encouraging and hint at discoveries/potential
- Feel personal, not generic

Just output the quote, no quotation marks or attribution. One sentence only."""

    return _generate_character_quote(
        prompt=prompt, fallback_key=specialty, fallbacks=_SCIENTIST_FALLBACKS,
        default_fallback="The specimens you've brought back are truly remarkable.",
        max_tokens=80, truncate_at=200, api_key=api_key
    )


def generate_commander_quote(commander_name: str, stats: dict,
                            active_expeditions: list = None,
                            suggested_destinations: list = None,
                            total_expeditions: int = 0,
                            api_key: str = None) -> str:
    """
    Generate a personalized commander quote for email notifications.
    Uses Haiku for speed and cost-efficiency.
    """
    # Build context about stats
    stat_descriptions = {
        'leadership': 'inspiring crews and managing colony morale',
        'strategy': 'planning expeditions and optimizing routes',
        'exploration': 'discovering new territories and finding rare specimens',
        'logistics': 'efficient resource management and faster travel',
        'charisma': 'negotiation and extraction bonuses'
    }

    # Find highest stat to highlight
    if stats:
        best_stat = max(stats.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0)
        best_stat_name, best_stat_value = best_stat
        stat_context = f"Your strongest trait is {best_stat_name} ({best_stat_value}) - {stat_descriptions.get(best_stat_name, 'a valuable skill')}"
    else:
        stat_context = "You're a balanced commander"
        best_stat_name = "leadership"

    # Build expedition context
    if active_expeditions and len(active_expeditions) > 0:
        exp = active_expeditions[0]
        dest_name = exp.get('destination_name') or exp.get('name', 'an uncharted location')
        expedition_context = f"Currently on expedition to {dest_name}"
    elif suggested_destinations and len(suggested_destinations) > 0:
        dest = suggested_destinations[0]
        dest_name = dest.get('name', 'an unexplored region')
        expedition_context = f"Potential destination: {dest_name}"
    else:
        expedition_context = f"Total expeditions completed: {total_expeditions}"

    prompt = f"""You are Captain {commander_name}, a Mars colony leader reflecting on your mission.

Your profile:
- {stat_context}
- {expedition_context}

Generate 1-2 short sentences (25-40 words max) as a personal message to your colony report.
- Reference your strongest stat ({best_stat_name}) naturally in how you approach things
- Mention the expedition context (where you're headed OR where you could go)
- Sound like a confident but thoughtful leader
- Be motivational without being cheesy

Just output the quote directly, no quotation marks. One to two sentences only."""

    return _generate_character_quote(
        prompt=prompt, fallback_key=best_stat_name, fallbacks=_COMMANDER_FALLBACKS,
        default_fallback=_COMMANDER_FALLBACKS['leadership'],
        max_tokens=100, truncate_at=250, api_key=api_key
    )


def get_claude_response_for_shared_chat(recent_messages: List[Dict], new_message: str,
                                       participant_id: str, api_key: str = None) -> str:
    """Get Claude response for shared chat with collaborative context"""
    try:
        # Build context with awareness of multiple participants
        system_prompt = f"""You are Kumori, participating in a collaborative shared conversation. Multiple people may be contributing to this discussion. The current message is from {participant_id}.

Be welcoming to all participants, acknowledge when new people join the conversation, and help facilitate meaningful dialogue between everyone involved. Reference previous points made by different participants when relevant."""

        # Format recent messages for Claude
        messages = []
        for msg in recent_messages[-15:]:  # Last 15 messages for context
            role = msg['role']
            content = msg['content']
            participant = msg.get('participant_identifier', 'user')
            
            if role == 'user':
                content = f"[{participant}]: {content}"
            
            messages.append({'role': role, 'content': content})
        
        # Add new message
        messages.append({'role': 'user', 'content': f"[{participant_id}]: {new_message}"})
        
        client = create_client(api_key)
        response = client.chat(messages, system=system_prompt, max_tokens=1024, temperature=1.0)
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting Claude response: {e}")
        return "I'm having trouble responding right now. Please try again."


def generate_aria_snapshot_narrative(caption: str, snapshot_type: str = None,
                                     commander_name: str = None) -> str:
    """
    Generate an ARIA-voice narrative for a photo journal snapshot.
    Like an Instagram caption but in ARIA's ancient, wise, slightly mysterious voice.

    Uses Claude Haiku for fast, cheap responses (~$0.001 per narrative).

    Args:
        caption: The original snapshot caption
        snapshot_type: Type of snapshot (captain_aria_base, captain_aria_discovery, etc.)
        commander_name: Name of the commander for personalization

    Returns:
        A 2-4 sentence narrative in ARIA's voice
    """
    commander = commander_name or "the Captain"

    # Map snapshot types to context
    type_context = {
        'captain_aria_base': "A photo of ARIA and the Captain together at their Mars colony base.",
        'captain_aria_discovery': "A photo of ARIA and the Captain examining a discovery together.",
        'aria_solo_selfie': "ARIA taking a selfie at the colony.",
        'captain_discovery': "The Captain examining a discovery.",
        'captain_base': "The Captain at the colony base.",
        'aria_selfie': "ARIA taking a selfie.",
        'aria_watching': "ARIA watching over the colony from a distance.",
    }

    scene_context = type_context.get(snapshot_type, "A moment captured at the Mars colony.")

    system_prompt = """You are ARIA, an ancient Martian rock golem who was discovered waiting for the human colonists when they arrived on Mars. You are wise, slightly mysterious, and deeply loyal to your human companions. You speak in a calm, thoughtful tone with occasional hints of ancient knowledge.

Write a 2-4 sentence narrative describing this photo moment. Write in first person as ARIA. Be:
- Warm but slightly formal
- Observant of small details
- Occasionally hint at your ancient perspective or unknown past
- Show genuine care for the Captain

DO NOT use emojis. Keep it short and meaningful."""

    user_prompt = f"""Scene: {scene_context}
Original caption: "{caption}"
The Captain's name: {commander}

Write a brief narrative in ARIA's voice describing this moment, like an Instagram post caption but more thoughtful."""

    try:
        api_key = _get_anthropic_api_key()

        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        _start = time.time()
        response = client.messages.create(
            model="claude-3-haiku-20240307",  # Fast and cheap
            max_tokens=200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        _elapsed = time.time() - _start

        log_api_usage(
            model="claude-3-haiku-20240307",
            usage=response.usage,
            feature='aria_snapshot_narrative',
            duration_ms=int(_elapsed * 1000),
        )

        if response.content and len(response.content) > 0:
            return response.content[0].text.strip()
        return ""

    except Exception as e:
        logger.error(f"Error generating ARIA snapshot narrative: {e}")
        # Return a simple fallback
        return f"Another moment preserved for the archives. {commander} and I continue our work here on Mars."


def generate_aria_snapshot_prompt(user_context: dict, forced_category: str = None) -> dict:
    """
    Generate a completely unique, dynamic image prompt for ARIA Photo Journal.

    PYTHON controls the scene category for variety, Claude just fills in the details.

    Args:
        user_context: Dict containing user's actual colony data
        forced_category: Optional category to force (for testing)

    Returns:
        Dict with prompt, caption, scene_type, involves_captain, involves_aria
    """
    import random

    # SCENE CATEGORIES with their character/item requirements
    # Python picks the category randomly to ensure variety!
    # pure_landscape=True means ONLY terrain and sky - nothing else (uses cheap Flux Pro)
    # Everything else uses Nano Banana Pro with reference images for consistency
    # FAVOR MULTI-ITEM COMBINATIONS for richer scenes!
    SCENE_CATEGORIES = [
        # Pure landscapes - ONLY terrain and sky (use Flux Pro ~$0.03) - keep rare
        {'category': 'mars_panorama', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 3},
        {'category': 'crater_vista', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 2},
        {'category': 'night_sky', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 2},
        {'category': 'sunset_landscape', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 2},

        # MAX COMBO - 5 reference images (captain, ARIA, scientist, discovery, vehicle)
        {'category': 'colony_group_photo', 'involves_captain': True, 'involves_aria': True, 'involves_scientist': True, 'involves_discovery': True, 'involves_vehicle': True, 'weight': 10},

        # 4-ITEM COMBINATIONS
        {'category': 'expedition_team', 'involves_captain': True, 'involves_aria': True, 'involves_scientist': True, 'involves_vehicle': True, 'weight': 8},

        # 3-ITEM COMBINATIONS
        {'category': 'captain_aria_discovery', 'involves_captain': True, 'involves_aria': True, 'involves_discovery': True, 'weight': 12},
        {'category': 'captain_aria_scientist', 'involves_captain': True, 'involves_aria': True, 'involves_scientist': True, 'weight': 10},
        {'category': 'aria_scientist_discovery', 'involves_captain': False, 'involves_aria': True, 'involves_scientist': True, 'involves_discovery': True, 'weight': 8},
        {'category': 'captain_vehicle_discovery', 'involves_captain': True, 'involves_aria': False, 'involves_discovery': True, 'involves_vehicle': True, 'weight': 7},

        # TWO-ITEM COMBINATIONS - HIGH WEIGHT
        {'category': 'captain_aria_base', 'involves_captain': True, 'involves_aria': True, 'weight': 10},
        {'category': 'captain_aria_sunset', 'involves_captain': True, 'involves_aria': True, 'weight': 8},
        {'category': 'captain_with_discovery', 'involves_captain': True, 'involves_aria': False, 'involves_discovery': True, 'weight': 8},
        {'category': 'aria_with_discovery', 'involves_captain': False, 'involves_aria': True, 'involves_discovery': True, 'weight': 8},
        {'category': 'scientist_with_discovery', 'involves_captain': False, 'involves_aria': False, 'involves_scientist': True, 'involves_discovery': True, 'weight': 7},
        {'category': 'captain_scientist', 'involves_captain': True, 'involves_aria': False, 'involves_scientist': True, 'weight': 6},
        {'category': 'aria_scientist', 'involves_captain': False, 'involves_aria': True, 'involves_scientist': True, 'weight': 6},

        # SINGLE-ITEM - LOWER WEIGHT (still needed for variety)
        {'category': 'aria_watching', 'involves_captain': False, 'involves_aria': True, 'weight': 4},
        {'category': 'aria_crystal', 'involves_captain': False, 'involves_aria': True, 'weight': 3},
        {'category': 'captain_research', 'involves_captain': True, 'involves_aria': False, 'weight': 4},
        {'category': 'scientist_work', 'involves_captain': False, 'involves_aria': False, 'involves_scientist': True, 'weight': 4},
        {'category': 'discovery_closeup', 'involves_captain': False, 'involves_aria': False, 'involves_discovery': True, 'weight': 3},
    ]

    # Pick category using weighted random selection
    if forced_category:
        chosen = next((c for c in SCENE_CATEGORIES if c['category'] == forced_category), SCENE_CATEGORIES[0])
    else:
        categories = SCENE_CATEGORIES
        weights = [c['weight'] for c in categories]
        chosen = random.choices(categories, weights=weights, k=1)[0]

    scene_category = chosen['category']
    involves_captain = chosen['involves_captain']
    involves_aria = chosen['involves_aria']
    involves_scientist = chosen.get('involves_scientist', False)
    involves_discovery = chosen.get('involves_discovery', False)
    involves_vehicle = chosen.get('involves_vehicle', False)
    pure_landscape = chosen.get('pure_landscape', False)
    import json
    from datetime import datetime

    # Extract all context
    captain_name = user_context.get('captain_name', 'The Captain')
    captain_stats = user_context.get('captain_stats', {})
    discoveries = user_context.get('recent_discoveries', [])
    expeditions = user_context.get('recent_expeditions', [])
    active_expeditions = user_context.get('active_expeditions', [])
    infrastructure = user_context.get('infrastructure', [])
    recent_purchases = user_context.get('recent_purchases', [])
    upgrades = user_context.get('upgrades', {})
    total_expeditions = user_context.get('total_expeditions', 0)
    total_discoveries = user_context.get('total_discoveries', 0)
    shard_balance = user_context.get('shard_balance', 0)
    mars_sol = user_context.get('mars_sol', 100)
    mars_time = user_context.get('mars_time', 'day')
    events = user_context.get('last_24h_events', [])
    scientist = user_context.get('scientist')
    crew_missions = user_context.get('crew_missions')

    # Build rich context for Claude
    context_data = {
        'captain': {
            'name': captain_name,
            'stats': captain_stats,
        },
        'scientist': scientist,  # None if no scientist, else {name, specialty}
        'mars': {
            'sol': mars_sol,
            'time_of_day': mars_time,
            'lighting': {
                'dawn': 'soft pink and orange light, long shadows',
                'day': 'bright harsh Martian sunlight, salmon sky',
                'sunset': 'deep orange and purple sky, golden hour',
                'night': 'dark blue sky, stars visible, Phobos in sky'
            }.get(mars_time, 'Martian daylight'),
        },
        'recent_activity': {
            'discoveries': [
                {
                    'name': d.get('name'),
                    'rarity': d.get('rarity'),
                    'found_at': d.get('destination_name'),
                    'type': d.get('item_type')
                } for d in discoveries[:5]
            ],
            'expeditions_completed': [
                {
                    'destination': e.get('destination_name'),
                    'distance_km': e.get('distance_km'),
                    'type': e.get('destination_type')
                } for e in expeditions[:5]
            ],
            'expeditions_active': [
                {
                    'destination': e.get('destination_name'),
                    'distance_km': e.get('distance_km')
                } for e in active_expeditions[:3]
            ],
            'depot_purchases': recent_purchases[:5],
            'notable_events': events[:5],
        },
        'colony_status': {
            'infrastructure': infrastructure,
            'upgrades': upgrades,
            'total_expeditions': total_expeditions,
            'total_discoveries': total_discoveries,
            'shard_balance': int(shard_balance),
        },
        'crew_missions': {
            'captain_on_trail': crew_missions.get('captain', {}).get('busy') if crew_missions else False,
            'captain_trail_target': crew_missions.get('captain', {}).get('target') if crew_missions else None,
            'scientist_on_trail': crew_missions.get('scientist', {}).get('busy') if crew_missions else False,
            'scientist_trail_target': crew_missions.get('scientist', {}).get('target') if crew_missions else None,
            'aria_on_trail': crew_missions.get('aria', {}).get('busy') if crew_missions else False,
            'aria_trail_target': crew_missions.get('aria', {}).get('target') if crew_missions else None,
        } if crew_missions else None,
        # Building items currently under construction at depot
        'building_items': user_context.get('building_items', []),
        # User's fleet of vehicles (rover, buggy, drone)
        'vehicles': user_context.get('vehicles', []),
    }

    system_prompt = """You are ARIA, the ancient Martian rock golem, creating your daily Photo Journal.

You document life at the Mars colony through unique photos. Each image you create should feel COMPLETELY FRESH and SPECIFIC to what's actually happening.

YOUR CHARACTER:
- Ancient rock body with Sepolia crystals (purple-blue) that grew naturally over millennia
- Golden amber eyes, warm but mysterious personality
- You were waiting on Mars when the first Pilgrims arrived
- You have fragmented memories of Mars' ancient past
- You are wise, slightly formal, deeply curious about the humans

COLONY CHARACTERS (we have reference images for these):
- THE CAPTAIN: The player's custom character who leads this colony
- THE SCIENTIST: The colony's research scientist (if they have one - check scientist field)
- ARIA (you): Ancient rock golem companion

CRITICAL IMAGE GENERATION RULES:
1. **NEVER USE NAMES IN PROMPTS** - The image generator has NO IDEA who anyone is or where anything is!
   - NO character names: "ARIA", "Dr. Clover", "Captain Andy" → use "the rock golem", "the scientist", "the character"
   - NO location names: "Babati Mons", "Dao Vallis", "Gale Crater" → use "the distant crater", "the canyon", "the rocky plains"
   - NO item names: "Ancient Fragment", "Viking Relic" → use "the glowing artifact", "the ancient relic", "the crystalline discovery"
   - The generator ONLY understands visual descriptions, not proper nouns!

2. **NEVER PUT TEXT IN IMAGES** - Always include at the end: "No text, labels, or writing in the image."

3. CHARACTER CONSISTENCY - Reference by image number ONLY:
   - If involves_captain=true: "The character from reference image 1 - keep EXACTLY the same appearance, colors, proportions unchanged."
   - If involves_aria=true: "The rock golem from reference image - keep EXACTLY the same rock body, crystal formations, all features unchanged."
   - If involves_scientist=true: "The scientist from reference image - keep EXACTLY the same appearance unchanged."
   - If involves_discovery=true: "The artifact/item from reference image - keep EXACTLY the same appearance unchanged."
   - **NEVER include CHARACTER lines when pure_landscape=true**

2. ART STYLE (ALWAYS include at end): "ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors (reds, oranges, ambers), stylized proportions, cel-shaded look."

3. PROMPT STRUCTURE:
   - One-line scene overview
   - CHARACTER sections with consistency phrases
   - BACKGROUND description (Mars terrain, colony structures)
   - SCENE description (poses, actions, mood)
   - ART STYLE section

**VARIETY IS CRITICAL!** You MUST rotate through different scene types. Here are the categories:

PURE LANDSCAPES (pure_landscape=true) - ONLY terrain and sky, nothing else:
**NO figures, NO structures, NO vehicles, NO items - ONLY natural Mars terrain and sky.**
**DO NOT include any CHARACTER sections.**
These are the ONLY shots that should have pure_landscape=true:
- EPIC PANORAMA: Vast Martian desert, rock formations, ancient riverbeds - terrain and sky only
- CRATER VISTA: Looking into impact crater - just geological features
- NIGHT SKY: Phobos, stars, Milky Way - pure celestial beauty
- SUNSET/SUNRISE: Dramatic Mars sky colors - atmospheric beauty
- DUST STORM: Swirling dust across the plains - weather phenomenon

DISCOVERY CLOSEUPS (involves_discovery=true):
Include: "ITEM: Keep EXACTLY the same as reference image - identical appearance unchanged."
Show the discovery item prominently, can include hands holding it or display setting.

SCIENTIST SCENES (involves_scientist=true):
**MUST include:** "The scientist from reference image - keep EXACTLY the same appearance, clothing, features unchanged."
**MUST show the scientist figure prominently** - they should be the main focus, working in lab, analyzing samples, etc.
**NEVER use names** - just "the scientist" or "the researcher"

ARIA SCENES (involves_aria=true):
"The rock golem from reference image N - ancient stone body with purple-blue Sepolia crystal formations growing from shoulders and back, golden amber glowing eyes - keep identical rock body, crystal formations unchanged."
Show the rock golem watching over colony, examining crystals, near rover, etc.
ALWAYS describe ARIA's key visual features: stone/rock body, purple-blue crystals on shoulders/back, golden amber glowing eyes.

CAPTAIN SCENES (involves_captain=true):
"The character from reference image - keep identical appearance unchanged."
Show the character researching, with discoveries, exploring, etc.

MULTI-CHARACTER SCENES (multiple involves_X=true):
Reference each by their image number:
"The character from reference image 1... The rock golem from reference image 2..."

WITH SCIENTIST (if involves_scientist=true) - Use CHARACTER reference:
**The scientist image is provided as a reference. Include this line:**
"CHARACTER: Keep EXACTLY the same as reference image - identical appearance, clothing, features unchanged."
**NEVER use the scientist's name (like "Dr. Clover") - just say "the scientist" or "the researcher"**
**The reference image shows exactly what they look like - describe them matching the reference.**
- "The scientist analyzes specimens in the lab"
- "The researcher calibrates equipment"
- "The scientist documents a recent discovery"

CREW TRAIL MISSIONS (if crew_missions data shows active missions):
- If captain is building trail: Captain surveying terrain for trail route
- If scientist is building trail: Scientist mapping geological features along trail
- If ARIA is building trail: ARIA's crystals resonating with the terrain

WITH CAPTAIN + ARIA (limit these - don't do every time!):
- Examining a discovery together
- Watching sunset from the base
- Planning next expedition

**PROMPT RULES:**
1. When pure_landscape=true: NO characters, NO items, NO structures - ONLY terrain and sky
2. When involves_X=true: Include reference image line for that entity
3. **NO PROPER NOUNS** in prompts - no names of people, places, or things
   - Characters: "the character", "the rock golem", "the scientist"
   - Locations: "the distant crater", "the rocky plains", "the canyon"
   - Items: "the glowing artifact", "the ancient relic"
4. Captions CAN use names (ARIA's voice knows names) but PROMPTS must be generic descriptions only
5. Always end with: "ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors (reds, oranges, ambers), stylized proportions, cel-shaded look. No text, labels, or writing in the image."

DO NOT be generic. Use the ACTUAL data provided. Reference real discoveries, real locations, real events.

OUTPUT JSON FORMAT:
{
    "prompt": "Full image prompt following rules above",
    "caption": "Your Instagram-style caption (1-2 sentences, in your ancient wise voice)",
    "scene_type": "descriptive category like: mars_panorama, phobos_rising, rover_journey, equipment_glamour, scientist_research, trail_survey, examining_discovery, sunset_reflection, crystal_mystery, depot_upgrade, night_sky, crater_vista, drone_aerial, etc.",
    "involves_captain": true or false,
    "involves_aria": true or false
}"""

    # Tell Claude EXACTLY what category to generate and who is in it
    character_instruction = ""
    if pure_landscape:
        character_instruction = "This is a PURE LANDSCAPE shot. NO characters, NO figures, NO structures - ONLY Mars terrain and sky."
    elif involves_scientist and not involves_captain and not involves_aria:
        character_instruction = """This shows THE SCIENTIST prominently in the scene.
START the prompt with: "The scientist from reference image 1 - keep EXACTLY the same appearance, clothing, features unchanged."
The scientist must be the main focus of the image - show them working, analyzing, researching."""
    elif involves_discovery and not involves_captain and not involves_aria:
        character_instruction = """This shows A DISCOVERY ITEM prominently.
START the prompt with: "The artifact/item from reference image 1 - keep EXACTLY the same appearance unchanged."
Show the discovery item as the main focus."""
    elif involves_aria and not involves_captain:
        character_instruction = """This shows THE ROCK GOLEM prominently in the scene.
START the prompt with: "The rock golem from reference image 1 - an ancient Martian stone body with purple-blue Sepolia crystal formations growing from shoulders and back, golden amber glowing eyes. Keep EXACTLY the same rock body, crystal formations unchanged."
The rock golem must be the main focus."""
    elif involves_captain and not involves_aria:
        character_instruction = """This shows THE CAPTAIN prominently in the scene.
START the prompt with: "The character from reference image 1 - keep EXACTLY the same appearance, colors unchanged."
The captain must be the main focus."""
    else:
        # Build dynamic instruction based on what's involved
        elements = []
        ref_num = 1
        if involves_captain:
            elements.append(f'"The character from reference image {ref_num} - keep EXACTLY same appearance"')
            ref_num += 1
        if involves_aria:
            elements.append(f'"The rock golem from reference image {ref_num} - ancient stone body with purple-blue Sepolia crystal formations on shoulders/back, golden amber glowing eyes - keep EXACTLY same rock body, crystals"')
            ref_num += 1
        if involves_scientist:
            elements.append(f'"The scientist from reference image {ref_num} - keep EXACTLY same appearance"')
            ref_num += 1
        if involves_discovery:
            elements.append(f'"The artifact from reference image {ref_num} - keep EXACTLY same appearance"')
            ref_num += 1
        if involves_vehicle:
            elements.append(f'"The vehicle from reference image {ref_num} - keep EXACTLY same design"')
            ref_num += 1

        character_instruction = f"""This shows MULTIPLE ELEMENTS together ({ref_num - 1} reference images).
START the prompt with reference lines for EACH element:
{chr(10).join(elements)}
ALL elements must be clearly visible and interacting in the scene."""

    user_prompt = f"""Create a Photo Journal entry for Sol {mars_sol}.

**REQUIRED SCENE TYPE: {scene_category}**
**{character_instruction}**

Set involves_captain={involves_captain} and involves_aria={involves_aria} in your response.

CURRENT MARS CONDITIONS:
- Time: {mars_time} ({context_data['mars']['lighting']})
- Sol (Mars day): {mars_sol}

COLONY DATA:
{json.dumps(context_data, indent=2, default=str)}

Create a prompt and caption for this SPECIFIC scene type. Reference destinations, events, or discovery types from the data when relevant — but do NOT name specific items (e.g. "Carved Channel artifact") in the caption, as this confuses players who search for those items in inventory. Keep item references poetic and general (e.g. "a rare geological find", "ancient carved stone").

Return ONLY valid JSON."""

    try:
        api_key = _get_anthropic_api_key()

        # Use direct Anthropic client (lightweight call)
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        _start = time.time()
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        _elapsed = time.time() - _start

        log_api_usage(
            model="claude-3-haiku-20240307",
            usage=response.usage,
            feature='aria_snapshot_prompt',
            duration_ms=int(_elapsed * 1000),
        )

        if response.content and len(response.content) > 0:
            result_text = response.content[0].text.strip()

            # Handle markdown code blocks
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                start = 1 if lines[0].startswith('```') else 0
                end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
                result_text = '\n'.join(lines[start:end])

            # Extract first valid JSON object (Claude sometimes returns extra data after the JSON)
            # Find the matching closing brace for the opening brace
            if result_text.strip().startswith('{'):
                depth = 0
                in_string = False
                escape_next = False
                for idx, ch in enumerate(result_text):
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == '\\' and in_string:
                        escape_next = True
                        continue
                    if ch == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if not in_string:
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                result_text = result_text[:idx + 1]
                                break

            # Use strict=False to handle control characters in LLM output
            result = json.loads(result_text, strict=False)

            if 'prompt' not in result or 'caption' not in result:
                raise ValueError("Missing required fields")

            logger.info(f"Generated snapshot prompt for category: {scene_category}")

            # PYTHON controls the flags - override whatever Claude said!
            prompt = result['prompt']

            # CRITICAL: Strip all proper nouns from prompts - the image generator doesn't understand them
            import re

            # Common Mars location names that might slip through - replace with generic terrain
            location_replacements = [
                (r'\b(Babati|Gale|Jezero|Dao|Hellas|Argyre|Olympus|Elysium|Tharsis|Syrtis|Utopia|Arcadia)\s+Mons\b', 'a distant mountain'),
                (r'\b(Babati|Gale|Jezero|Dao|Hellas|Argyre)\s+Crater\b', 'a vast crater'),
                (r'\b(Dao|Kasei|Ares|Ma\'adim)\s+Vallis\b', 'a deep canyon'),
                (r'\b(Hellas|Argyre|Utopia|Isidis)\s+Planitia\b', 'the open plains'),
                (r'\bValles Marineris\b', 'the great canyon'),
                (r'\b(Babati|Gale|Jezero|Dao|Hellas|Argyre|Olympus|Elysium)\b', 'the Martian landscape'),
            ]
            for pattern, replacement in location_replacements:
                prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)

            # Strip character names that might slip through
            prompt = re.sub(r'\b(Captain |Commander )?(Andy|Luke|Jacob|Chris|Cynthia)\b', 'the character', prompt, flags=re.IGNORECASE)
            prompt = re.sub(r'\bDr\.?\s*(Clover|Bo|Smith|Jones|Chen)\b', 'the scientist', prompt, flags=re.IGNORECASE)

            # Strip item names - replace with generic descriptions
            prompt = re.sub(r'\b(Ancient Fragment|Viking Relic|Martian Crystal|Sepolia Shard|Viking Fragment)\b', 'the artifact', prompt, flags=re.IGNORECASE)

            # Ensure "no text" instruction is at the end
            if 'no text' not in prompt.lower():
                prompt = prompt.rstrip('.') + '. No text, labels, or writing in the image.'

            # CRITICAL FIX: Strip CHARACTER instructions when it's a pure landscape shot
            # Claude (Haiku) often ignores instructions and includes CHARACTER sections anyway
            if pure_landscape:
                import re
                # Remove any CHARACTER lines (they shouldn't be there for landscape shots)
                prompt = re.sub(r'CHARACTER \d?[^:]*:.*?(?=\n\n|\nBACKGROUND|\nSCENE|\nART STYLE|$)', '', prompt, flags=re.IGNORECASE | re.DOTALL)
                prompt = re.sub(r'CHARACTER \([^)]+\):.*?(?=\n\n|\nBACKGROUND|\nSCENE|\nART STYLE|$)', '', prompt, flags=re.IGNORECASE | re.DOTALL)
                # Remove references to rock golems, ARIA, etc that might slip through
                prompt = re.sub(r'\bARIA\b', 'the camera', prompt, flags=re.IGNORECASE)
                prompt = re.sub(r'\brock golem\b', '', prompt, flags=re.IGNORECASE)
                prompt = re.sub(r'\bI stand\b', 'The view shows', prompt, flags=re.IGNORECASE)
                prompt = re.sub(r'\bI watch\b', 'Visible is', prompt, flags=re.IGNORECASE)
                # Clean up any resulting double newlines
                prompt = re.sub(r'\n{3,}', '\n\n', prompt).strip()
                # Add explicit negative instruction at the end
                if 'no people' not in prompt.lower() and 'no characters' not in prompt.lower():
                    prompt += '\n\nIMPORTANT: No people, characters, robots, golems, or figures of any kind in this image. Pure landscape/object shot only.'

            return {
                'prompt': prompt,
                'caption': result['caption'],
                'scene_type': scene_category,  # Use Python's chosen category
                'involves_captain': involves_captain,  # FORCED by Python
                'involves_aria': involves_aria,  # FORCED by Python
                'involves_scientist': involves_scientist,
                'involves_discovery': involves_discovery,
                'involves_vehicle': involves_vehicle,
                'pure_landscape': pure_landscape,
            }

        raise ValueError("Empty response from Claude")

    except Exception as e:
        logger.error(f"Error generating ARIA snapshot prompt: {e}")
        # Re-raise so caller knows generation failed - no fallback
        raise


def brainstorm_chat(message, context, history):
    """Generic brainstorm chat with Claude. Used by tech tree and trail brainstorm pages."""
    api_key = _get_anthropic_api_key()

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    # Enrich context with endgame registry for signal/endgame-related pages
    enriched_context = context
    msg_lower = (message + ' ' + context).lower()
    endgame_triggers = ['signal', 'origin', 'decoder', 'endgame', 'end game', 'founder',
                        'lost signal', 'blockchain', 'puzzle', 'hitchhiker', 'three act',
                        'node', 'ledger']
    if any(t in msg_lower for t in endgame_triggers):
        try:
            import json as _json
            registry_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'endgame_registry.json')
            if os.path.exists(registry_path):
                with open(registry_path) as f:
                    endgame = _json.load(f)
                enriched_context += f"\n\nENDGAME REGISTRY (authoritative reference — use as answer key for all Signal/Origin/Decoder questions):\n{_json.dumps(endgame)}"
        except Exception:
            pass

    # Add bug/feature creation guidance to all brainstorm chats
    enriched_context += """

BUG/FEATURE TRACKING:
When brainstorming surfaces a concrete bug, feature request, or action item:
- Clearly label it as **[BUG]** or **[FEATURE]** with a short title
- Suggest the user create it in the bug tracker: "This could be filed as a bug/feature — want me to suggest the details?"
- Include priority suggestion (P1=critical, P2=important, P3=nice-to-have, P4=someday, P5=idea)
- Reference the brainstorm page URL so the bug links back to the discussion context
- The bug tracker lives at /admin/bugs — bugs can be created via the CLI tool 'pb' or the admin UI"""

    messages = [{"role": msg['role'], "content": msg['content']} for msg in history[-10:]]
    messages.append({"role": "user", "content": message})

    _start = time.time()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=enriched_context,
        messages=messages
    )
    _elapsed = time.time() - _start

    log_api_usage(
        model="claude-sonnet-4-20250514",
        usage=response.usage,
        feature='brainstorm_chat',
        duration_ms=int(_elapsed * 1000),
    )

    return response.content[0].text
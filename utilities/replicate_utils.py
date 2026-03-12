import replicate
import logging
from google.cloud import secretmanager
from config import PROJECT_ID, REPLICATE_TOKEN_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_secrets_cache = {}
_sm_client = None

def get_secret(secret_id, project_id=None):
    """Retrieve secret from Google Cloud Secret Manager (cached)"""
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

class VisionAnalyzer:
    """Generic image analysis using LLaVA-13B vision model"""
    
    def __init__(self, token_secret_id=None, project_id=None):
        """Initialize VisionAnalyzer with Replicate API credentials"""
        logger.info("Initializing VisionAnalyzer...")
        self.project_id = project_id or PROJECT_ID
        token_id = token_secret_id or REPLICATE_TOKEN_ID
        token = get_secret(token_id, self.project_id)
        self.client = replicate.Client(api_token=token)
        self.model = "yorickvp/llava-13b:80537f9eead1a5bfa72d5ac6ea6414379be41d4d4f6679fd776e9535d1eb58bb"
        logger.info("VisionAnalyzer initialized successfully")
    
    def analyze(self, image_url, prompt, temperature=0.2, max_tokens=1024):
        """
        Generic analysis method - accepts any custom prompt
        
        Args:
            image_url: URL of the image to analyze
            prompt: Any question or instruction for the model
            temperature: Randomness (0=deterministic, 1=random)
            max_tokens: Maximum response length
        
        Returns:
            String response from the model
        """
        logger.info(f"Analyzing image with LLaVA...")
        try:
            output = self.client.run(
                self.model,
                input={
                    "image": image_url,
                    "prompt": prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": 1
                }
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
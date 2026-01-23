"""
Twilio authentication utilities
"""
import logging
import config
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def verify_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    """
    Verify Twilio signature for WebSocket connection using official Twilio RequestValidator
    
    Args:
        request_url: The full URL of the request (without query string)
        params: Dictionary of query parameters
        signature: The X-Twilio-Signature header value
    
    Returns:
        True if signature is valid, False otherwise
    """
    logger.info("verify_twilio_signature called (url=%s)", request_url)
    logger.debug(f"=== Twilio Signature Verification Debug ===")
    logger.debug(f"Request URL: {request_url}")
    logger.debug(f"Query params received: {params}")
    logger.debug(f"Signature header received: {signature}")
    logger.debug(f"Auth token configured: {bool(config.settings.twilio_auth_token)}")
    logger.debug(f"Auth token length: {len(config.settings.twilio_auth_token) if config.settings.twilio_auth_token else 0}")
    
    if not config.settings.twilio_auth_token:
        logger.warning("Twilio auth token not configured, skipping signature verification")
        return True  # Allow connection if token not configured (for development)
    
    if not signature:
        logger.error("Missing X-Twilio-Signature header")
        return False
    
    try:
        # Initialize the Twilio RequestValidator with auth token
        validator = RequestValidator(config.settings.twilio_auth_token)
        
        # Validate the signature using Twilio's official validator
        # The validator.validate() method handles all the HMAC-SHA1 computation internally
        is_valid = validator.validate(request_url, params, signature)
        
        logger.info(f"Twilio RequestValidator result: {is_valid}")
        logger.info(f"=== Verification result: {is_valid} ===")
        
        return is_valid
    except Exception as e:
        logger.error(f"Error during Twilio signature verification: {e}", exc_info=True)
        return False

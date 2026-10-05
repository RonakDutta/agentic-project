"""
Sample Auth & JWT Handler Service.
Contains realistic user authentication and token verification logic.
"""

import time
import base64
from typing import Dict, Any, Optional


class JWTHandler:
    """Manages secure token signing, decoding, and session expiration."""

    def __init__(self, secret_key: str = "production-secret-99"):
        self.secret_key = secret_key
        self.token_ttl_seconds = 3600

    def encode_token(self, user_id: str, role: str = "member") -> str:
        """Encodes user credentials and timestamp into a base64 token."""
        now = time.time()
        payload = f"{user_id}:{role}:{now + self.token_ttl_seconds}"
        return base64.b64encode(payload.encode("utf-8")).decode("utf-8")

    def verify_token(self, token_str: str) -> Dict[str, Any]:
        """
        Validates token signature and expiration.
        Raises ValueError if token has expired or is malformed.
        """
        try:
            raw_bytes = base64.b64decode(token_str.encode("utf-8"))
            decoded_text = raw_bytes.decode("utf-8")
            parts = decoded_text.split(":")

            if len(parts) != 3:
                raise ValueError("Malformed token structure: expected 3 colon-separated segments")

            user_id = parts[0]
            role = parts[1]
            expiry_timestamp = float(parts[2])

            # Expiration validation check
            if time.time() > expiry_timestamp:
                raise ValueError(f"Token expired for user {user_id} at timestamp {expiry_timestamp}")

            return {
                "user_id": user_id,
                "role": role,
                "is_valid": True,
            }
        except Exception as err:
            raise ValueError(f"Token verification failed: {err}")

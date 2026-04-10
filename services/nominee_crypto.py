"""
Fernet encryption for nominee PII at application layer (DynamoDB still uses SSE at rest).
"""

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config.settings import settings

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None


def _build_fernet() -> Fernet:
    key_str = (settings.patient_nominee_fernet_key or "").strip()
    if key_str:
        return Fernet(key_str.encode("utf-8") if isinstance(key_str, str) else key_str)
    if settings.is_production:
        raise RuntimeError(
            "PATIENT_NOMINEE_FERNET_KEY is required in production for nominee encryption"
        )
    # Development: generate ephemeral key (nominee data lost on restart unless key set)
    logger.warning(
        "PATIENT_NOMINEE_FERNET_KEY not set; using ephemeral dev key (data not portable across restarts)"
    )
    return Fernet(Fernet.generate_key())


def get_nominee_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _build_fernet()
    return _fernet


def encrypt_field(plain: str) -> str:
    if plain is None:
        return ""
    return get_nominee_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_field(token: str) -> str:
    if not token:
        return ""
    try:
        return get_nominee_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt nominee field (wrong key or corrupt data)")
        return ""

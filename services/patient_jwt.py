"""
Patient-facing JWT helpers: Google-style ID tokens (unverified decode) and
signed dev/test-user tokens (issuer anvega-test, HS256).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt

from config import settings
from config.settings import Settings

logger = logging.getLogger(__name__)

TEST_USER_JWT_ISSUER = "anvega-test"
TEST_USER_EMAIL_HOST = "test.anvega.local"


def is_allowed_test_user_sub(user_id: str, cfg: Optional[Settings] = None) -> bool:
    """
    True only for ids equal to ``{prefix}{digits}`` (e.g. test.anvega1, test.anvega2).
    No separator between prefix and the numeric suffix; suffix must be 1+ ASCII digits.
    """
    cfg = cfg or settings
    uid = (user_id or "").strip()
    prefix = (cfg.test_user_sub_prefix or "test.anvega").strip()
    if not uid.startswith(prefix):
        return False
    suffix = uid[len(prefix) :]
    return bool(suffix) and suffix.isdigit()


def _display_name_for_test_user(uid: str) -> str:
    """e.g. test.anvega1 -> Test user (anvega1)."""
    rest = uid.split(".", 2)
    label = rest[-1] if len(rest) >= 2 else uid
    return f"Test user ({label})"


def mint_test_user_access_token(user_id: str, cfg: Optional[Settings] = None) -> Tuple[str, int]:
    """
    Issue a signed JWT for an allowed test user. Raises ValueError if disabled or invalid id.
    Returns (token, expires_in_seconds).
    """
    cfg = cfg or settings
    uid = user_id.strip()
    if not cfg.enable_test_user_login:
        raise ValueError("Test user login is disabled")
    if not is_allowed_test_user_sub(uid, cfg):
        p = (cfg.test_user_sub_prefix or "test.anvega").strip()
        raise ValueError(
            f"User id must be {p} immediately followed by a number (e.g. {p}1, {p}2)"
        )

    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=cfg.test_user_token_ttl_days)
    payload: Dict[str, Any] = {
        "sub": uid,
        "email": f"{uid}@{TEST_USER_EMAIL_HOST}",
        "name": _display_name_for_test_user(uid),
        "picture": "",
        "iss": TEST_USER_JWT_ISSUER,
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(payload, cfg.test_user_jwt_secret, algorithm="HS256")
    expires_in = int((exp - now).total_seconds())
    return token, expires_in


def get_patient_token_identity(
    token: str,
    cfg: Optional[Settings] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Return (sub, claims) if the token is usable as a non-guest patient identity.

    When ``Settings.patient_bearer_legacy_jwt_decode`` is True, API layers use their legacy
    unverified-decode branches instead of calling this helper.

    - Google / Firebase style tokens: decoded without signature verification (existing behaviour).
    - Test tokens (iss == anvega-test): require enable_test_user_login, allowed sub prefix,
      and valid HS256 signature.
    """
    cfg = cfg or settings
    try:
        unverified: Dict[str, Any] = jwt.decode(
            token, options={"verify_signature": False}
        )
    except jwt.PyJWTError as e:
        logger.debug("Patient JWT decode failed: %s", e)
        return None

    iss = unverified.get("iss")
    sub = unverified.get("sub") or unverified.get("user_id") or unverified.get("uid")
    if not sub:
        return None

    if iss == TEST_USER_JWT_ISSUER:
        if not cfg.enable_test_user_login:
            return None
        if not is_allowed_test_user_sub(str(sub), cfg):
            return None
        try:
            verified = jwt.decode(
                token,
                cfg.test_user_jwt_secret,
                algorithms=["HS256"],
                issuer=TEST_USER_JWT_ISSUER,
                options={"require": ["exp", "sub", "iss"]},
            )
        except jwt.PyJWTError as e:
            logger.debug("Test user JWT verification failed: %s", e)
            return None
        vsub = verified.get("sub")
        if not vsub:
            return None
        return str(vsub), verified

    return str(sub), unverified

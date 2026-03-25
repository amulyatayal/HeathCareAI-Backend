"""
Chat identity: guests never require OAuth. Test bypass uses IS_AUTHENTICATION_REQUIRED=N.

Set ``IS_AUTHENTICATION_REQUIRED=N`` so fully anonymous requests (no Bearer, no X-User-ID)
use ``UNAUTHENTICATED_TEST_USER_ID`` (default ``anonymous_test``).

Or use :class:`TestChatAuthenticationBypass` with ``unittest.mock.patch``.
"""

from unittest.mock import MagicMock, patch

from api.routes import resolve_chat_user_identity


class TestChatAuthenticationBypass:
    """Guest vs test-bypass behavior via patched settings."""

    def test_when_default_guest_no_headers_no_401(self):
        with patch("api.routes.get_settings") as mock_gs:
            s = MagicMock()
            s.chat_authentication_required = True
            mock_gs.return_value = s
            user_id, is_guest = resolve_chat_user_identity(None, None)
            assert user_id is None
            assert is_guest is True

    def test_when_guest_x_user_id_used_for_session(self):
        with patch("api.routes.get_settings") as mock_gs:
            s = MagicMock()
            s.chat_authentication_required = True
            mock_gs.return_value = s
            user_id, is_guest = resolve_chat_user_identity(None, "guest_session_abc")
            assert is_guest is True
            assert user_id == "guest_session_abc"

    def test_when_auth_not_required_empty_headers_gets_synthetic_user(self):
        with patch("api.routes.get_settings") as mock_gs:
            s = MagicMock()
            s.chat_authentication_required = False
            s.unauthenticated_test_user_id = "integration_test_user"
            mock_gs.return_value = s
            user_id, is_guest = resolve_chat_user_identity(None, None)
            assert user_id == "integration_test_user"
            assert is_guest is True

    def test_when_auth_not_required_valid_bearer_still_used(self):
        import jwt

        token = jwt.encode({"sub": "real_user_1"}, "secret", algorithm="HS256")

        with patch("api.routes.get_settings") as mock_gs:
            s = MagicMock()
            s.chat_authentication_required = False
            s.unauthenticated_test_user_id = "should_not_use"
            mock_gs.return_value = s
            user_id, is_guest = resolve_chat_user_identity(f"Bearer {token}", None)
            assert user_id == "real_user_1"
            assert is_guest is False

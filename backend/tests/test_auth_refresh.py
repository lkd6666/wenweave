import unittest
from types import SimpleNamespace

from fastapi import HTTPException, Response

from app.api.deps import get_current_user
from app.api.routes.auth import REFRESH_TOKEN_COOKIE, refresh_access_token
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from app.models.user import UserRole


class AuthRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=17, role=UserRole.USER, is_active=True)
        self.db = SimpleNamespace(get=lambda model, user_id: self.user if user_id == self.user.id else None)

    def test_refresh_rotates_cookie_and_returns_a_new_access_token(self) -> None:
        response = Response()
        refreshed = refresh_access_token(
            response=response,
            refresh_token=create_refresh_token(str(self.user.id)),
            db=self.db,
        )

        self.assertEqual(decode_access_token(refreshed.access_token)["token_type"], ACCESS_TOKEN_TYPE)
        self.assertIn(f"{REFRESH_TOKEN_COOKIE}=", response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])

    def test_access_token_cannot_refresh_and_refresh_token_cannot_authorize(self) -> None:
        refresh_response = refresh_access_token(
            response=Response(),
            refresh_token=create_access_token(str(self.user.id)),
            db=self.db,
        )
        self.assertEqual(refresh_response.status_code, 401)
        self.assertIn("Max-Age=0", refresh_response.headers["set-cookie"])

        refresh_token = create_refresh_token(str(self.user.id))
        self.assertEqual(decode_access_token(refresh_token)["token_type"], REFRESH_TOKEN_TYPE)
        with self.assertRaises(HTTPException) as access_error:
            get_current_user(token=refresh_token, db=self.db)
        self.assertEqual(access_error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()

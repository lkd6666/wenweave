import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.deps import get_current_user
from app.api.routes.users import change_my_password, update_user
from app.core.security import (
    create_access_token,
    hash_password,
    is_forced_password_change_value,
    password_hash_requires_change,
    verify_password,
)
from app.models.user import UserRole
from app.schemas.user import ChangePasswordRequest, UserUpdate


class PasswordPolicyTests(unittest.TestCase):
    def test_unsafe_password_values_are_detected(self) -> None:
        self.assertTrue(is_forced_password_change_value("editor", "123456"))
        self.assertTrue(is_forced_password_change_value("editor", "12345678"))
        self.assertTrue(is_forced_password_change_value("editor", "editor"))
        self.assertFalse(is_forced_password_change_value("editor", "editor-strong-password"))

    def test_stored_hashes_are_detected(self) -> None:
        self.assertTrue(password_hash_requires_change("editor", hash_password("123456")))
        self.assertTrue(password_hash_requires_change("editor", hash_password("editor")))
        self.assertFalse(password_hash_requires_change("editor", hash_password("editor-strong-password")))

    def test_forced_user_cannot_use_unsafe_replacement_password(self) -> None:
        user = SimpleNamespace(
            id=1,
            username="editor",
            password_hash=hash_password("123456"),
            password_change_required=True,
            role=UserRole.USER,
            is_active=True,
        )
        db = SimpleNamespace(commit=lambda: None, refresh=lambda _: None)

        with self.assertRaises(HTTPException) as error:
            change_my_password(
                payload=ChangePasswordRequest(old_password="123456", new_password="editor"),
                current_user=user,
                db=db,
            )

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("不能使用", str(error.exception.detail))

    def test_successful_replacement_clears_the_requirement(self) -> None:
        user = SimpleNamespace(
            id=1,
            username="editor",
            password_hash=hash_password("12345678"),
            password_change_required=True,
            role=UserRole.USER,
            is_active=True,
        )
        db = SimpleNamespace(commit=lambda: None, refresh=lambda _: None)

        change_my_password(
            payload=ChangePasswordRequest(old_password="12345678", new_password="editor-strong-password"),
            current_user=user,
            db=db,
        )

        self.assertFalse(user.password_change_required)
        self.assertTrue(verify_password("editor-strong-password", user.password_hash))

    def test_administrator_can_assign_a_temporary_weak_password(self) -> None:
        user = SimpleNamespace(
            id=1,
            username="editor",
            display_name="编辑",
            password_hash=hash_password("editor-strong-password"),
            password_change_required=False,
            role=UserRole.USER,
            is_active=True,
        )
        db = SimpleNamespace(get=lambda _model, _user_id: user, commit=lambda: None, refresh=lambda _: None)

        update_user(user_id=user.id, payload=UserUpdate(password="123456"), db=db)

        self.assertTrue(user.password_change_required)
        self.assertTrue(verify_password("123456", user.password_hash))

    def test_forced_user_is_rejected_from_business_dependencies(self) -> None:
        user = SimpleNamespace(id=1, password_change_required=True, is_active=True)
        db = SimpleNamespace(get=lambda _model, _user_id: user)

        with self.assertRaises(HTTPException) as error:
            get_current_user(token=create_access_token("1"), db=db)

        self.assertEqual(error.exception.status_code, 403)
        self.assertIn("先修改密码", str(error.exception.detail))


if __name__ == "__main__":
    unittest.main()

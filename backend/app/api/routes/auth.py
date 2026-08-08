import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_TOKEN_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path="/api/auth",
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
    )


def _refresh_failure_response() -> JSONResponse:
    response = JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "登录会话已失效，请重新登录"})
    _clear_refresh_cookie(response)
    return response


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
    token = create_access_token(subject=str(user.id), extra_claims={"role": user.role.value})
    _set_refresh_cookie(response, create_refresh_token(subject=str(user.id)))
    return TokenResponse(access_token=token)


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> TokenResponse | JSONResponse:
    try:
        payload = decode_refresh_token(refresh_token or "")
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError, jwt.PyJWTError):
        return _refresh_failure_response()

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return _refresh_failure_response()

    token = create_access_token(subject=str(user.id), extra_claims={"role": user.role.value})
    _set_refresh_cookie(response, create_refresh_token(subject=str(user.id)))
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user

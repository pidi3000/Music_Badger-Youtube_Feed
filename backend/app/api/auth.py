from fastapi import APIRouter, HTTPException, Request, Response, status

from app.deps import AppConfig, DbSession
from app.schemas import AuthStatus, LoginRequest, OkResponse
from app.security import create_session_token, verify_secret, verify_session_token
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=OkResponse)
async def login(body: LoginRequest, response: Response, session: DbSession, config: AppConfig):
    settings = await get_or_create_settings(session)
    await session.commit()

    if not verify_secret(body.secret, settings.access_secret_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid secret")

    token = create_session_token()
    response.set_cookie(
        key=config.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=config.session_max_age_seconds,
        path="/",
    )
    return OkResponse()


@router.post("/logout", response_model=OkResponse)
async def logout(response: Response, config: AppConfig):
    response.delete_cookie(key=config.session_cookie_name, path="/")
    return OkResponse()


@router.get("/status", response_model=AuthStatus)
async def status_check(request: Request, session: DbSession, config: AppConfig):
    token = request.cookies.get(config.session_cookie_name)
    authenticated = bool(token and verify_session_token(token))
    if not authenticated:
        return AuthStatus(authenticated=False, youtube_connected=False)

    settings = await get_or_create_settings(session)
    await session.commit()
    return AuthStatus(
        authenticated=True,
        youtube_connected=settings.youtube_refresh_token_encrypted is not None,
    )

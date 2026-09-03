import secrets

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config import get_config
from app.deps import AppConfig, DbSession, HttpClient, RequireAuth
from app.encryption import encrypt
from app.schemas import OkResponse, YoutubeAuthStart
from app.services import oauth, youtube_client
from app.services.oauth import OAuthNotConfigured, OAuthTokenError
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/youtube/auth", tags=["youtube-auth"])

_STATE_COOKIE = "youtube_oauth_state"


@router.get("/start", response_model=YoutubeAuthStart, dependencies=[RequireAuth])
async def start(response: Response, config: AppConfig):
    state = secrets.token_urlsafe(24)
    try:
        url = oauth.build_authorization_url(config, state)
    except OAuthNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    response.set_cookie(
        key=_STATE_COOKIE, value=state, httponly=True, samesite="lax", max_age=600, path="/api/youtube/auth"
    )
    return YoutubeAuthStart(authorization_url=url)


@router.get("/callback")
async def callback(
    request: Request,
    session: DbSession,
    http_client: HttpClient,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse(url=f"/settings?youtube=error&reason={error}")

    expected_state = request.cookies.get(_STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid OAuth state")

    config = get_config()
    try:
        tokens = await oauth.exchange_code_for_tokens(http_client, config, code)
    except (OAuthNotConfigured, OAuthTokenError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if not tokens.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return a refresh token — disconnect any prior grant for this app "
            "in your Google account and try again",
        )

    my_channel = await youtube_client.get_my_channel(http_client, tokens.access_token)

    settings = await get_or_create_settings(session)
    settings.youtube_refresh_token_encrypted = encrypt(tokens.refresh_token)
    if my_channel is not None:
        settings.youtube_channel_id = my_channel.id
        settings.youtube_channel_title = my_channel.title
    await session.commit()

    redirect = RedirectResponse(url="/settings?youtube=connected")
    redirect.delete_cookie(key=_STATE_COOKIE, path="/api/youtube/auth")
    return redirect


@router.delete("", response_model=OkResponse, dependencies=[RequireAuth])
async def disconnect(session: DbSession):
    settings = await get_or_create_settings(session)
    settings.youtube_refresh_token_encrypted = None
    settings.youtube_channel_id = None
    settings.youtube_channel_title = None
    await session.commit()
    return OkResponse()

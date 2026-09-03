"""Manual Google OAuth2 authorization-code flow (no google-auth-oauthlib —
kept async-native via httpx, same as the Data API client). Scope is
read-only: we only ever read the user's subscriptions/channel data.

No real Google OAuth client exists yet for this build (see
PROJECT_OUTLINE.md §2 "Build-time YouTube credentials") — this module is
exercised in tests against a mocked token endpoint.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import Config

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


class OAuthNotConfigured(Exception):
    pass


class OAuthTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    expires_in: int
    refresh_token: str | None = None


def _require_client_credentials(config: Config) -> tuple[str, str]:
    if not config.youtube_oauth_client_id or not config.youtube_oauth_client_secret:
        raise OAuthNotConfigured(
            "YOUTUBE_OAUTH_CLIENT_ID / YOUTUBE_OAUTH_CLIENT_SECRET are not set"
        )
    return config.youtube_oauth_client_id, config.youtube_oauth_client_secret


def build_authorization_url(config: Config, state: str) -> str:
    client_id, _ = _require_client_credentials(config)
    params = {
        "client_id": client_id,
        "redirect_uri": config.youtube_oauth_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def _post_token_request(client: httpx.AsyncClient, data: dict) -> TokenResponse:
    response = await client.post(TOKEN_ENDPOINT, data=data)
    if response.status_code >= 400:
        raise OAuthTokenError(f"token endpoint returned {response.status_code}: {response.text}")
    payload = response.json()
    return TokenResponse(
        access_token=payload["access_token"],
        expires_in=payload["expires_in"],
        refresh_token=payload.get("refresh_token"),
    )


async def exchange_code_for_tokens(client: httpx.AsyncClient, config: Config, code: str) -> TokenResponse:
    client_id, client_secret = _require_client_credentials(config)
    return await _post_token_request(
        client,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": config.youtube_oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
    )


async def refresh_access_token(client: httpx.AsyncClient, config: Config, refresh_token: str) -> TokenResponse:
    client_id, client_secret = _require_client_credentials(config)
    return await _post_token_request(
        client,
        {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
    )

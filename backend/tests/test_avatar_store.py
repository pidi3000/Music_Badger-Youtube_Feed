import httpx
import pytest

from app.services import avatar_store


class _FakeConfig:
    def __init__(self, media_dir):
        self.media_dir = str(media_dir)


def _mock_client(status_code=200, content=b"fake-image-bytes", content_type="image/jpeg") -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=content, headers={"content-type": content_type}, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_store_channel_avatar_downloads_and_saves_file(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_store, "get_config", lambda: _FakeConfig(tmp_path))

    async with _mock_client() as client:
        result = await avatar_store.store_channel_avatar(client, "UCabc123", "https://example.com/thumb.jpg")

    assert result == "/media/avatars/UCabc123.jpg"
    saved = tmp_path / "avatars" / "UCabc123.jpg"
    assert saved.exists()
    assert saved.read_bytes() == b"fake-image-bytes"


@pytest.mark.asyncio
async def test_store_channel_avatar_guesses_extension_from_content_type(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_store, "get_config", lambda: _FakeConfig(tmp_path))

    async with _mock_client(content_type="image/png") as client:
        result = await avatar_store.store_channel_avatar(client, "UCpng", "https://example.com/thumb")

    assert result == "/media/avatars/UCpng.png"


@pytest.mark.asyncio
async def test_store_channel_avatar_returns_none_when_remote_url_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_store, "get_config", lambda: _FakeConfig(tmp_path))

    async with _mock_client() as client:
        result = await avatar_store.store_channel_avatar(client, "UCnothumb", None)

    assert result is None
    assert not (tmp_path / "avatars").exists()


@pytest.mark.asyncio
async def test_store_channel_avatar_returns_none_on_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_store, "get_config", lambda: _FakeConfig(tmp_path))

    async with _mock_client(status_code=404, content=b"") as client:
        result = await avatar_store.store_channel_avatar(client, "UCmissing", "https://example.com/404.jpg")

    assert result is None
    assert not (tmp_path / "avatars" / "UCmissing.jpg").exists()


@pytest.mark.asyncio
async def test_store_channel_avatar_returns_none_on_connection_error(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_store, "get_config", lambda: _FakeConfig(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await avatar_store.store_channel_avatar(client, "UCunreachable", "https://example.com/thumb.jpg")

    assert result is None

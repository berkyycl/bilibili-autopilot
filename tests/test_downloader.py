import asyncio
from types import SimpleNamespace

import httpx
import pytest

from bot.downloader import DownloadError, MediaRef, download, same_media
from bot.telegram import BotAPI, TelegramError
from tests.fakes import make_settings


def media(size):
    return MediaRef(file_id="F", file_unique_id="U", file_size=size, message_id=1)


class ShortAPI:
    """İstenenden az bayt yazan sahte Bot API."""

    def __init__(self, data):
        self.data = data

    async def download_file(self, file_id, dest, progress=None):
        dest.write_bytes(self.data)
        return dest


@pytest.mark.parametrize("data", [b"", b"x" * 50])
def test_truncated_or_empty_download_is_rejected(tmp_path, data):
    settings = make_settings(tmp_path, api_id=None, api_hash=None)
    dest = tmp_path / "video.mp4"
    with pytest.raises(DownloadError):
        asyncio.run(download(media(100), dest, api=ShortAPI(data), settings=settings))
    assert not dest.exists()  # yarım dosya geride kalmaz


def test_exact_download_is_accepted(tmp_path):
    settings = make_settings(tmp_path, api_id=None, api_hash=None)
    dest = tmp_path / "video.mp4"
    assert asyncio.run(download(media(100), dest, api=ShortAPI(b"x" * 100), settings=settings)) == dest


def test_bot_api_stream_detects_short_body(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "videos/a.mp4", "file_size": 100}})
        return httpx.Response(200, content=b"x" * 60)

    async def go():
        api = BotAPI("1:abc")
        api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await api.download_file("F", tmp_path / "a.mp4")
        finally:
            await api.close()

    with pytest.raises(TelegramError):
        asyncio.run(go())
    assert not (tmp_path / "a.mp4").exists() and not (tmp_path / "a.mp4.part").exists()


def test_same_media_compares_unique_id():
    assert same_media(media(1), SimpleNamespace(file_unique_id="U"))
    assert not same_media(media(1), SimpleNamespace(file_unique_id="BASKA"))

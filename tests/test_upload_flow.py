"""/yukle akışının uçtan uca testi: sahte Telegram, sahte biliup, sahte Bilibili/GitHub API."""

import asyncio
import base64
import json
import stat
import sys
import textwrap

import httpx
from nacl import encoding, public

from bot import bili_auth
from bot import messages as M
from bot import upload_flow
from bot.context import BotContext, Deadline
from bot.cookies import encode_cookies
from tests.fakes import FakeAPI, FakeInbox, make_settings, message, png_bytes
from tests.test_auth_and_secrets import LOGIN_DATA


def fake_biliup(tmp_path, *, sleep: float = 0.0):
    """Argümanları kontrol eden, çerezi 'yenileyen' ve BV numarası basan sahte biliup."""
    script = tmp_path / "fake-biliup"
    script.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            f"""
            import json, sys, time
            args = sys.argv[1:]
            cookie_path = args[1]
            assert args[2] == "upload", args
            assert "--title=Mod tanıtımı" in args and "--tid=17" in args and "--tag=MOD" in args
            assert any(a.startswith("--cover=") for a in args)
            time.sleep({sleep})
            info = json.load(open(cookie_path))
            info["token_info"]["access_token"] = "YENI-TOKEN"
            json.dump(info, open(cookie_path, "w"))
            sys.stderr.write("\\r1.00 GiB/1.00 GiB (9 MiB/s)")
            print('ResponseData {{ code: 0, data: Some(Object {{"bvid": String("BV1ab411c7mD")}}) }}')
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def run_upload(tmp_path, monkeypatch, inbox_messages, *, biliup_sleep=0.0, download_sleep=0.0):
    settings = make_settings(tmp_path, biliup_bin=fake_biliup(tmp_path, sleep=biliup_sleep))
    api = FakeAPI(files={"big": png_bytes()})
    inbox = FakeInbox(inbox_messages)
    private = public.PrivateKey.generate()
    saved = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "nav" in request.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"isLogin": True, "uname": "u"}})
        if "oauth2/info" in request.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"expires_in": 999999, "refresh": False}})
        if request.url.path.endswith("public-key"):
            key = private.public_key.encode(encoding.Base64Encoder()).decode()
            return httpx.Response(200, json={"key_id": "k", "key": key})
        body = json.loads(request.content)
        saved["value"] = public.SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"]))
        return httpx.Response(201)

    async def fake_download(media, dest, *, api, settings, progress=None):
        await asyncio.sleep(download_sleep)
        dest.write_bytes(b"video")
        if progress:
            await progress(5, 5)
        return dest

    monkeypatch.setattr(upload_flow, "download", fake_download)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            ctx = BotContext(
                settings, api, inbox, Deadline(settings.run_budget), http,
                encode_cookies(bili_auth.build_login_info(LOGIN_DATA)),
            )
            await upload_flow.run_upload(ctx)
            return ctx

    ctx = asyncio.run(go())
    return ctx, api, saved


def dialog_messages():
    video = message(
        message_id=2,
        document={"file_id": "VID", "file_unique_id": "u", "file_size": 50 * 1024**2, "file_name": "a.mp4", "mime_type": "video/mp4"},
    )
    cover = message(message_id=5, photo=[{"file_id": "big", "file_unique_id": "b", "file_size": 9000, "width": 1280}])
    return [video, message("Mod tanıtımı"), message("Açıklama"), cover]


def test_full_upload_success_and_renewed_cookie_is_saved(tmp_path, monkeypatch):
    ctx, api, saved = run_upload(tmp_path, monkeypatch, dialog_messages())
    assert any("BV1ab411c7mD" in text for text in api.sent), api.sent
    # biliup çerezi yeniledi → secret güncellendi ve bu çalışmada yeni çerez kullanılıyor
    assert json.loads(base64.b64decode(saved["value"]))["token_info"]["access_token"] == "YENI-TOKEN"
    assert json.loads(base64.b64decode(ctx.cookies_b64))["token_info"]["access_token"] == "YENI-TOKEN"
    # geçici dosyalar silindi
    assert not any((tmp_path / "work").glob("upload-*"))


def test_cancel_during_download(tmp_path, monkeypatch):
    _, api, saved = run_upload(tmp_path, monkeypatch, dialog_messages() + [message("/iptal")], download_sleep=5)
    assert M.CANCELLING in api.sent and M.CANCELLED in api.sent
    assert not any("BV1" in text for text in api.sent)
    assert "value" not in saved


def test_login_required_without_cookies(tmp_path):
    settings = make_settings(tmp_path)
    api = FakeAPI()

    async def go():
        async with httpx.AsyncClient() as http:
            ctx = BotContext(settings, api, FakeInbox([]), Deadline(settings.run_budget), http, "")
            await upload_flow.run_upload(ctx)

    asyncio.run(go())
    assert api.sent == [M.LOGIN_REQUIRED]

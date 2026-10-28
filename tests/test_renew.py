import asyncio
import base64
import json
import stat
import sys

import httpx
from nacl import encoding, public

from bot import bili_auth, renew
from bot import messages as M
from bot.cookies import encode_cookies
from tests.test_auth_and_secrets import LOGIN_DATA


class FakeBotAPI:
    sent: list[str] = []

    def __init__(self, token):
        pass

    async def send_message(self, chat_id, text, **kwargs):
        FakeBotAPI.sent.append(text)

    async def close(self):
        pass


def setup(monkeypatch, tmp_path, *, days_left, nav_code=0):
    private = public.PrivateKey.generate()
    saved = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "nav" in request.url.path:
            return httpx.Response(200, json={"code": nav_code, "data": {"isLogin": nav_code == 0}})
        if "oauth2/info" in request.url.path:
            return httpx.Response(200, json={"code": 0, "data": {"expires_in": days_left * 86400, "refresh": False}})
        if request.url.path.endswith("public-key"):
            return httpx.Response(200, json={"key_id": "k", "key": private.public_key.encode(encoding.Base64Encoder()).decode()})
        body = json.loads(request.content)
        saved["value"] = public.SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"]))
        return httpx.Response(204)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(renew.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    FakeBotAPI.sent = []
    monkeypatch.setattr(renew, "BotAPI", FakeBotAPI)

    script = tmp_path / "fake-biliup"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "path = sys.argv[2]; assert sys.argv[3] == 'renew'\n"
        "info = json.load(open(path)); info['token_info']['access_token'] = 'YENI'\n"
        "json.dump(info, open(path, 'w'))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    for key, value in {
        "TELEGRAM_BOT_TOKEN": "1:abc",
        "ALLOWED_USER_ID": "42",
        "GH_PAT": "pat",
        "GITHUB_REPOSITORY": "o/r",
        "RUNNER_TEMP": str(tmp_path),
        "BILIUP_BIN": str(script),
        "BILIBILI_COOKIES_B64": encode_cookies(bili_auth.build_login_info(LOGIN_DATA)),
    }.items():
        monkeypatch.setenv(key, value)
    return saved


def test_renews_when_token_is_close_to_expiry(monkeypatch, tmp_path):
    saved = setup(monkeypatch, tmp_path, days_left=10)
    assert asyncio.run(renew.renew(force=False)) == 0
    assert json.loads(base64.b64decode(saved["value"]))["token_info"]["access_token"] == "YENI"


def test_skips_when_token_is_fresh(monkeypatch, tmp_path):
    saved = setup(monkeypatch, tmp_path, days_left=150)
    assert asyncio.run(renew.renew(force=False)) == 0
    assert "value" not in saved and FakeBotAPI.sent == []


def test_notifies_when_session_expired(monkeypatch, tmp_path):
    saved = setup(monkeypatch, tmp_path, days_left=150, nav_code=-101)
    assert asyncio.run(renew.renew(force=False)) == 0
    assert FakeBotAPI.sent == [M.RENEW_EXPIRED] and "value" not in saved

import asyncio
import base64
import hashlib
import json
import os
import stat

import httpx
import pytest
from nacl import encoding, public

from bot import bili_auth, github_secrets
from bot.cookies import CookieError, CookieFile, decode_cookies_b64, encode_cookies

LOGIN_DATA = {
    "is_new": False,
    "mid": 1,
    "access_token": "ACCESS-TOKEN-1",
    "refresh_token": "REFRESH-TOKEN-1",
    "expires_in": 15552000,
    "token_info": {
        "mid": 1,
        "access_token": "ACCESS-TOKEN-1",
        "refresh_token": "REFRESH-TOKEN-1",
        "expires_in": 15552000,
    },
    "cookie_info": {
        "cookies": [
            {"name": "SESSDATA", "value": "SESSDATA-VALUE", "http_only": 1, "expires": 1, "secure": 0},
            {"name": "bili_jct", "value": "BILIJCT-VALUE", "http_only": 0, "expires": 1, "secure": 0},
            {"name": "DedeUserID", "value": "1", "http_only": 0, "expires": 1, "secure": 0},
        ],
        "domains": [".bilibili.com"],
    },
    "sso": ["https://passport.bilibili.com/api/v2/sso"],
}


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_sign_params_matches_bilibili_algorithm():
    signed = bili_auth.sign_params({"ts": 1, "appkey": "k", "local_id": "0"}, "SECRET")
    assert signed["sign"] == hashlib.md5(b"appkey=k&local_id=0&ts=1SECRET").hexdigest()


def test_build_login_info_is_biliup_compatible():
    info = bili_auth.build_login_info(LOGIN_DATA)
    assert set(info) == {"cookie_info", "sso", "token_info", "platform"}
    assert info["platform"] == "BiliTV"
    assert bili_auth.cookie_map(info)["SESSDATA"] == "SESSDATA-VALUE"
    secrets = bili_auth.sensitive_values(info)
    assert {"SESSDATA-VALUE", "BILIJCT-VALUE", "ACCESS-TOKEN-1", "REFRESH-TOKEN-1"} <= set(secrets)
    with pytest.raises(bili_auth.BiliAuthError):
        bili_auth.build_login_info({"cookie_info": {}})


def test_qr_request_and_poll_states():
    codes = iter([86039, 86090, 0])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("auth_code"):
            return httpx.Response(200, json={"code": 0, "data": {"url": "https://x/qr", "auth_code": "abc"}})
        code = next(codes)
        return httpx.Response(200, json={"code": code, "data": LOGIN_DATA if code == 0 else None})

    async def go():
        async with client_with(handler) as client:
            ticket = await bili_auth.request_qr(client)
            states = [(await bili_auth.poll_qr(client, ticket.auth_code))[0] for _ in range(3)]
            return ticket, states

    ticket, states = asyncio.run(go())
    assert ticket.auth_code == "abc"
    assert states == [bili_auth.QrState.WAITING, bili_auth.QrState.SCANNED, bili_auth.QrState.SUCCESS]


def test_render_qr_png():
    assert bili_auth.render_qr_png("https://example.com/qr").startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "nav, oauth, expected",
    [
        ({"code": 0, "data": {"isLogin": True, "uname": "u"}}, {"code": 0, "data": {"expires_in": 86400 * 10, "refresh": False}}, True),
        ({"code": -101, "data": {"isLogin": False}}, None, False),
        ({"code": 0, "data": {"isLogin": True}}, {"code": -2, "message": "Access_Key错误"}, False),
        # güvenlik kontrolü (风控) gibi hatalar oturumu geçersiz saymaz
        ({"code": -352, "message": "风控校验失败"}, {"code": 0, "data": {"expires_in": 86400, "refresh": False}}, None),
        ({"code": 0, "data": {"isLogin": True}}, {"code": -400, "message": "请求错误"}, None),
    ],
)
def test_check_login(nav, oauth, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        if "nav" in request.url.path:
            assert "SESSDATA=SESSDATA-VALUE" in request.headers["Cookie"]
            return httpx.Response(200, json=nav)
        return httpx.Response(200, json=oauth)

    async def go():
        async with client_with(handler) as client:
            return await bili_auth.check_login(client, bili_auth.build_login_info(LOGIN_DATA))

    status = asyncio.run(go())
    assert status.valid is expected
    if expected:
        assert status.uname == "u" and round(status.token_days_left) == 10


def test_check_login_network_error_is_unknown():
    def handler(request):
        raise httpx.ConnectError("yok")

    async def go():
        async with client_with(handler) as client:
            return await bili_auth.check_login(client, bili_auth.build_login_info(LOGIN_DATA))

    assert asyncio.run(go()).valid is None


def test_cookie_file_roundtrip(tmp_path):
    b64 = encode_cookies(bili_auth.build_login_info(LOGIN_DATA))
    cookie_file = CookieFile(b64, tmp_path)
    assert stat.S_IMODE(os.stat(cookie_file.path).st_mode) == 0o600
    assert not cookie_file.changed()

    cookie_file.path.write_text("{yarım")  # bozuk içerik asla "değişti" sayılmaz
    assert not cookie_file.changed()

    info = bili_auth.build_login_info(LOGIN_DATA)
    info["token_info"]["access_token"] = "NEW"
    cookie_file.path.write_text(json.dumps(info))
    assert cookie_file.changed()
    assert json.loads(base64.b64decode(cookie_file.current_b64()))["token_info"]["access_token"] == "NEW"
    cookie_file.mark_saved()
    assert not cookie_file.changed()
    cookie_file.remove()
    assert not cookie_file.path.exists()

    with pytest.raises(CookieError):
        decode_cookies_b64("bm90IGpzb24=")


def test_seal_can_be_opened_with_private_key():
    private = public.PrivateKey.generate()
    public_b64 = private.public_key.encode(encoding.Base64Encoder()).decode()
    sealed = github_secrets.seal(public_b64, "gizli")
    assert public.SealedBox(private).decrypt(base64.b64decode(sealed)) == b"gizli"


@pytest.mark.parametrize("put_status, error", [(201, None), (204, None), (403, "Secrets: Read and write")])
def test_put_secret(put_status, error):
    private = public.PrivateKey.generate()
    key = private.public_key.encode(encoding.Base64Encoder()).decode()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer pat"
        if request.method == "GET":
            return httpx.Response(200, json={"key_id": "kid", "key": key})
        body = json.loads(request.content)
        seen["value"] = public.SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"]))
        assert request.url.path == "/repos/o/r/actions/secrets/BILIBILI_COOKIES_B64"
        return httpx.Response(put_status)

    async def go():
        async with client_with(handler) as client:
            await github_secrets.put_secret(client, "pat", "o/r", "BILIBILI_COOKIES_B64", "deger")

    if error:
        with pytest.raises(github_secrets.SecretUpdateError, match=error):
            asyncio.run(go())
    else:
        asyncio.run(go())
        assert seen["value"] == b"deger"

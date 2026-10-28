"""Bilibili girişi: QR kod ile giriş, oturum kontrolü ve çerez yardımcıları.

biliup'ın kendi `login` komutu etkileşimli çalışır ve QR kodu terminale
(yani herkese açık Actions loguna) basar. Bu yüzden QR girişini burada,
biliup ile birebir aynı Bilibili TV API'si ve aynı `cookies.json` formatıyla
yapıyoruz; QR kod sadece Telegram'dan kullanıcıya gönderilir.
"""

from __future__ import annotations

import enum
import hashlib
import io
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

# Bilibili'nin herkese açık uygulama anahtarları (biliup ile aynı; gizli değildir).
TV_APPKEY = "4409e2ce8ffd12b8"
TV_APPSEC = "59b43e04ad6965f34319062b478f83dd"
ANDROID_APPKEY = "783bbb7264451d82"
ANDROID_APPSEC = "2653583c8873dea268ab9386918b1d65"

QR_AUTH_CODE_URL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
OAUTH_INFO_URL = "https://passport.bilibili.com/x/passport-login/oauth2/info"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
_HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}

# Oturumun gerçekten geçersiz olduğunu gösteren kodlar:
# -101 hesap giriş yapmamış, -2 erişim anahtarı hatalı, -658 token süresi dolmuş
INVALID_SESSION_CODES = {-101, -2, -658}

# QR poll cevap kodları
_QR_WAITING = 86039  # henüz taranmadı / onaylanmadı
_QR_SCANNED = 86090  # tarandı, onay bekleniyor
_QR_EXPIRED = 86038  # süresi doldu


class BiliAuthError(Exception):
    """Bilibili giriş hatası. Mesajı kullanıcıya gösterilebilir; gizli veri içermez."""


def sign_params(params: dict[str, Any], appsec: str) -> dict[str, str]:
    """Bilibili APP imzası: parametreler alfabetik sıralanıp md5(query + appsec) eklenir."""
    items = sorted((key, str(value)) for key, value in params.items())
    query = urllib.parse.urlencode(items)
    signed = dict(items)
    signed["sign"] = hashlib.md5((query + appsec).encode()).hexdigest()
    return signed


# --- QR ile giriş ------------------------------------------------------------------


@dataclass(frozen=True)
class QrTicket:
    url: str
    auth_code: str


class QrState(enum.Enum):
    WAITING = "waiting"
    SCANNED = "scanned"
    EXPIRED = "expired"
    SUCCESS = "success"


async def request_qr(client: httpx.AsyncClient) -> QrTicket:
    params = sign_params({"appkey": TV_APPKEY, "local_id": "0", "ts": int(time.time())}, TV_APPSEC)
    try:
        response = await client.post(QR_AUTH_CODE_URL, data=params, headers=_HEADERS)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise BiliAuthError("Bilibili'ye ulaşılamadı") from None
    data = payload.get("data") or {}
    if payload.get("code") != 0 or not data.get("url") or not data.get("auth_code"):
        raise BiliAuthError(f"Bilibili hata kodu {payload.get('code')}")
    return QrTicket(url=data["url"], auth_code=data["auth_code"])


async def poll_qr(client: httpx.AsyncClient, auth_code: str) -> tuple[QrState, dict[str, Any] | None]:
    """QR kodun durumunu sorgular. Başarılıysa Bilibili'nin döndürdüğü giriş verisini verir."""
    params = sign_params(
        {"appkey": TV_APPKEY, "auth_code": auth_code, "local_id": "0", "ts": int(time.time())},
        TV_APPSEC,
    )
    try:
        response = await client.post(QR_POLL_URL, data=params, headers=_HEADERS)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return QrState.WAITING, None  # geçici ağ hatası: bir sonraki denemede tekrar sor
    code = payload.get("code")
    if code == 0 and payload.get("data"):
        return QrState.SUCCESS, payload["data"]
    if code == _QR_WAITING:
        return QrState.WAITING, None
    if code == _QR_SCANNED:
        return QrState.SCANNED, None
    if code == _QR_EXPIRED:
        return QrState.EXPIRED, None
    raise BiliAuthError(f"Bilibili hata kodu {code}")


def build_login_info(data: dict[str, Any]) -> dict[str, Any]:
    """Bilibili cevabından biliup'ın `cookies.json` formatını üretir."""
    cookie_info = data.get("cookie_info")
    token_info = data.get("token_info")
    if not isinstance(cookie_info, dict) or not isinstance(token_info, dict):
        raise BiliAuthError("Bilibili beklenmeyen bir cevap döndürdü")
    for key in ("access_token", "refresh_token", "mid", "expires_in"):
        if key not in token_info:
            raise BiliAuthError("Bilibili cevabında giriş anahtarı eksik")
    return {
        "cookie_info": cookie_info,
        "sso": list(data.get("sso") or []),
        "token_info": token_info,
        "platform": "BiliTV",  # biliup yenileme (renew) için bu alanı kullanır
    }


def render_qr_png(url: str) -> bytes:
    """QR kodu bellekte PNG olarak üretir (diske yazılmaz)."""
    import qrcode  # ağır bağımlılık; sadece gerektiğinde yükle

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# --- Çerez yardımcıları ------------------------------------------------------------


def cookie_map(info: dict[str, Any]) -> dict[str, str]:
    cookies = (info.get("cookie_info") or {}).get("cookies") or []
    return {str(c.get("name")): str(c.get("value")) for c in cookies if c.get("name")}


def sensitive_values(info: dict[str, Any]) -> list[str]:
    """Loglarda/mesajlarda asla görünmemesi gereken değerler (maskeleme ve sansür için)."""
    values = list(cookie_map(info).values())
    token = info.get("token_info") or {}
    values += [str(token.get("access_token") or ""), str(token.get("refresh_token") or "")]
    return [v for v in values if len(v) >= 6]


# --- Oturum kontrolü ---------------------------------------------------------------


@dataclass
class LoginStatus:
    valid: bool | None  # None: kontrol edilemedi (ağ hatası vb.)
    uname: str | None = None
    token_days_left: float | None = None
    needs_refresh: bool = False


async def check_login(client: httpx.AsyncClient, info: dict[str, Any]) -> LoginStatus:
    """Çerezlerin (web) ve erişim anahtarının (app) hâlâ geçerli olup olmadığını kontrol eder."""
    cookies = cookie_map(info)
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    token = (info.get("token_info") or {}).get("access_token")
    if not cookies or not token:
        return LoginStatus(valid=False)

    # Sadece "oturum/anahtar geçersiz" anlamına gelen kodlar oturumu geçersiz sayar.
    # Diğer hatalar (ör. -352 güvenlik kontrolü, geçici sorunlar) "bilinmiyor" kabul
    # edilir; böylece geçerli bir oturum yanlışlıkla engellenmez.
    status = LoginStatus(valid=None)
    cookies_ok = False
    try:
        response = await client.get(NAV_URL, headers={**_HEADERS, "Cookie": cookie_header})
        nav = response.json()
        if nav.get("code") == 0 and (nav.get("data") or {}).get("isLogin"):
            cookies_ok = True
            status.uname = (nav.get("data") or {}).get("uname")
        elif nav.get("code") in INVALID_SESSION_CODES:
            return LoginStatus(valid=False)
    except (httpx.HTTPError, ValueError):
        return status

    params = sign_params(
        {"access_key": token, "actionKey": "appkey", "appkey": ANDROID_APPKEY, "ts": int(time.time())},
        ANDROID_APPSEC,
    )
    try:
        response = await client.get(OAUTH_INFO_URL, params=params, headers=_HEADERS)
        oauth = response.json()
    except (httpx.HTTPError, ValueError):
        return status
    if oauth.get("code") in INVALID_SESSION_CODES:
        return LoginStatus(valid=False, uname=status.uname)
    if oauth.get("code") != 0:
        return status
    data = oauth.get("data") or {}
    status.valid = True if cookies_ok else None
    status.needs_refresh = bool(data.get("refresh"))
    if isinstance(data.get("expires_in"), (int, float)):
        status.token_days_left = data["expires_in"] / 86400
    return status

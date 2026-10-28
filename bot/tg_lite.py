"""Sadece Python standart kütüphanesiyle çalışan minimal Telegram Bot API istemcisi.

Hızlı kontrol (check.py) ve hata bildirimi (notify_failure.py) bağımlılık
kurulmadan çalışabilsin diye ayrı tutulur.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TgLiteError(Exception):
    """Telegram API hatası. Mesajı token ya da içerik barındırmaz."""

    def __init__(self, method: str, code: int, description: str = "") -> None:
        super().__init__(f"{method} başarısız (kod {code})")
        self.code = code
        self.description = description


def call(token: str, method: str, params: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    data = urllib.parse.urlencode(
        {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in (params or {}).items()}
    ).encode()
    request = urllib.request.Request(API_URL.format(token=token, method=method), data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # Telegram hata durumunda da JSON gövde döndürür.
        try:
            payload = json.load(exc)
        except Exception:
            raise TgLiteError(method, exc.code) from None
    if not payload.get("ok"):
        raise TgLiteError(method, int(payload.get("error_code", 0)), str(payload.get("description", "")))
    return payload["result"]


def get_updates(token: str, offset: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Bekleyen güncellemeleri beklemeden (timeout=0) okur.

    409 (webhook tanımlı) hatası alınırsa webhook'u silip bir kez daha dener.
    """
    params: dict[str, Any] = {"timeout": 0, "limit": limit, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    try:
        return call(token, "getUpdates", params)
    except TgLiteError as exc:
        if exc.code != 409:
            raise
        call(token, "deleteWebhook", {"drop_pending_updates": False})
        return call(token, "getUpdates", params)


def is_authorized(update: dict[str, Any], allowed_user_id: int) -> bool:
    """Güncelleme, yetkili kullanıcının bota özelden gönderdiği bir mesaj mı?"""
    message = update.get("message") or {}
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    return (
        sender.get("id") == allowed_user_id
        and chat.get("id") == allowed_user_id
        and chat.get("type") == "private"
    )

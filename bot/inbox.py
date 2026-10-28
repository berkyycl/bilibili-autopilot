"""Telegram'dan gelen mesajları sırayla veren kuyruk.

- Sadece yetkili kullanıcının bota özelden gönderdiği mesajları geçirir;
  diğer herkesin mesajları sessizce yok sayılır.
- Bot API'de `getUpdates(offset=N)` çağrısı N'den küçük tüm güncellemeleri
  "onaylar" (Telegram'dan siler). Kuyruk her çağrıda son görülen güncellemenin
  bir fazlasını offset olarak gönderir; çıkışta `commit()` ile kalanlar onaylanır.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Any

from bot.log import describe, log
from bot.telegram import BotAPI, TelegramError

LONG_POLL_MAX = 50  # saniye


# Türkçe klavyeyle yazılan komutlar da anlaşılsın: /giriş → /giris, /yükle → /yukle
_TURKISH = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def command_of(message: dict[str, Any]) -> str | None:
    """Mesaj bir komutsa ('/yukle@BotAdi' gibi) normalleştirilmiş halini ('/yukle') döndürür."""
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return None
    return text.split()[0].split("@")[0].translate(_TURKISH).lower()


def is_authorized(message: dict[str, Any], allowed_user_id: int) -> bool:
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    return (
        sender.get("id") == allowed_user_id
        and chat.get("id") == allowed_user_id
        and chat.get("type") == "private"
    )


class Inbox:
    def __init__(self, api: BotAPI, allowed_user_id: int) -> None:
        self._api = api
        self._allowed = allowed_user_id
        self._offset: int | None = None
        self._queue: deque[dict[str, Any]] = deque()

    async def _fetch(self, timeout: int) -> None:
        try:
            updates = await self._api.get_updates(self._offset, timeout)
        except TelegramError as exc:
            if exc.error_code == 409:
                # Webhook tanımlıysa getUpdates çalışmaz; webhook'u kaldır.
                log.warning("Telegram webhook'u kaldırılıyor (getUpdates ile çakışıyordu).")
                await self._api.delete_webhook()
                return
            log.warning("Telegram güncellemeleri alınamadı (%s); tekrar denenecek.", describe(exc))
            await asyncio.sleep(3)
            return
        for update in updates:
            self._offset = int(update["update_id"]) + 1
            message = update.get("message")
            if message and is_authorized(message, self._allowed):
                self._queue.append(message)

    async def poll_now(self) -> None:
        """Beklemeden bekleyen mesajları çeker."""
        await self._fetch(0)

    def pop_nowait(self) -> dict[str, Any] | None:
        return self._queue.popleft() if self._queue else None

    async def next(self, timeout: float) -> dict[str, Any] | None:
        """Bir sonraki mesajı en fazla `timeout` saniye bekler; gelmezse None döner."""
        deadline = time.monotonic() + max(timeout, 0)
        while not self._queue:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await self._fetch(min(LONG_POLL_MAX, math.ceil(remaining)))
        return self._queue.popleft()

    async def commit(self) -> None:
        """Şimdiye kadar alınan tüm güncellemeleri Telegram'a onaylatır."""
        if self._offset is None:
            return
        try:
            await self._api.get_updates(self._offset, 0, limit=1)
        except TelegramError as exc:
            log.warning("Telegram güncellemeleri onaylanamadı (%s).", describe(exc))

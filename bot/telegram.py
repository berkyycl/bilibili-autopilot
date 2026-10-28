"""Telegram Bot API için küçük, asenkron bir istemci (httpx).

Konuşma/durum yönetimi Bot API ile yapılır. 20 MB'tan büyük dosyaların
indirilmesi için MTProto kullanılır (bkz. downloader.py).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024


class TelegramError(Exception):
    """Bot API hatası. str() değeri token ya da mesaj içeriği barındırmaz."""

    def __init__(self, method: str, error_code: int, description: str = "") -> None:
        super().__init__(f"{method} başarısız (kod {error_code})")
        self.method = method
        self.error_code = error_code
        self.description = description


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _form_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class BotAPI:
    def __init__(self, token: str) -> None:
        self._token = token
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        files: dict[str, Any] | None = None,
        read_timeout: float = 30.0,
        retries: int = 5,
    ) -> Any:
        """Bir Bot API metodunu çağırır; geçici hatalarda ve 429'da yeniden dener."""
        url = f"{API_BASE}/bot{self._token}/{method}"
        timeout = httpx.Timeout(30.0, read=read_timeout)
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in range(retries):
            try:
                if files:
                    data = {k: _form_value(v) for k, v in params.items()}
                    response = await self._client.post(url, data=data, files=files, timeout=timeout)
                else:
                    response = await self._client.post(url, json=params, timeout=timeout)
                payload = response.json()
            except (httpx.TransportError, ValueError):
                # Ağ hatası ya da JSON olmayan cevap (ör. 502): biraz bekleyip tekrar dene.
                if attempt == retries - 1:
                    raise TelegramError(method, -1, "Telegram'a ulaşılamadı") from None
                await asyncio.sleep(2 * (attempt + 1))
                continue

            if payload.get("ok"):
                return payload.get("result")
            code = int(payload.get("error_code", response.status_code))
            description = str(payload.get("description", ""))
            if code == 429:
                retry_after = int((payload.get("parameters") or {}).get("retry_after", 5))
                await asyncio.sleep(min(retry_after, 60) + 1)
                continue
            if code >= 500 and attempt < retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            raise TelegramError(method, code, description)
        raise TelegramError(method, -1, "yeniden deneme sınırı aşıldı")

    # --- Güncellemeler -------------------------------------------------------

    async def get_updates(self, offset: int | None, timeout: int, limit: int = 100) -> list[dict[str, Any]]:
        """Long polling ile güncellemeleri alır. offset'ten küçük güncellemeler onaylanmış olur."""
        params: dict[str, Any] = {"timeout": timeout, "limit": limit, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return await self.call("getUpdates", params, read_timeout=timeout + 20, retries=2)

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", {"drop_pending_updates": False})

    # --- Mesajlar ------------------------------------------------------------

    async def send_message(self, chat_id: int, text: str, *, link_preview: bool = False) -> dict[str, Any]:
        return await self.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": _truncate(text, MAX_MESSAGE_LENGTH),
                "link_preview_options": {"is_disabled": not link_preview},
            },
        )

    async def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            await self.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": _truncate(text, MAX_MESSAGE_LENGTH),
                    "link_preview_options": {"is_disabled": True},
                },
            )
        except TelegramError as exc:
            # Metin aynıysa Telegram hata döndürür; bu bizim için sorun değil.
            if "not modified" not in exc.description:
                raise

    async def send_photo(self, chat_id: int, photo: bytes, *, caption: str = "") -> dict[str, Any]:
        return await self.call(
            "sendPhoto",
            {"chat_id": chat_id, "caption": _truncate(caption, MAX_CAPTION_LENGTH)},
            files={"photo": ("image.png", photo, "image/png")},
        )

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, retries=2)
        except TelegramError:
            pass  # silinemezse önemli değil

    # --- Dosyalar (sadece 20 MB'a kadar) ---------------------------------------

    async def download_file(
        self,
        file_id: str,
        dest: Path,
        progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> Path:
        """getFile ile küçük (≤20 MB) bir dosyayı indirir."""
        info = await self.call("getFile", {"file_id": file_id})
        file_path = info.get("file_path")
        if not file_path:
            raise TelegramError("getFile", -1, "dosya yolu alınamadı")
        total = int(info.get("file_size") or 0)
        url = f"{API_BASE}/file/bot{self._token}/{file_path}"
        done = 0
        try:
            async with self._client.stream("GET", url, timeout=httpx.Timeout(30.0, read=120.0)) as response:
                if response.status_code != 200:
                    raise TelegramError("getFile", response.status_code, "dosya indirilemedi")
                with open(dest, "wb") as fh:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            await progress(done, total)
        except httpx.TransportError:
            raise TelegramError("getFile", -1, "bağlantı koptu") from None
        return dest

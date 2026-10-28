"""Bir bot çalışması boyunca paylaşılan durum ve yardımcılar."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from bot import github_secrets
from bot.config import Settings
from bot.inbox import Inbox
from bot.log import describe, log, mask
from bot.telegram import BotAPI, TelegramError

T = TypeVar("T")


class Deadline:
    """Çalışmanın toplam süre bütçesi (GitHub job timeout'undan önce bitirmek için)."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())


class OperationCancelled(Exception):
    """Uzun işlem kullanıcı (/iptal) ya da süre bütçesi nedeniyle durduruldu."""

    def __init__(self, by_user: bool) -> None:
        super().__init__("iptal edildi")
        self.by_user = by_user


@dataclass
class BotContext:
    settings: Settings
    api: BotAPI
    inbox: Inbox
    deadline: Deadline
    http: httpx.AsyncClient  # Bilibili ve GitHub istekleri için
    cookies_b64: str  # güncel Bilibili çerezi (giriş/yenileme sonrası güncellenir)

    @property
    def chat_id(self) -> int:
        return self.settings.allowed_user_id

    async def say(self, text: str, *, link_preview: bool = False) -> dict[str, Any] | None:
        """Kullanıcıya mesaj gönderir; Telegram hatası işi durdurmaz."""
        try:
            return await self.api.send_message(self.chat_id, text, link_preview=link_preview)
        except TelegramError as exc:
            log.warning("Telegram mesajı gönderilemedi (%s).", describe(exc))
            return None

    async def save_cookies(self, new_b64: str) -> str | None:
        """Yeni çerezi BILIBILI_COOKIES_B64 secret'ına yazar. Hata varsa nedenini döndürür."""
        mask(new_b64)
        self.cookies_b64 = new_b64  # bu çalışmanın geri kalanı yeni çerezi kullansın
        if not self.settings.gh_pat or not self.settings.github_repository:
            return "GH_PAT secret'ı tanımlı değil"
        try:
            await github_secrets.put_secret(
                self.http,
                self.settings.gh_pat,
                self.settings.github_repository,
                github_secrets.COOKIES_SECRET_NAME,
                new_b64,
            )
        except github_secrets.SecretUpdateError as exc:
            log.warning("Çerez secret'ı güncellenemedi.")
            return str(exc)
        log.info("Bilibili çerez secret'ı güncellendi.")
        return None


class StatusMessage:
    """Tek bir Telegram mesajını düzenleyerek durum gösterir (hız sınırına takılmadan)."""

    def __init__(self, ctx: BotContext, min_interval: float = 5.0) -> None:
        self._ctx = ctx
        self._min_interval = min_interval
        self._message_id: int | None = None
        self._last_text = ""
        self._last_edit = 0.0

    async def show(self, text: str, *, force: bool = False) -> None:
        if text == self._last_text:
            return
        now = time.monotonic()
        if not force and self._message_id is not None and now - self._last_edit < self._min_interval:
            return
        self._last_text, self._last_edit = text, now
        if self._message_id is None:
            message = await self._ctx.say(text)
            self._message_id = message.get("message_id") if message else None
            return
        try:
            await self._ctx.api.edit_message_text(self._ctx.chat_id, self._message_id, text)
        except TelegramError as exc:
            log.warning("Durum mesajı güncellenemedi (%s).", describe(exc))


class ProgressTicker:
    """İlerlemeyi saklar ve durum mesajını belirli aralıklarla günceller.

    İlerleme bilgisi gelmese bile geçen süre gösterilir; kullanıcı işin
    takılmadığını görür.
    """

    def __init__(
        self,
        status: StatusMessage,
        render: Callable[[int | None, int | None, float], str],
        interval: float = 6.0,
    ) -> None:
        self._status = status
        self._render = render
        self._interval = interval
        self._done: int | None = None
        self._total: int | None = None
        self._started = time.monotonic()
        self._task: asyncio.Task[None] | None = None

    async def update(self, done: int, total: int) -> None:
        self._done, self._total = done, total

    async def _loop(self) -> None:
        while True:
            await self._status.show(self._render(self._done, self._total, time.monotonic() - self._started))
            await asyncio.sleep(self._interval)

    async def __aenter__(self) -> "ProgressTicker":
        self._started = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task


async def run_cancellable(awaitable: Awaitable[T], cancel: asyncio.Event, timeout: float) -> T:
    """İşi çalıştırır; /iptal gelirse ya da süre dolarsa durdurup OperationCancelled fırlatır."""
    task = asyncio.ensure_future(awaitable)
    waiter = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, timeout=max(timeout, 1), return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
    if task in done:
        return task.result()
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task
    raise OperationCancelled(by_user=cancel.is_set())


async def watch_for_cancel(ctx: BotContext, cancel: asyncio.Event) -> None:
    """Uzun işlemler sırasında Telegram'ı dinler: /iptal gelirse işareti verir."""
    from bot import messages as M
    from bot.inbox import command_of

    while not cancel.is_set():
        try:
            message = await ctx.inbox.next(timeout=25)
            if message is None:
                continue
            if command_of(message) in ("/iptal", "/cancel"):
                cancel.set()
                await ctx.say(M.CANCELLING)
                return
            await ctx.say(M.BUSY)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # dinleyici asla ana işi düşürmemeli
            log.warning("İptal dinleyicisinde hata (%s).", describe(exc))
            await asyncio.sleep(5)

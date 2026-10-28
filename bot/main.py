"""Botun ana programı (workflow'un "Botu çalıştır" adımı).

Bekleyen mesajları sırayla işler:
  /yukle  → video yükleme konuşması (upload_flow)
  /giris  → Bilibili QR girişi (login_flow)
  /durum  → Bilibili oturum durumu
  /iptal, /yardim, diğerleri → kısa cevaplar
Bir iş bittikten sonra kısa bir süre (varsayılan 3 dk) yeni komut bekler;
gelmezse kapanır. Böylece arka arkaya birkaç video beklemeden yüklenebilir.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from typing import Any

import httpx

from bot import messages as M
from bot.bili_auth import USER_AGENT
from bot.config import ConfigError, initial_cookies_b64, load_settings
from bot.context import BotContext, Deadline
from bot.inbox import Inbox, command_of
from bot.log import describe, log, setup_logging
from bot.login_flow import run_login, run_status
from bot.notify_failure import notify
from bot.telegram import BotAPI, TelegramError
from bot.upload_flow import run_upload


async def handle(ctx: BotContext, message: dict[str, Any]) -> bool:
    """Tek bir mesajı işler. Bir iş yapıldıysa True döner (ardından kısa süre beklenir)."""
    command = command_of(message)
    if command in ("/yukle", "/upload"):
        await run_upload(ctx)
        return True
    if command in ("/giris", "/login"):
        await run_login(ctx)
        return True
    if command in ("/durum", "/status"):
        await run_status(ctx)
        return True
    if command in ("/iptal", "/cancel"):
        await ctx.say(M.NOTHING_TO_CANCEL)
        return False
    if command in ("/start", "/yardim", "/help"):
        await ctx.say(M.HELP)
        return False
    await ctx.say(M.UNKNOWN)
    return False


BOT_COMMANDS = [
    {"command": "yukle", "description": "Bilibili'ye video yükle"},
    {"command": "giris", "description": "Bilibili'ye QR kod ile giriş yap"},
    {"command": "durum", "description": "Bilibili oturum durumunu göster"},
    {"command": "iptal", "description": "Devam eden işlemi iptal et"},
    {"command": "yardim", "description": "Yardım"},
]


async def serve(ctx: BotContext) -> None:
    # Telegram'daki komut menüsünü güncel tut (BotFather'da elle ayarlamaya gerek kalmaz).
    try:
        await ctx.api.call("setMyCommands", {"commands": BOT_COMMANDS}, retries=1)
    except TelegramError:
        pass
    await ctx.inbox.poll_now()
    linger = False
    while True:
        message = ctx.inbox.pop_nowait()
        if message is None:
            await ctx.inbox.poll_now()
            message = ctx.inbox.pop_nowait()
        if message is None and linger and ctx.deadline.remaining() > ctx.settings.idle_linger + 120:
            log.info("Yeni komut için kısa süre bekleniyor.")
            message = await ctx.inbox.next(timeout=ctx.settings.idle_linger)
        if message is None:
            break
        try:
            linger = await handle(ctx, message)
        except Exception as exc:
            log.error("Komut işlenirken beklenmeyen hata (%s).", describe(exc))
            await ctx.say(M.UNEXPECTED_ERROR)
            linger = False


async def amain() -> int:
    setup_logging()
    os.umask(0o077)  # oluşturulan geçici dosyaları sadece bu kullanıcı okuyabilsin
    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("Ayar hatası: %s", exc)
        # Haber ver ve bekleyen mesajları at; yoksa her 5 dakikada aynı hata tekrarlanır.
        notify(f"⚠️ Ayar hatası: {exc}. GitHub → Settings → Secrets and variables bölümünü kontrol et.")
        return 1

    settings.work_dir.mkdir(parents=True, exist_ok=True)
    api = BotAPI(settings.bot_token)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers={"User-Agent": USER_AGENT}) as http:
            ctx = BotContext(
                settings=settings,
                api=api,
                inbox=Inbox(api, settings.allowed_user_id),
                deadline=Deadline(settings.run_budget),
                http=http,
                cookies_b64=initial_cookies_b64(),
            )
            try:
                await serve(ctx)
            finally:
                await ctx.inbox.commit()
    finally:
        await api.close()
        shutil.rmtree(settings.work_dir, ignore_errors=True)
    log.info("Bot işini bitirdi.")
    return 0


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 130
    except BaseException as exc:  # traceback basma: gizli veri içerebilir
        print(f"Beklenmeyen hata: {describe(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

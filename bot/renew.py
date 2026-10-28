"""Bilibili oturumunu otomatik yenileme (renew.yml workflow'u, günde bir kez).

1. Oturum geçerli mi bak (çerez + erişim anahtarı).
2. Erişim anahtarının süresi yaklaşıyorsa ya da Bilibili yenile diyorsa
   `biliup renew` ile yenile ve yeni çerezi BILIBILI_COOKIES_B64 secret'ına yaz.
3. Oturum tamamen geçersizse kullanıcıya Telegram'dan "/giris yapman gerekiyor" de.

FORCE_RENEW=true ile süreye bakmadan yenilenir (workflow'u elle çalıştırırken seçilebilir).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

from bot import bili_auth, github_secrets
from bot import messages as M
from bot.biliup import run_biliup
from bot.config import ConfigError, initial_cookies_b64, load_settings
from bot.cookies import CookieError, CookieFile
from bot.log import describe, log, mask, setup_logging
from bot.telegram import BotAPI, TelegramError

RENEW_WHEN_DAYS_LEFT = 30


async def _notify(api: BotAPI, chat_id: int, text: str) -> None:
    try:
        await api.send_message(chat_id, text)
    except TelegramError as exc:
        log.warning("Telegram bildirimi gönderilemedi (%s).", describe(exc))


async def renew(force: bool) -> int:
    settings = load_settings()
    cookies_b64 = initial_cookies_b64()
    if not cookies_b64:
        log.info("Kayıtlı Bilibili oturumu yok; yenileme atlandı.")
        return 0

    settings.work_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="renew-", dir=settings.work_dir))
    api = BotAPI(settings.bot_token)
    chat_id = settings.allowed_user_id
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            try:
                cookie_file = CookieFile(cookies_b64, work)
            except CookieError:
                log.warning("Çerez secret'ı okunamadı.")
                await _notify(api, chat_id, M.COOKIES_UNREADABLE)
                return 0
            info = cookie_file.info()
            mask(*bili_auth.sensitive_values(info))

            status = await bili_auth.check_login(http, info)
            if status.valid is False:
                log.info("Bilibili oturumu geçersiz; kullanıcı bilgilendiriliyor.")
                await _notify(api, chat_id, M.RENEW_EXPIRED)
                return 0
            days_left = status.token_days_left
            if days_left is None and not force:
                log.warning("Oturum durumu öğrenilemedi; yenileme bir sonraki çalışmaya kaldı.")
                return 0
            due = force or status.needs_refresh or (days_left is not None and days_left < RENEW_WHEN_DAYS_LEFT)
            if not due:
                log.info("Oturum geçerli; yenilemeye gerek yok.")
                return 0

            # Yenileme eski anahtarı geçersiz kılar. Yeni çerezi kaydedemezsek
            # oturum kaybolur; bu yüzden önce GitHub'a yazabildiğimizi doğrula.
            if not settings.gh_pat or not settings.github_repository:
                await _notify(api, chat_id, M.RENEW_GITHUB_PROBLEM.format(reason="GH_PAT secret'ı tanımlı değil"))
                return 1
            try:
                await github_secrets.get_public_key(http, settings.gh_pat, settings.github_repository)
            except github_secrets.SecretUpdateError as exc:
                await _notify(api, chat_id, M.RENEW_GITHUB_PROBLEM.format(reason=exc))
                return 1

            result = await run_biliup(settings.biliup_bin, cookie_file.path, ["renew"], cwd=work)
            if result.returncode != 0:
                log.warning("biliup renew başarısız oldu.")
                after = await bili_auth.check_login(http, cookie_file.info())
                if after.valid is False:
                    await _notify(api, chat_id, M.RENEW_EXPIRED)
                return 1
            if not cookie_file.changed():
                log.info("Yenileme yeni bir çerez üretmedi; değişiklik yok.")
                return 0

            new_b64 = cookie_file.current_b64()
            mask(new_b64, *bili_auth.sensitive_values(cookie_file.info()))
            try:
                await github_secrets.put_secret(
                    http, settings.gh_pat, settings.github_repository, github_secrets.COOKIES_SECRET_NAME, new_b64
                )
            except github_secrets.SecretUpdateError as exc:
                log.warning("Yenilenen çerez kaydedilemedi.")
                await _notify(api, chat_id, M.RENEW_SAVE_FAILED.format(reason=exc))
                return 1
            log.info("Bilibili oturumu yenilendi ve secret güncellendi.")
            return 0
    finally:
        await api.close()
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    setup_logging()
    os.umask(0o077)
    force = os.environ.get("FORCE_RENEW", "").strip().lower() == "true"
    try:
        return asyncio.run(renew(force))
    except ConfigError as exc:
        log.error("Ayar hatası: %s", exc)
        return 1
    except BaseException as exc:  # traceback basma: gizli veri içerebilir
        print(f"Beklenmeyen hata: {describe(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""/giris: Bilibili QR kod girişi ve /durum: oturum durumu.

QR kod sadece Telegram'dan kullanıcıya gönderilir; diske ya da loga yazılmaz.
Giriş başarılı olunca biliup formatındaki çerez base64'lenip GitHub API ile
BILIBILI_COOKIES_B64 secret'ına (libsodium ile şifrelenerek) yazılır.
"""

from __future__ import annotations

import json
import time

from bot import bili_auth, github_secrets
from bot import messages as M
from bot.context import BotContext
from bot.cookies import CookieError, decode_cookies_b64, encode_cookies
from bot.inbox import command_of
from bot.log import describe, log, mask

QR_LIFETIME_SECONDS = 175  # Bilibili TV QR kodu ~180 sn geçerli
POLL_INTERVAL_SECONDS = 3


async def run_login(ctx: BotContext) -> None:
    log.info("Giriş oturumu başladı.")
    settings = ctx.settings
    if not settings.gh_pat or not settings.github_repository:
        await ctx.say(M.GH_PAT_MISSING)
        return
    # Kullanıcı boşuna QR taramasın: önce GitHub'a yazabildiğimizi doğrula.
    try:
        await github_secrets.get_public_key(ctx.http, settings.gh_pat, settings.github_repository)
    except github_secrets.SecretUpdateError as exc:
        await ctx.say(M.GH_PAT_PROBLEM.format(reason=exc))
        return

    try:
        ticket = await bili_auth.request_qr(ctx.http)
    except bili_auth.BiliAuthError as exc:
        await ctx.say(M.QR_REQUEST_FAILED.format(reason=exc))
        return

    photo = await ctx.api.send_photo(ctx.chat_id, bili_auth.render_qr_png(ticket.url), caption=M.QR_CAPTION)
    qr_message_id = photo.get("message_id") if photo else None
    try:
        data = await _wait_for_scan(ctx, ticket)
    finally:
        if qr_message_id:
            await ctx.api.delete_message(ctx.chat_id, qr_message_id)
    if data is None:
        return

    try:
        info = bili_auth.build_login_info(data)
    except bili_auth.BiliAuthError as exc:
        await ctx.say(M.LOGIN_FAILED.format(reason=exc))
        return
    mask(*bili_auth.sensitive_values(info))
    status = await bili_auth.check_login(ctx.http, info)

    error = await ctx.save_cookies(encode_cookies(info))
    if error:
        await ctx.say(M.LOGIN_SAVE_FAILED.format(reason=error))
        return
    log.info("Bilibili girişi başarılı.")
    account = f" (hesap: {status.uname})" if status.uname else ""
    await ctx.say(M.LOGIN_SUCCESS.format(account=account))


async def _wait_for_scan(ctx: BotContext, ticket: bili_auth.QrTicket) -> dict | None:
    """QR kod taranıp onaylanana kadar bekler. İptal/zaman aşımında None döner."""
    deadline = time.monotonic() + QR_LIFETIME_SECONDS
    scanned_notified = False
    while time.monotonic() < deadline:
        try:
            state, data = await bili_auth.poll_qr(ctx.http, ticket.auth_code)
        except bili_auth.BiliAuthError as exc:
            await ctx.say(M.LOGIN_FAILED.format(reason=exc))
            return None
        if state is bili_auth.QrState.SUCCESS:
            return data
        if state is bili_auth.QrState.EXPIRED:
            break
        if state is bili_auth.QrState.SCANNED and not scanned_notified:
            scanned_notified = True
            await ctx.say(M.QR_SCANNED)
        # Beklerken gelen mesajlara bak (bu bekleme aynı zamanda poll aralığıdır).
        message = await ctx.inbox.next(timeout=POLL_INTERVAL_SECONDS)
        if message is not None:
            if command_of(message) in ("/iptal", "/cancel"):
                await ctx.say(M.CANCELLED)
                log.info("Giriş kullanıcı tarafından iptal edildi.")
                return None
            await ctx.say(M.QR_WAITING)
    await ctx.say(M.QR_EXPIRED)
    log.info("QR kodun süresi doldu.")
    return None


async def run_status(ctx: BotContext) -> None:
    """Bilibili oturumunun geçerli olup olmadığını bildirir."""
    if not ctx.cookies_b64:
        await ctx.say(M.LOGIN_REQUIRED)
        return
    try:
        info = json.loads(decode_cookies_b64(ctx.cookies_b64))
    except CookieError:
        await ctx.say(M.COOKIES_UNREADABLE)
        return
    try:
        status = await bili_auth.check_login(ctx.http, info)
    except Exception as exc:
        log.warning("Oturum kontrolü başarısız (%s).", describe(exc))
        await ctx.say(M.STATUS_UNKNOWN)
        return
    if status.valid is None:
        await ctx.say(M.STATUS_UNKNOWN)
    elif not status.valid:
        await ctx.say(M.STATUS_INVALID)
    else:
        account = f" (hesap: {status.uname})" if status.uname else ""
        days = M.STATUS_DAYS.format(days=int(status.token_days_left)) if status.token_days_left else ""
        await ctx.say(M.STATUS_VALID.format(account=account, days=days))

"""/yukle: bilgileri topla → videoyu Telegram'dan indir → biliup ile Bilibili'ye yükle."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

from bot import bili_auth
from bot import messages as M
from bot.biliup import BiliupError, build_upload_args, explain_failure, find_bvid, run_biliup
from bot.conversation import StepContext, UploadRequest, build_steps, run_dialog, summary, video_suffix
from bot.context import (
    BotContext,
    OperationCancelled,
    ProgressTicker,
    StatusMessage,
    run_cancellable,
    watch_for_cancel,
)
from bot.cookies import CookieError, CookieFile
from bot.downloader import DownloadError, download
from bot.log import describe, log

# Yeni bir yükleme konuşmasına başlamak için gereken asgari çalışma süresi.
MIN_SESSION_SECONDS = 40 * 60
# Konuşma sırasında indirme + yükleme için ayrılan süre.
TRANSFER_RESERVE_SECONDS = 25 * 60
# Süre bütçesinin sonunda temizlik ve mesajlar için bırakılan pay.
SAFETY_MARGIN_SECONDS = 60


async def run_upload(ctx: BotContext) -> None:
    log.info("Yükleme oturumu başladı.")
    if not ctx.cookies_b64:
        await ctx.say(M.LOGIN_REQUIRED)
        return
    if ctx.deadline.remaining() < MIN_SESSION_SECONDS:
        await ctx.say(M.RUN_ALMOST_OVER)
        return

    ctx.settings.work_dir.mkdir(parents=True, exist_ok=True)
    session_path = Path(tempfile.mkdtemp(prefix="upload-", dir=ctx.settings.work_dir))
    cookie_file: CookieFile | None = None
    try:
        try:
            cookie_file = CookieFile(ctx.cookies_b64, session_path)
        except CookieError:
            await ctx.say(M.COOKIES_UNREADABLE)
            return

        # Oturum geçersizse kullanıcı boşuna 2 GB video göndermesin.
        status = await bili_auth.check_login(ctx.http, cookie_file.info())
        if status.valid is False:
            await ctx.say(M.LOGIN_EXPIRED)
            return

        req = UploadRequest(tid=ctx.settings.bili_tid, tags=list(ctx.settings.bili_tags))
        step_ctx = StepContext(bot=ctx, session_dir=session_path)
        if not await run_dialog(step_ctx, build_steps(ctx.settings), req, reserve=TRANSFER_RESERVE_SECONDS):
            return

        await ctx.say(summary(req))
        await ctx.inbox.commit()  # konuşma mesajlarını onayla; tekrar işlenmesinler
        await _transfer(ctx, req, session_path, cookie_file)
    finally:
        if cookie_file is not None:
            await _persist_renewed_cookies(ctx, cookie_file)
            cookie_file.remove()
        shutil.rmtree(session_path, ignore_errors=True)


async def _transfer(ctx: BotContext, req: UploadRequest, session_dir: Path, cookie_file: CookieFile) -> None:
    """İndirme ve yükleme aşamaları; bu sırada /iptal dinlenir."""
    assert req.video is not None
    cancel = asyncio.Event()
    watcher = asyncio.create_task(watch_for_cancel(ctx, cancel))
    status = StatusMessage(ctx)
    try:
        # 1) Telegram'dan indir
        video_path = session_dir / f"video{video_suffix(req.video)}"
        await status.show(M.DOWNLOAD_STARTING, force=True)
        async with ProgressTicker(
            status, lambda done, total, elapsed: M.progress_line(M.DOWNLOAD_STARTING, done, total, elapsed)
        ) as ticker:
            video_path = await run_cancellable(
                download(req.video, video_path, api=ctx.api, settings=ctx.settings, progress=ticker.update),
                cancel,
                ctx.deadline.remaining() - SAFETY_MARGIN_SECONDS,
            )
        log.info("Video indirildi.")

        # 2) Bilibili'ye yükle
        await status.show(M.UPLOAD_STARTING, force=True)
        args = build_upload_args(
            video_path=video_path,
            title=req.title,
            description=req.description,
            tid=req.tid,
            tags=req.tags,
            cover_path=req.cover_path,
            line=ctx.settings.bili_line,
            watermark=ctx.settings.bili_watermark,
        )
        async with ProgressTicker(
            status, lambda done, total, elapsed: M.progress_line(M.UPLOAD_STARTING, done, total, elapsed), 10.0
        ) as ticker:
            result = await run_cancellable(
                run_biliup(ctx.settings.biliup_bin, cookie_file.path, args, cwd=session_dir, on_progress=ticker.update),
                cancel,
                ctx.deadline.remaining() - SAFETY_MARGIN_SECONDS,
            )
        secrets = bili_auth.sensitive_values(cookie_file.info())
        if result.returncode != 0:
            raise explain_failure(result.output, secrets)

        bvid = find_bvid(result.output)
        log.info("Yükleme başarılı.")
        await status.show("✅ Tamamlandı.", force=True)
        if bvid:
            size_bytes = M.exact_bytes(video_path.stat().st_size)
            await ctx.say(M.UPLOAD_SUCCESS.format(bvid=bvid, size_bytes=size_bytes), link_preview=True)
        else:
            await ctx.say(M.UPLOAD_SUCCESS_NO_BVID)
    except OperationCancelled as exc:
        log.info("İşlem durduruldu (%s).", "kullanıcı" if exc.by_user else "süre")
        await status.show("⏹ Durduruldu.", force=True)
        if exc.by_user:
            await ctx.say(M.CANCELLED)
        else:
            await ctx.say(M.DEADLINE_DURING_OPERATION)
    except DownloadError as exc:
        log.warning("Video indirilemedi.")
        await ctx.say(M.DOWNLOAD_FAILED.format(reason=exc.reason))
    except BiliupError as exc:
        log.warning("Bilibili yüklemesi başarısız.")
        text = M.UPLOAD_FAILED.format(reason=exc.reason)
        if exc.detail:
            text += f"\n\nAyrıntı:\n{exc.detail}"
        await ctx.say(text)
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


async def _persist_renewed_cookies(ctx: BotContext, cookie_file: CookieFile) -> None:
    """biliup oturumu kendiliğinden yenilediyse yeni çerezi secret'a kaydet."""
    try:
        if not cookie_file.changed():
            return
        log.info("biliup Bilibili oturumunu yeniledi; secret güncelleniyor.")
        error = await ctx.save_cookies(cookie_file.current_b64())
        if error:
            await ctx.say(M.COOKIES_SAVE_WARNING.format(reason=error))
        else:
            cookie_file.mark_saved()
    except Exception as exc:
        log.warning("Yenilenen çerez kaydedilemedi (%s).", describe(exc))

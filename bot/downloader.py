"""Telegram'dan dosya indirme.

- 20 MB'a kadar: Bot API (getFile) yeterli.
- 20 MB üstü (2 GB'a kadar): Bot API izin vermez; MTProto ile indiririz.
  Kurigram (bakımı süren Pyrogram fork'u) bot token + API_ID + API_HASH ile
  giriş yapar. Oturum sadece bellekte tutulur (in_memory), diske .session
  dosyası yazılmaz.

MTProto tarafında önce Bot API'nin verdiği file_id ile indirmeyi deneriz
(Bot API ve Pyrogram aynı file_id biçimini kullanır). file_id'deki dosya
referansının süresi dolmuşsa mesajı chat/message id ile yeniden alıp indiririz.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from bot.config import Settings
from bot.log import describe, log
from bot.telegram import BotAPI, TelegramError

BOT_API_DOWNLOAD_LIMIT = 20 * 1024 * 1024

ProgressCallback = Callable[[int, int], Awaitable[None]]


class DownloadError(Exception):
    """İndirme başarısız. `reason` kullanıcıya gösterilebilir."""

    def __init__(self, reason: str) -> None:
        super().__init__("indirme başarısız")
        self.reason = reason


@dataclass(frozen=True)
class MediaRef:
    """Telegram'daki bir dosyaya referans. İçeriği/adı asla loglanmaz."""

    file_id: str
    file_unique_id: str
    file_size: int | None
    message_id: int
    file_name: str | None = None
    mime_type: str | None = None
    # "document": dosya olarak gönderildi (orijinal bayt); "video"/"animation":
    # Telegram uygulaması göndermeden önce yeniden kodlamış olabilir.
    kind: str = "document"

    @property
    def needs_mtproto(self) -> bool:
        return self.file_size is None or self.file_size > BOT_API_DOWNLOAD_LIMIT


async def download(
    media: MediaRef,
    dest: Path,
    *,
    api: BotAPI,
    settings: Settings,
    progress: ProgressCallback | None = None,
) -> Path:
    """Dosyayı uygun yöntemle `dest` yoluna indirir ve Telegram'daki boyutla birebir aynı mı kontrol eder."""
    if not media.needs_mtproto:
        try:
            path = await api.download_file(media.file_id, dest, progress)
            return verify_size(path, media.file_size)
        except TelegramError as exc:
            log.warning("Bot API ile indirme başarısız (%s).", describe(exc))
            if not settings.mtproto_enabled:
                raise DownloadError("Telegram'dan dosya alınamadı") from None
    if not settings.mtproto_enabled:
        raise DownloadError("20 MB üstü dosyalar için TELEGRAM_API_ID ve TELEGRAM_API_HASH gerekli")
    path, expected = await _download_mtproto(media, dest, settings, progress)
    return verify_size(path, expected)


def verify_size(path: Path, expected: int | None) -> Path:
    """İnen dosya eksik/boş ise siler ve hata verir. Böylece yarım bir video asla yüklenmez."""
    size = path.stat().st_size if path.exists() else 0
    if size == 0 or (expected and size != expected):
        path.unlink(missing_ok=True)
        log.warning("İndirilen dosyanın boyutu beklenenle uyuşmuyor.")
        raise DownloadError("Video eksik indirildi (boyut uyuşmuyor); tekrar dene")
    return path


def same_media(media: MediaRef, candidate: object) -> bool:
    """Yeniden alınan mesajdaki dosya, kullanıcının gönderdiği dosyayla aynı mı?"""
    return not media.file_unique_id or getattr(candidate, "file_unique_id", None) == media.file_unique_id


async def _download_mtproto(
    media: MediaRef, dest: Path, settings: Settings, progress: ProgressCallback | None
) -> tuple[Path, int | None]:
    """(indirilen dosya, Telegram'a göre beklenen bayt sayısı) döndürür."""
    from pyrogram import Client, raw, utils
    from pyrogram.errors import AccessTokenInvalid, ApiIdInvalid, BadRequest, RPCError

    total = media.file_size or 0
    expected = media.file_size

    async def on_progress(current: int, reported_total: int) -> None:
        if progress:
            await progress(current, total or reported_total)

    client = Client(
        "bilibot",
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        bot_token=settings.bot_token,
        in_memory=True,  # .session dosyası oluşturma
        no_updates=True,  # güncellemeleri Bot API ile alıyoruz
        workdir=str(dest.parent),
        sleep_threshold=120,
    )
    try:
        async with client:
            try:
                result = await client.download_media(media.file_id, file_name=str(dest), progress=on_progress)
            except (BadRequest, ValueError) as exc:
                # Çoğunlukla dosya referansının süresi dolmuştur: mesajı yeniden al.
                log.info("file_id ile indirilemedi (%s); mesaj yeniden alınıyor.", describe(exc))
                response = await client.invoke(
                    raw.functions.messages.GetMessages(id=[raw.types.InputMessageID(id=media.message_id)])
                )
                messages = await utils.parse_messages(client, response)
                message = next((m for m in messages if m and not getattr(m, "empty", False)), None)
                if message is None:
                    raise DownloadError("Mesaj Telegram'da bulunamadı (silinmiş olabilir)") from None
                found = message.video or message.document or message.animation
                if found is None or not same_media(media, found):
                    raise DownloadError("Mesajdaki video değişmiş; videoyu tekrar gönder") from None
                expected = expected or getattr(found, "file_size", None)
                result = await client.download_media(message, file_name=str(dest), progress=on_progress)
    except DownloadError:
        raise
    except (ApiIdInvalid, AccessTokenInvalid):
        raise DownloadError("TELEGRAM_API_ID / TELEGRAM_API_HASH geçersiz (README'ye bak)") from None
    except RPCError as exc:
        log.warning("MTProto indirme hatası (%s).", describe(exc))
        raise DownloadError("Telegram dosyayı vermedi (MTProto hatası)") from None
    except (OSError, ConnectionError) as exc:
        log.warning("MTProto bağlantı hatası (%s).", describe(exc))
        raise DownloadError("Telegram bağlantısı koptu") from None
    if not result:
        raise DownloadError("İndirme tamamlanamadı")
    return Path(str(result)), expected

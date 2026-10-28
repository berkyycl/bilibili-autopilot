"""/yukle konuşması: adımlar ve adımları sırayla yürüten diyalog.

Her adım bağımsız bir sınıftır ve `build_steps()` listesine eklenir. Yeni bir
soru (ör. kategori ya da etiket) eklemek için yeni bir Step yazıp listeye
koymak yeterlidir. Kategori (tid) ve etiket adımları zaten hazır; varsayılan
olarak kapalıdır ve BILI_ASK_TID / BILI_ASK_TAGS değişkenleriyle açılır.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bot import messages as M
from bot.config import MAX_TAG_LENGTH, MAX_TAGS, Settings, parse_tags
from bot.context import BotContext
from bot.downloader import BOT_API_DOWNLOAD_LIMIT, MediaRef
from bot.inbox import command_of
from bot.log import describe, log
from bot.telegram import TelegramError

MAX_TITLE_LENGTH = 80  # Bilibili sınırı
MAX_DESCRIPTION_LENGTH = 2000  # Bilibili sınırı
SKIP_COMMAND = "/atla"
CONTINUE_COMMAND = "/devam"
# Adımların kendisinin yorumladığı komutlar (diğer komutlar diyalogda reddedilir)
STEP_COMMANDS = (SKIP_COMMAND, CONTINUE_COMMAND)
CANCEL_COMMANDS = ("/iptal", "/cancel")

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".flv", ".avi", ".webm", ".m4v", ".wmv", ".ts", ".mpg", ".mpeg", ".3gp",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass
class UploadRequest:
    """Kullanıcıdan toplanan yükleme bilgileri."""

    tid: int
    tags: list[str]
    video: MediaRef | None = None
    title: str = ""
    description: str = ""
    cover_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # ileride eklenecek alanlar için


@dataclass
class StepContext:
    bot: BotContext
    session_dir: Path

    @property
    def settings(self) -> Settings:
        return self.bot.settings


# --- Mesajlardan medya çıkarma ------------------------------------------------------


def _media_ref(obj: dict[str, Any], message: dict[str, Any], kind: str = "document") -> MediaRef:
    return MediaRef(
        file_id=obj["file_id"],
        file_unique_id=obj.get("file_unique_id", ""),
        file_size=obj.get("file_size"),
        message_id=message["message_id"],
        file_name=obj.get("file_name"),
        mime_type=obj.get("mime_type"),
        kind=kind,
    )


def extract_video(message: dict[str, Any]) -> MediaRef | None:
    """Mesajdaki videoyu bulur. `kind` alanı, Telegram uygulamasının videoyu
    sıkıştırmış olabileceği gönderimleri ("video", sessiz videolar için "animation") ayırır."""
    if message.get("video"):
        return _media_ref(message["video"], message, "video")
    document = message.get("document")
    if document:
        mime = (document.get("mime_type") or "").lower()
        suffix = Path(document.get("file_name") or "").suffix.lower()
        if mime.startswith("video/") or suffix in VIDEO_EXTENSIONS:
            kind = "animation" if message.get("animation") else "document"
            return _media_ref(document, message, kind)
    return None


def extract_image(message: dict[str, Any]) -> MediaRef | None:
    photos = message.get("photo")
    if photos:
        # Telegram aynı fotoğrafın birkaç boyutunu gönderir; en büyüğünü al.
        return _media_ref(max(photos, key=lambda p: p.get("file_size") or p.get("width", 0)), message)
    document = message.get("document")
    if document:
        mime = (document.get("mime_type") or "").lower()
        suffix = Path(document.get("file_name") or "").suffix.lower()
        if mime.startswith("image/") or suffix in IMAGE_EXTENSIONS:
            return _media_ref(document, message)
    return None


def video_suffix(media: MediaRef) -> str:
    """İndirilen videoya verilecek uzantı (dosyanın orijinal adı kullanılmaz)."""
    suffix = Path(media.file_name or "").suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return suffix
    mime = (media.mime_type or "").lower()
    for ext, kind in ((".mkv", "matroska"), (".mov", "quicktime"), (".webm", "webm"), (".avi", "avi")):
        if kind in mime:
            return ext
    return ".mp4"


def prepare_cover(source: Path, dest: Path) -> None:
    """Kapak görselini Bilibili'nin beklediği JPEG biçimine çevirir."""
    from PIL import Image, ImageOps

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        image.thumbnail((2560, 1600))  # gereksiz büyük görselleri küçült
        image.save(dest, "JPEG", quality=92)


# --- Adımlar ----------------------------------------------------------------------


class Step(ABC):
    """Konuşmadaki bir soru. `accept` None dönerse cevap kabul edilmiştir;
    aksi halde dönen metin kullanıcıya gösterilir ve aynı adım tekrarlanır."""

    @abstractmethod
    def prompt(self, req: UploadRequest) -> str: ...

    @abstractmethod
    async def accept(self, message: dict[str, Any], req: UploadRequest, ctx: StepContext) -> str | None: ...


class VideoStep(Step):
    def __init__(self) -> None:
        self._compressed: MediaRef | None = None  # /devam onayı bekleyen sıkıştırılmış video

    def prompt(self, req: UploadRequest) -> str:
        return M.ASK_VIDEO

    async def accept(self, message: dict[str, Any], req: UploadRequest, ctx: StepContext) -> str | None:
        if command_of(message) == CONTINUE_COMMAND and self._compressed:
            media = self._compressed  # kullanıcı sıkıştırılmış haliyle yüklemeyi onayladı
        else:
            media = extract_video(message)
            if media is None:
                return M.NEED_VIDEO
            if media.kind != "document":
                # Telegram uygulaması "video" olarak gönderilen klipleri yeniden kodlar.
                self._compressed = media
                return M.COMPRESSED_VIDEO
        if media.needs_mtproto and not ctx.settings.mtproto_enabled:
            return M.NEED_MTPROTO
        free = shutil.disk_usage(ctx.session_dir).free
        if media.file_size and media.file_size * 1.05 > free:
            return M.NOT_ENOUGH_DISK.format(free=M.human_size(free))
        req.video = media
        return None


class TextStep(Step):
    def __init__(self, attr: str, prompt: str, max_length: int, *, skippable: bool = False) -> None:
        self.attr = attr
        self._prompt = prompt
        self.max_length = max_length
        self.skippable = skippable

    def prompt(self, req: UploadRequest) -> str:
        return self._prompt.format(max=self.max_length)

    def clean(self, text: str) -> str:
        return text.strip()

    async def accept(self, message: dict[str, Any], req: UploadRequest, ctx: StepContext) -> str | None:
        text = message.get("text")
        if text is None:
            return M.NEED_TEXT
        command = command_of(message)
        if command:
            if self.skippable and command == SKIP_COMMAND:
                setattr(req, self.attr, "")
                return None
            return M.COMMAND_IN_DIALOG  # "/atla" gibi bir komut başlık olarak kaydedilmesin
        value = self.clean(text)
        if not value:
            return M.EMPTY_TEXT
        if len(value) > self.max_length:
            return M.TOO_LONG.format(length=len(value), max=self.max_length)
        setattr(req, self.attr, value)
        return None


class TitleStep(TextStep):
    def __init__(self) -> None:
        super().__init__("title", M.ASK_TITLE, MAX_TITLE_LENGTH)

    def clean(self, text: str) -> str:
        return " ".join(text.split())  # başlıkta satır sonu olmasın


class CoverStep(Step):
    def prompt(self, req: UploadRequest) -> str:
        return M.ASK_COVER

    async def accept(self, message: dict[str, Any], req: UploadRequest, ctx: StepContext) -> str | None:
        media = extract_image(message)
        if media is None:
            return M.NEED_IMAGE
        if media.file_size and media.file_size > BOT_API_DOWNLOAD_LIMIT:
            return M.IMAGE_TOO_BIG
        # Kapak küçük olduğu için hemen indirip kontrol ediyoruz; böylece sorun
        # varsa kullanıcı daha videoyu yüklemeden başka bir görsel gönderebilir.
        source = ctx.session_dir / "cover_source"
        try:
            await ctx.bot.api.download_file(media.file_id, source)
        except TelegramError as exc:
            log.warning("Kapak görseli indirilemedi (%s).", describe(exc))
            return M.IMAGE_DOWNLOAD_FAILED
        dest = ctx.session_dir / "cover.jpg"
        try:
            prepare_cover(source, dest)
        except Exception as exc:  # Pillow açamadıysa
            log.info("Kapak görseli işlenemedi (%s).", describe(exc))
            return M.IMAGE_UNREADABLE
        finally:
            source.unlink(missing_ok=True)
        req.cover_path = dest
        return None


class TidStep(Step):
    def prompt(self, req: UploadRequest) -> str:
        return M.ASK_TID.format(default=req.tid)

    async def accept(self, message: dict[str, Any], req: UploadRequest, ctx: StepContext) -> str | None:
        if command_of(message) == SKIP_COMMAND:
            return None
        text = (message.get("text") or "").strip()
        if not text.isdigit() or int(text) <= 0:
            return M.NEED_TID
        req.tid = int(text)
        return None


class TagsStep(Step):
    def prompt(self, req: UploadRequest) -> str:
        return M.ASK_TAGS.format(max_tags=MAX_TAGS, max_len=MAX_TAG_LENGTH, default=", ".join(req.tags))

    async def accept(self, message: dict[str, Any], req: UploadRequest, ctx: StepContext) -> str | None:
        if command_of(message) == SKIP_COMMAND:
            return None
        text = message.get("text")
        if text is None:
            return M.NEED_TEXT
        tags = parse_tags(text)
        if not tags or len(tags) > MAX_TAGS or any(len(t) > MAX_TAG_LENGTH for t in tags):
            return M.BAD_TAGS.format(max_tags=MAX_TAGS, max_len=MAX_TAG_LENGTH)
        req.tags = tags
        return None


def build_steps(settings: Settings) -> list[Step]:
    """Sorulacak adımların listesi. Sıra burada belirlenir."""
    steps: list[Step] = [
        VideoStep(),
        TitleStep(),
        TextStep("description", M.ASK_DESCRIPTION, MAX_DESCRIPTION_LENGTH, skippable=True),
        CoverStep(),
    ]
    if settings.ask_tid:
        steps.append(TidStep())
    if settings.ask_tags:
        steps.append(TagsStep())
    return steps


# --- Diyalog ----------------------------------------------------------------------


async def run_dialog(ctx: StepContext, steps: list[Step], req: UploadRequest, *, reserve: float) -> bool:
    """Adımları sırayla sorar. Tamamlanırsa True; iptal/zaman aşımında False döner.

    `reserve`: indirme + yükleme için çalışma süresinden ayrılacak saniye.
    """
    bot = ctx.bot
    step_timeout = ctx.settings.step_timeout
    for step in steps:
        await bot.say(step.prompt(req))
        while True:
            budget = bot.deadline.remaining() - reserve
            wait = min(step_timeout, budget)
            message = await bot.inbox.next(timeout=wait) if wait > 0 else None
            if message is None:
                if budget <= step_timeout:
                    await bot.say(M.RUN_BUDGET_EXHAUSTED)
                else:
                    await bot.say(M.STEP_TIMEOUT.format(minutes=int(step_timeout // 60)))
                log.info("Yükleme konuşması zaman aşımıyla bitti.")
                return False
            command = command_of(message)
            if command in CANCEL_COMMANDS:
                await bot.say(M.CANCELLED)
                log.info("Yükleme kullanıcı tarafından iptal edildi.")
                return False
            if command and command not in STEP_COMMANDS:
                await bot.say(M.COMMAND_IN_DIALOG)
                continue
            error = await step.accept(message, req, ctx)
            if error is None:
                break
            await bot.say(error)
    return True


def summary(req: UploadRequest) -> str:
    return M.SUMMARY.format(
        size=M.human_size(req.video.file_size if req.video else None),
        source=M.SOURCE_ORIGINAL if req.video and req.video.kind == "document" else M.SOURCE_COMPRESSED,
        title=req.title,
        description=M.shorten(req.description, 300) or "(yok)",
        tid=req.tid,
        tags=", ".join(req.tags),
    )

"""biliup CLI'yi (github.com/biliup/biliup) çalıştıran sarmalayıcı.

Güvenlik: biliup'ın çıktısı başlık, dosya adı, kullanıcı adı ve hatta token
içerebilir. Bu yüzden çıktının TAMAMI bellekte yakalanır ve Actions loguna
ASLA yazılmaz. Kullanıcıya (sadece Telegram'dan) gösterilen hata ayrıntıları
da önce gizli değerlerden temizlenir.

biliup ilerleme çubuğunu sadece bir terminale (TTY) çizer; çubuğu okuyup
Telegram'da yüzde gösterebilmek için biliup sahte bir terminalde (pty) çalıştırılır.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import re
import signal
import struct
import termios
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Iterable

ProgressCallback = Callable[[int, int], Awaitable[None]]

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>]")
_BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_PROGRESS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([KMGT]i?B|B)\s*/\s*(\d+(?:\.\d+)?)\s*([KMGT]i?B|B)(?!/s)"
)
_CODE_RE = re.compile(r"""\\?"?code\\?"?\s*[:=]\s*(-?\d+)""")
_MESSAGE_RE = re.compile(r"""\\?"?message\\?"?\s*[:=]\s*\\?"(.*?)\\?\"""")
_UNITS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
          "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}

# Sık görülen Bilibili hata kodları → anlaşılır Türkçe açıklama
KNOWN_ERRORS: dict[int, str] = {
    -101: "Bilibili oturumu geçersiz. /giris yapman gerekiyor.",
    -2: "Bilibili erişim anahtarı geçersiz. /giris yapman gerekiyor.",
    -352: "Bilibili güvenlik kontrolü (风控) isteği engelledi. Bir süre sonra tekrar dene.",
    -412: "Bilibili istekleri geçici olarak engelledi. Bir süre sonra tekrar dene.",
    21070: "Çok sık video yüklendi (Bilibili sınırı). Biraz bekleyip tekrar dene.",
}
LOGIN_ERROR_CODES = {-101, -2}


class BiliupError(Exception):
    """biliup başarısız oldu. `reason` kullanıcıya gösterilebilir (sadece Telegram'da)."""

    def __init__(self, reason: str, detail: str = "", login_required: bool = False) -> None:
        super().__init__("biliup başarısız")
        self.reason = reason
        self.detail = detail
        self.login_required = login_required


@dataclass
class BiliupResult:
    returncode: int
    output: str  # ANSI kodlarından arındırılmış, sınırlı uzunlukta çıktı


# --- Çıktı işleme ----------------------------------------------------------------


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def parse_progress(line: str) -> tuple[int, int] | None:
    """İlerleme çubuğundaki '1.20 GiB/2.00 GiB' kısmını (gönderilen, toplam) bayta çevirir."""
    match = None
    for match in _PROGRESS_RE.finditer(line):
        pass  # satırdaki son eşleşme en günceli
    if not match:
        return None
    done = float(match.group(1)) * _UNITS[match.group(2).upper()]
    total = float(match.group(3)) * _UNITS[match.group(4).upper()]
    if total <= 0 or done > total * 1.01:
        return None
    return int(done), int(total)


def find_bvid(output: str) -> str | None:
    found = _BVID_RE.findall(output)
    return found[-1] if found else None


def redact(text: str, secrets: Iterable[str]) -> str:
    """Gizli değerleri ve token benzeri parametreleri metinden siler."""
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "***")
    return re.sub(
        r"(?i)(access_key|access_token|refresh_token|SESSDATA|bili_jct|csrf|sign)([\"'=:\s]+)[^\s\"'&,}]+",
        r"\1\2***",
        text,
    )


def explain_failure(output: str, secrets: Iterable[str]) -> BiliupError:
    """biliup çıktısından kullanıcıya gösterilecek anlaşılır bir hata üretir."""
    clean = redact(output, secrets)
    codes = [int(c) for c in _CODE_RE.findall(clean) if int(c) != 0]
    messages = [m for m in _MESSAGE_RE.findall(clean) if m and m != "0"]
    tail = "\n".join(line[:300] for line in clean.strip().splitlines()[-12:])
    detail = tail[-1500:]

    code = codes[-1] if codes else None
    if code in KNOWN_ERRORS:
        return BiliupError(KNOWN_ERRORS[code], detail, login_required=code in LOGIN_ERROR_CODES)
    if code is not None:
        message = f": {messages[-1]}" if messages else ""
        return BiliupError(f"Bilibili hata kodu {code}{message}", detail)
    lowered = clean.lower()
    if "cookies.json" in lowered or "open cookies file" in lowered:
        return BiliupError("Giriş bilgileri okunamadı. /giris yapman gerekiyor.", detail, login_required=True)
    if "timed out" in lowered or "timeout" in lowered or "connection" in lowered:
        return BiliupError("Bilibili ile bağlantı sorunu oluştu. Biraz sonra tekrar dene.", detail)
    return BiliupError("Bilinmeyen bir hata oluştu (ayrıntı aşağıda).", detail)


# --- Süreç çalıştırma ------------------------------------------------------------


def _set_winsize(fd: int, rows: int = 40, cols: int = 160) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _kill_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


async def run_biliup(
    biliup_bin: str,
    cookie_path: Path,
    args: list[str],
    *,
    cwd: Path,
    on_progress: ProgressCallback | None = None,
    max_lines: int = 400,
) -> BiliupResult:
    """biliup'ı sahte terminalde çalıştırır ve çıktısını (loglamadan) yakalar.

    Bu coroutine iptal edilirse (asyncio.CancelledError) biliup süreci öldürülür.
    """
    loop = asyncio.get_running_loop()
    master_fd, slave_fd = pty.openpty()
    _set_winsize(slave_fd)
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "NO_COLOR": "1",
        "RUST_LOG": "info",
        "RUST_BACKTRACE": "0",
    }
    try:
        process = await asyncio.create_subprocess_exec(
            biliup_bin,
            "-u",
            str(cookie_path),
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(cwd),
            env=env,
            start_new_session=True,  # iptalde tüm süreç grubunu öldürebilmek için
        )
    except OSError:
        os.close(master_fd)
        os.close(slave_fd)
        raise BiliupError("biliup programı bulunamadı ya da çalıştırılamadı (kurulum adımına bak).") from None
    os.close(slave_fd)

    # pty'den okuma bloklayıcıdır; ayrı bir thread okuyup asyncio kuyruğuna aktarır.
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def reader() -> None:
        try:
            while True:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:  # EIO: süreç bitti ve terminal kapandı
                    break
                if not chunk:
                    break
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    thread = threading.Thread(target=reader, name="biliup-pty-reader", daemon=True)
    thread.start()

    lines: deque[str] = deque(maxlen=max_lines)
    pending = ""
    last_was_progress = False
    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            pending += chunk.decode("utf-8", errors="replace")
            # İlerleme çubuğu '\r' ile aynı satırı yeniden çizer.
            parts = re.split(r"[\r\n]", pending)
            pending = parts.pop()
            for part in parts:
                text = strip_ansi(part).strip()
                if not text:
                    continue
                progress = parse_progress(text)
                if progress and on_progress:
                    await on_progress(*progress)
                # Terminal gibi davran: art arda çizilen çubuklardan sadece sonuncusu kalır.
                # (Çubukla aynı satıra düşen log yazısı da böylece kaybolmaz.)
                if progress and last_was_progress and lines:
                    lines[-1] = text
                else:
                    lines.append(text)
                last_was_progress = progress is not None
        if pending.strip():
            lines.append(strip_ansi(pending).strip())
        returncode = await process.wait()
    except BaseException:
        # İptal ya da beklenmeyen hata: biliup'ı kibarca, olmazsa zorla durdur.
        _kill_group(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), timeout=10)
        except BaseException:
            _kill_group(process.pid, signal.SIGKILL)
        raise
    finally:
        # Okuyucu thread süreç bitince kendiliğinden durur; event loop'u bloklamadan bekle.
        await loop.run_in_executor(None, thread.join, 5)
        try:
            os.close(master_fd)
        except OSError:
            pass
    return BiliupResult(returncode=returncode, output="\n".join(lines))


def build_upload_args(
    *,
    video_path: Path,
    title: str,
    description: str,
    tid: int,
    tags: list[str],
    cover_path: Path | None,
    line: str | None,
    watermark: bool = False,
) -> list[str]:
    """`biliup upload` argümanları. Kullanıcı metinleri '--ad=değer' biçiminde verilir ki
    '-' ile başlayan bir başlık bayrak sanılmasın."""
    args = [
        "upload",
        "--copyright=1",
        f"--tid={tid}",
        f"--title={title}",
        f"--tag={','.join(tags)}",
    ]
    if description:
        args.append(f"--desc={description}")
    if cover_path:
        args.append(f"--cover={cover_path}")
    if line:
        args.append(f"--line={line}")
    # Bilibili, hesabın filigran ayarı açıksa videonun köşesine "kullanıcı adı + logo"
    # ekler. Durumu her yüklemede açıkça gönderiyoruz (0 = filigran yok).
    args.append(f"--extra-fields={json.dumps({'watermark': {'state': 1 if watermark else 0}})}")
    args += ["--", str(video_path)]
    return args

"""Herkese açık GitHub Actions logları için güvenli loglama.

Kural: loglara sadece genel durum yazılır ("kontrol edildi", "yükleme başarılı").
Token, çerez, QR kod, video başlığı/açıklaması, dosya adları ve Telegram mesaj
içerikleri ASLA loglanmaz. Hata durumunda bile sadece hata *türü* yazılır.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("bilibot")

# Bu kütüphaneler istek URL'lerini (bot token içerir), dosya adlarını ya da
# ayrıntılı hata metinlerini loglayabilir; hepsini susturuyoruz.
_NOISY_LOGGERS = ("httpx", "httpcore", "pyrogram", "PIL", "asyncio", "hpack")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def describe(exc: BaseException) -> str:
    """Bir hatayı loglanabilir hale getirir: sadece türü, mesajı değil."""
    return type(exc).__name__


def mask(*values: str | None) -> None:
    """GitHub Actions'a bu değerleri loglarda '***' ile gizlemesini söyler.

    Zaten hiçbir gizli değeri yazdırmıyoruz; bu ek bir güvenlik katmanıdır
    (ör. çalışma sırasında yeni oluşan Bilibili çerezleri için).
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for value in values:
        if not value:
            continue
        for line in str(value).splitlines():
            line = line.strip()
            if len(line) >= 6:
                sys.stdout.write(f"::add-mask::{line}\n")
    sys.stdout.flush()

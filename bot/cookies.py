"""BILIBILI_COOKIES_B64 secret'ından geçici bir cookies.json dosyası oluşturur.

Dosya sadece çalışma süresince, runner'ın geçici klasöründe (depo dışında)
0600 izniyle durur ve iş bitince silinir. biliup çalışırken oturumu
yenileyebilir (dosyayı yeniden yazar); `changed()` bunu tespit eder ki yeni
çerezler GitHub Secret'ına geri yazılabilsin.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any


class CookieError(Exception):
    """Çerez secret'ı çözümlenemedi."""


def _validate(raw: bytes) -> bytes:
    """İçeriğin biliup'ın cookies.json formatında olduğunu doğrular."""
    try:
        info = json.loads(raw)
    except ValueError:
        raise CookieError("Bilibili çerezi geçerli JSON değil") from None
    if not isinstance(info, dict) or "cookie_info" not in info or "token_info" not in info:
        raise CookieError("Bilibili çerezi beklenen biliup formatında değil")
    return raw


def decode_cookies_b64(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise CookieError("BILIBILI_COOKIES_B64 çözümlenemedi") from None
    return _validate(raw)


def encode_cookies(info: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(info, ensure_ascii=False, indent=2).encode()).decode()


class CookieFile:
    def __init__(self, b64: str, directory: Path) -> None:
        self._original = decode_cookies_b64(b64)
        self.path = directory / "cookies.json"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self._original)

    def read_bytes(self) -> bytes:
        try:
            return self.path.read_bytes()
        except OSError:
            return self._original

    def info(self) -> dict[str, Any]:
        return json.loads(self.read_bytes())

    def changed(self) -> bool:
        """biliup dosyayı geçerli yeni bir içerikle değiştirdi mi?"""
        current = self.read_bytes()
        if current == self._original:
            return False
        try:
            _validate(current)
        except CookieError:
            return False  # yarım yazılmış/bozuk dosyayı asla secret'a yazma
        return True

    def current_b64(self) -> str:
        return base64.b64encode(self.read_bytes()).decode()

    def mark_saved(self) -> None:
        self._original = self.read_bytes()

    def remove(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

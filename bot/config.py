"""Ayarları ortam değişkenlerinden (GitHub Secrets ve Variables) okur.

Gizli değerler (token, çerez vb.) sadece ortam değişkenlerinden gelir;
koda ya da depoya asla yazılmaz.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Değişken tanımlanmamışsa kullanılan varsayılanlar.
DEFAULT_TID = 17  # Bilibili "单机游戏" (tek oyunculu oyunlar) kategorisi
DEFAULT_TAGS = ("MOD", "模组", "游戏")
DEFAULT_STEP_TIMEOUT_MINUTES = 15
DEFAULT_RUN_BUDGET_MINUTES = 110  # job timeout'u (120 dk) dolmadan önce kendimiz bitiririz
DEFAULT_IDLE_LINGER_SECONDS = 900  # bir işten sonra 15 dk yeni komut bekle

# Bilibili sınırları
MAX_TAGS = 12
MAX_TAG_LENGTH = 20


class ConfigError(Exception):
    """Eksik ya da hatalı ayar. Mesajı loglanabilir; gizli değer içermez."""


def _env(name: str, default: str = "") -> str:
    # Telefondan kopyala-yapıştır yaparken eklenen boşluk/satır sonlarını temizle.
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} bir tam sayı olmalı") from exc


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "evet", "e"}


def parse_tags(raw: str) -> list[str]:
    """Virgülle (ya da Çince virgülle) ayrılmış etiketleri temizleyip listeler."""
    tags: list[str] = []
    for part in re.split(r"[,，]", raw):
        tag = part.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


@dataclass(frozen=True)
class Settings:
    """Bir çalışma boyunca değişmeyen ayarlar."""

    bot_token: str
    allowed_user_id: int
    api_id: int | None
    api_hash: str | None
    gh_pat: str | None
    github_repository: str | None  # "kullanici/depo"
    bili_tid: int
    bili_tags: tuple[str, ...]
    bili_line: str | None
    ask_tid: bool
    ask_tags: bool
    step_timeout: float  # saniye
    run_budget: float  # saniye
    idle_linger: float  # saniye
    work_dir: Path
    biliup_bin: str

    @property
    def mtproto_enabled(self) -> bool:
        """20 MB üstü dosyaları indirmek için MTProto bilgileri var mı?"""
        return self.api_id is not None and bool(self.api_hash)


def load_settings() -> Settings:
    """Ortam değişkenlerinden ayarları okur; eksik zorunlu değer varsa ConfigError fırlatır."""
    bot_token = _env("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ConfigError("TELEGRAM_BOT_TOKEN secret'ı eksik")

    allowed_raw = _env("ALLOWED_USER_ID")
    if not allowed_raw:
        raise ConfigError("ALLOWED_USER_ID secret'ı eksik")
    try:
        allowed_user_id = int(allowed_raw)
    except ValueError as exc:
        raise ConfigError("ALLOWED_USER_ID bir sayı olmalı") from exc

    api_id_raw = _env("TELEGRAM_API_ID")
    try:
        api_id = int(api_id_raw) if api_id_raw else None
    except ValueError as exc:
        raise ConfigError("TELEGRAM_API_ID bir sayı olmalı") from exc

    tags = parse_tags(_env("BILI_TAGS")) or list(DEFAULT_TAGS)
    work_root = Path(_env("RUNNER_TEMP") or tempfile.gettempdir())

    return Settings(
        bot_token=bot_token,
        allowed_user_id=allowed_user_id,
        api_id=api_id,
        api_hash=_env("TELEGRAM_API_HASH") or None,
        gh_pat=_env("GH_PAT") or None,
        github_repository=_env("GITHUB_REPOSITORY") or None,
        bili_tid=_env_int("BILI_TID", DEFAULT_TID),
        bili_tags=tuple(tags[:MAX_TAGS]),
        bili_line=_env("BILI_LINE").lower() or None,
        ask_tid=_env_bool("BILI_ASK_TID"),
        ask_tags=_env_bool("BILI_ASK_TAGS"),
        step_timeout=60.0 * _env_int("STEP_TIMEOUT_MINUTES", DEFAULT_STEP_TIMEOUT_MINUTES),
        run_budget=60.0 * _env_int("RUN_BUDGET_MINUTES", DEFAULT_RUN_BUDGET_MINUTES),
        idle_linger=float(_env_int("IDLE_LINGER_SECONDS", DEFAULT_IDLE_LINGER_SECONDS)),
        work_dir=work_root / "bilibot",
        biliup_bin=_env("BILIUP_BIN") or "biliup",
    )


def initial_cookies_b64() -> str:
    """BILIBILI_COOKIES_B64 secret'ını okur (boşluklar temizlenmiş halde)."""
    return re.sub(r"\s+", "", os.environ.get("BILIBILI_COOKIES_B64", ""))

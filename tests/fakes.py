"""Testler için sahte Telegram nesneleri."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from bot.config import Settings


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        bot_token="123:TEST",
        allowed_user_id=42,
        api_id=1,
        api_hash="hash",
        gh_pat="pat",
        github_repository="owner/repo",
        bili_tid=17,
        bili_tags=("MOD",),
        bili_line=None,
        bili_watermark=False,
        ask_tid=False,
        ask_tags=False,
        step_timeout=900.0,
        run_budget=6600.0,
        idle_linger=0.0,
        work_dir=tmp_path / "work",
        biliup_bin="biliup",
    )
    values.update(overrides)
    return Settings(**values)


def message(text: str | None = None, *, user_id: int = 42, message_id: int = 1, **extra: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": message_id,
        "from": {"id": user_id},
        "chat": {"id": user_id, "type": "private"},
    }
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return msg


def png_bytes(size: tuple[int, int] = (1280, 720)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeAPI:
    """BotAPI yerine geçer: gönderilen mesajları kaydeder."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.sent: list[str] = []
        self.calls: list[str] = []
        self.files = files or {}
        self._next_id = 100

    async def send_message(self, chat_id: int, text: str, *, link_preview: bool = False) -> dict[str, Any]:
        self.sent.append(text)
        self._next_id += 1
        return {"message_id": self._next_id}

    async def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        self.sent.append(text)

    async def call(self, method: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        self.calls.append(method)
        return True

    async def download_file(self, file_id: str, dest: Path, progress: Any = None) -> Path:
        dest.write_bytes(self.files[file_id])
        return dest


class FakeInbox:
    """Inbox yerine geçer: önceden belirlenen mesajları sırayla verir."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = list(messages)
        self.timeouts: list[float] = []

    async def next(self, timeout: float) -> dict[str, Any] | None:
        self.timeouts.append(timeout)
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(min(timeout, 0.05))  # gerçek long polling gibi kontrolü bırak
        return None

    async def poll_now(self) -> None:
        pass

    def pop_nowait(self) -> dict[str, Any] | None:
        return self.messages.pop(0) if self.messages else None

    async def commit(self) -> None:
        self.committed = True

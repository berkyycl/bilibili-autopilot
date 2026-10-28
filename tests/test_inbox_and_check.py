import asyncio

import pytest

from bot import check, tg_lite
from bot.config import ConfigError, load_settings, parse_tags
from bot.inbox import Inbox, command_of
from tests.fakes import message


class ScriptedAPI:
    """get_updates çağrılarını kaydeden sahte Bot API."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    async def get_updates(self, offset, timeout, limit=100):
        self.calls.append((offset, timeout))
        return self.batches.pop(0) if self.batches else []


def update(update_id, msg):
    return {"update_id": update_id, "message": msg}


def test_command_of():
    assert command_of(message("/yukle@BenimBotum ekstra")) == "/yukle"
    assert command_of(message("/IPTAL")) == "/iptal"
    assert command_of(message("/giriş")) == "/giris"
    assert command_of(message("/Yükle")) == "/yukle"
    assert command_of(message("/yardım")) == "/yardim"
    assert command_of(message("merhaba")) is None
    assert command_of(message(None, photo=[{}])) is None


def test_inbox_filters_strangers_and_commits_offset():
    api = ScriptedAPI(
        [
            [
                update(10, message("/yukle")),
                update(11, message("/yukle", user_id=999)),  # yabancı
                update(12, {**message("/yukle"), "chat": {"id": -100, "type": "group"}}),  # grup
                update(13, message("başlık")),
            ]
        ]
    )
    inbox = Inbox(api, 42)

    async def go():
        await inbox.poll_now()
        got = [inbox.pop_nowait(), inbox.pop_nowait(), inbox.pop_nowait()]
        await inbox.commit()
        return got

    got = asyncio.run(go())
    assert [m["text"] for m in got if m] == ["/yukle", "başlık"]
    assert got[2] is None
    assert api.calls[-1] == (14, 0)  # hepsi onaylandı


def test_inbox_next_times_out():
    api = ScriptedAPI([])
    inbox = Inbox(api, 42)
    assert asyncio.run(inbox.next(timeout=0)) is None


def test_parse_tags():
    assert parse_tags(" MOD, 模组，MOD ,, 游戏 ") == ["MOD", "模组", "游戏"]


def test_load_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " 1:abc \n")
    monkeypatch.setenv("ALLOWED_USER_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_ID", "")
    monkeypatch.setenv("BILI_TAGS", "")
    monkeypatch.setenv("BILI_TID", "")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    settings = load_settings()
    assert settings.bot_token == "1:abc"
    assert settings.bili_tid == 17 and settings.bili_tags == ("MOD", "模组", "游戏")
    assert not settings.mtproto_enabled
    assert settings.step_timeout == 900
    monkeypatch.setenv("ALLOWED_USER_ID", "abc")
    with pytest.raises(ConfigError):
        load_settings()


@pytest.mark.parametrize(
    "updates, expected",
    [
        ([], "false"),
        ([update(1, message("/yukle", user_id=7))], "false"),
        ([update(1, message("/yukle", user_id=7)), update(2, message("/yukle"))], "true"),
    ],
)
def test_check_reports_work(monkeypatch, tmp_path, updates, expected):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "42")
    calls = []

    def fake_get_updates(token, offset=None, limit=100):
        calls.append(offset)
        return updates if offset is None else []

    monkeypatch.setattr(tg_lite, "get_updates", fake_get_updates)
    assert check.main() == 0
    assert output.read_text().strip() == f"has_work={expected}"
    if updates and expected == "false":
        assert calls[-1] == updates[-1]["update_id"] + 1  # yabancı mesajlar atıldı
    if expected == "true":
        assert calls == [None]  # mesajlara dokunulmadı


def test_check_without_secrets_is_quiet(monkeypatch, tmp_path):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_USER_ID", raising=False)
    assert check.main() == 0
    assert output.read_text().strip() == "has_work=false"


def test_check_network_error_is_not_fatal(monkeypatch, tmp_path):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "42")

    def boom(*args, **kwargs):
        raise OSError("ağ yok")

    monkeypatch.setattr(tg_lite, "get_updates", boom)
    assert check.main() == 0
    assert output.read_text().strip() == "has_work=false"

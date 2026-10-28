import asyncio

import httpx

from bot import main
from bot import messages as M
from bot.context import BotContext, Deadline
from tests.fakes import FakeAPI, FakeInbox, make_settings, message


def test_serve_answers_simple_commands_and_exits(tmp_path):
    settings = make_settings(tmp_path)
    api = FakeAPI()
    inbox = FakeInbox([message("/start"), message("/iptal"), message("selam")])

    async def go():
        async with httpx.AsyncClient() as http:
            ctx = BotContext(settings, api, inbox, Deadline(settings.run_budget), http, "")
            await main.serve(ctx)

    asyncio.run(go())
    assert api.sent == [M.HELP, M.NOTHING_TO_CANCEL, M.UNKNOWN]
    assert api.calls == ["setMyCommands"]


def test_serve_survives_unexpected_errors(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    api = FakeAPI()

    async def boom(ctx):
        raise RuntimeError("gizli ayrıntı")

    monkeypatch.setattr(main, "run_status", boom)

    async def go():
        async with httpx.AsyncClient() as http:
            ctx = BotContext(settings, api, FakeInbox([message("/durum"), message("/yardim")]), Deadline(60), http, "")
            await main.serve(ctx)

    asyncio.run(go())
    assert api.sent == [M.UNEXPECTED_ERROR, M.HELP]
    assert not any("gizli" in text for text in api.sent)

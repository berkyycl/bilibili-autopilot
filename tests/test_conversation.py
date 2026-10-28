import asyncio

import httpx

from bot import messages as M
from bot.context import BotContext, Deadline
from bot.conversation import StepContext, UploadRequest, build_steps, run_dialog, summary, video_suffix
from tests.fakes import FakeAPI, FakeInbox, make_settings, message, png_bytes


def run(ctx_messages, tmp_path, files=None, **settings_overrides):
    settings = make_settings(tmp_path, **settings_overrides)
    api = FakeAPI(files=files)
    inbox = FakeInbox(ctx_messages)
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    async def go():
        async with httpx.AsyncClient() as http:
            bot = BotContext(settings, api, inbox, Deadline(settings.run_budget), http, "")
            req = UploadRequest(tid=settings.bili_tid, tags=list(settings.bili_tags))
            ok = await run_dialog(StepContext(bot, session_dir), build_steps(settings), req, reserve=0)
            return ok, req

    ok, req = asyncio.run(go())
    return ok, req, api, inbox


def video_doc(message_id=2, size=500 * 1024 * 1024, name="klip.MP4", mime="video/mp4"):
    return message(
        message_id=message_id,
        document={"file_id": "VID", "file_unique_id": "u", "file_size": size, "file_name": name, "mime_type": mime},
    )


def photo(message_id=5):
    return message(
        message_id=message_id,
        photo=[
            {"file_id": "small", "file_unique_id": "s", "file_size": 1000, "width": 90},
            {"file_id": "big", "file_unique_id": "b", "file_size": 90000, "width": 1280},
        ],
    )


def test_happy_path_collects_everything(tmp_path):
    ok, req, api, _ = run(
        [video_doc(), message("  Harika   mod\nvideosu "), message("/atla"), photo()],
        tmp_path,
        files={"big": png_bytes()},
    )
    assert ok
    assert req.video.file_id == "VID"
    assert req.title == "Harika mod videosu"
    assert req.description == ""
    assert req.cover_path.name == "cover.jpg" and req.cover_path.exists()
    assert api.sent[0] == M.ASK_VIDEO
    assert "Kapak: hazır" in summary(req)


def test_cancel_in_the_middle(tmp_path):
    ok, _, api, _ = run([video_doc(), message("/iptal")], tmp_path)
    assert not ok
    assert api.sent[-1] == M.CANCELLED


def test_invalid_inputs_are_asked_again(tmp_path):
    long_title = "x" * 81
    ok, req, api, _ = run(
        [
            message("merhaba"),  # video değil
            video_doc(),
            message(long_title),  # çok uzun
            message("/yukle"),  # konuşma sırasında başka komut
            message("Başlık"),
            message("Açıklama metni"),
            message("yazı"),  # görsel değil
            photo(),
        ],
        tmp_path,
        files={"big": png_bytes()},
    )
    assert ok
    assert req.title == "Başlık" and req.description == "Açıklama metni"
    assert M.NEED_VIDEO in api.sent
    assert M.TOO_LONG.format(length=81, max=80) in api.sent
    assert M.COMMAND_IN_DIALOG in api.sent
    assert M.NEED_IMAGE in api.sent


def test_unreadable_cover_is_rejected(tmp_path):
    ok, _, api, _ = run(
        [video_doc(), message("T"), message("D"), photo()],
        tmp_path,
        files={"big": b"bu bir resim degil"},
    )
    assert not ok  # mesajlar bitti → zaman aşımı
    assert M.IMAGE_UNREADABLE in api.sent


def test_step_timeout(tmp_path):
    ok, _, api, inbox = run([video_doc()], tmp_path)
    assert not ok
    assert api.sent[-1] == M.STEP_TIMEOUT.format(minutes=15)
    assert inbox.timeouts[-1] == 900.0


def test_big_video_without_mtproto_is_rejected(tmp_path):
    ok, _, api, _ = run([video_doc()], tmp_path, api_id=None, api_hash=None)
    assert not ok
    assert M.NEED_MTPROTO in api.sent


def test_optional_tid_and_tag_steps(tmp_path):
    ok, req, _, _ = run(
        [video_doc(), message("T"), message("D"), photo(), message("171"), message("a, b，c")],
        tmp_path,
        files={"big": png_bytes()},
        ask_tid=True,
        ask_tags=True,
    )
    assert ok
    assert req.tid == 171
    assert req.tags == ["a", "b", "c"]


def test_video_sent_as_video_and_suffix():
    from bot.conversation import extract_video

    media = extract_video(message(video={"file_id": "v", "file_size": 10, "mime_type": "video/quicktime"}))
    assert media is not None and video_suffix(media) == ".mov"
    doc = extract_video(video_doc(name="a.mkv", mime="application/octet-stream"))
    assert doc is not None and video_suffix(doc) == ".mkv"
    assert extract_video(message(document={"file_id": "x", "file_name": "a.pdf", "mime_type": "application/pdf"})) is None


def test_compressed_video_needs_confirmation(tmp_path):
    compressed = message(message_id=2, video={"file_id": "V", "file_unique_id": "u", "file_size": 1000, "mime_type": "video/mp4"})
    ok, req, api, _ = run(
        [compressed, message("/devam"), message("T"), message("/atla"), photo()],
        tmp_path,
        files={"big": png_bytes()},
    )
    assert ok and req.video.file_id == "V" and req.video.kind == "video"
    assert M.COMPRESSED_VIDEO in api.sent
    assert "sıkıştırılmış video" in summary(req)


def test_resending_as_file_replaces_compressed_video(tmp_path):
    compressed = message(message_id=2, video={"file_id": "V", "file_unique_id": "u", "file_size": 1000})
    ok, req, _, _ = run([compressed, video_doc(message_id=3), message("T"), message("/atla"), photo()], tmp_path, files={"big": png_bytes()})
    assert ok and req.video.file_id == "VID" and req.video.kind == "document"
    assert "orijinal kalite" in summary(req)


def test_muted_android_video_counts_as_compressed(tmp_path):
    muted = video_doc()
    muted["animation"] = dict(muted["document"])
    ok, _, api, _ = run([muted], tmp_path)
    assert not ok and M.COMPRESSED_VIDEO in api.sent


def test_commands_are_not_saved_as_title(tmp_path):
    ok, req, api, _ = run(
        [video_doc(), message("/atla"), message("/devam"), message("Gerçek başlık"), message("/atla"), photo()],
        tmp_path,
        files={"big": png_bytes()},
    )
    assert ok and req.title == "Gerçek başlık"
    assert api.sent.count(M.COMMAND_IN_DIALOG) == 2


def test_queued_messages_after_compressed_video_are_not_lost(tmp_path):
    # Kullanıcı bot uyanmadan her şeyi sıraya koymuş, video "video" olarak gitmiş.
    compressed = message(message_id=2, video={"file_id": "V", "file_unique_id": "u", "file_size": 1000})
    ok, req, api, _ = run([compressed, message("Başlık"), message("/atla"), photo()], tmp_path, files={"big": png_bytes()})
    assert ok and req.video.file_id == "V" and req.title == "Başlık" and req.description == ""
    assert M.COMPRESSED_VIDEO in api.sent and M.NEED_VIDEO not in api.sent


def test_devam_is_not_saved_as_tag(tmp_path):
    ok, req, api, _ = run(
        [video_doc(), message("T"), message("/atla"), photo(), message("/devam"), message("/atla")],
        tmp_path,
        files={"big": png_bytes()},
        ask_tags=True,
    )
    assert ok and req.tags == ["MOD"]
    assert M.COMMAND_IN_DIALOG in api.sent

import asyncio
import os
import stat
import sys
import textwrap
import time

import pytest

from bot.biliup import (
    BiliupError,
    build_upload_args,
    explain_failure,
    find_bvid,
    parse_progress,
    redact,
    run_biliup,
    strip_ansi,
)

SUCCESS_LOG = (
    "2026-10-28 10:00:01  INFO biliup::uploader: APP接口投稿成功\n"
    '2026-10-28 10:00:01  INFO biliup: ResponseData { code: 0, data: Some(Object {"aid": Number(1155), '
    '"bvid": String("BV1xx411c7mD")}), message: "0", ttl: Some(1) }\n'
)


def test_parse_progress():
    line = "⠁ [00:01:02] [#####-----] 512.00 MiB/2.00 GiB (8.25 MiB/s, 3m)"
    assert parse_progress(line) == (512 * 1024**2, 2 * 1024**3)
    assert parse_progress("12.00 MiB/s") is None
    assert parse_progress("hiçbir şey") is None


def test_strip_ansi_and_bvid():
    assert strip_ansi("\x1b[32mINFO\x1b[0m ok") == "INFO ok"
    assert find_bvid(SUCCESS_LOG) == "BV1xx411c7mD"
    assert find_bvid("bvid yok") is None


def test_explain_known_and_unknown_errors():
    out = 'Error: Custom("ResponseData { code: 21070, data: None, message: \\"您投稿的频率过快\\", ttl: Some(1) }")'
    err = explain_failure(out, [])
    assert "Çok sık" in err.reason and not err.login_required

    err = explain_failure('{"code":-101,"message":"账号未登录"}', [])
    assert err.login_required

    err = explain_failure("ResponseData { code: 12345, message: \"标题过长\" }", [])
    assert "12345" in err.reason and "标题过长" in err.reason


def test_redact_removes_secrets():
    text = "access_key=abcdef123456&x=1 SESSDATA=zzz9999 token GIZLI-DEGER-123"
    clean = redact(text, ["GIZLI-DEGER-123"])
    assert "abcdef123456" not in clean and "zzz9999" not in clean and "GIZLI-DEGER-123" not in clean


def test_build_upload_args_protects_leading_dash(tmp_path):
    args = build_upload_args(
        video_path=tmp_path / "video.mp4",
        title="-v bir başlık",
        description="satır1\nsatır2",
        tid=17,
        tags=["MOD", "游戏"],
        cover_path=tmp_path / "cover.jpg",
        line="bda2",
    )
    assert args[0] == "upload"
    assert "--title=-v bir başlık" in args
    assert "--desc=satır1\nsatır2" in args
    assert "--tag=MOD,游戏" in args
    assert args[-2:] == ["--", str(tmp_path / "video.mp4")]


def _fake_biliup(tmp_path, body: str):
    script = tmp_path / "fake-biliup"
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_run_biliup_captures_output_and_progress(tmp_path):
    fake = _fake_biliup(
        tmp_path,
        """
        import sys, time
        assert sys.argv[1] == "-u" and sys.argv[3] == "upload"
        assert sys.stderr.isatty()
        for i in (1, 2):
            sys.stderr.write(f"\\r\\x1b[2K[{i}] {i}.00 GiB/2.00 GiB (5 MiB/s)")
            sys.stderr.flush()
            time.sleep(0.05)
        sys.stdout.write('''""" + SUCCESS_LOG.replace("\n", "\\n") + """''')
        """,
    )
    seen = []

    async def on_progress(done, total):
        seen.append((done, total))

    result = asyncio.run(
        run_biliup(fake, tmp_path / "cookies.json", ["upload"], cwd=tmp_path, on_progress=on_progress)
    )
    assert result.returncode == 0
    assert find_bvid(result.output) == "BV1xx411c7mD"
    assert seen[-1] == (2 * 1024**3, 2 * 1024**3)
    assert result.output.count("GiB/2.00") == 1  # yeniden çizilen çubuktan sadece sonuncusu kalır


def test_run_biliup_nonzero_exit(tmp_path):
    fake = _fake_biliup(tmp_path, "import sys\nprint('Error: boom')\nsys.exit(1)\n")
    result = asyncio.run(run_biliup(fake, tmp_path / "c.json", ["renew"], cwd=tmp_path))
    assert result.returncode == 1 and "boom" in result.output


def test_run_biliup_cancel_kills_process(tmp_path):
    marker = tmp_path / "pid"
    fake = _fake_biliup(tmp_path, f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n")

    async def go():
        task = asyncio.create_task(run_biliup(fake, tmp_path / "c.json", ["upload"], cwd=tmp_path))
        for _ in range(100):
            if marker.exists() and marker.read_text():
                break
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    started = time.monotonic()
    asyncio.run(go())
    assert time.monotonic() - started < 15
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_missing_binary_raises_friendly_error(tmp_path):
    with pytest.raises(BiliupError):
        asyncio.run(run_biliup(str(tmp_path / "yok"), tmp_path / "c.json", ["renew"], cwd=tmp_path))

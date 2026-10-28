"""Hızlı kontrol: yetkili kullanıcıdan bekleyen bir mesaj var mı?

Her 5 dakikada bir çalışan workflow'un ilk adımıdır. Sadece standart
kütüphaneyi kullanır; böylece hiçbir bağımlılık kurulmadan birkaç saniyede
biter. Sonucu GitHub Actions çıktısına `has_work=true/false` olarak yazar.

- Yetkili kullanıcıdan mesaj varsa: mesajlara dokunmaz (onları bot.main işler).
- Yoksa: yetkisiz kişilerden gelen mesajları kuyruktan atar ve çıkar.
"""

from __future__ import annotations

import os
import sys
import urllib.error

from bot import tg_lite


def _write_output(has_work: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"has_work={'true' if has_work else 'false'}\n")


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_raw = os.environ.get("ALLOWED_USER_ID", "").strip()
    if not token or not allowed_raw.lstrip("-").isdigit():
        # Kurulum henüz bitmemiş olabilir: her 5 dakikada kırmızı çalışma ve hata
        # e-postası üretmemek için sadece uyarı verip başarılı çıkıyoruz.
        print(
            "::warning::TELEGRAM_BOT_TOKEN ve/veya ALLOWED_USER_ID secret'ı eksik ya da hatalı; "
            "bot çalışmıyor. README'deki kurulum adımlarına bakın."
        )
        _write_output(False)
        return 0
    allowed_user_id = int(allowed_raw)

    try:
        updates = tg_lite.get_updates(token)
    except tg_lite.TgLiteError as exc:
        _write_output(False)
        if exc.code in (401, 404):
            print("Telegram bot token'ı geçersiz görünüyor (TELEGRAM_BOT_TOKEN).")
            return 1
        print(f"Telegram'a ulaşılamadı (kod {exc.code}); bir sonraki çalışmada tekrar denenecek.")
        return 0
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Geçici ağ sorunu: çalışmayı kırmızıya boyayıp her 5 dakikada e-posta
        # yağdırmamak için başarılı çıkıyoruz.
        print(f"Telegram'a ulaşılamadı ({type(exc).__name__}); bir sonraki çalışmada tekrar denenecek.")
        _write_output(False)
        return 0

    has_work = any(tg_lite.is_authorized(u, allowed_user_id) for u in updates)
    if has_work:
        print("Yetkili kullanıcıdan bekleyen mesaj var; bot başlatılıyor.")
    else:
        if updates:
            # Yetkisiz mesajları kuyruktan at (onaylamak = Telegram'dan silinmesi).
            try:
                tg_lite.get_updates(token, offset=updates[-1]["update_id"] + 1, limit=1)
            except Exception as exc:  # önemsiz; bir sonraki çalışmada tekrar denenir
                print(f"Yetkisiz mesajlar temizlenemedi ({type(exc).__name__}).")
        print("Kontrol edildi: bekleyen komut yok.")
    _write_output(has_work)
    return 0


if __name__ == "__main__":
    sys.exit(main())

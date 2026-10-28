"""Bot çalışamadığında kullanıcıya haber verir.

Kurulum adımı başarısız olursa, çalışma zaman aşımına uğrarsa ya da ayarlarda
hata varsa kullanılır. Ayrıca bekleyen mesajları kuyruktan atar; aksi halde
her 5 dakikada bir aynı istek yeniden denenir, yine başarısız olur ve sonsuz
bir döngü oluşurdu. Sadece standart kütüphaneyi kullanır (bağımlılık kurulumu
başarısız olmuş olabilir).
"""

from __future__ import annotations

import os
import sys

from bot import tg_lite

SETUP_FAILED = (
    "⚠️ Bot çalışırken bir sorun oluştu (kurulum adımı başarısız oldu ya da süre doldu). "
    "Son isteğin işlenemedi; birkaç dakika sonra tekrar dene.\n"
    "Sorun sürerse GitHub → Actions sekmesindeki son çalışmaya bak."
)


def notify(text: str) -> bool:
    """Bekleyen mesajları atar ve kullanıcıya `text` mesajını gönderir. Başarılıysa True."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_raw = os.environ.get("ALLOWED_USER_ID", "").strip()
    if not token or not allowed_raw.lstrip("-").isdigit():
        return False
    try:
        updates = tg_lite.get_updates(token)
        if updates:
            tg_lite.get_updates(token, offset=updates[-1]["update_id"] + 1, limit=1)
        tg_lite.call(token, "sendMessage", {"chat_id": int(allowed_raw), "text": text})
    except Exception as exc:
        print(f"Hata bildirimi gönderilemedi ({type(exc).__name__}).")
        return False
    print("Kullanıcı hatadan haberdar edildi.")
    return True


def main() -> int:
    notify(SETUP_FAILED)
    return 0


if __name__ == "__main__":
    sys.exit(main())

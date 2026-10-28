"""Kullanıcıya (Telegram'da) gösterilen tüm metinler ve biçimlendirme yardımcıları.

Metinler tek yerde durur; böylece dil/üslup değişiklikleri kolaydır.
Mesajlar düz metin olarak gönderilir (parse_mode yok), kaçış gerekmez.
"""

from __future__ import annotations

# --- Genel -------------------------------------------------------------------

HELP = (
    "👋 Merhaba! Telefonundaki videoları Bilibili'ye yükleyen botum.\n\n"
    "Komutlar:\n"
    "/yukle – Bilibili'ye video yükle\n"
    "/giris – Bilibili hesabına QR kod ile giriş yap\n"
    "/durum – Bilibili oturumunun durumunu göster\n"
    "/iptal – Devam eden işlemi iptal et\n"
    "/yardim – Bu mesaj\n\n"
    "ℹ️ GitHub Actions üzerinde çalışıyorum ve yaklaşık 5 dakikada bir uyanıyorum. "
    "Bu yüzden komutuna birkaç dakika (bazen daha uzun) gecikmeyle cevap verebilirim; "
    "lütfen aynı komutu tekrar tekrar gönderme."
)
UNKNOWN = "Bunu anlayamadım 🤔 Video yüklemek için /yukle, yardım için /yardim yaz."
NOTHING_TO_CANCEL = "İptal edilecek bir işlem yok."
UNEXPECTED_ERROR = (
    "⚠️ Beklenmeyen bir hata oluştu. Tekrar dene; sorun sürerse GitHub → Actions "
    "sekmesindeki son çalışmaya bak."
)
RUN_ALMOST_OVER = (
    "⏳ Bu çalışmanın süresi dolmak üzere. Lütfen yaklaşık 5 dakika sonra tekrar /yukle yaz."
)
CANCELLED = "❌ İptal edildi."
CANCELLING = "🛑 İptal ediliyor…"
BUSY = "⏳ Şu an bir işlem sürüyor. İptal etmek için /iptal yaz."

# --- Yükleme konuşması ---------------------------------------------------------

ASK_VIDEO = (
    "🎬 Videoyu DOSYA olarak gönder (orijinal kalite için şart):\n"
    "• Android: 📎 → Dosya → Galeri → videoyu seç\n"
    "   (ya da galeride videoyu seçip ⋮ → Sıkıştırmadan gönder)\n"
    "• iPhone: 📎 → videoyu seç → ⋯ → Dosya olarak gönder\n"
    "En fazla 2 GB. İptal için /iptal"
)
ASK_TITLE = "📝 Başlığı yaz (en fazla {max} karakter)."
ASK_DESCRIPTION = "📄 Açıklamayı yaz (en fazla {max} karakter). Açıklama istemiyorsan /atla yaz."
ASK_COVER = "🖼 Kapak görselini gönder (fotoğraf ya da JPG/PNG dosyası)."
ASK_TID = "🗂 Kategori numarasını (tid) yaz. Varsayılanı ({default}) kullanmak için /atla yaz."
ASK_TAGS = (
    "🏷 Etiketleri virgülle ayırarak yaz (en fazla {max_tags} etiket, her biri en fazla "
    "{max_len} karakter). Varsayılanlar için /atla yaz: {default}"
)

NEED_VIDEO = "Bu bir video değil 🙂 Lütfen videoyu dosya olarak gönder."
COMPRESSED_VIDEO = (
    "⚠️ Bu video normal \"video\" olarak gönderilmiş. Telegram uygulaması bu şekilde "
    "gönderilen videoları sıkıştırır (çoğunlukla en fazla 720p–1080p, düşük bit hızı).\n"
    "Orijinal kalite için videoyu DOSYA olarak tekrar gönder.\n"
    "Yine de bu haliyle yüklemek istersen /devam yaz."
)
NEED_MTPROTO = (
    "Bu video 20 MB'tan büyük. Büyük dosyaları indirebilmem için TELEGRAM_API_ID ve "
    "TELEGRAM_API_HASH secret'larının tanımlı olması gerekiyor (README'ye bak)."
)
NOT_ENOUGH_DISK = "Bu video sunucudaki boş alana sığmıyor ({free} boş). Daha küçük bir video dene."
NEED_TEXT = "Lütfen metin olarak yaz."
EMPTY_TEXT = "Bu alan boş olamaz, lütfen bir şey yaz."
TOO_LONG = "Çok uzun: {length} karakter (en fazla {max}). Lütfen kısaltıp tekrar gönder."
NEED_IMAGE = "Lütfen kapak için bir fotoğraf ya da görsel dosyası (JPG/PNG) gönder."
IMAGE_TOO_BIG = "Görsel çok büyük (20 MB üstü). Daha küçük bir görsel gönder."
IMAGE_UNREADABLE = "Bu görseli açamadım. JPG ya da PNG formatında başka bir görsel dene."
IMAGE_DOWNLOAD_FAILED = "Görseli Telegram'dan alamadım, lütfen tekrar gönder."
NEED_TID = "Kategori numarası pozitif bir tam sayı olmalı (ör. 17). Varsayılan için /atla yaz."
BAD_TAGS = "Etiketler geçersiz: en az 1, en fazla {max_tags} etiket; her biri en fazla {max_len} karakter."
COMMAND_IN_DIALOG = (
    "Şu an yükleme bilgilerini topluyorum. İstenen bilgiyi gönder ya da iptal için /iptal yaz."
)
STEP_TIMEOUT = (
    "⏰ {minutes} dakikadır cevap gelmedi; yükleme iptal edildi. "
    "İstediğinde tekrar /yukle yazabilirsin."
)
RUN_BUDGET_EXHAUSTED = (
    "⏰ Bu GitHub çalışmasının süresi dolmak üzere; yükleme iptal edildi. "
    "Birkaç dakika sonra tekrar /yukle yaz."
)

# --- Yükleme aşamaları -----------------------------------------------------------

SUMMARY = (
    "📋 Özet\n"
    "🎬 Video: {size} ({source})\n"
    "📝 Başlık: {title}\n"
    "📄 Açıklama: {description}\n"
    "🖼 Kapak: hazır\n"
    "🗂 Kategori (tid): {tid}\n"
    "🏷 Etiketler: {tags}\n\n"
    "Yükleme başlıyor… İptal için /iptal"
)
SOURCE_ORIGINAL = "dosya olarak, orijinal kalite"
SOURCE_COMPRESSED = "sıkıştırılmış video"
DOWNLOAD_STARTING = "⬇️ Video Telegram'dan indiriliyor…"
UPLOAD_STARTING = "⬆️ Bilibili'ye yükleniyor…"
UPLOAD_SUCCESS = (
    "✅ Video Bilibili'ye yüklendi!\n"
    "🔗 https://www.bilibili.com/video/{bvid}\n"
    "📦 Gönderilen dosya: {size_bytes} bayt (telefonundaki orijinalle karşılaştırabilirsin)\n\n"
    "Not: Video, Bilibili incelemesinden (审核) geçtikten sonra herkese açık olur.\n"
    "Başka video için /yukle yazabilirsin."
)
UPLOAD_SUCCESS_NO_BVID = (
    "✅ Video Bilibili'ye gönderildi, ancak BV numarasını okuyamadım. "
    "Bilibili uygulamasında 投稿管理 (yüklemelerim) bölümünden kontrol edebilirsin."
)
DOWNLOAD_FAILED = "❌ Video Telegram'dan indirilemedi: {reason}\nTekrar denemek için /yukle yaz."
UPLOAD_FAILED = "❌ Bilibili'ye yükleme başarısız: {reason}"
DEADLINE_DURING_OPERATION = (
    "⏰ GitHub çalışma süresi dolduğu için işlem durduruldu. Video çok büyük ya da "
    "bağlantı yavaş olabilir; tekrar dene."
)
COOKIES_SAVE_WARNING = (
    "⚠️ Bilibili oturumu yenilendi ama GitHub'a kaydedilemedi ({reason}). "
    "Bir sonraki yüklemede /giris yapman gerekebilir."
)

# --- Giriş (QR) --------------------------------------------------------------------

LOGIN_REQUIRED = "🔑 Önce Bilibili'ye giriş yapman gerekiyor: /giris yaz."
LOGIN_EXPIRED = "🔑 Bilibili oturumunun süresi dolmuş ya da geçersiz. /giris yapman gerekiyor."
COOKIES_UNREADABLE = (
    "🔑 Kayıtlı Bilibili giriş bilgileri okunamadı (BILIBILI_COOKIES_B64 bozuk). /giris yap."
)
GH_PAT_MISSING = (
    "GH_PAT secret'ı tanımlı değil; giriş bilgilerini GitHub'a kaydedemem. "
    "README'deki GH_PAT adımlarını uygula."
)
GH_PAT_PROBLEM = "GitHub'a erişemiyorum: {reason}"
QR_CAPTION = (
    "📷 Bilibili giriş QR kodu (yaklaşık 3 dakika geçerli)\n\n"
    "1) Bu görsele uzun bas → Galeriye kaydet\n"
    "2) Bilibili uygulamasında tarama (扫一扫) ekranını aç → albüm (相册) simgesine dokun → "
    "bu görseli seç\n"
    "3) Uygulamada girişi onayla (确认登录)\n\n"
    "🔒 Bu kodu kimseyle paylaşma! İptal için /iptal"
)
QR_SCANNED = "📱 QR kod tarandı. Şimdi Bilibili uygulamasında girişi onayla."
QR_EXPIRED = "⌛ QR kodun süresi doldu. Tekrar denemek için /giris yaz."
QR_WAITING = "QR kodun taranmasını bekliyorum. İptal için /iptal yaz."
QR_REQUEST_FAILED = "❌ Bilibili'den QR kod alınamadı: {reason}. Biraz sonra tekrar /giris dene."
LOGIN_FAILED = "❌ Bilibili girişi başarısız: {reason}. Tekrar /giris dene."
LOGIN_SUCCESS = (
    "✅ Bilibili girişi başarılı{account}!\n"
    "Giriş bilgileri GitHub Secret'ına (BILIBILI_COOKIES_B64) şifreli olarak kaydedildi. "
    "Artık /yukle ile video yükleyebilirsin."
)
LOGIN_SAVE_FAILED = "⚠️ Bilibili'ye giriş yapıldı ama bilgiler GitHub'a kaydedilemedi: {reason}"

# --- Durum ve otomatik yenileme --------------------------------------------------

STATUS_VALID = "✅ Bilibili oturumu geçerli{account}.{days}"
STATUS_DAYS = " Erişim anahtarı yaklaşık {days} gün daha geçerli (otomatik yenilenir)."
STATUS_INVALID = "❌ Bilibili oturumu geçersiz ya da süresi dolmuş. /giris yap."
STATUS_UNKNOWN = "❓ Bilibili'ye şu an ulaşılamadı; oturum durumu kontrol edilemedi."
RENEW_EXPIRED = (
    "⚠️ Bilibili oturumunun süresi dolmuş. Video yükleyebilmek için /giris yapman gerekiyor."
)
RENEW_SAVE_FAILED = (
    "⚠️ Bilibili oturumu yenilendi ama GitHub Secret'ına kaydedilemedi: {reason}\n"
    "GH_PAT'ı kontrol et; ardından /giris yapman gerekebilir."
)
RENEW_GITHUB_PROBLEM = (
    "⚠️ Bilibili oturumunu otomatik yenilemem gerekiyor ama GitHub'a erişemiyorum: {reason}"
)


# --- Biçimlendirme yardımcıları ------------------------------------------------------


def human_size(num_bytes: float | None) -> str:
    if not num_bytes:
        return "?"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def exact_bytes(num_bytes: int) -> str:
    """1234567 → '1.234.567' (Türkçe binlik ayırıcı)."""
    return f"{num_bytes:,}".replace(",", ".")


def human_duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} sa {minutes} dk"
    if minutes:
        return f"{minutes} dk {secs} sn"
    return f"{secs} sn"


def progress_line(prefix: str, done: int | None, total: int | None, elapsed: float) -> str:
    """'⬇️ İndiriliyor… %42 (420 MB / 1.0 GB) · ⏱ 1 dk 3 sn' gibi bir satır üretir."""
    parts = [prefix]
    if done is not None and total:
        percent = min(100, int(done * 100 / total))
        parts.append(f"%{percent} ({human_size(done)} / {human_size(total)})")
    parts.append(f"⏱ {human_duration(elapsed)}")
    return " ".join(parts)


def shorten(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"

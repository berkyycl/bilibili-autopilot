# Bilibili Autopilot 🎬 → 📺

Telegram'dan gönderdiğin videoyu, **GitHub Actions sunucusunun interneti** üzerinden Bilibili hesabına yükleyen bot.

Mobil internetin bitse bile Telegram kullanımın kotandan düşmüyorsa (sınırsız Telegram paketi), videoyu sadece Telegram'a gönderirsin; Bilibili'ye yükleme GitHub'ın sunucusundan yapılır. Böylece kotandan yalnızca Telegram'a gönderim gider.

- Sunucu yok, Cloudflare yok, Google Apps Script yok — **her şey GitHub Actions'ta** çalışır.
- Depo **herkese açık (public)** olduğu için Actions dakikaları ücretsiz ve sınırsızdır.
- Tüm kurulum **sadece telefonla** yapılabilir (bilgisayar gerekmez).

---

## İçindekiler

1. [Nasıl çalışır?](#nasıl-çalışır)
2. [Kurulum (telefondan)](#kurulum-telefondan)
3. [Kullanım](#kullanım)
4. [Video kalitesi](#video-kalitesi)
5. [Ayarlar (Variables)](#ayarlar-variables)
6. [Otomatik oturum yenileme](#otomatik-oturum-yenileme)
7. [60 gün kuralı ve keepalive](#60-gün-kuralı-ve-keepalive)
8. [Güvenlik](#güvenlik)
9. [Sık karşılaşılan sorunlar](#sık-karşılaşılan-sorunlar)
10. [Proje yapısı](#proje-yapısı)

---

## Nasıl çalışır?

Telegram, GitHub'ı doğrudan tetikleyemez. Bu yüzden bot **5 dakikada bir kendiliğinden uyanır**:

```
Sen (Telegram)  ──/yukle──▶  Telegram sunucusu  (mesaj burada bekler)
                                     ▲
GitHub Actions (5 dk'da bir) ────────┘ "bekleyen komut var mı?"
   ├─ yoksa  → birkaç saniyede kapanır
   └─ varsa  → uyanık kalır, seninle canlı konuşur:
                video → başlık → açıklama → kapak
                ├─ videoyu Telegram'dan indirir (2 GB'a kadar, MTProto)
                └─ biliup ile Bilibili'ye yükler → sana BV linkini gönderir
```

- **Konuşma** Telegram Bot API ile (long polling) yürütülür.
- **Büyük dosya indirme**: Bot API sadece 20 MB'a kadar indirmeye izin verir. Daha büyük videolar [Kurigram](https://pypi.org/project/kurigram/) (bakımı süren Pyrogram fork'u) ile MTProto üzerinden indirilir (2 GB'a kadar; Telegram Premium ise 4 GB).
- **Bilibili'ye yükleme**: [biliup](https://github.com/biliup/biliup) komut satırı aracı (eski adıyla biliup-rs). Her çalışmada sabit bir sürüm GitHub release'den indirilir ve SHA-256 ile doğrulanır.
- **Bilibili girişi**: `/giris` yazınca QR kodu **sadece sana Telegram'dan** gelir. Giriş bilgileri (çerezler) şifrelenerek GitHub Secret'ına yazılır.

> ⏱ **Gecikme:** GitHub'ın zamanlayıcısı "5 dakikada bir"i garanti etmez; yoğun saatlerde 10–20 dakika gecikebilir. Komutunu gönderdikten sonra bot uyanınca cevap verir. Aynı komutu tekrar tekrar gönderme. Acelen varsa [botu elle uyandırabilirsin](#botu-hemen-uyandırmak).

---

## Kurulum (telefondan)

> 📱 GitHub'ın bazı ayar sayfaları mobil uygulamada yok. Bu adımlarda telefonundaki tarayıcıyı (Chrome/Safari) kullan; sayfa sıkışık görünürse tarayıcı menüsünden **"Masaüstü sitesi"** seçeneğini aç.

Toplam 6 secret ekleyeceksin (biri otomatik oluşur):

| Secret | Ne? | Nereden? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Botunun şifresi | Adım 1 – BotFather |
| `TELEGRAM_API_ID` | Telegram uygulama numarası | Adım 2 – my.telegram.org |
| `TELEGRAM_API_HASH` | Telegram uygulama anahtarı | Adım 2 – my.telegram.org |
| `ALLOWED_USER_ID` | Senin Telegram kullanıcı numaran | Adım 3 |
| `GH_PAT` | Botun GitHub secret'ını güncelleyebilmesi için token | Adım 4 |
| `BILIBILI_COOKIES_B64` | Bilibili giriş bilgileri | **Elle ekleme!** `/giris` otomatik oluşturur |

### Adım 0 – Depo ayarları

1. Deponun **herkese açık (Public)** olduğundan emin ol: depo → **Settings** → en altta *Danger Zone* → *Change visibility*.
2. Actions açık olmalı: depo → **Settings** → **Actions** → **General** → *Allow all actions and reusable workflows* seçili olsun.
3. Aynı sayfada *Fork pull request workflows from outside collaborators* için **"Require approval for all outside collaborators"** seçmeni öneririm (ekstra güvenlik).
4. Kodun **varsayılan (default) dalda** (genelde `main`) olması gerekir. Zamanlanmış workflow'lar **sadece varsayılan dalda** çalışır.

### Adım 1 – Telegram botu oluştur (BotFather)

1. Telegram'da [@BotFather](https://t.me/BotFather)'ı aç → **Başlat**.
2. `/newbot` yaz.
3. Bot için bir isim yaz (ör. `Bilibili Yükleyicim`).
4. Bir kullanıcı adı yaz; sonu `bot` ile bitmeli (ör. `berkay_bili_bot`).
5. BotFather sana `123456789:AA...` gibi bir **token** verir. Bu **`TELEGRAM_BOT_TOKEN`**. Kopyala, kimseyle paylaşma.

> Komut menüsünü (/yukle, /giris…) bot kendisi ayarlar; BotFather'da ek bir şey yapmana gerek yok.

### Adım 2 – API ID ve API HASH (my.telegram.org)

Bunlar 20 MB'tan büyük videoları indirmek için gerekli.

1. Tarayıcıda [my.telegram.org](https://my.telegram.org) adresini aç.
2. Telefon numaranı **uluslararası formatta** yaz (ör. `+905xxxxxxxxx`) → *Next*.
3. Kod **SMS ile değil, Telegram uygulamasına mesaj olarak** gelir. Kodu gir → *Sign In*.
4. **API development tools**'a dokun.
5. Formu doldur:
   - *App title*: `bilibot` (istediğin bir isim)
   - *Short name*: `bilibot2025` (5–32 karakter, sadece harf/rakam)
   - *Platform*: `Android` (ya da `Other`)
   - *URL* ve *Description*: boş bırakabilirsin
6. **Create application** → ekranda görünen:
   - `App api_id` (sadece rakam) → **`TELEGRAM_API_ID`**
   - `App api_hash` (32 karakter) → **`TELEGRAM_API_HASH`**

> ⚠️ "ERROR" uyarısı alırsan: tarayıcıda *Masaüstü sitesi*ni aç, VPN/reklam engelleyiciyi kapat, başka bir tarayıcı dene ya da *App title*/*Short name*'i değiştir. Bu Telegram tarafında bilinen bir sorundur; birkaç denemede genelde geçer.

### Adım 3 – Kendi Telegram kullanıcı ID'ni öğren

1. Telegram'da [@userinfobot](https://t.me/userinfobot)'u aç → **Başlat**.
2. Sana `Id: 123456789` gibi bir sayı gönderir. Bu **`ALLOWED_USER_ID`**.

Bot **sadece bu numaradan** gelen mesajlara cevap verir; başka herkesi tamamen yok sayar.

### Adım 4 – GH_PAT oluştur (en dar yetkiyle)

`/giris` ile aldığın Bilibili çerezini botun GitHub Secret'ına yazabilmesi için gerekli. Sadece **bu depoya** ve sadece **Secrets** iznine sahip bir *fine-grained* token oluşturacağız:

1. Tarayıcıda [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) adresini aç.
   (Ya da: profil fotoğrafı → *Settings* → en altta *Developer settings* → *Personal access tokens* → **Fine-grained tokens** → *Generate new token*.)
2. *Token name*: `bilibili-autopilot`
3. *Expiration*: en uzun seçenek (ör. 1 yıl; varsa *No expiration*). Süresi dolunca bot sana Telegram'dan haber verir; o zaman yenisini oluşturup secret'ı güncellersin.
4. *Resource owner*: kendi hesabın.
5. *Repository access*: **Only select repositories** → sadece `bilibili-autopilot`.
6. *Permissions* → *Repository permissions* → **Secrets** → **Read and write**.
   (*Metadata: Read-only* otomatik eklenir. Başka hiçbir izin verme.)
7. **Generate token** → çıkan `github_pat_...` değerini kopyala. Bu **`GH_PAT`**. (Bir daha gösterilmez.)

> Neden "classic" token değil? Classic token'lar tüm depolarına erişebilir. Fine-grained token sadece bu depoda, sadece secret yazabilir; sızsa bile zarar sınırlı kalır.

### Adım 5 – Secrets ekle

1. Depo → **Settings** → **Secrets and variables** → **Actions** → **Secrets** sekmesi
   (doğrudan: `https://github.com/<kullanıcı-adın>/bilibili-autopilot/settings/secrets/actions`).
2. **New repository secret** ile şu 5 secret'ı tek tek ekle (isimler birebir aynı olmalı):
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`
   - `ALLOWED_USER_ID`
   - `GH_PAT`
3. `BILIBILI_COOKIES_B64`'ü **ekleme**; ilk `/giris`'te bot kendisi oluşturur.

### Adım 6 – (İsteğe bağlı) Variables ekle

Kategori ve etiketleri değiştirmek istersen: aynı sayfada **Variables** sekmesi → *New repository variable*. Hiçbirini eklemezsen varsayılanlar kullanılır. Ayrıntılar: [Ayarlar](#ayarlar-variables).

### Adım 7 – Workflow'ları çalıştır

1. Depo → **Actions** sekmesi. "Workflows aren't being run on this repository" gibi bir uyarı görürsen **"I understand… enable them"** düğmesine bas.
2. Soldan **Bilibili Bot** → **Run workflow** ile bir kez elle çalıştır. Yeşil tik görmelisin (bekleyen komut yoksa birkaç saniyede biter).

### Adım 8 – İlk Bilibili girişi (`/giris`)

1. Telegram'da botuna `/giris` yaz ve bot uyanana kadar bekle (birkaç dakika sürebilir).
2. Bot sana bir **QR kod görseli** gönderir (yaklaşık 3 dakika geçerli).
3. Videoyu yükleyeceğin telefon ile QR'ı göstereceğin telefon aynı olduğu için:
   1. QR görseline **uzun bas → Galeriye kaydet**.
   2. **Bilibili uygulamasını** aç → tarama (**扫一扫**) ekranını aç (tarama simgesi genellikle **我的** sekmesinin sağ üst köşesindedir).
   3. Tarama ekranında **albüm (相册)** simgesine dokun → kaydettiğin QR görselini seç.
   4. Uygulamada girişi **onayla (确认登录)**.
4. Bot "✅ Bilibili girişi başarılı" der. Giriş bilgileri `BILIBILI_COOKIES_B64` secret'ına şifreli olarak kaydedilir; QR mesajı sohbetten silinir.

Artık `/yukle` ile video yükleyebilirsin. 🎉

---

## Kullanım

### Video yükleme

1. Bota `/yukle` yaz.
2. **"Videoyu gönder"** → videoyu **dosya olarak** gönder (2 GB'a kadar). Ayrıntılar için [Video kalitesi](#video-kalitesi) bölümüne bak.
3. **"Başlığı yaz"** → başlığı yaz (en fazla 80 karakter).
4. **"Açıklamayı yaz"** → açıklamayı yaz (en fazla 2000 karakter; istemiyorsan `/atla`).
5. **"Kapak görselini gönder"** → fotoğraf ya da JPG/PNG dosyası gönder.
6. Bot bir **özet** gösterir ve yüklemeye başlar; ilerlemeyi tek bir mesajı güncelleyerek gösterir:
   `⬇️ Video Telegram'dan indiriliyor… %42` → `⬆️ Bilibili'ye yükleniyor… %75`
7. Bitince **Bilibili linkini** (`https://www.bilibili.com/video/BV...`) ve gönderilen dosyanın **tam bayt sayısını** gönderir. Video, Bilibili incelemesinden (审核) geçtikten sonra herkese açık olur.

İpuçları:
- Bot uyanmadan önce videoyu ve bilgileri **sırayla önceden gönderebilirsin** (`/yukle` → video → başlık → açıklama → kapak). Bot uyanınca hepsini sırayla işler.
- Bir yükleme bitince bot **3 dakika daha** yeni komut bekler; arka arkaya video yüklerken tekrar uyanmasını beklemen gerekmez.

### Komutlar

| Komut | Ne yapar? |
|---|---|
| `/yukle` | Video yükleme konuşmasını başlatır |
| `/giris` | Bilibili'ye QR kod ile giriş yapar (ilk kurulumda ve oturum süresi dolunca) |
| `/durum` | Bilibili oturumunun geçerli olup olmadığını ve kalan süreyi gösterir |
| `/iptal` | Her an, devam eden işlemi iptal eder (indirme/yükleme sırasında da) |
| `/atla` | Açıklama adımını boş geçer |
| `/devam` | Sıkıştırılmış ("video" olarak gönderilmiş) videoyu yine de yükler |
| `/yardim` | Yardım mesajı |

- Bir adımda **15 dakika** cevap vermezsen işlem zaman aşımıyla iptal olur ve bot sana haber verir.
- Hata olursa bot anlaşılır bir açıklama gönderir (gerekirse altında Bilibili'nin teknik ayrıntısıyla birlikte; bu ayrıntı **sadece sana** gelir, loglara yazılmaz).

### Botu hemen uyandırmak

GitHub mobil uygulaması (ya da tarayıcı) → depo → **Actions** → **Bilibili Bot** → **Run workflow**. Bot birkaç saniye içinde uyanıp bekleyen komutlarını işler.

---

## Video kalitesi

Bot, Telegram'a gönderdiğin dosyayı **bayt bayt aynen** Bilibili'ye iletir. Hiçbir yerde yeniden kodlama yapılmaz. Telegram'dan inen dosyanın boyutu Telegram'daki boyutla karşılaştırılır; eksik inen bir video asla yüklenmez. Bitince gönderilen dosyanın tam bayt sayısı mesajda yazar; telefonundaki orijinalin boyutuyla karşılaştırabilirsin.

Kaliteyi belirleyen iki yer var:

1. **Telegram'a nasıl gönderdiğin.** Normal "video" olarak gönderirsen Telegram uygulaması videoyu göndermeden önce **sıkıştırır**. iPhone her zaman; Android neredeyse her zaman (en fazla 1080p, çoğunlukla 720p; düşük bit hızı, HDR kaybolur). Orijinal için **dosya olarak** gönder:
   - **Android:** 📎 → **Dosya** → **Galeri** → videoyu seç; ya da galeride videoyu seçip ⋮ → **Sıkıştırmadan gönder**.
   - **iPhone:** 📎 → videoyu seç → ⋯ → **Dosya olarak gönder**. (Ağır çekim videolar yine sıkıştırılabilir.)

   Video normal "video" olarak gelirse bot uyarır. Dosya olarak tekrar gönderebilir ya da `/devam` ile o haliyle yükleyebilirsin.
2. **Bilibili'nin kendisi.** Bilibili yüklenen **her** videoyu kendi sunucusunda yeniden kodlar (转码压制); izleyiciye hiçbir zaman orijinal dosya gitmez. Bu bütün yüklemeler için geçerlidir, telefondan uygulamayla yüklesen bile. 1080P+, 60 fps, 4K ve HDR seçenekleri kaynak destekliyorsa oluşur ve izleyicilerden sadece **大会员** (premium) üyelere gösterilir. Yapılabilecek en iyi şey Bilibili'ye orijinal dosyayı vermektir; bot bunu yapar.

---

## Ayarlar (Variables)

Depo → Settings → Secrets and variables → Actions → **Variables** sekmesinden ayarlanır. Hepsi isteğe bağlıdır.

| Variable | Varsayılan | Açıklama |
|---|---|---|
| `BILI_TID` | `17` | Bilibili kategori numarası (aşağıdaki tabloya bak) |
| `BILI_TAGS` | `MOD,模组,游戏` | Virgülle ayrılmış etiketler (en fazla 12, her biri en fazla 20 karakter) |
| `BILI_ASK_TID` | `false` | `true` yaparsan bot her yüklemede kategoriyi de sorar |
| `BILI_ASK_TAGS` | `false` | `true` yaparsan bot her yüklemede etiketleri de sorar |
| `BILI_WATERMARK` | `false` | `true` yaparsan Bilibili videonun köşesine kullanıcı adı + bilibili logosu filigranını ekler |
| `BILI_LINE` | (otomatik) | Yükleme hattı. Yükleme yavaşsa dene: `bda2`, `bldsa`, `tx`, `txa`, `alia` |
| `STEP_TIMEOUT_MINUTES` | `15` | Bir adımda cevap için beklenecek süre (dakika) |
| `IDLE_LINGER_SECONDS` | `180` | Bir iş bittikten sonra yeni komut için bekleme süresi (saniye; `0` = hemen kapan) |
| `BILIUP_VERSION` | `v1.3.4` | Kullanılacak [biliup release](https://github.com/biliup/biliup/releases) sürümü |
| `BILIUP_SHA256` | (GitHub'dan) | İsteğe bağlı: biliup arşivinin beklenen SHA-256 özeti |

Sık kullanılan oyun kategorileri (`BILI_TID`):

| tid | Kategori |
|---|---|
| `17` | 单机游戏 – Tek oyunculu oyunlar (mod videoları için uygun) |
| `65` | 网络游戏 – Online oyunlar |
| `172` | 手机游戏 – Mobil oyunlar |
| `171` | 电子竞技 – E-spor |
| `136` | 音游 – Ritim oyunları |
| `121` | GMV – Oyun müzik videoları |

---

## Otomatik oturum yenileme

**Bilibili Oturum Yenileme** workflow'u (`renew.yml`) her gün bir kez çalışır:

- Oturum geçerliyse ve erişim anahtarının bitmesine 30 günden fazla varsa hiçbir şey yapmaz.
- Süre yaklaşıyorsa `biliup renew` ile yeniler ve yeni çerezi `BILIBILI_COOKIES_B64` secret'ına yazar.
- Oturum tamamen geçersizse Telegram'dan **"/giris yapman gerekiyor"** mesajı gönderir.

Ayrıca biliup yükleme sırasında oturumu kendiliğinden yenilerse, bot yeni çerezi de otomatik kaydeder. Elle yenilemek için: Actions → *Bilibili Oturum Yenileme* → *Run workflow* → "Süresine bakmadan şimdi yenile".

---

## 60 gün kuralı ve keepalive

GitHub, herkese açık bir depoda **60 gün boyunca hiç commit olmazsa** zamanlanmış workflow'ları otomatik olarak **devre dışı bırakır**. Bot da 5 dakikalık zamanlayıcıyla çalıştığı için durur.

Bunu önlemek için **Keepalive** workflow'u (`keepalive.yml`) her pazartesi çalışır:

1. GitHub API ile depodaki zamanlanmış workflow'ları "etkin" olarak işaretler (sayaç sıfırlanır, commit oluşturmaz).
2. Ek güvence olarak, son commit 45 günden eskiyse `chore: keepalive` adlı **boş bir commit** atar.

Yine de bir gün GitHub'dan "scheduled workflows disabled" e-postası gelirse: Actions → ilgili workflow → **Enable workflow**.

---

## Güvenlik

Depo herkese açık olduğu için şu kurallar uygulanır:

- **Hiçbir gizli bilgi kodda ya da depoda yok.** Token'lar, çerezler, API anahtarları sadece GitHub Secrets'ta durur.
- **Loglar herkese açıktır; bu yüzden loglara sadece genel durum yazılır** ("Kontrol edildi", "Yükleme başarılı"). Secret'lar, çerezler, QR kod, video başlığı/açıklaması, dosya adları ve Telegram mesaj içerikleri **asla** loglanmaz. Hata durumunda bile sadece hata *türü* yazılır. biliup'ın çıktısı (başlık, kullanıcı adı, token içerebilir) bellekte yakalanır, loglara basılmaz. Çalışma sırasında oluşan yeni çerezler ek önlem olarak GitHub'a "maskele" komutuyla da bildirilir.
- **Çerez dosyası** her çalışmada secret'tan geçici olarak (depo dışında, sadece sahibin okuyabileceği izinle) oluşturulur ve iş bitince silinir. MTProto oturumu sadece bellekte tutulur, `.session` dosyası oluşmaz.
- **Bot sadece `ALLOWED_USER_ID`'ye cevap verir**; diğer herkesin mesajlarını okumadan kuyruktan atar.
- **Fork'lardan gelen pull request'ler secret'lara erişemez:** botu çalıştıran workflow'lar sadece zamanlayıcı ve elle çalıştırma ile tetiklenir; `pull_request_target` hiçbir yerde kullanılmaz. Test workflow'u hiçbir secret kullanmaz.
- **Tedarik zinciri:** GitHub Actions adımları commit SHA'sına sabitlenmiştir; biliup belirli bir sürümle indirilip SHA-256 ile doğrulanır; Python paketlerinin sürümleri sabitlenmiştir.
- **GH_PAT** en dar yetkiyle (sadece bu depo, sadece Secrets) oluşturulur.
- `.gitignore`, `cookies.json`, `*.session`, indirilen medya ve geçici dosyaların yanlışlıkla commit'lenmesini engeller.

**Bir bilgi sızdıysa:**
- Bot token'ı: @BotFather → `/revoke` → yeni token'ı `TELEGRAM_BOT_TOKEN` secret'ına yaz.
- GH_PAT: GitHub → Settings → Developer settings → token'ı sil, yenisini oluştur.
- Bilibili çerezi: Bilibili uygulamasının hesap güvenliği ayarlarından diğer oturumları kapat (ya da şifreni değiştir), sonra botta `/giris` yap.
- API ID/HASH: tek başına hesabına erişim sağlamaz (giriş için Telegram'dan gelen kod gerekir). Yine de şüphelenirsen Telegram → Ayarlar → Cihazlar'dan tanımadığın oturumları kapat.

---

## Sık karşılaşılan sorunlar

**Bot hiç cevap vermiyor.**
- Biraz bekle: GitHub zamanlayıcısı 10–20 dk gecikebilir. Ya da [elle uyandır](#botu-hemen-uyandırmak).
- Actions sekmesinde *Bilibili Bot* çalışmaları görünüyor mu? Görünmüyorsa: Actions açık mı (Adım 0/7), kod varsayılan dalda mı, workflow devre dışı mı ([60 gün kuralı](#60-gün-kuralı-ve-keepalive))?
- Çalışmalar kırmızıysa içine bak: "token'ı geçersiz" → `TELEGRAM_BOT_TOKEN`'ı kontrol et.
- `ALLOWED_USER_ID` doğru mu? Bot başka numaralara **hiç** cevap vermez.

**"⚠️ Ayar hatası: …" mesajı geldi.** Mesajda adı geçen secret/variable'ı kontrol et (ör. `TELEGRAM_API_ID` sadece rakam olmalı, `BILI_TID` sayı olmalı).

**"⚠️ Bot çalışırken bir sorun oluştu (kurulum adımı…)" mesajı geldi.** Actions'taki son çalışmada hangi adımın kırmızı olduğuna bak. *biliup kur* adımıysa biliup'ın yeni bir sürümü/dosya adı değişmiş olabilir: `BILIUP_VERSION` variable'ına [release sayfasındaki](https://github.com/biliup/biliup/releases) güncel sürümü (ör. `v1.3.5`) yaz.

**`/giris`: "GH_PAT … izni yok" / "geçersiz ya da süresi dolmuş".** [Adım 4](#adım-4--gh_pat-oluştur-en-dar-yetkiyle)'ü tekrar yap: token sadece bu depoyu seçmeli ve *Secrets: Read and write* izni olmalı. Yeni token'ı `GH_PAT` secret'ına yaz.

**QR kodun süresi doluyor / tarayamıyorum.** QR yaklaşık 3 dakika geçerli. Görsel gelir gelmez galeriye kaydet ve Bilibili uygulamasındaki tarama ekranında **albüm** simgesinden seç. Süre dolarsa tekrar `/giris` yaz.

**"Bu video 20 MB'tan büyük… TELEGRAM_API_ID…"** → `TELEGRAM_API_ID` ve `TELEGRAM_API_HASH` secret'larını ekle ([Adım 2](#adım-2--api-id-ve-api-hash-mytelegramorg)).

**"TELEGRAM_API_ID / TELEGRAM_API_HASH geçersiz".** my.telegram.org'daki değerleri tekrar kopyala; başında/sonunda boşluk olmasın.

**"🔑 Bilibili oturumunun süresi dolmuş…"** → `/giris` yap.

**Bilibili hata kodu 21070 ("Çok sık video yüklendi").** Bilibili'nin yükleme sıklığı sınırı; bir süre bekleyip tekrar dene.

**Bilibili güvenlik kontrolü (风控, -352/-412).** GitHub sunucuları yurt dışında olduğu için Bilibili bazen istekleri geçici olarak engelleyebilir. Bir süre sonra tekrar dene; sürerse Bilibili uygulamasından hesabında bir uyarı olup olmadığına bak.

**Yükleme çok yavaş ya da "süre doldu".** Tek bir çalışma en fazla 120 dakika sürebilir. `BILI_LINE` variable'ıyla farklı bir yükleme hattı dene (ör. `bda2`, `tx`, `alia`).

**Video kalitesi düşük.** Telegram'da videoyu "video" olarak gönderirsen Telegram uygulaması videoyu sıkıştırır. **Dosya** olarak gönder ([Video kalitesi](#video-kalitesi)).

**"Video eksik indirildi (boyut uyuşmuyor)".** Telegram'dan inen dosya beklenenden küçük geldi; bot yarım videoyu yüklemez. `/yukle` ile tekrar dene.

**Videonun köşesinde "kullanıcı adı + bilibili" filigranı var.** Bu filigranı Bilibili ekler. Bot her yüklemede filigranı kapalı ister (`BILI_WATERMARK` ile açılabilir). Yine de görürsen Bilibili uygulamasında 创作中心 (Yaratıcı merkezi) → ayarlar → 水印设置 (filigran ayarı) bölümünden de kapat. Daha önce yüklenmiş videodaki filigran kalıcıdır; kaldırmak için videoyu yeniden yüklemek gerekir.

**Kapak reddedildi.** Yatay (16:9 ya da 16:10), en az 960×600 piksel bir JPG/PNG dene.

---

## Proje yapısı

```
.github/workflows/
  bot.yml          5 dk'da bir: komut kontrolü + konuşma + yükleme
  renew.yml        Günde bir: Bilibili oturumunu kontrol et / yenile
  keepalive.yml    Haftada bir: 60 gün kuralına karşı workflow'ları etkin tut
  tests.yml        Kod değişince testleri çalıştır (secret kullanmaz)
bot/
  check.py         Hızlı kontrol (sadece standart kütüphane, birkaç saniye)
  main.py          Botun ana döngüsü ve komut yönlendirme
  conversation.py  /yukle soruları (adımlar; yeni soru eklemek kolay)
  upload_flow.py   İndirme + yükleme + ilerleme + /iptal
  login_flow.py    /giris (QR) ve /durum
  renew.py         Otomatik oturum yenileme
  downloader.py    Telegram'dan indirme (Bot API ≤20 MB, MTProto >20 MB)
  biliup.py        biliup CLI sarmalayıcı (çıktıyı loglamadan yakalar)
  bili_auth.py     Bilibili QR girişi ve oturum kontrolü
  github_secrets.py  Secret'ı libsodium ile şifreleyip GitHub'a yazma
  telegram.py, inbox.py, tg_lite.py   Telegram istemcileri
  messages.py      Kullanıcıya giden tüm metinler
scripts/install_biliup.sh   biliup'ı indir + SHA-256 doğrula
tests/             Birim ve uçtan uca testler
```

### Geliştirme

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Yeni bir soru eklemek (ör. ileride kategoriyi her seferinde sormak) için `bot/conversation.py` içinde bir `Step` sınıfı yazıp `build_steps()` listesine eklemek yeterli. Kategori (`TidStep`) ve etiket (`TagsStep`) adımları zaten hazır; `BILI_ASK_TID` / `BILI_ASK_TAGS` variable'larıyla açılır.

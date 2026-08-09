# Hesiva

Hesiva, büyükbaş veteriner hekimliği iş akışında kullanılan müşteri hesap, borç ve ödeme takibini modernleştirmek amacıyla geliştirilen offline-first masaüstü uygulamasıdır.

Proje, eski Veresiye 5 uygulamasının yerine geçecek şekilde tasarlanmıştır.

## Neden Hesiva?

Mevcut eski yazılım:

- yalnız eski Windows ortamlarında sağlıklı çalışıyor
- modern işletim sistemlerinde sürdürülebilir değil
- veri taşıma ve yedekleme açısından sınırlı
- uzun vadeli bakım için uygun değil

Hesiva'nın amacı mevcut iş akışını tamamen değiştirmek değil; onu güvenilir, modern ve sürdürülebilir bir masaüstü uygulamasına taşımaktır.

## Temel yaklaşım

Hesiva şu prensiplerle geliştirilmektedir:

- offline-first
- yerel SQLite veritabanı
- cloud bağımlılığı yok
- telemetry yok
- tek bilgisayar kullanımına uygun
- Linux-first
- Windows secondary
- veri bütünlüğü öncelikli
- masaüstü ve klavye odaklı kullanım
- eski programdan geçişi kolaylaştıran tanıdık iş akışı

## Version 1 kapsamı

Hesiva V1 aşağıdaki temel alanları kapsar.

### Müşteriler

- müşteri oluşturma
- düzenleme
- arama
- arşivleme
- arşivden çıkarma
- müşteri bazlı hesap görünümü

### Hesap hareketleri

- borç kaydı
- ödeme kaydı
- serbest metin açıklama
- işlem tarihi
- isteğe bağlı hayvan bağlantısı
- bakiye hesaplama

Finansal hareketler signed integer kuruş olarak saklanır:

- pozitif değer = borç
- negatif değer = ödeme

Bakiye, işlem geçmişinden hesaplanır ve müşteri kaydında ayrı bir alan olarak tutulmaz.

Kullanıcı arayüzünde pozitif bakiye **Borç**, sıfır bakiye nötr `0,00 TL`, negatif bakiye ise
işaretsiz mutlak tutarıyla **Fazla Ödeme** olarak gösterilir. İç hesaplama signed integer kuruş
semantiğini korur.

### İşlem düzeltme politikası

V1'de mevcut finansal işlemler doğrudan düzenlenmez.

Yanlış bir işlem:

1. void / iptal edilir
2. geçmişte korunur
3. aktif bakiyeden çıkarılır
4. gerekiyorsa doğru işlem yeniden oluşturulur

Bu yaklaşım finansal geçmişin sessizce değiştirilmesini önler.

### Hayvanlar

- müşteriye bağlı hayvan kaydı
- küpe numarası
- ad
- tür
- notlar
- arşivleme
- arşivden çıkarma

Hayvan kaydı finansal işlem için zorunlu değildir.

Arşivleme fiziksel silme değildir. Müşteri ve hayvan kayıtları sonradan arşivden çıkarılabilir;
ancak müşteriyi arşivden çıkarmak hayvanlarını otomatik olarak çıkarmaz ve arşivdeki bir müşterinin
hayvanı müşteri aktif edilmeden arşivden çıkarılamaz.

### Hatırlatmalar

- tarih
- not
- tamamlandı durumu
- iptal durumu
- geciken hatırlatmaların görüntülenmesi

### Raporlar ve hesap özeti

- müşteri hesap özeti
- tarih aralığı
- aylık özet
- yıllık özet
- yazdırma / PDF çıktısı

### Backup / Restore

- güvenli yerel yedekleme
- yedekten geri yükleme
- SQLite Online Backup API tabanlı yaklaşım

### Veresiye 5 veri aktarımı

V1, eski Veresiye 5 verilerinin boş bir Hesiva veritabanına aktarılmasını hedefler.

Planlanan aktarım:

- müşteri kartları
- tarihsel hesap hareketleri
- borçlar
- ödemeler
- legacy referans ID'leri

Eski kaynak veri salt okunur olarak açılır ve değiştirilmez.

## V1 dışında kalanlar

Hesiva V1 bilinçli olarak şunları içermez:

- stok yönetimi
- ürün kataloğu
- tıbbi hasta kayıt sistemi
- teşhis / tedavi geçmişi
- aşı yönetimi
- randevu yönetimi
- cloud sync
- çok kullanıcılı sistem
- kullanıcı rolleri
- uzak sunucu
- ERP / CRM özellikleri

## Teknoloji

### Runtime

- Python 3.13+
- PySide6

### Veri katmanı

- SQLite
- SQLAlchemy 2.x
- Alembic

### Güvenlik

- Argon2id parola hashing
- yerel dosya izinleri
- cloud veya telemetry yok

### Test / kalite

- pytest
- Ruff

### Paketleme

- PyInstaller `onedir` paketleme temeli bulunmaktadır
- Linux x86_64 birincil build hedefidir
- Windows x86_64 build'i Windows üzerinde ayrıca doğrulanacaktır

## Mimari

Hesiva katmanlı ve açık bir mimari kullanır:

    UI
    ↓
    Services
    ↓
    Repositories
    ↓
    SQLAlchemy / SQLite

## Temel kurallar

- UI doğrudan SQL çalıştırmaz.
- UI repository kullanmaz.
- Business rules Service katmanındadır.
- Repository yalnız persistence ile ilgilenir.
- Transaction sınırları Service katmanında yönetilir.
- Global mutable Session kullanılmaz.

## Veritabanı

Ana iş nesneleri:

- Customer
- Animal
- Transaction
- Reminder

### Customer

Müşteri bilgileri ve lifecycle alanlarını içerir.

Bakiye alanı içermez.

### Animal

Bir müşteriye bağlıdır.

Küpe numarası global olarak unique değildir.

### Transaction

Finansal gerçeğin ana kaynağıdır.

- `amount_kurus > 0` → borç
- `amount_kurus < 0` → ödeme
- `amount_kurus == 0` → geçersiz

Voided işlemler bakiye hesaplamasına dahil edilmez.

### Reminder

Bir müşteriye bağlı hatırlatma kaydıdır.

Aktif hatırlatma:

- `completed_at IS NULL`
- `cancelled_at IS NULL`

## Uygulama başlangıcı ve veritabanı güvenliği

Hesiva production veritabanını uygulama veri dizininde tutar.

Linux:

- `$XDG_DATA_HOME/hesiva/hesiva.db`
- fallback: `~/.local/share/hesiva/hesiva.db`

Windows:

- `%LOCALAPPDATA%/Hesiva/hesiva.db`

Production schema Alembic ile yönetilir.

Yeni veritabanı:

- geçici dosyada hazırlanır
- migration `head` seviyesine uygulanır
- doğrulanır
- başarıyla tamamlandıktan sonra final konuma yayınlanır

Mevcut eski migration sürümündeki production veritabanı otomatik olarak değiştirilmez.

Backup sistemi devreye alınmadan mevcut kullanıcı verisine otomatik schema upgrade uygulanmaması, geliştirme sürecinde bilinçli bir güvenlik kararıdır.

## UI / UX

Hesiva masaüstü kullanımına göre tasarlanmıştır.

Ana hedefler:

- hızlı müşteri bulma
- borç / ödeme durumunu hemen görme
- minimum tıklama ile işlem kaydetme
- klavye ile rahat kullanım

Temel görsel referans:

`docs/design/V1UIFreeze.pdf`

Bu dosya Hesiva V1 için frozen görsel implementasyon referansıdır.

PDF, projenin eski çalışma adı olan Cari döneminde oluşturulmuştur. Uygulamada görünen ürün adı Hesiva olarak uygulanır.

Ana pencere:

- sol müşteri paneli
- sağ müşteri detay paneli
- Genel
- Hayvanlar
- Hesap Hareketleri
- Hatırlatmalar

1366x768 temel tasarım referansıdır ancak pencere sabit boyutlu değildir.

Uygulama daha büyük masaüstü çözünürlüklerine doğal şekilde genişleyecektir.

## Klavye kullanımı

UI mümkün olduğunca keyboard-friendly tasarlanır.

Genel davranış:

- Tab → sonraki alan
- Shift+Tab → önceki alan
- Enter → güvenli durumlarda kaydet / onayla
- Esc → iptal / kapat

Destructive aksiyonlar Enter'a varsayılan olarak bağlanmaz.

## Geliştirme durumu

Temel V1 iş akışları ve Linux PyInstaller `onedir` paketleme temeli uygulanmıştır. Bu çalışma henüz
nihai V1 yayın ilanı değildir; hedef Linux ortamı/eski donanım ve gerçek Windows build doğrulaması
tamamlanmalıdır.

## Kurulum

Repository'yi klonlayın:

    git clone https://github.com/kayraterlemez/Hesiva.git
    cd hesiva

Sanal ortam oluşturun:

    python3.13 -m venv .venv
    source .venv/bin/activate

Development kurulumu:

    pip install -e ".[dev]"

## Çalıştırma

    python -m hesiva

Kurulum sonrasında console entry point kullanılıyorsa:

    hesiva

Linux'ta Qt ortamına bağlı olarak gerekli sistem paketlerinin kurulu olması gerekebilir.

## Testler

Tüm testleri çalıştırmak için:

    pytest

Lint:

    ruff check .

Format kontrolü:

    ruff format --check .

Linux `onedir` paketi (önce test/lint doğrulaması çalışır):

    scripts/build_linux.sh

Oluşan paketi izole kullanıcı verisiyle doğrulamak için:

    scripts/smoke_packaged_linux.sh

Paketleme, platform sınırlamaları ve yayın kontrol listesi için `docs/12-release.md` dosyasına bakın.

## Proje dokümantasyonu

Detaylı tasarım ve teknik kararlar `docs/` klasöründedir.

- `docs/01-vision.md` — ürün vizyonu
- `docs/02-requirements.md` — gereksinimler
- `docs/03-ui.md` — UI/UX davranışları
- `docs/04-database.md` — veri modeli ve database kuralları
- `docs/05-roadmap.md` — geliştirme yol haritası
- `docs/06-security.md` — güvenlik
- `docs/07-backup.md` — backup / restore
- `docs/08-import.md` — Veresiye 5 import
- `docs/09-architecture.md` — yazılım mimarisi
- `docs/10-coding-style.md` — kod standartları
- `docs/11-testing.md` — test yaklaşımı
- `docs/12-release.md` — paketleme ve yayın hazırlığı
- `docs/design/V1UIFreeze.pdf` — frozen V1 görsel referansı

## Geliştirme prensipleri

Bu projede özellikle şu yaklaşım tercih edilir:

- küçük ve odaklı değişiklikler
- bir milestone = bir commit
- schema değişikliklerinde Alembic
- business rule değişikliklerinde test
- production verisini koruyan davranış
- import sırasında kaynak verinin değiştirilmemesi
- UI'da business logic bulunmaması
- dokümantasyon ile implementasyonun sürekli uyumlu tutulması

## Platform hedefleri

Birincil:

- Linux desktop

İkincil:

- Windows

Hedef donanım düşük kaynaklı eski bilgisayarları da kapsar. Bu nedenle ağır web runtime'ları ve gereksiz servis bağımlılıkları kullanılmaz.

## Lisans

Projenin lisans durumu netleştiğinde burada belirtilecektir.

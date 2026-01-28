# 🛫 Warden "Pre-Flight" Checklists (Definition of Done)

Bu döküman, Warden projesine eklenecek her kod parçası, modül veya özellik için **ZORUNLU** bitiş kriterlerini (DoD) içerir. Tıpkı bir pilotun uçuş öncesi kontrolleri gibi, bu maddelerden biri bile eksikse o özellik "Bitti" **değildir** ve Merge edilemez.

---

## 🏗️ 1. Core Platform (Engine) Checklist
*Core değişiklikleri (Orchestrator, Pipeline, Registry, Rust Bridge) için.*

Hedef: **Stabilite, Genişletilebilirlik, Şeffaflık.**

- [ ] **Extensibility (Open/Closed P.):** Yapılan değişiklik, çekirdek koda dokunmadan (yeni bir dosya/plugin ekleyerek) genişletilebiliyor mu?
    - *Hayır ise: Refactor et. Core, switch-case veya if-else bloklarıyla büyümemeli.*
- [ ] **Agnosticism:** Core motor, spesifik bir dilin (Python, JS) veya kuralın (SQL Injection) detayını biliyor mu?
    - *Evet ise: Soyutla. Core sadece "Rule" ve "ValidationResult" bilmeli.*
- [ ] **Stability & Memory:** 10.000 dosyalık taramada bellek sızıntısı var mı?
    - *Kontrol: `warden scan --memory-profile` ile doğrula.*
- [ ] **Error Isolation:** Bir bileşen çökerse (örn. Thread panic), Core bunu yakalayıp rapora yansıtıyor mu (Graceful Degradation)?
    - *Test: `ChaosFrame` veya `Example Exception` ile kasıtlı hata fırlat.*
- [ ] **Configurability:** Tüm yeni parametreler `.warden/config.yaml` üzerinden yönetilebiliyor mu? (Hardcoded değer YASAK).
- [ ] **Telemetry:** Core'un aldığı her karar (karar ağacı) `structlog` ile yapısal JSON olarak loglanıyor mu?

---

## 🔄 2. Phases (Pipeline Steps) Checklist
*Pipeline adımları (Discovery, Classification, Analysis, vb.) için.*

Hedef: **Idempotency, Veri Bütünlüğü, Hata Toleransı.**

- [ ] **Idempotency:** Bu faz aynı girdiyle 100 kere çalıştırıldığında, bit-bit aynı çıktıyı veriyor mu?
    - *Özellikle LLM kullanan fazlar için Seed/Temperature=0 kontrolü.*
- [ ] **State Integrity:** Fazdan çıkan veri (Context), bir sonraki fazın beklediği şemaya %100 uyuyor mu? (Pydantic validation).
- [ ] **Partial Success:** Faz içindeki 50 dosyadan 1'i hata verirse, diğer 49'u işlenip o 1 hata raporda belirtiliyor mu? Yoksa tüm faz patlıyor mu?
- [ ] **Performance Budget:** Fazın toplam çalışma süresi, belirlenen bütçeyi (örn. Discovery için <2sn) aşıyor mu?
- [ ] **Skip Logic:** Eğer bu fazın çalışmasına gerek yoksa (örn. değişen dosya yok), akıllıca "Skip" edebiliyor mu?

---

## 🧩 3. Frames (Work Units) Checklist
*Bireysel iş birimleri (Security Frame, Orphan Detection, vb.) için.*

Hedef: **Güvenilirlik (Confidence), Düşük Gürültü, Tek Sorumluluk.**

- [ ] **Single Responsibility (SRP):** Bu Frame tek bir işi mi yapıyor?
    - *Örn: Security Frame hem güvenlik hem stil kontrolü yapamaz.*
- [ ] **False Positive Rate (FPR):** 100 dosyalık numune setinde yanlış alarm oranı %5'in altında mı?
    - *Test: `examples/false_positives` seti ile doğrula.*
- [ ] **Performance/Offload:** Bu kontrol Rust tarafında (Regex/Metric) yapılabilir miydi?
    - *Evet ise: Python'da yazma. Rust'a taşı.*
- [ ] **Configuration:** Kullanıcı bu kontrolü ID'si ile disable edebiliyor veya ayarlarını değiştirebiliyor mu?
- [ ] **Error Handling:** Analiz sırasında dosya bozuksa veya yetki yoksa, Frame sessizce hatayı raporlayıp devam ediyor mu?
- [ ] **Explainability:** Üretilen bulgu (Finding) *neden* bulunduğunu ve *nasıl* düzeltileceğini net bir dille (veya kodla) anlatıyor mu?

---

## 📦 4. Release / Merge Checklist
*Kodun main branch'e girmeden önceki son kontrolü.*

- [ ] **Linter/Formatter:** `ruff check` ve `black` (veya eşdeğeri) hatasız geçiyor mu?
- [ ] **Tests:** Tüm birim testleri ve kritik entegrasyon testleri (Happy path + Edge cases) geçiyor mu?
- [ ] **Documentation:** Yeni eklenen özellik `docs/` altında veya ilgili `README.md`'de belgelendi mi?
- [ ] **Dogfooding:** Bu değişikliği önce Warden'ın kendi kod tabanında (`warden scan .`) denedim mi?
- [ ] **No Regression:** Bu değişiklik mevcut çalışan bir özelliği bozuyor mu?

---

> **KAPLAN KURALI:** Eğer yukarıdaki maddelerden **Core** veya **Phase** bölümündekilerden biri bile eksikse, o PR merge edilemez. Frame bölümündeki eksikler "Experimental" etiketiyle (varsayılan kapalı) kabul edilebilir.

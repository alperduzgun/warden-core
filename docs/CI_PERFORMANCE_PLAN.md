# Warden CI Performans İyileştirmesi - Geliştirme Planı

## Versiyon Bilgisi
- **Tarih:** 2026-01-26
- **Versiyon:** 1.0
- **Durum:** Onay Bekliyor

---

## Vizyon

**Mevcut Durum:** CI'da 2-6 saat scan süresi, 6 saat GitHub timeout'a takılıyor

**Hedef:** PR scan'leri 3-10 dakika, context-aware analiz kalitesi korunarak

---

## Temel Konsept: Static Intelligence

Proje bilgisi bir kez çıkarılır, repo'da saklanır, CI her seferinde okur.

```
INIT (1 kez)          →    REPO'DA SAKLA    →    CI (her PR)
Projeyi anla               Intelligence          Oku ve kullan
Modülleri haritalandır     dosyaları             Yeniden keşfetme
```

---

## Faz Geçiş Kuralı

```
┌─────────────┐     Doğrulama      ┌─────────────┐
│   FAZ N     │ ──────────────────▶│  FAZ N+1    │
└─────────────┘     Geçti ✅       └─────────────┘
                        │
                   Geçmedi ❌
                        │
                        ▼
               Geri dön, düzelt
```

**Her faz sonunda:**
1. Doğrulama adımlarını çalıştır
2. Tümü geçerse → sonraki faza ilerle
3. Biri bile geçmezse → düzelt, tekrar doğrula

---

# Faz 1: Intelligence Altyapısı

## 1.1 Intelligence Modeli Tasarımı

### Amaç
Proje hakkında ne bilmemiz gerektiğini tanımla

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `ProjectContext` | `src/warden/analysis/domain/project_context.py` | Genişletilecek: module_map, security_posture ekle |
| `FileContext` | `src/warden/analysis/domain/file_context.py` | Mevcut, yeterli |
| `PreAnalysisResult` | `src/warden/analysis/domain/file_context.py` | Mevcut, intelligence export için kullanılacak |

### Yapılacaklar
- ProjectContext'e module_map ve security_posture ekle
- ModuleInfo, SecurityPosture modelleri oluştur
- Intelligence export şeması tanımla

### Çıktılar
```
src/warden/analysis/domain/intelligence.py  # Yeni
src/warden/analysis/domain/project_context.py  # Güncellendi
```

### ✅ Doğrulama 1.1

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Model import edilebilir | `from warden.analysis.domain.intelligence import ModuleInfo, SecurityPosture` | Import hatası yok |
| 2 | ProjectContext genişletildi | `ProjectContext()` oluştur, `module_map` attribute var mı | AttributeError yok |
| 3 | Serialization çalışıyor | `ModuleInfo(...).model_dump_json()` | Valid JSON çıktısı |
| 4 | Örnek veri oluşturulabiliyor | 3 modüllü örnek intelligence oluştur | Hatasız oluştu |

**Geçiş Kriteri:** 4/4 başarılı

---

## 1.2 Intelligence Üretici Geliştirmesi

### Amaç
Init sırasında intelligence dosyalarını oluştur

### Mevcut Yapılar

| Yapı | Dosya | Durum |
|------|-------|-------|
| `ProjectPurposeDetector` | `src/warden/analysis/application/project_purpose_detector.py` | ✅ Mevcut, prompt güncellenecek |
| `ProjectStructureAnalyzer` | `src/warden/analysis/application/project_structure_analyzer.py` | ✅ Mevcut, olduğu gibi kullanılacak |
| `DependencyGraph` | `src/warden/analysis/application/dependency_graph.py` | ✅ Mevcut, AST ilişkileri için |
| `MemoryManager` | `src/warden/memory/application/memory_manager.py` | ✅ Mevcut, module_map storage eklenecek |
| `PreAnalysisPhase` | `src/warden/analysis/application/pre_analysis_phase.py` | ✅ Mevcut, intelligence export eklenecek |

### Yapılacaklar
1. ProjectPurposeDetector prompt'unu güncelle (risk_level, security_focus)
2. MemoryManager'a module_map storage ekle
3. PreAnalysisPhase'de intelligence export ekle
4. AST ilişki grafiği export

### Çıktılar
```
.warden/intelligence/
  ├── project.json
  ├── modules.json
  ├── exceptions.json
  └── relations.json
```

### ✅ Doğrulama 1.2

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | LLM yeni format dönüyor | Detector'ı test projede çalıştır | risk_level, security_focus içeren JSON |
| 2 | Module map kaydediliyor | `memory_manager.get_module_map()` çağır | Dolu dict dönüyor |
| 3 | Intelligence dosyaları oluşuyor | Test projede PreAnalysisPhase çalıştır | 4 dosya .warden/intelligence/ altında |
| 4 | Relations doğru | İki ilişkili dosya (A imports B) | relations.json'da A→B ilişkisi var |
| 5 | Kritik dosya exception | utils/crypto.py olan proje | exceptions.json'da crypto.py P0 olarak |

**Geçiş Kriteri:** 5/5 başarılı

**Smoke Test:**
```bash
# Warden'ın kendi repo'sunda çalıştır
cd warden-core
python -c "
from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase
# ... intelligence üret ve dosyaları kontrol et
"
ls -la .warden/intelligence/
```

---

## 1.3 Intelligence Okuyucu Geliştirmesi

### Amaç
Scan sırasında intelligence'ı yükle ve kullan

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `BaselineManager` | `src/warden/cli/commands/helpers/baseline_manager.py` | Pattern olarak kullanılacak |
| `MemoryManager._enrich_context_from_memory()` | `memory_manager.py` | Pattern olarak |

### Yapılacaklar
- IntelligenceLoader sınıfı oluştur
- Load, lookup, cache mekanizmaları

### Çıktılar
```
src/warden/cli/commands/helpers/intelligence_loader.py  # Yeni
```

### ✅ Doğrulama 1.3

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Loader dosya okuyor | `IntelligenceLoader(".warden/intelligence").load()` | IntelligenceModel dönüyor |
| 2 | Module lookup çalışıyor | `loader.get_module_for_file("src/auth/jwt.py")` | "auth" modülü, P0 risk |
| 3 | Exception override çalışıyor | `loader.get_risk_for_file("utils/crypto.py")` | P0 (utils P3 olmasına rağmen) |
| 4 | Missing file handling | `loader.get_module_for_file("yeni/dosya.py")` | P1_HIGH default, warning log |
| 5 | Cache çalışıyor | Aynı dosyayı 2 kez sorgula | İkinci çağrı daha hızlı |

**Geçiş Kriteri:** 5/5 başarılı

---

## 🚧 Faz 1 Final Doğrulaması

**End-to-End Test:**
```
1. Boş bir test proje oluştur (auth/, payments/, utils/ klasörleri)
2. warden init çalıştır (henüz entegre değilse manuel tetikle)
3. .warden/intelligence/ dosyalarını kontrol et
4. IntelligenceLoader ile dosyaları oku
5. Her dosya için doğru modül ve risk dönüyor mu?
```

| # | Kontrol | Beklenen |
|---|---------|----------|
| 1 | project.json var | ✅ |
| 2 | modules.json'da 3 modül | auth(P0), payments(P0), utils(P3) |
| 3 | auth/login.py sorgusu | module=auth, risk=P0 |
| 4 | utils/helpers.py sorgusu | module=utils, risk=P3 |
| 5 | utils/crypto.py sorgusu | module=utils, risk=P0 (exception) |
| 6 | new_folder/file.py sorgusu | module=unknown, risk=P1 (default) |

**Faz 1 Geçiş Kriteri:** 6/6 başarılı → Faz 2'ye geç

---

# Faz 2: Güvenlik Katmanları (Safeguards)

## 2.1 Freshness Kontrolü

### Amaç
Eski intelligence ile yanlış karar vermeyi engelle

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `MemoryManager._validate_environment_hash()` | `memory_manager.py` | Pattern olarak kullanılacak |
| `BaselineManager.is_outdated()` | `baseline_manager.py` | Pattern olarak kullanılacak |
| `GitHelper` | `src/warden/cli/commands/helpers/git_helper.py` | Son commit tarihi için |

### Yapılacaklar
- Intelligence yaş kontrolü
- Yeni dosya tespiti
- Warning mekanizması

### ✅ Doğrulama 2.1

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Yaş hesaplanıyor | 7 günlük intelligence dosyası | `age_days=7` |
| 2 | Yeni dosya tespiti | Intelligence'dan sonra dosya ekle | "X new files not in intelligence" |
| 3 | Warning üretiliyor | 7+ günlük intelligence | Warning log çıktısı |
| 4 | Taze intelligence OK | 1 günlük intelligence | Warning yok |

**Geçiş Kriteri:** 4/4 başarılı

---

## 2.2 Unknown Module Handler

### Amaç
Intelligence'da olmayan yeni modülleri güvenli handle et

### Yapılacaklar
- Module lookup miss → P1_HIGH default
- Warning üret

### ✅ Doğrulama 2.2

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Unknown module P1 | Yeni klasör ekle, sorgula | risk=P1_HIGH |
| 2 | Warning üretiliyor | Yeni klasör sorgula | "Unknown module, defaulting to P1" |
| 3 | Known module etkilenmedi | Bilinen modül sorgula | Doğru risk level |

**Geçiş Kriteri:** 3/3 başarılı

---

## 2.3 Critical Keyword Override

### Amaç
Yanlış sınıflandırılmış kritik dosyaları yakala

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `CRITICALITY_MAP` | `pre_analysis_phase.py` | Genişletilecek |
| `_is_file_critical()` | `pre_analysis_phase.py` | Mevcut, keyword logic eklenecek |

### Yapılacaklar
- Keyword listesi tanımla
- Override logic ekle

### Keyword Listesi
```python
CRITICAL_KEYWORDS = {
    "P0": ["crypto", "encrypt", "decrypt", "secret", "credential",
           "password", "token", "jwt", "oauth", "payment", "billing",
           "charge", "stripe", "paypal", "bank"],
    "P1": ["auth", "login", "session", "permission", "role", "admin",
           "user", "account", "profile", "pii", "gdpr"]
}
```

### ✅ Doğrulama 2.3

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | crypto keyword | utils/crypto.py (utils P3) | risk=P0 override |
| 2 | auth keyword | helpers/auth_utils.py (helpers P3) | risk=P1 override |
| 3 | payment keyword | lib/payment_processor.py | risk=P0 override |
| 4 | Normal dosya etkilenmedi | utils/formatters.py | risk=P3 (inherit) |
| 5 | Config'den özelleştirilebilir | Custom keyword ekle | Override çalışıyor |

**Geçiş Kriteri:** 5/5 başarılı

---

## 2.4 Test Dosyası Filtreleme

### Amaç
Test dosyalarını production gibi taramayı engelle

### Yapılacaklar
- Test file detection logic
- Otomatik P3_LOW assignment

### Test Dosyası Tespit Kuralları
- Dosya adı: `test_*`, `*_test.py`, `*.spec.ts`, `*.test.js`
- Klasör: `tests/`, `__tests__/`, `spec/`, `test/`
- İçerik: pytest, unittest, jest, mocha import'ları

### ✅ Doğrulama 2.4

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | test_ prefix | test_payment.py | is_test=True, risk=P3 |
| 2 | _test suffix | payment_test.py | is_test=True, risk=P3 |
| 3 | tests/ klasörü | tests/test_auth.py | is_test=True, risk=P3 |
| 4 | spec dosyası | auth.spec.ts | is_test=True, risk=P3 |
| 5 | Production etkilenmedi | src/auth/login.py | is_test=False, risk=inherit |

**Geçiş Kriteri:** 5/5 başarılı

---

## 2.5 LLM Output Validasyonu

### Amaç
LLM hallucination'larını tespit et

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `DependencyGraph` | `dependency_graph.py` | Import analizi için |
| `ASTProviderRegistry` | `src/warden/ast/application/provider_registry.py` | AST parsing için |

### Yapılacaklar
- LLM claim extraction
- AST cross-validation
- Unverified flag

### ✅ Doğrulama 2.5

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Verified claim | LLM "uses FastAPI" + fastapi import var | verified=True |
| 2 | Unverified claim | LLM "uses OAuth" + oauth import yok | verified=False, warning |
| 3 | Partial verification | 3 claim, 2 doğru | verified_ratio=0.66 |

**Geçiş Kriteri:** 3/3 başarılı

---

## 2.6 Cross-Module İlişki Kontrolü

### Amaç
Modüller arası güvenlik açıklarını yakala

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `DependencyGraph` | `dependency_graph.py` | Modüller arası ilişkiler |

### Yapılacaklar
- Cross-module rules config
- Validation logic

### Örnek Config
```yaml
cross_module_rules:
  - if_module: payments
    must_import: [auth, validation]
  - if_module: admin
    must_import: [auth, permissions]
```

### ✅ Doğrulama 2.6

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Rule tanımlanabiliyor | Config'e payments→auth rule ekle | Parse ediliyor |
| 2 | Violation tespit | payments/ dosyası auth import etmiyor | Warning üretiliyor |
| 3 | Compliance OK | payments/ dosyası auth import ediyor | Warning yok |

**Geçiş Kriteri:** 3/3 başarılı

---

## 🚧 Faz 2 Final Doğrulaması

**Safeguard Integration Test:**
```
1. Faz 1'deki test projeyi kullan
2. Intelligence'ı 10 gün önceki tarihle oluştur
3. Yeni bir modül ekle (notifications/)
4. utils/secret_handler.py ekle
5. tests/test_auth.py ekle
6. Scan çalıştır
```

| # | Kontrol | Beklenen |
|---|---------|----------|
| 1 | Freshness warning | "Intelligence is 10 days old" |
| 2 | Unknown module handling | notifications/ → P1_HIGH |
| 3 | Keyword override | secret_handler.py → P0 |
| 4 | Test filtering | test_auth.py → P3, LLM skip |
| 5 | Tüm warning'ler loglandı | Structured log output |

**Faz 2 Geçiş Kriteri:** 5/5 başarılı → Faz 3'e geç

---

# Faz 3: CI Entegrasyonu

## 3.1 CI Modu Geliştirmesi

### Amaç
CI ortamı için optimize edilmiş scan modu

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `scan.py` | `src/warden/cli/commands/scan.py` | Ana scan komutu |
| `--diff` flag | `scan.py` | ✅ Zaten mevcut! |
| `--base` flag | `scan.py` | ✅ Zaten mevcut! |
| `GitHelper.get_changed_files()` | `git_helper.py` | ✅ Diff detection mevcut |
| `BaselineManager` | `baseline_manager.py` | ✅ Baseline okuma mevcut |

### Yapılacaklar
- `--ci` flag ekle
- Read-only mod
- Intelligence entegrasyonu

### ✅ Doğrulama 3.1

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | --ci flag çalışıyor | `warden scan --ci` | Hata yok |
| 2 | Read-only mod | CI modda memory write | Yazma yok |
| 3 | Intelligence yükleniyor | CI modda scan | Intelligence context kullanılıyor |
| 4 | Diff entegrasyonu | `--ci --diff` | Sadece değişen dosyalar |
| 5 | Çıktı formatı | CI modda scan | CI-friendly output (SARIF) |

**Geçiş Kriteri:** 5/5 başarılı

---

## 3.2 Adaptive Strateji

### Amaç
Kaynak ve rate limit durumuna göre strateji belirle

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `OrchestratedLlmClient` | `src/warden/llm/providers/orchestrated.py` | ✅ Tiered execution mevcut |
| `LLMMetricsCollector` | `src/warden/llm/metrics.py` | ✅ Rate limit tracking |
| `@resilient` decorator | `src/warden/shared/infrastructure/resilience.py` | ✅ Circuit breaker mevcut |

### Yapılacaklar
- Rate limit detection
- Strategy selector
- Graceful degradation

### Strateji Tablosu

| Durum | Strateji |
|-------|----------|
| Groq OK, <20 kritik dosya | Full LLM |
| Groq OK, >20 kritik dosya | Top 20 LLM, geri kalan Rust |
| Groq limited, <10 kritik | Ollama fallback |
| Groq limited, >10 kritik | P0 only LLM, P1+ Rust |

### ✅ Doğrulama 3.2

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Rate limit tespit | Groq 429 response simüle et | is_rate_limited=True |
| 2 | Strateji değişiyor | Rate limited durumda | P0_ONLY stratejisine geç |
| 3 | Fallback çalışıyor | Groq fail | Ollama'ya düş |
| 4 | Normal mod | Groq OK | Full LLM stratejisi |

**Geçiş Kriteri:** 4/4 başarılı

---

## 3.3 Budget Limiter

### Amaç
LLM maliyetini kontrol altında tut

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `LLMMetricsCollector` | `metrics.py` | Call counting mevcut |
| Config yapısı | `.warden/config.yaml` | Budget config eklenecek |

### Yapılacaklar
- Budget config
- Call limiting
- Priority ordering

### Config Örneği
```yaml
ci:
  max_llm_calls_per_pr: 20
  max_llm_calls_nightly: 200
  priority_order: [P0, P1, P2, P3]
```

### ✅ Doğrulama 3.3

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Config okunuyor | max_llm_calls_per_pr: 10 | Limit 10 |
| 2 | Limit uygulanıyor | 15 kritik dosya, limit 10 | 10 LLM call, 5 Rust-only |
| 3 | Öncelik sırası | P0, P1, P2 dosyalar | P0 önce, P2 skip |
| 4 | Warning üretiliyor | Limit aşıldığında | "Budget reached, X files skipped" |

**Geçiş Kriteri:** 4/4 başarılı

---

## 🚧 Faz 3 Final Doğrulaması

**CI Simulation Test:**
```
1. Test projede 30 dosya değiştir (10 P0, 10 P1, 10 P2)
2. Budget limit: 15
3. Groq rate limit simüle et
4. warden scan --ci --diff çalıştır
```

| # | Kontrol | Beklenen |
|---|---------|----------|
| 1 | Sadece 30 dosya tarandı | Tüm proje değil |
| 2 | 15 LLM call yapıldı | Budget respected |
| 3 | P0 dosyaların hepsi LLM | 10/10 P0 → LLM |
| 4 | P1'den 5 tanesi LLM | Kalan budget |
| 5 | P2 hepsi Rust-only | Budget bitti |
| 6 | Rate limit handling | Ollama fallback veya P0_ONLY |
| 7 | Toplam süre | <10 dakika |

**Faz 3 Geçiş Kriteri:** 7/7 başarılı → Faz 4'e geç

---

# Faz 4: Baseline Yönetimi

## 4.1 Modül Bazlı Baseline

### Amaç
Her modül için ayrı baseline takibi

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `BaselineManager` | `baseline_manager.py` | ✅ Mevcut, genişletilecek |
| `get_fingerprints()` | `baseline_manager.py` | ✅ Bulgu fingerprint'leri |

### Yapılacaklar
- Modül bazlı dosya yapısı
- Per-module fingerprints
- Migration (eski baseline → yeni format)

### Yeni Yapı
```
.warden/baseline/
  ├── _meta.json
  ├── auth.json
  ├── payments.json
  └── users.json
```

### ✅ Doğrulama 4.1

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Modül dosyaları oluşuyor | Baseline oluştur | auth.json, payments.json, utils.json |
| 2 | Fingerprint doğru | auth/ bulgusu | auth.json'da fingerprint var |
| 3 | Cross-module ayrım | auth ve payments bulgusu | Ayrı dosyalarda |
| 4 | Migration çalışıyor | Eski baseline.json var | Yeni formata dönüştü |
| 5 | Meta dosyası | Baseline oluştur | _meta.json var, timestamp doğru |

**Geçiş Kriteri:** 5/5 başarılı

---

## 4.2 Baseline Güncelleme Stratejisi

### Amaç
Doğru zamanda baseline güncelle

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `_create_baseline_async()` | `init.py` | ✅ Baseline oluşturma mevcut |
| `generate-baseline.yml` | `.github/workflows/` | ✅ Nightly workflow mevcut |

### Yapılacaklar
- `--update-baseline` flag
- Main merge trigger
- Selective update

### Güncelleme Kuralları

| Durum | Baseline Güncellensin mi? |
|-------|---------------------------|
| PR scan | ❌ Hayır (read-only) |
| Main merge | ✅ Evet |
| Nightly | ✅ Evet |
| Manuel | ✅ Evet (`--update-baseline`) |

### ✅ Doğrulama 4.2

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Flag çalışıyor | `warden scan --update-baseline` | Baseline güncellendi |
| 2 | PR'da güncelleme yok | `warden scan --ci` (PR) | Baseline değişmedi |
| 3 | Selective update | Sadece auth/ değişti | Sadece auth.json güncellendi |
| 4 | Nightly workflow | Workflow çalıştır | Tüm modüller güncellendi |

**Geçiş Kriteri:** 4/4 başarılı

---

## 4.3 Debt Tracking

### Amaç
Çözülmemiş bulguları takip et

### Yapılacaklar
- Debt age hesaplama
- Debt warning threshold
- Debt report

### Debt Yapısı
```json
{
  "module": "users",
  "findings": [...],
  "debt_count": 3,
  "oldest_debt_age_days": 14,
  "last_scan": "2024-01-20"
}
```

### Debt Thresholds

| Yaş | Aksiyon |
|-----|---------|
| 7 gün | PR'da uyarı |
| 14 gün | PR'da dikkat çekici uyarı |
| 30 gün | Block (opsiyonel) |

### ✅ Doğrulama 4.3

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Debt age hesaplanıyor | 7 günlük bulgu | debt_age_days=7 |
| 2 | Warning threshold | 14+ gün | Warning üretiliyor |
| 3 | Debt report | `warden baseline debt` | Modül bazlı debt listesi |
| 4 | Debt azalıyor | Bulgu fix'lendi | debt_count düştü |

**Geçiş Kriteri:** 4/4 başarılı

---

## 🚧 Faz 4 Final Doğrulaması

**Baseline Lifecycle Test:**
```
1. Test projede init → baseline oluştur
2. auth/'a yeni bulgu ekle (kod değiştir)
3. PR scan → baseline değişmemeli
4. Main merge simüle et → baseline güncellenmeli
5. 7 gün bekle (veya tarih manipüle et)
6. Tekrar scan → debt warning görmeli
```

| # | Kontrol | Beklenen |
|---|---------|----------|
| 1 | Initial baseline | 3 modül dosyası |
| 2 | PR scan | Baseline unchanged |
| 3 | Yeni bulgu tespit | "New finding in auth/" |
| 4 | Main merge update | auth.json güncellendi |
| 5 | Debt tracking | debt_age tracking başladı |
| 6 | Debt warning | 7+ gün sonra warning |

**Faz 4 Geçiş Kriteri:** 6/6 başarılı → Faz 5'e geç

---

# Faz 5: Kullanıcı Deneyimi

## 5.1 Init Akışı Güncellemesi

### Amaç
Init'te intelligence ve baseline oluştur

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `init_command()` | `src/warden/cli/commands/init.py` | Ana init komutu |
| `_create_baseline_async()` | `init.py` | ✅ Baseline oluşturma mevcut |

### Yapılacaklar
- Intelligence generation step
- Progress feedback
- Error handling

### Yeni Init Akışı
```
warden init
  → config oluştur
  → proje analizi (LLM)
  → modül mapping (LLM)
  → AST ilişki grafiği
  → intelligence kaydet
  → baseline oluştur
  → bitti
```

### ✅ Doğrulama 5.1

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Intelligence oluşuyor | `warden init` | .warden/intelligence/ var |
| 2 | Baseline oluşuyor | `warden init` | .warden/baseline/ var |
| 3 | Progress gösteriliyor | Init çalıştır | Step by step progress |
| 4 | Hata durumu | LLM fail | Graceful error, partial success |
| 5 | Süre makul | Normal proje | <10 dakika |

**Geçiş Kriteri:** 5/5 başarılı

---

## 5.2 Refresh Komutu

### Amaç
Intelligence'ı manuel güncelle

### Yapılacaklar
- `warden refresh` komutu
- `--module` flag
- `--quick` flag

### Kullanım
```bash
warden refresh              # Tam güncelleme
warden refresh --module auth  # Sadece auth modülü
warden refresh --quick      # Sadece yeni dosyalar
```

### ✅ Doğrulama 5.2

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Full refresh | `warden refresh` | Tüm intelligence güncellendi |
| 2 | Module refresh | `warden refresh --module auth` | Sadece auth güncellendi |
| 3 | Quick refresh | `warden refresh --quick` | Sadece yeni dosyalar |
| 4 | Idempotent | 2 kez çalıştır | Aynı sonuç |

**Geçiş Kriteri:** 4/4 başarılı

---

## 5.3 CI Workflow Şablonları

### Amaç
Kolay CI kurulumu

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| CI workflow generation | `init.py` | ✅ Mevcut template |
| `github_actions.py` | `src/warden/infrastructure/ci/` | CI helper'lar |

### Yapılacaklar
- PR workflow template
- Nightly workflow template
- Release workflow template

### Workflow Dosyaları
```
.github/workflows/
  ├── warden-pr.yml       # --ci --diff
  ├── warden-nightly.yml  # --update-baseline
  └── warden-release.yml  # --strict
```

### ✅ Doğrulama 5.3

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | PR workflow | `warden init --ci` | warden-pr.yml oluştu |
| 2 | Nightly workflow | `warden init --ci` | warden-nightly.yml oluştu |
| 3 | Workflow syntax | GitHub Actions lint | Valid YAML |
| 4 | PR workflow doğru flag | İçeriği kontrol et | --ci --diff var |
| 5 | Nightly workflow doğru flag | İçeriği kontrol et | --update-baseline var |

**Geçiş Kriteri:** 5/5 başarılı

---

## 🚧 Faz 5 Final Doğrulaması

**Full User Journey Test:**
```
1. Yeni proje oluştur (gerçekçi yapı)
2. warden init çalıştır
3. PR aç, değişiklik yap
4. warden scan --ci --diff çalıştır
5. Main'e merge et
6. warden refresh çalıştır
7. CI workflow'ları kontrol et
```

| # | Kontrol | Beklenen |
|---|---------|----------|
| 1 | Init tamamlandı | Intelligence + Baseline oluştu |
| 2 | Init süresi | <10 dakika |
| 3 | PR scan çalıştı | Değişen dosyalar tarandı |
| 4 | PR scan süresi | <5 dakika |
| 5 | Context doğru | LLM doğru modül bilgisi aldı |
| 6 | Refresh çalıştı | Intelligence güncellendi |
| 7 | CI workflows valid | GitHub'da çalışabilir |

**Faz 5 Geçiş Kriteri:** 7/7 başarılı → Faz 6'ya geç

---

# Faz 6: Monitoring ve Feedback

## 6.1 Scan Metrikleri

### Amaç
Performans ve kaliteyi ölç

### Mevcut Yapılar

| Yapı | Dosya | Kullanım |
|------|-------|----------|
| `LLMMetricsCollector` | `src/warden/llm/metrics.py` | ✅ LLM metrikleri mevcut |
| `_cost_analysis()` | `metrics.py` | ✅ Cost tracking mevcut |

### Yapılacaklar
- Intelligence hit rate
- Scan summary metrikleri
- Performance tracking

### ✅ Doğrulama 6.1

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | LLM metrics çalışıyor | Scan sonrası | Call count, duration görünüyor |
| 2 | Intelligence hit rate | Scan sonrası | "Intelligence hit rate: 95%" |
| 3 | Scan summary | Scan sonrası | Toplam süre, dosya sayısı |

**Geçiş Kriteri:** 3/3 başarılı

---

## 6.2 Intelligence Quality Score

### Amaç
Intelligence kalitesini ölç

### Yapılacaklar
- Quality score hesaplama
- CI output'a ekleme

### Score Faktörleri

| Faktör | Ağırlık |
|--------|---------|
| Age (gün) | 30% |
| Coverage | 30% |
| Validation rate | 25% |
| Conflict rate | 15% |

### ✅ Doğrulama 6.2

| # | Doğrulama | Nasıl | Beklenen |
|---|-----------|-------|----------|
| 1 | Score hesaplanıyor | Scan sonrası | 0-100 arası skor |
| 2 | Faktörler doğru | Score breakdown | Age, coverage, validation |
| 3 | CI'da görünüyor | CI scan | Score output'ta var |

**Geçiş Kriteri:** 3/3 başarılı

---

## 🚧 Faz 6 Final Doğrulaması (ve Proje Final)

**Production Readiness Test:**
```
1. Warden'ın kendi repo'sunda full cycle çalıştır
2. Gerçek GitHub Actions'da PR workflow test et
3. Nightly workflow test et
4. Metrikleri topla ve değerlendir
```

| # | Kontrol | Beklenen |
|---|---------|----------|
| 1 | Self-hosting çalışıyor | Warden kendini taradı |
| 2 | PR scan süresi | <10 dakika |
| 3 | Context quality | False positive artmadı |
| 4 | Intelligence score | >80 |
| 5 | Metrics toplanıyor | Dashboard/log'da görünüyor |
| 6 | Debt tracking çalışıyor | Mevcut bulgular tracked |

**Faz 6 Geçiş Kriteri:** 6/6 başarılı → 🎉 PROJE TAMAMLANDI

---

# Dosya Değişiklik Haritası

```
src/warden/
├── analysis/
│   ├── domain/
│   │   ├── project_context.py      # 🔧 Güncelle (module_map, security_posture)
│   │   └── intelligence.py         # 🆕 Yeni (ModuleInfo, IntelligenceModel)
│   └── application/
│       ├── project_purpose_detector.py  # 🔧 Güncelle (prompt, validation)
│       ├── pre_analysis_phase.py        # 🔧 Güncelle (intelligence export)
│       └── dependency_graph.py          # ✅ Olduğu gibi
│
├── memory/
│   └── application/
│       └── memory_manager.py       # 🔧 Güncelle (module_map methods)
│
├── llm/
│   ├── providers/
│   │   └── orchestrated.py         # 🔧 Güncelle (rate limit detection)
│   └── metrics.py                  # 🔧 Güncelle (intelligence metrics)
│
├── cli/
│   └── commands/
│       ├── scan.py                 # 🔧 Güncelle (--ci flag)
│       ├── init.py                 # 🔧 Güncelle (intelligence generation)
│       ├── refresh.py              # 🆕 Yeni
│       └── helpers/
│           ├── baseline_manager.py      # 🔧 Güncelle (modül bazlı)
│           ├── intelligence_loader.py   # 🆕 Yeni
│           └── git_helper.py            # ✅ Olduğu gibi
│
└── shared/
    └── infrastructure/
        └── resilience.py           # ✅ Olduğu gibi

.warden/
├── intelligence/                   # 🆕 Yeni klasör
│   ├── project.json
│   ├── modules.json
│   ├── exceptions.json
│   └── relations.json
│
├── baseline/                       # 🔧 Yeni yapı (tek dosyadan klasöre)
│   ├── _meta.json
│   └── {module}.json
│
└── config.yaml                     # 🔧 Güncelle (CI budget config)

.github/workflows/
├── warden-pr.yml                   # 🔧 Güncelle
└── warden-nightly.yml              # 🔧 Güncelle
```

**Özet:**
- 🆕 Yeni: 3 dosya
- 🔧 Güncelle: 12 dosya
- ✅ Değişmez: 4 dosya

---

# Doğrulama Özeti

| Faz | Doğrulama Sayısı | Kritik | Geçiş Kriteri |
|-----|------------------|--------|---------------|
| 1.1 | 4 | Model çalışıyor | 4/4 |
| 1.2 | 5 | Intelligence üretiliyor | 5/5 |
| 1.3 | 5 | Intelligence okunuyor | 5/5 |
| **Faz 1 Final** | 6 | End-to-end | 6/6 |
| 2.1 | 4 | Freshness | 4/4 |
| 2.2 | 3 | Unknown module | 3/3 |
| 2.3 | 5 | Keyword override | 5/5 |
| 2.4 | 5 | Test filtering | 5/5 |
| 2.5 | 3 | LLM validation | 3/3 |
| 2.6 | 3 | Cross-module | 3/3 |
| **Faz 2 Final** | 5 | Safeguards | 5/5 |
| 3.1 | 5 | CI mode | 5/5 |
| 3.2 | 4 | Adaptive | 4/4 |
| 3.3 | 4 | Budget | 4/4 |
| **Faz 3 Final** | 7 | CI simulation | 7/7 |
| 4.1 | 5 | Module baseline | 5/5 |
| 4.2 | 4 | Baseline update | 4/4 |
| 4.3 | 4 | Debt tracking | 4/4 |
| **Faz 4 Final** | 6 | Baseline lifecycle | 6/6 |
| 5.1 | 5 | Init flow | 5/5 |
| 5.2 | 4 | Refresh | 4/4 |
| 5.3 | 5 | CI templates | 5/5 |
| **Faz 5 Final** | 7 | User journey | 7/7 |
| 6.1 | 3 | Metrics | 3/3 |
| 6.2 | 3 | Quality score | 3/3 |
| **Faz 6 Final** | 6 | Production ready | 6/6 |

**Toplam:** 111 doğrulama noktası

---

# Başarı Kriterleri

| Metrik | Mevcut | Hedef |
|--------|--------|-------|
| PR scan süresi | 45-120 dk | 3-10 dk |
| Nightly scan süresi | 6+ saat | 30-60 dk |
| LLM call / PR | 100-500 | 10-30 |
| False positive rate | ? | <%20 azalma |
| CI timeout failure | Sık | Nadir |
| Context quality | Yüksek | Korunacak |

---

# Sonraki Adımlar

1. ✅ Plan onayı
2. ⏳ Faz 1.1'den başla
3. Her faz sonunda doğrulama
4. Doğrulama geçerse sonraki faz
5. Tüm fazlar tamamlanınca production release

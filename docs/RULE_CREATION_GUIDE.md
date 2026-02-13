# Warden Kural Oluşturma Rehberi (Rule Creation Guide)

Warden, projenizin "Kod Anayasasını" belirlemek için güçlü bir kural motoru kullanır. Bu rehber, kendi kurallarınızı nasıl oluşturacağınızı, "Dynamic Activation" özelliğini nasıl kullanacağınızı ve farklı kural tiplerini açıklar.

## 1. Kural Dosyası Yapısı
Kurallar YAML formatında tanımlanır. Varsayılan olarak `.warden/rules` dizini altında bulunurlar (örn. `.warden/rules/{language}/`).

Basit bir kural örneği:
```yaml
rules:
  - id: "python-no-print"
    name: "No Print Statements"
    description: "Production kodunda print() fonksiyonu kullanılmamalıdır, logger kullanın."
    severity: "medium"
    tags: ["convention", "python"]
    # Dynamic Activation: Sadece Python projelerinde yükle (Opsiyonel)
    activation:
      language: "python"
    
    # Kural Tipi: Regex Deseni
    pattern: "print\\s*\\("
    message: "Lütfen 'print' yerine 'logger' kullanın."
```

## 2. Dynamic Rule Activation (Bağlam-Duyarlı Yükleme)
Warden 2.0 ile gelen bu özellik, kuralların sadece **ilgili proje tipinde** yüklenmesini sağlar.
Eskiden tüm kurallar her projede çalışırdı (örneğin Django kuralı FastAPI projesinde hata verebilirdi). Artık kuralın başına `activation` bloğu ekleyerek bunu engelleyebilirsiniz.

### Kullanım:
```yaml
activation:
  {etiket_adı}: "{etiket_değeri}"
```
**Desteklenen Etiketler (Context Tags):**
*   `language`: `python`, `javascript`, `go`, vb.
*   `framework`: `fastapi`, `django`, `react`, `flask`, vb.
*   `database`: `postgresql`, `mysql`, `mongodb`, vb.

### Örnekler:
This rule **ONLY** loads if the project is detected as FastAPI:
```yaml
  - id: "fastapi-secure-cookies"
    name: "FastAPI Secure Cookies"
    activation:
      framework: "fastapi"  # <--- KRİTİK NOKTA
    pattern: "SessionMiddleware\\(.*?https_only=False"
    message: "FastAPI SessionMiddleware 'https_only=True' olmalıdır."
```

This rule **ONLY** loads if the project uses PostgreSQL:
```yaml
  - id: "postgres-no-jsonb-index-abuse"
    activation:
      database: "postgresql"
    ...
```

> [!IMPORTANT]
> `activation` bloğu kullanıldığında, eğer proje bu etiketi (tag) sağlamıyorsa, kural **HİÇ YÜKLENMEZ** (Fail Safe).
> Eğer `activation` bloğu YOKSA, kural **HER ZAMAN** yüklenir (Generic Rule).

---

## 3. Kural Tipleri (Rule Types)

Warden 3 ana kural tipini destekler:

### A. Pattern (Regex) Rules
En hızlı ve basit yöntemdir. Kod içinde regex (düzenli ifade) arar.
```yaml
    type: "pattern"
    pattern: "password\\s*=\\s*['\"]\\w+['\"]"  # Hardcoded şifre tespiti
    conditions:
       pattern: "..." (Alternatif yazım)
```

### B. Convention Rules (Standartlar)
Daha karmaşık isimlendirme ve yapı standartları için.
```yaml
    type: "convention"
    conditions:
      naming:
        asyncMethodSuffix: "_async"  # Async metotlar _async ile bitmeli
      api:
        routePattern: "^/api/v[0-9]+/" # API route'ları versiyonlu olmalı
```

### C. Script Rules (External Helpers)
Bash, Python veya başka bir script çalıştırarak validasyon yapar.
```yaml
    type: "script"
    script_path: "scripts/check_file_size.sh"
    timeout: 30
```

### D. AI Rules (LLM-Driven Audit)
Karmaşık mantık hatalarını, race condition durumlarını veya mimari uyumsuzlukları tespit etmek için LLM kullanır. Regex ile tespiti imkansız olan durumlar için idealdir.
```yaml
    type: "ai"
    description: "Audit the code for potential race conditions in async loops."
    message: "AI detected logic flaw: {reason}"
    severity: "high"
```
> [!TIP]
> `ai` ve `script` tipi kurallarda `conditions` bloğu zorunlu değildir. AI kuralı direkt olarak `description` alanındaki direktifi kullanır.

## 5. Kural Atama ve Çalışma Hiyerarşisi (Rule Assignment)

Warden'da bir kuralı tanımlamak (YAML dosyası oluşturmak) yetmez, onu **nerede ve ne zaman** çalışacağını da belirlemeniz gerekir. Bu atamalar genellikle `.warden/rules/root.yaml` veya `config.yaml` dosyasında yapılır.

### A. Global Kurallar (Global Rules)
Tüm tarama boyunca, her dosyaya ve her frame'den bağımsız olarak uygulanır.
```yaml
global_rules:
  - id: "no-secrets"
  - id: "file-size-limit"
```

### B. Frame Kuralları (Pre/Post Rules)
Kurallar belirli bir **Frame** (örneğin `security`, `orphan`) çalışmadan önce veya sonra çalışacak şekilde atanabilir.

*   **pre_rules:** Frame'in kendi mantığı (örn. LLM taraması veya AST analizi) çalışmadan **önce** çalışır. Eğer kural ihlal edilirse ve `on_fail: stop` ise Frame hiç çalışmaz.
*   **post_rules:** Frame işini bitirdikten **sonra** çalışır. Genellikle Frame'in bulamadığı uç durumları yakalamak için kullanılır.

**Örnek (`root.yaml`):**
```yaml
frame_rules:
  security:
    pre_rules:
      - id: "env-var-api-keys"
      - id: "no-hardcoded-passwords"
    post_rules:
      - id: "security-audit-script"
    on_fail: "stop"  # Blocker bulunursa frame'i durdur
```

---

## 6. Kural Alanları (Reference)
| Alan | Tip | Zorunlu? | Açıklama |
| :--- | :--- | :--- | :--- |
| `id` | string | Evet | Benzersiz kural ID'si (`kebab-case`). |
| `name` | string | Evet | İnsan tarafından okunabilir isim. |
| `severity` | string | Hayır | `info`, `low`, `medium`, `high`, `critical`, `warning`, `error` (Default: `medium`). |
| `isBlocker` | boolean | Hayır | `true` ise CI/CD pipeline'ı durdurur. |
| `activation`| dict | Hayır | `framework: fastapi` gibi bağlam filtresi. |
| `tags` | list | Hayır | `security`, `style`, `performance` vb. etiketler. |
| `message` | string | Hayır | Hata durumunda gösterilecek mesaj. AI kurallarında `{reason}` değişkeni kullanılabilir. |
| `category` | string | Hayır | `security`, `convention`, `performance`, `logic`, `architectural`, `consistency`, `backend-ipc`. |
| `pattern` | string | Duruma göre | Regex deseni (Pattern kuralları için). |
| `language` | list | Hayır | Kuralın geçerli olduğu diller (örn. `[python, go]`). |
| `exceptions`| list | Hayır | Kuraldan muaf tutulacak dosya desenleri (Glob). |

---

## 7. Best Practices (İpuçları)
1.  **Regex Kullanımı:** Regex'lerinizde kaçış karakterlerine (`\`) dikkat edin. YAML içinde `\\` olarak yazmanız gerekebilir.
2.  **Performans:** Çok karmaşık regex'ler tarama süresini uzatabilir.
3.  **Strict Activation:** Projeye özgü bir kural yazıyorsanız MUTLAKA `activation` kullanın. Genel kuralları kirletmeyin.
4.  **Pre-Rule Avantajı:** Maliyetli bir Frame'i (örn. LLM kullananlar) çalıştırmadan önce basit regex kontrollerini `pre_rules` olarak ekleyerek vakit kazanın.
5.  **Test Edin:** Kuralı yazdıktan sonra `.warden/rules/` altına (veya alt klasörlerine) koyun ve `warden scan` ile deneyin.

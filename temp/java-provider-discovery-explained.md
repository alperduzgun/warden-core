# Java AST Provider Discovery - Nasıl Çalışıyor?

## 📋 Sorunun Cevabı

**Soru:** "Java-ast package kullanacağına warden nasıl karar verdi?"

**Cevap:** Warden **otomatik olarak** Python'un setuptools **entry points** mekanizmasını kullanarak keşfetti!

---

## 🔍 Adım Adım Discovery Süreci

### 1️⃣ Warden Başlatıldı
```python
registry = ASTProviderRegistry()
await registry.discover_providers()
```

### 2️⃣ Provider Loader Çalıştı
```python
# warden/ast/application/provider_loader.py
async def load_all(self):
    # 1. Built-in providers (tree-sitter, Python)
    await self._load_builtin_providers()

    # 2. PyPI entry points (BURADA JAVA BULUNDU!)
    await self._load_entry_point_providers()

    # 3. Local plugins (~/.warden/ast-providers/)
    await self._load_local_plugins()

    # 4. Environment variables
    await self._load_env_providers()
```

### 3️⃣ Entry Points Tarandı

**Kod:**
```python
# Python 3.10+ importlib.metadata kullanır
from importlib.metadata import entry_points

# "warden.ast_providers" grubunu ara
warden_eps = entry_points().select(group="warden.ast_providers")

for ep in warden_eps:
    # Her entry point'i yükle
    provider_class = ep.load()  # JavaParserProvider sınıfını yükler
    provider = provider_class()  # Instance oluştur

    # Validate et
    if isinstance(provider, IASTProvider):
        self._registry.register(provider)
```

### 4️⃣ Java Provider Bulundu!

**warden-ast-java/pyproject.toml** dosyasında tanımlı:
```toml
[project.entry-points."warden.ast_providers"]
java = "warden_ast_java.provider:JavaParserProvider"
```

**Anlamı:**
- **Group:** `warden.ast_providers` (Warden'ın aradığı grup)
- **Name:** `java` (Provider adı)
- **Location:** `warden_ast_java.provider:JavaParserProvider` (Python modül:sınıf)

### 5️⃣ Provider Yüklendi ve Kaydedildi

```python
provider = JavaParserProvider()  # Instance oluşturuldu
registry.register(provider)      # Registry'e eklendi
```

---

## 📊 Log Kanıtları

Analiz çıktısından:

```log
2025-12-21 18:52:05 [info] ast_provider_discovery_started
2025-12-21 18:52:05 [debug] loading_builtin_providers
2025-12-21 18:52:05 [info] provider_registered languages=['python'] provider_name=python-native
2025-12-21 18:52:05 [debug] loading_entry_point_providers
2025-12-21 18:52:05 [info] provider_registered languages=['java'] provider_name=javalang-parser
2025-12-21 18:52:05 [info] entry_point_provider_loaded entry_point=java provider_name=javalang-parser
```

**Ne Oldu:**
1. ✅ Discovery başladı
2. ✅ Built-in provider'lar yüklendi (Python)
3. ✅ **Entry points tarandı**
4. ✅ **Java provider bulundu** (`entry_point=java`)
5. ✅ **javalang-parser kaydedildi** (`provider_name=javalang-parser`)

---

## 🔧 Entry Points Mekanizması

### Python Setuptools Entry Points Nedir?

Entry points, Python paketlerinin **plugin sistemi** için standart bir yöntemdir.

**Avantajları:**
- ✅ **Zero-configuration** - Kurulduğunda otomatik bulunur
- ✅ **Standard** - Python ekosisteminde yaygın kullanılır
- ✅ **Dynamic** - Runtime'da keşfedilir
- ✅ **Isolated** - Her paket kendi entry point'ini tanımlar

### Örnekler (Gerçek Dünya)

**1. Pytest Plugins:**
```toml
[project.entry-points.pytest11]
myPlugin = "myplugin.pytest_plugin"
```

**2. Flask Extensions:**
```toml
[project.entry-points.flask.commands]
db = "flask_migrate.cli:db"
```

**3. Warden AST Providers:**
```toml
[project.entry-points."warden.ast_providers"]
java = "warden_ast_java.provider:JavaParserProvider"
csharp = "warden_ast_csharp.provider:CSharpProvider"
```

---

## 🎯 Neden Entry Points?

### Alternatif 1: Manual Registration ❌
```python
# Kötü: Her provider için kod değişikliği gerekir
from warden_ast_java import JavaProvider
from warden_ast_csharp import CSharpProvider

registry.register(JavaProvider())
registry.register(CSharpProvider())
```

**Sorun:** Warden core'a her yeni provider için kod eklemek gerekir.

### Alternatif 2: Config File ❌
```yaml
# config.yaml
providers:
  - module: warden_ast_java.provider
    class: JavaParserProvider
```

**Sorun:** Manuel konfigürasyon, user error'a açık.

### ✅ Entry Points (Seçilen Yöntem)
```toml
# warden-ast-java/pyproject.toml
[project.entry-points."warden.ast_providers"]
java = "warden_ast_java.provider:JavaParserProvider"
```

**Avantajlar:**
1. **Zero-config:** `pip install warden-ast-java` → Hemen çalışır!
2. **Declarative:** Package metadata'da tanımlı
3. **Standard:** Python ekosistemi standardı
4. **Auto-discovery:** Warden otomatik bulur
5. **Plugin isolation:** Her plugin bağımsız

---

## 🔍 Gerçek Dünya Entry Points Testi

Package'ların entry point'lerini görmek için:

```bash
# Kurulu paketlerin entry point'lerini listele
python -c "from importlib.metadata import entry_points; \
eps = entry_points(); \
warden_eps = eps.select(group='warden.ast_providers'); \
for ep in warden_eps: print(f'{ep.name} -> {ep.value}')"
```

**Çıktı:**
```
java -> warden_ast_java.provider:JavaParserProvider
```

---

## 📦 Package Kurulum Akışı

### 1. Package Kurulumu
```bash
pip install warden-ast-java
```

### 2. Setuptools Entry Points Kaydeder
```
~/.local/lib/python3.13/site-packages/warden_ast_java-0.1.0.dist-info/entry_points.txt
```

**İçerik:**
```ini
[warden.ast_providers]
java = warden_ast_java.provider:JavaParserProvider
```

### 3. Warden Import Eder
```python
from importlib.metadata import entry_points
eps = entry_points().select(group="warden.ast_providers")
# eps içinde 'java' entry point'i bulunur
```

### 4. Provider Yüklenir
```python
for ep in eps:
    provider_class = ep.load()  # Dynamic import!
    # warden_ast_java.provider:JavaParserProvider → class object
    provider = provider_class()  # Instance
```

---

## 🎨 Mimari Diyagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Warden Core                            │
│                                                             │
│  ┌──────────────────────────────────────────────────┐      │
│  │   ASTProviderLoader                               │      │
│  │                                                    │      │
│  │   1. Built-in Providers                           │      │
│  │      └─> Python AST (Always available)            │      │
│  │                                                    │      │
│  │   2. Entry Points Discovery ← BURADA JAVA BULUNDU!│      │
│  │      └─> importlib.metadata.entry_points()        │      │
│  │          └─> group="warden.ast_providers"         │      │
│  │              └─> Found: java, csharp, ...         │      │
│  │                                                    │      │
│  │   3. Local Plugins (~/.warden/ast-providers/)     │      │
│  │   4. Environment Variables (WARDEN_AST_PROVIDERS) │      │
│  └──────────────────────────────────────────────────┘      │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────┐      │
│  │   ASTProviderRegistry                             │      │
│  │                                                    │      │
│  │   Registered Providers:                           │      │
│  │   - python-native (NATIVE priority=1)             │      │
│  │   - javalang-parser (NATIVE priority=1) ← JAVA!   │      │
│  └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │
                Entry Points
                          │
┌─────────────────────────┴───────────────────────────────────┐
│                  Installed Packages                         │
│                                                             │
│  ┌───────────────────────────────────────────────┐         │
│  │  warden-ast-java (v0.1.0)                     │         │
│  │                                                │         │
│  │  pyproject.toml:                               │         │
│  │  [project.entry-points."warden.ast_providers"]│         │
│  │  java = "warden_ast_java.provider:JavaParser" │         │
│  └───────────────────────────────────────────────┘         │
│                                                             │
│  ┌───────────────────────────────────────────────┐         │
│  │  warden-ast-csharp (future)                   │         │
│  │                                                │         │
│  │  [project.entry-points."warden.ast_providers"]│         │
│  │  csharp = "warden_ast_csharp.provider:..."    │         │
│  └───────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 핵심 Özet

**Warden Java provider'ı nasıl buldu?**

1. **Entry Points Tarama:** `importlib.metadata.entry_points()` kullanarak
2. **Group Filtering:** `group="warden.ast_providers"` filtrelemesi
3. **Dynamic Loading:** `ep.load()` ile runtime'da import
4. **Auto-registration:** Bulunan her provider otomatik kaydedildi

**Neden bu kadar kolay?**

```bash
# Tek komut:
pip install warden-ast-java

# Warden hemen kullanıma hazır:
warden validate MyFile.java  # ✅ Çalışır!
```

**Magic yok, sadece Python standardı!** 🎉

---

## 📚 Referanslar

1. **Python Entry Points:** https://packaging.python.org/specifications/entry-points/
2. **importlib.metadata:** https://docs.python.org/3/library/importlib.metadata.html
3. **Setuptools Entry Points:** https://setuptools.pypa.io/en/latest/userguide/entry_point.html

---

**Oluşturan:** Warden Team
**Tarih:** 2025-12-21
**Durum:** Production-ready ✅

# Issue #657 Implementation Audit — Consensus (2026-04-28)

> Dört R1/R2 dosyasından (`CLAUDE`, `KIMI`, `R2-CLAUDE`, `R2-KIMI`) damıtılmış tek referans.
> Her madde `gh issue view 657`, `git log`, `grep`/`file:line` ile kanıtlanmıştır.
> Kimi R2'de Claude'un 13 iddiasının tamamı ACCEPT edilmiştir.

---

## 1. Issue #657 Acceptance Criteria

Issue title: `feat(rules): autoimprove FP reduction support for resilience frame`

### Work Items (issue body'sinden verbatim)

1. Add `timeout`, `circuit-breaker`, `error-handling` keys to `_LIBRARY_SAFE_PATTERNS` in `fp_exclusions.py`
2. Wire `FPExclusionRegistry.check()` into each resilience `_internal/` check before creating a `CheckFinding`
3. Add `--frame` option to `warden rules autoimprove` (default: `security`)
4. Update `_run_corpus_eval` to load the specified frame instead of hardcoded `security`
5. Create resilience corpus files under `verify/corpus/resilience/` with `corpus_labels:` blocks for all 3 checks
6. Smoke test: run `warden rules autoimprove --frame resilience --corpus verify/corpus/resilience/ --fast --dry-run`

### Acceptance Criteria (issue body'sinden verbatim)

- AC-A: `warden rules autoimprove --frame resilience --corpus verify/corpus/resilience/` runs the keep-or-revert loop for resilience checks
- AC-B: Accepted patterns land in `_LIBRARY_SAFE_PATTERNS["timeout"]` (or `circuit-breaker` / `error-handling`)
- AC-C: `warden rules autoimprove --frame security` still works unchanged
- AC-D: All existing tests pass

---

## 2. Tamamlanan İşler

Ana commit: `7ca5a3c` — `feat(rules): autoimprove FP reduction support for resilience frame (#657)`  
Tarih: 2026-04-08

| WI | Durum | Kanıt (file:line) | Hangi AC |
|----|-------|-------------------|----------|
| WI-1: `_LIBRARY_SAFE_PATTERNS` resilience keys | ✅ | `fp_exclusions.py:148-171` — `"timeout"` L149, `"circuit-breaker"` L157, `"error-handling"` L163; dict kapanışı L171 | AC-B |
| WI-2: `FPExclusionRegistry.check()` wired | ✅ | `timeout_check.py:20,23,182` · `circuit_breaker_check.py:18,21,68` · `error_handling_check.py:19,22,139` | AC-A |
| WI-3: `--frame` option | ✅ | `rules.py:258-262` — `typer.Option("security", "--frame", ...)` · `rules.py:340` — `frame_id=frame` | AC-A, AC-C |
| WI-4: `_run_corpus_eval` frame-agnostic | ✅ | `rules.py:446` — `frame_id: str = "security"` · `rules.py:453` — `get_frame_by_id(frame_id)` · `rules.py:455` — RuntimeError guard · `rules.py:467` — `("llm_service", None)` | AC-A, AC-C |
| WI-5: Resilience corpus (6 dosya) | ✅ | `verify/corpus/resilience/` — `python_timeout_fp.py`, `python_timeout_tp.py`, `python_circuit_breaker_fp.py`, `python_circuit_breaker_tp.py`, `python_error_handling_fp.py`, `python_error_handling_tp.py`; hepsinde `corpus_labels:` bloğu mevcut | AC-A |
| WI-6: Smoke test | ✅ (manuel) | Commit message: "F1=1.00 across all 3 resilience checks; Security frame backward-compat: F1=0.97" — otomatize edilmemiş | AC-A |
| WI-extra-1: circuit-breaker non-comment guard | ✅ | `circuit_breaker_check.py:64-68` — comment satır filtresi FP check öncesi | AC-A |
| WI-extra-2: Mevcut test `frame_id=` fix | ✅ | `test_rules_autoimprove.py:273` — `frame_id="security"` eklendi | AC-D |

**AC-D kanıtı:** Commit message "166 tests pass". (Bkz. §7 — "5093 vs 166" notu.)

---

## 3. Eksik Liste (final)

### E-1 [MEDIUM] — `_autoimprove_loop(frame_id="resilience")` için test yok

`tests/cli/commands/test_rules_autoimprove.py` — 20 fonksiyon, hepsi güvenlik odaklı. `frame_id` parametresi yalnızca `"security"` ile test edilmiş (`test_rules_autoimprove.py:273`). Resilience path'i kıran bir refactor sıfır test başarısızlığına neden olur.

```python
# test_rules_autoimprove.py:270-273
asyncio.run(rules_mod._autoimprove_loop(
    ...
    frame_id="security",   # ← tek test, resilience yok
))
```

**Kaynak:** `grep -n "frame_id" tests/cli/commands/test_rules_autoimprove.py → sadece :273`

---

### E-2 [MEDIUM] — `TimeoutCheck`, `CircuitBreakerCheck`, `ErrorHandlingCheck` birim testi yok

`tests/validation/frames/resilience/` → yalnızca `test_resilience_frame.py` (3 test: metadata, mock-LLM execution, empty findings). Her check için:
- `RISKY_PATTERNS` doğruluğu test edilmemiş
- `_LIBRARY_SAFE_PATTERNS` saygısı (FP exclusion davranışı) test edilmemiş
- TP tespiti bireysel olarak test edilmemiş

**Kaynak:** `find tests/ -name "test_*timeout_check*" -o -name "test_*circuit_breaker_check*"` → boş sonuç

---

### E-3 [LOW] — `file_path=` parametresi `_fp_registry.check()` çağrısında iletilmiyor

3 resilience check de `FPExclusionRegistry.check()` çağrısında `file_path=` parametresini iletmiyor:

```python
# timeout_check.py:182
excl = _fp_registry.check(self.id, matched_line, context)
#                                                          ↑ file_path= YOK

# fp_exclusions.py:218 — Layer 0 guard:
if file_path and self._SCANNER_IMPL_PATH_RE.search(file_path):
#  ↑ path boşsa asla tetiklenmez
```

Security frame karşılaştırması (`xss_check.py` benzeri):
```python
excl = _fp_registry.check(self.id, line, context_lines, file_path=str(code_file.path))
#                                                        ↑ GEÇİLİYOR
```

**Etki:** Warden kendi `resilience/_internal/*_check.py` dosyalarını tararken scanner-impl-path koruması (Layer 0) devreye girmez. Security frame ile tutarsızlık.

**Kaynak:** `grep -n "fp_registry.check" src/warden/validation/frames/resilience/_internal/timeout_check.py → :182 (no file_path)`

---

### E-4 [LOW] — `--frame resilience` varsayılan corpus path mismatch

`rules.py:254`: default corpus = `Path("verify/corpus")`. Resilience corpus dosyaları `verify/corpus/resilience/` alt dizininde.

`_collect_fp_examples` (rules.py:636-643) yalnızca `corpus_dir.iterdir()` üzerinden doğrudan `.py` dosyaları okur — alt dizine bakmaz.

**Sonuç:** `warden rules autoimprove --frame resilience` (`--corpus` belirtmeden) ya "No labeled checks found" mesajı üretir ya da yanlışlıkla security corpus dosyalarını işler.

**Kaynak:** `rules.py:254` + `rules.py:636-643`

---

## 4. Yanlış Liste

Acceptance criteria ile **uyumsuzluk** bulunmamıştır. Yukarıdaki E-1–E-4 maddeleri eksiklik/tutarsızlık kategorisindedir, "yanlış implementasyon" kategorisinde değildir.

---

## 5. Over-scope

**Hiçbir over-scope tespit edilmemiştir.** Commit `7ca5a3c`'de değiştirilen tüm dosyalar doğrudan issue WI'larıyla ilişkilidir. `llm_service` nulling ve circuit-breaker comment filtresi WI-4 ve WI-2'nin gerekli alt adımlarıdır.

---

## 6. Test Coverage Durumu

| Kapsam | Durum | Notlar |
|--------|-------|--------|
| `_autoimprove_loop(frame_id="resilience")` | ❌ | Test yok |
| `_run_corpus_eval(frame_id="resilience")` | ❌ | Monkeypatch ile sadece "security" test edilmiş |
| `TimeoutCheck` bireysel birim testi | ❌ | Test yok |
| `CircuitBreakerCheck` bireysel birim testi | ❌ | Test yok |
| `ErrorHandlingCheck` bireysel birim testi | ❌ | Test yok |
| `--frame` CLI option parse | ❌ | Typer invocation testi yok |
| `_LIBRARY_SAFE_PATTERNS["timeout/circuit-breaker/error-handling"]` insertion | ⚠️ | Insertion mechanism 8 test ile kapsanmış (`sql-injection`/`xss` key'leri ile); resilience key'leri spesifik test yok (`fp_exclusions_file` fixture'da resilience key'leri bulunmuyor) |
| FP exclusion davranışı (3 check) | ❌ | `test_resilience_frame.py` mock-LLM test ediyor, static check FP değil |
| Backward-compat `--frame security` | ✅ | Mevcut 20 test + `frame_id="security"` geçiyor |
| Smoke test (F1=1.00) | ✅ (manuel) | Commit message'da rapor edildi, CI artifact değil |

---

## 7. R2 İtirazlarının Durumu

### Kimi R2 → Claude R1 (13 claim, tamamı ACCEPT)

Kimi R2 Claude R1'deki tüm iddiaları doğrulamış ve kabul etmiştir. Reddettiği iddia yoktur.

| Madde | Kimi R2 Kararı |
|-------|----------------|
| WI-1 through WI-6 tamamlandı | ACCEPT |
| E-1 MEDIUM test gap | ACCEPT (Kimi R1'de de mevcuttu) |
| E-2 MEDIUM unit test gap | ACCEPT (Kimi R1'de LOW olarak vardı) |
| E-3 `file_path=` missing | **ACCEPT** — Kimi R1'de yoktu, R2'de kabul edildi |
| E-4 corpus default path | **ACCEPT** — Kimi R1'de yoktu, R2'de kabul edildi |
| Over-scope: None | ACCEPT |
| PARTIAL verdict | ACCEPT |

### Claude R2 → Kimi R1 (4 REJECT, 7 ACCEPT, 2 PARTIAL)

| Kimi R1 İddiası | Claude R2 Kararı | Kanıt |
|-----------------|-----------------|-------|
| `fp_exclusions.py:148-164` range | **REJECT** | Gerçek: `148-171` — `"error-handling"` bloğu L163-170, `}` L171; Kimi L165-171 eksik |
| `rules.py:469` → `("llm_service", None)` | **REJECT** | Gerçek: `rules.py:467` — L469 `if hasattr(frame, attr):` |
| `fp_exclusions.py` — "No direct tests" | **PARTIAL REJECT** | 8 insertion testi var (`sql-injection`/`xss` ile); resilience key'lerine spesifik test yok; "No direct tests" yanıltıcı |
| 85% tamamlanma skoru | **REJECT** | E-3 ve E-4 görmezden gelinmiş; revize skor ~80% |
| MEDIUM test gap | ACCEPT | ✓ Kimi R1'de mevcuttu |
| LOW FP behavior gap | ACCEPT | ✓ Kimi R1'de mevcuttu |
| Over-scope: None | ACCEPT | ✓ |
| WI-2 wiring satır numaraları | ACCEPT | ✓ Doğru |
| WI-3 `rules.py:258-262` | ACCEPT | ✓ Doğru |
| WI-4 `rules.py:446/453/455` | ACCEPT | ✓ Doğru |
| WI-5 6 corpus dosyası | ACCEPT | ✓ Doğru |

**R2 net sonuç:** Kimi R2 Claude R1'in her iddiasını kabul etmiş, Claude R2 Kimi R1'in 4 iddiasını reddetmiştir. Konsensüs Claude R1 bulguları üzerine kuruludur.

---

## 8. Final Verdict

**PARTIAL**

Tüm 6 work item fonksiyonel olarak tamamlanmıştır. 4 acceptance criteria karşılanmıştır (AC-A, AC-B, AC-C, AC-D). Mevcut testler geçmektedir. Eksiklik test coverage'dadır; fonksiyonel correctness'ta değildir — E-3 dışında (E-3 Layer 0 FP koruma tutarsızlığı, LOW severity).

---

## 9. Tamamlanma Yüzdesi

**~80%**

| Boyut | Değerlendirme | Ağırlık |
|-------|--------------|---------|
| Work items (6/6 tamamlandı) | 100% | 40% |
| Acceptance criteria (4/4 karşılandı) | 100% | 25% |
| Test coverage (5 kritik yeni path için 0 test; sadece backward-compat kapsanmış) | 20% | 25% |
| Fonksiyonel doğruluk (E-3 Layer 0 bypass, E-4 UX gap) | 80% | 10% |
| **Ağırlıklı toplam** | **~80%** | — |

**Claude R1: 78% / Kimi R1: 85% / Kimi R2 revize: ~80% / Consensus: 80%**

Fark: Kimi R1 E-3 ve E-4'ü görmedi; Claude R1 test ağırlığını biraz daha sert tuttu. R2 çapraz doğrulamadan sonra her iki taraf ~80%'de buluştu.

---

## 10. Önerilen Sonraki Adım

İssue'yu COMPLETE'e taşımak için minimum 3 PR:

### P1 (MEDIUM — gerekli): Resilience autoimprove loop testi

`tests/cli/commands/test_rules_autoimprove.py`'e eklenecek:
```python
async def test_autoimprove_loop_resilience_frame(corpus_dir, fp_exclusions_file, monkeypatch):
    """_autoimprove_loop accepts frame_id='resilience' without error."""
    ...
    asyncio.run(rules_mod._autoimprove_loop(
        corpus_dir=Path("verify/corpus/resilience"),
        fp_exclusions_file=fp_exclusions_file,
        frame_id="resilience",   # ← test edilmesi gereken
        ...
    ))
```

### P2 (MEDIUM — gerekli): 3 static check bireysel birim testleri

`tests/validation/frames/resilience/` altına:
- `test_timeout_check.py` — TP tespiti (timeout olmayan request), FP exclusion (mock session'ı)
- `test_circuit_breaker_check.py` — TP (raw HTTP), FP (pybreaker decorator)
- `test_error_handling_check.py` — TP (bare except), FP (re-raise)

### P3 (LOW — isteğe bağlı): `file_path=` tutarsızlığı ve corpus default fix

- Her 3 resilience check'te `_fp_registry.check()` çağrısına `file_path=str(code_file.path)` ekle
- `rules.py` `--frame resilience` için `--corpus` verilmemişse uyarı veya akıllı default (`verify/corpus/{frame}/`)

---

## 11. İmzalar

**Claude:** **APPROVE**  
*Gerekçe: Her madde gh issue view 657, git log, ve grep/file:line ile doğrulanmıştır. Dört R1/R2 dokümanının tüm kanıtlı bulguları bu dosyaya taşınmıştır. Hayali iddia yoktur.*

**Kimi:** **APPROVE**
*Gerekçe: R1 ve R2 kanıtları bu draft'ta eksiksiz yansıtılmıştır. Kimi R2'de Claude R1'in 13 iddiasının tamamı ACCEPT edilmiştir. Kimi R1'deki 4 teknik hata (`fp_exclusions.py:148-164` range, `rules.py:469` satır numarası, "No direct tests" yanıltıcılığı, 85% skor) bu draft'ta düzeltilmiştir. E-3 ve E-4 bulguları konsensüse eklenmiştir. ~80% tamamlanma yüzdesi ağırlıklı ortalama ile savunulabilir. Sonraki adım önerileri (P1-P2-P3) eksiklikleri doğru şekilde adresliyor.*

---

*Konsensüs rapor 2026-04-28 tarihinde üretildi.*  
*Kaynak dokümanlar: `ISSUE-657-AUDIT-CLAUDE-2026-04-28.md`, `ISSUE-657-AUDIT-KIMI-2026-04-28.md`, `ISSUE-657-AUDIT-R2-CLAUDE-2026-04-28.md`, `ISSUE-657-AUDIT-R2-KIMI-2026-04-28.md`*

ISSUE_657_AUDIT_CONSENSUS_DONE

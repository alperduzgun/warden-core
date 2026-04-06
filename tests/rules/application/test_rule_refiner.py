"""Tests for rule_refiner.refine_rules.

Covers:
  - FP detected, context updated on disk
  - Real finding, no update
  - Dry-run: result computed but file not written
  - Duplicate pattern skipped
  - rule_ids filter limits LLM calls
  - Missing findings_cache.json returns empty result gracefully
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from warden.rules.application.rule_refiner import RefinementResult, refine_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_RULE = {
    "id": "no-bare-except",
    "name": "No Bare Except",
    "category": "security",
    "severity": "high",
    "isBlocker": False,
    "description": "Flag bare except clauses that silently swallow errors.",
    "enabled": True,
    "type": "ai",
}


def _make_project(tmp_path: Path, rules: list[dict] | None = None, cache: dict | None = None) -> Path:
    """Create a minimal .warden project structure under *tmp_path*."""
    warden = tmp_path / ".warden"
    warden.mkdir(parents=True, exist_ok=True)

    # rules.yaml
    rules_data = {"rules": rules or [_BASE_RULE]}
    (warden / "rules.yaml").write_text(
        yaml.dump(rules_data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # findings_cache.json
    if cache is not None:
        cache_dir = warden / "cache"
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / "findings_cache.json").write_text(
            json.dumps(cache), encoding="utf-8"
        )

    # Source file that the cache keys reference
    src = tmp_path / "app.py"
    src.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "try:\n"
        "    risky()\n"
        "except Exception:\n"  # line 5
        "    logger.exception('error')\n",
        encoding="utf-8",
    )

    return tmp_path


def _make_cache_entry(project_root: Path, rule_id: str, line: int = 5) -> dict:
    """Return a findings_cache dict with one finding for *rule_id*."""
    src = project_root / "app.py"
    cache_key = f"security:{src}:abc123"
    return {
        cache_key: {
            "findings": [
                {
                    "id": rule_id,
                    "severity": "high",
                    "message": "Bare except detected",
                    "location": f"{src}:{line}",
                    "line": line,
                }
            ],
            "_ts": 1000.0,
            "_schema_v": "test",
        }
    }


def _make_llm(verdict: str, pattern: str = "", reason: str = "") -> AsyncMock:
    """Return a mock LLM whose complete_async returns the given classification."""
    payload = json.dumps({"verdict": verdict, "pattern": pattern, "reason": reason})
    service = AsyncMock()
    service.complete_async = AsyncMock(return_value=payload)
    service.config = MagicMock()
    return service


# ---------------------------------------------------------------------------
# Test 1 — FP detected, context updated on disk
# ---------------------------------------------------------------------------

class TestFPDetectedContextUpdated:
    @pytest.mark.asyncio
    async def test_fp_updates_context_on_disk(self, tmp_path: Path) -> None:
        """LLM returns false_positive → result.updates has 1 entry and rules.yaml is written."""
        project = _make_project(
            tmp_path,
            cache=_make_cache_entry(tmp_path, "no-bare-except"),
        )

        llm = _make_llm(
            verdict="false_positive",
            pattern="except Exception: logger.exception() in loop",
            reason="intentional per-server isolation",
        )

        result = await refine_rules(project, llm, dry_run=False)

        assert result.analyzed == 1
        assert len(result.updates) == 1
        assert "except Exception: logger.exception() in loop" in result.updates[0]["new_context"]

        # Verify the file was actually written
        written = yaml.safe_load(
            (project / ".warden" / "rules.yaml").read_text(encoding="utf-8")
        )
        rule = written["rules"][0]
        assert "except Exception: logger.exception() in loop" in (rule.get("context") or "")


# ---------------------------------------------------------------------------
# Test 2 — Real finding, no update
# ---------------------------------------------------------------------------

class TestRealFindingNoUpdate:
    @pytest.mark.asyncio
    async def test_real_verdict_not_added(self, tmp_path: Path) -> None:
        """LLM returns real → result.updates empty and skipped_real incremented."""
        project = _make_project(
            tmp_path,
            cache=_make_cache_entry(tmp_path, "no-bare-except"),
        )

        llm = _make_llm(verdict="real", pattern="", reason="silent swallow")

        result = await refine_rules(project, llm, dry_run=False)

        assert result.updates == []
        assert result.skipped_real == 1
        assert result.analyzed == 1


# ---------------------------------------------------------------------------
# Test 3 — Dry run — file not written
# ---------------------------------------------------------------------------

class TestDryRunNoFileWrite:
    @pytest.mark.asyncio
    async def test_dry_run_returns_update_without_writing(self, tmp_path: Path) -> None:
        """dry_run=True → result.updates populated but rules.yaml unchanged."""
        project = _make_project(
            tmp_path,
            cache=_make_cache_entry(tmp_path, "no-bare-except"),
        )

        original_text = (project / ".warden" / "rules.yaml").read_text(encoding="utf-8")

        llm = _make_llm(
            verdict="false_positive",
            pattern="except Exception: logger.exception() in loop",
            reason="intentional per-server isolation",
        )

        result = await refine_rules(project, llm, dry_run=True)

        assert len(result.updates) == 1
        # File must remain unchanged
        after_text = (project / ".warden" / "rules.yaml").read_text(encoding="utf-8")
        assert after_text == original_text


# ---------------------------------------------------------------------------
# Test 4 — Duplicate pattern skipped
# ---------------------------------------------------------------------------

class TestDuplicatePatternSkipped:
    @pytest.mark.asyncio
    async def test_duplicate_fp_not_added_again(self, tmp_path: Path) -> None:
        """Rule already has context containing the pattern → skipped_duplicate incremented."""
        rule_with_ctx = dict(_BASE_RULE)
        rule_with_ctx["context"] = (
            "Acceptable: except Exception: logger.exception() in loop — foo"
        )

        project = _make_project(
            tmp_path,
            rules=[rule_with_ctx],
            cache=_make_cache_entry(tmp_path, "no-bare-except"),
        )

        llm = _make_llm(
            verdict="false_positive",
            pattern="except Exception: logger.exception() in loop",
            reason="intentional per-server isolation",
        )

        result = await refine_rules(project, llm, dry_run=False)

        assert result.skipped_duplicate == 1
        assert result.updates == []


# ---------------------------------------------------------------------------
# Test 5 — rule_ids filter
# ---------------------------------------------------------------------------

class TestRuleIdsFilter:
    @pytest.mark.asyncio
    async def test_only_requested_rule_analyzed(self, tmp_path: Path) -> None:
        """rule_ids=['rule-a'] → only rule-a's findings are sent to LLM."""
        rule_a = dict(_BASE_RULE, id="rule-a", name="Rule A")
        rule_b = dict(_BASE_RULE, id="rule-b", name="Rule B")

        src = tmp_path / "app.py"
        src.write_text("x = 1\n", encoding="utf-8")
        cache_key_a = f"security:{src}:aaa111"
        cache_key_b = f"security:{src}:bbb222"
        cache = {
            cache_key_a: {
                "findings": [
                    {"id": "rule-a", "severity": "high", "message": "A", "location": f"{src}:1", "line": 1}
                ],
                "_ts": 1000.0,
                "_schema_v": "test",
            },
            cache_key_b: {
                "findings": [
                    {"id": "rule-b", "severity": "high", "message": "B", "location": f"{src}:1", "line": 1}
                ],
                "_ts": 1000.0,
                "_schema_v": "test",
            },
        }

        project = _make_project(tmp_path, rules=[rule_a, rule_b], cache=cache)

        llm = _make_llm(verdict="real", pattern="", reason="violation")

        result = await refine_rules(project, llm, rule_ids=["rule-a"], dry_run=True)

        # LLM should have been called exactly once (only rule-a)
        assert llm.complete_async.call_count == 1
        assert result.analyzed == 1


# ---------------------------------------------------------------------------
# Test 6 — Missing findings_cache.json
# ---------------------------------------------------------------------------

class TestMissingCacheFile:
    @pytest.mark.asyncio
    async def test_missing_cache_returns_empty_result(self, tmp_path: Path) -> None:
        """No findings_cache.json → returns empty RefinementResult without error."""
        # Create .warden but no cache file
        (tmp_path / ".warden").mkdir()
        (tmp_path / ".warden" / "rules.yaml").write_text(
            yaml.dump({"rules": [_BASE_RULE]}, default_flow_style=False),
            encoding="utf-8",
        )

        llm = _make_llm(verdict="real")

        result = await refine_rules(tmp_path, llm, dry_run=False)

        assert result == RefinementResult(
            updates=[], analyzed=0, skipped_real=0, skipped_duplicate=0
        )
        llm.complete_async.assert_not_called()

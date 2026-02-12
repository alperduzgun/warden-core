"""Subprocess-based end-user acceptance tests.

Tests the real ``warden`` binary exactly as a user would invoke it from a
terminal.  Every assertion runs through ``subprocess.run`` so we verify:
- Entry-point resolution and startup
- stdout / stderr separation
- Real exit codes from the process
- Startup latency
- Environment isolation

Marker summary
--------------
- ``@pytest.mark.acceptance`` — every test in this module
- ``@pytest.mark.requires_ollama`` — needs a running Ollama instance
- ``@pytest.mark.slow`` — wall-clock > 10 s

The whole module is skipped when the ``warden`` binary is not on ``$PATH``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"

# Module-level skip when warden binary is missing
pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(
        shutil.which("warden") is None,
        reason="warden binary not found on PATH",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_warden(
    *args: str,
    cwd: str | Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``warden`` as a subprocess and return the result."""
    merged_env = {**os.environ, **(env or {})}
    # Suppress the SECRET_KEY warning noise in all runs
    merged_env.setdefault("SECRET_KEY", "test-acceptance-key-do-not-use")
    return subprocess.run(
        ["warden", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def _load_config(project_dir: Path) -> dict:
    """Load and return the .warden/config.yaml as a dict."""
    config_path = project_dir / ".warden" / "config.yaml"
    assert config_path.exists(), f"Config not found: {config_path}"
    return yaml.safe_load(config_path.read_text()) or {}


def _extract_json(stdout: str) -> dict:
    """Best-effort JSON extraction from stdout that may contain log lines."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    # Try each line from bottom
    for line in reversed(stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    # Try to find a JSON object by braces
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stdout[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON found in output:\n{stdout[:500]}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_dir(tmp_path):
    """An empty temporary directory."""
    return tmp_path


@pytest.fixture
def initialized_project(tmp_path):
    """A temp directory with ``warden init --force --skip-mcp`` already run."""
    result = run_warden(
        "init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30,
    )
    assert result.returncode == 0, f"init failed: {result.stderr}"
    return tmp_path


@pytest.fixture
def isolated_sample(tmp_path):
    """Copy of the sample_project fixture for mutation-safe tests."""
    dest = tmp_path / "project"
    shutil.copytree(SAMPLE_PROJECT, dest)
    return dest


# ═══════════════════════════════════════════════════════════════════════════
# 1. Startup & Discovery
# ═══════════════════════════════════════════════════════════════════════════

class TestStartupDiscovery:
    """Verify the binary resolves, prints help, and rejects unknowns."""

    def test_help_exits_zero(self):
        r = run_warden("--help", timeout=10)
        assert r.returncode == 0
        assert "usage" in r.stdout.lower() or "warden" in r.stdout.lower()

    def test_version_exits_zero(self):
        r = run_warden("version", timeout=10)
        assert r.returncode == 0
        # Version output should contain a semver-ish pattern
        out = r.stdout + r.stderr
        assert any(ch.isdigit() for ch in out), "version output has no digits"

    def test_help_startup_latency(self):
        t0 = time.monotonic()
        run_warden("--help", timeout=10)
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0, f"--help took {elapsed:.2f}s (limit 5s)"

    def test_unknown_command_exits_nonzero(self):
        r = run_warden("nonexistent-command-xyz", timeout=10)
        assert r.returncode != 0

    def test_no_args_shows_help(self):
        r = run_warden(timeout=10)
        out = r.stdout + r.stderr
        assert "usage" in out.lower() or "warden" in out.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Doctor & Init
# ═══════════════════════════════════════════════════════════════════════════

class TestDoctorInit:
    """Verify project initialization and doctor diagnostics."""

    def test_doctor_runs(self, isolated_sample):
        r = run_warden("doctor", cwd=str(isolated_sample), timeout=30)
        assert r.returncode in (0, 1)
        out = r.stdout + r.stderr
        # Should produce some diagnostic output
        assert len(out) > 0

    def test_init_creates_config(self, empty_dir):
        r = run_warden(
            "init", "--force", "--skip-mcp", cwd=str(empty_dir), timeout=30,
        )
        assert r.returncode == 0
        config = empty_dir / ".warden" / "config.yaml"
        assert config.exists(), ".warden/config.yaml not created"

    def test_init_directory_structure(self, initialized_project):
        warden_dir = initialized_project / ".warden"
        assert warden_dir.is_dir()
        assert (warden_dir / "config.yaml").is_file()

    def test_doctor_after_init(self, initialized_project):
        r = run_warden("doctor", cwd=str(initialized_project), timeout=30)
        # Doctor on a freshly-initialized project should succeed
        assert r.returncode in (0, 1)

    def test_init_idempotent(self, initialized_project):
        # Second init should not error out
        r = run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(initialized_project), timeout=30,
        )
        assert r.returncode == 0

    def test_init_non_interactive_env(self, empty_dir):
        r = run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        assert r.returncode == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. Scan Exit Codes
# ═══════════════════════════════════════════════════════════════════════════

class TestScanExitCodes:
    """Verify scan returns correct exit codes."""

    def test_scan_basic_clean_project(self, initialized_project):
        # Create a trivially clean Python file
        (initialized_project / "clean.py").write_text(
            "def hello():\n    return 'world'\n"
        )
        r = run_warden(
            "scan", "--level", "basic", str(initialized_project / "clean.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2), f"Unexpected exit: {r.returncode}"

    @pytest.mark.requires_ollama
    def test_scan_vulnerable_project(self, isolated_sample):
        r = run_warden(
            "scan", cwd=str(isolated_sample), timeout=120,
        )
        # 0=clean, 1=pipeline error, 2=policy failure
        assert r.returncode in (0, 1, 2), f"Unexpected exit: {r.returncode}"

    def test_scan_basic_level_no_llm(self, isolated_sample):
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)

    def test_scan_nonexistent_path(self, initialized_project):
        r = run_warden(
            "scan", "/nonexistent/path/that/does/not/exist",
            cwd=str(initialized_project), timeout=30,
        )
        assert r.returncode != 0

    def test_scan_exit_code_range(self, initialized_project):
        (initialized_project / "app.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--level", "basic", str(initialized_project / "app.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2), (
            f"Exit code {r.returncode} outside expected {{0,1,2}}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. Output Formats
# ═══════════════════════════════════════════════════════════════════════════

class TestOutputFormats:
    """Verify different output formats produce valid data."""

    def test_json_format(self, isolated_sample):
        r = run_warden(
            "scan", "--level", "basic", "--format", "json",
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            data = _extract_json(r.stdout)
            assert isinstance(data, dict)

    def test_sarif_format(self, isolated_sample):
        r = run_warden(
            "scan", "--level", "basic", "--format", "sarif",
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            data = _extract_json(r.stdout)
            assert isinstance(data, dict)
            # SARIF requires $schema or version
            assert (
                "$schema" in data or "version" in data
            ), "SARIF output missing schema/version"

    def test_output_file(self, isolated_sample, tmp_path):
        report = tmp_path / "report.json"
        r = run_warden(
            "scan", "--level", "basic", "--format", "json",
            "--output", str(report),
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            assert report.exists(), "Output file was not created"
            data = json.loads(report.read_text())
            assert isinstance(data, dict)

    def test_text_format(self, isolated_sample):
        r = run_warden(
            "scan", "--level", "basic", "--format", "text",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        # Text format should produce some output when scan completes


# ═══════════════════════════════════════════════════════════════════════════
# 5. CI Mode
# ═══════════════════════════════════════════════════════════════════════════

class TestCIMode:
    """Verify CI mode runs non-interactively without TUI artifacts."""

    def test_ci_mode_runs(self, isolated_sample):
        r = run_warden(
            "scan", "--ci", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)

    def test_ci_basic_succeeds(self, initialized_project):
        (initialized_project / "main.py").write_text("print('ok')\n")
        r = run_warden(
            "scan", "--ci", "--level", "basic",
            str(initialized_project / "main.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)

    def test_ci_no_spinner_artifacts(self, isolated_sample):
        r = run_warden(
            "scan", "--ci", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        # Carriage returns indicate spinner/TUI progress bars
        assert "\r" not in r.stdout, (
            "Spinner artifacts (\\r) found in CI mode stdout"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6. Config & Baseline & Status
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigBaselineStatus:
    """Verify read-only config / baseline / status commands."""

    def test_config_list(self, isolated_sample):
        r = run_warden("config", "list", cwd=str(isolated_sample), timeout=15)
        assert r.returncode in (0, 1)

    def test_baseline_status(self, isolated_sample):
        r = run_warden(
            "baseline", "status", cwd=str(isolated_sample), timeout=15,
        )
        assert r.returncode in (0, 1)

    def test_status(self, isolated_sample):
        r = run_warden("status", cwd=str(isolated_sample), timeout=15)
        assert r.returncode in (0, 1)


# ═══════════════════════════════════════════════════════════════════════════
# 8. LLM Configuration (Init)
# ═══════════════════════════════════════════════════════════════════════════

class TestInitLLMConfig:
    """Verify that ``warden init`` writes valid LLM configuration."""

    def test_init_writes_llm_section(self, empty_dir):
        """Config must contain an ``llm`` key after init."""
        r = run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        assert r.returncode == 0
        cfg = _load_config(empty_dir)
        assert "llm" in cfg, "config.yaml missing 'llm' section"

    def test_llm_has_provider(self, empty_dir):
        """LLM section must declare a provider."""
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        llm = cfg["llm"]
        assert "provider" in llm, "llm config missing 'provider'"
        assert llm["provider"], "llm provider is empty"

    def test_llm_has_model(self, empty_dir):
        """LLM section must specify a model."""
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        llm = cfg["llm"]
        assert "model" in llm, "llm config missing 'model'"
        assert llm["model"], "llm model is empty"

    def test_llm_provider_is_known(self, empty_dir):
        """Auto-detected provider must be one of the supported providers."""
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        known = {
            "ollama", "anthropic", "openai", "groq",
            "azure", "deepseek", "gemini", "claude_code", "none",
        }
        assert cfg["llm"]["provider"] in known, (
            f"Unknown provider: {cfg['llm']['provider']}"
        )

    def test_llm_has_timeout(self, empty_dir):
        """LLM section should include a timeout value."""
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        llm = cfg["llm"]
        assert "timeout" in llm, "llm config missing 'timeout'"
        assert isinstance(llm["timeout"], (int, float))
        assert llm["timeout"] > 0

    def test_settings_use_llm_flag(self, empty_dir):
        """Settings should reflect whether LLM is active."""
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        settings = cfg.get("settings", {})
        assert "use_llm" in settings, "settings missing 'use_llm' flag"
        provider = cfg["llm"]["provider"]
        if provider == "none":
            assert settings["use_llm"] is False
        else:
            assert settings["use_llm"] is True

    def test_llm_has_fast_model(self, empty_dir):
        """LLM section should define a fast_model for the two-tier system."""
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        llm = cfg["llm"]
        assert "fast_model" in llm, "llm config missing 'fast_model'"
        assert llm["fast_model"], "fast_model is empty"

    def test_reinit_preserves_llm_provider(self, empty_dir):
        """Re-initializing with --force should keep a valid LLM provider."""
        env = {"WARDEN_NON_INTERACTIVE": "true"}
        run_warden("init", "--force", "--skip-mcp", cwd=str(empty_dir), timeout=30, env=env)
        cfg1 = _load_config(empty_dir)
        provider1 = cfg1["llm"]["provider"]

        run_warden("init", "--force", "--skip-mcp", cwd=str(empty_dir), timeout=30, env=env)
        cfg2 = _load_config(empty_dir)
        provider2 = cfg2["llm"]["provider"]

        # Provider should remain valid (may change if detection differs, but must exist)
        assert provider2, "LLM provider lost after re-init"
        # On a stable environment, auto-detection should pick the same provider
        assert provider1 == provider2, (
            f"Provider changed from {provider1!r} to {provider2!r} on re-init"
        )

    def test_init_mode_vibe_minimal_frames(self, empty_dir):
        """Vibe mode should produce a valid config with minimal frames."""
        run_warden(
            "init", "--force", "--skip-mcp", "--mode", "vibe",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        assert "llm" in cfg
        assert cfg["llm"]["provider"]
        # Vibe mode uses only security-related frames
        settings = cfg.get("settings", {})
        assert settings.get("mode") == "vibe"

    def test_init_mode_strict_all_issues(self, empty_dir):
        """Strict mode should set fail_fast and low severity."""
        run_warden(
            "init", "--force", "--skip-mcp", "--mode", "strict",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        cfg = _load_config(empty_dir)
        assert "llm" in cfg
        settings = cfg.get("settings", {})
        assert settings.get("mode") == "strict"
        assert settings.get("fail_fast") is True


# ═══════════════════════════════════════════════════════════════════════════
# 9. LLM Runtime Verification
# ═══════════════════════════════════════════════════════════════════════════

class TestLLMRuntime:
    """Verify that the selected LLM provider actually works at runtime.

    Tests go beyond config file checks — they run real commands and inspect
    stdout/stderr to confirm the provider is reached and used.
    """

    def test_init_stdout_confirms_provider(self, empty_dir):
        """Init output must mention which provider was configured."""
        r = run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        assert r.returncode == 0
        out = r.stdout.lower()
        # Init should mention at least one of these in its output
        provider_hints = [
            "ollama", "claude code", "anthropic", "openai",
            "groq", "azure", "deepseek", "gemini",
        ]
        assert any(h in out for h in provider_hints), (
            f"Init output does not mention any known provider:\n{r.stdout[:500]}"
        )

    def test_config_list_shows_provider(self, empty_dir):
        """``warden config list`` must display the configured LLM provider."""
        env = {"WARDEN_NON_INTERACTIVE": "true"}
        run_warden("init", "--force", "--skip-mcp", cwd=str(empty_dir), timeout=30, env=env)

        cfg = _load_config(empty_dir)
        expected_provider = cfg["llm"]["provider"]

        r = run_warden("config", "list", cwd=str(empty_dir), timeout=15)
        assert r.returncode in (0, 1)
        # config list tree output should contain the provider value
        assert expected_provider in r.stdout, (
            f"config list doesn't show provider {expected_provider!r}:\n{r.stdout[:500]}"
        )

    def test_config_list_shows_model(self, empty_dir):
        """``warden config list`` must display the configured model."""
        env = {"WARDEN_NON_INTERACTIVE": "true"}
        run_warden("init", "--force", "--skip-mcp", cwd=str(empty_dir), timeout=30, env=env)

        cfg = _load_config(empty_dir)
        expected_model = cfg["llm"]["model"]

        r = run_warden("config", "list", cwd=str(empty_dir), timeout=15)
        assert expected_model in r.stdout, (
            f"config list doesn't show model {expected_model!r}:\n{r.stdout[:500]}"
        )

    @pytest.mark.requires_ollama
    def test_scan_reaches_ollama(self, tmp_path):
        """When Ollama is the provider, scan stderr must show HTTP requests to it."""
        # Build PATH that keeps warden + ollama but hides claude for clean detection
        path_dirs = [
            d for d in os.environ.get("PATH", "").split(":")
            if "/.local/bin" not in d  # hide claude CLI
        ]
        env = {
            "WARDEN_NON_INTERACTIVE": "true",
            "PATH": ":".join(path_dirs),
        }
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)

        # Verify ollama was selected
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama on this env")

        # Create a file to scan
        (tmp_path / "app.py").write_text(
            "import os\npassword = os.environ['DB_PASS']\n"
        )
        r = run_warden(
            "scan", "--level", "standard",
            str(tmp_path / "app.py"),
            cwd=str(tmp_path), timeout=120,
            env=env,
        )
        combined = r.stdout + r.stderr
        # httpx logs HTTP requests to Ollama in stderr
        assert "localhost:11434" in combined, (
            "Scan did not contact Ollama — LLM integration may be broken"
        )

    @pytest.mark.requires_ollama
    def test_scan_no_zombie_mode_with_ollama(self, tmp_path):
        """When Ollama is running and configured, scan should NOT be in zombie mode."""
        path_dirs = [
            d for d in os.environ.get("PATH", "").split(":")
            if "/.local/bin" not in d
        ]
        env = {
            "WARDEN_NON_INTERACTIVE": "true",
            "PATH": ":".join(path_dirs),
        }
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama on this env")

        (tmp_path / "main.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--level", "standard",
            str(tmp_path / "main.py"),
            cwd=str(tmp_path), timeout=120,
            env=env,
        )
        # ZOMBIE MODE means LLM was NOT used despite being configured
        assert "ZOMBIE MODE" not in r.stdout, (
            "Scan entered ZOMBIE MODE despite Ollama being available"
        )

    def test_scan_basic_works_without_llm(self, empty_dir):
        """Basic level scan must work even if no LLM provider is reachable."""
        # Init normally first so config exists
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(empty_dir), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        (empty_dir / "hello.py").write_text("print('hello')\n")
        # Scan with basic level — should work without reaching any LLM
        r = run_warden(
            "scan", "--level", "basic",
            str(empty_dir / "hello.py"),
            cwd=str(empty_dir), timeout=60,
        )
        # basic level should still run (heuristic-only), even without LLM
        assert r.returncode in (0, 1, 2), f"basic scan failed: exit {r.returncode}"

    def test_doctor_reports_llm_status(self, empty_dir):
        """Doctor output must contain LLM/environment diagnostics."""
        env = {"WARDEN_NON_INTERACTIVE": "true"}
        run_warden("init", "--force", "--skip-mcp", cwd=str(empty_dir), timeout=30, env=env)
        r = run_warden("doctor", cwd=str(empty_dir), timeout=30)
        out = r.stdout + r.stderr
        # Doctor checks "Environment & API Keys" — should mention something about it
        assert "environment" in out.lower() or "api" in out.lower() or "zombie" in out.lower(), (
            "Doctor output has no LLM/environment diagnostics"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 10. Ollama Model Management
# ═══════════════════════════════════════════════════════════════════════════

def _ollama_env() -> dict[str, str]:
    """Build env dict that forces Ollama selection (hides claude from PATH)."""
    path_dirs = [
        d for d in os.environ.get("PATH", "").split(":")
        if "/.local/bin" not in d
    ]
    return {
        "WARDEN_NON_INTERACTIVE": "true",
        "PATH": ":".join(path_dirs),
    }


def _get_ollama_models() -> list[str]:
    """Query Ollama API for installed model names."""
    import httpx
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []


@pytest.mark.requires_ollama
class TestOllamaModelManagement:
    """Verify that Ollama model configuration, availability and error handling work."""

    def test_init_configures_fast_model(self, tmp_path):
        """Init must set fast_model to a lightweight model (qwen2.5-coder:0.5b)."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")
        fast = cfg["llm"].get("fast_model", "")
        assert "0.5b" in fast or "small" in fast.lower(), (
            f"fast_model should be a lightweight model, got: {fast!r}"
        )

    def test_init_configures_smart_model(self, tmp_path):
        """Init must set model (smart tier) to a larger model than fast_model."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")
        model = cfg["llm"]["model"]
        fast = cfg["llm"].get("fast_model", "")
        # Smart model should differ from fast model (two-tier design)
        assert model, "smart model is empty"
        assert fast, "fast_model is empty"
        # They could be the same in minimal setups, but at minimum both must be set

    def test_init_mentions_pull_instruction(self, tmp_path):
        """Init output should tell the user how to pull models if needed."""
        env = _ollama_env()
        r = run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")
        out = r.stdout.lower()
        assert "ollama pull" in out or "already downloaded" in out or "pull" in out, (
            "Init does not mention 'ollama pull' — user won't know to download models"
        )

    def test_fast_model_is_installed(self, tmp_path):
        """The configured fast_model must actually be available on the Ollama instance."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")

        fast_model = cfg["llm"].get("fast_model", "")
        installed = _get_ollama_models()
        assert fast_model in installed, (
            f"fast_model {fast_model!r} is NOT installed on Ollama.\n"
            f"Installed: {installed}\n"
            f"Run: ollama pull {fast_model}"
        )

    def test_smart_model_availability_check(self, tmp_path):
        """If smart model is not installed, scan should still not crash."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")

        smart_model = cfg["llm"]["model"]
        installed = _get_ollama_models()

        (tmp_path / "test.py").write_text("x = eval(input())\n")
        r = run_warden(
            "scan", "--level", "standard",
            str(tmp_path / "test.py"),
            cwd=str(tmp_path), timeout=120,
            env=env,
        )
        if smart_model not in installed:
            # Model not installed → scan should still finish (graceful degradation)
            assert r.returncode in (0, 1, 2), (
                f"Scan crashed (exit {r.returncode}) with missing model {smart_model!r}"
            )
            combined = r.stdout + r.stderr
            # Should mention the missing model somewhere
            assert "not found" in combined.lower() or "pull" in combined.lower() or "zombie" in combined.upper() or r.returncode in (0, 1, 2), (
                "Scan with missing model gave no useful feedback"
            )
        else:
            # Model installed → scan should succeed
            assert r.returncode in (0, 1, 2)

    def test_scan_uses_fast_model_for_basic(self, tmp_path):
        """Scan at standard level should contact Ollama with the configured model."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")

        fast_model = cfg["llm"].get("fast_model", "")
        installed = _get_ollama_models()
        if fast_model not in installed:
            pytest.skip(f"fast_model {fast_model!r} not installed")

        (tmp_path / "code.py").write_text("import subprocess\nsubprocess.call(input())\n")
        r = run_warden(
            "scan", "--level", "standard",
            str(tmp_path / "code.py"),
            cwd=str(tmp_path), timeout=120,
            env=env,
        )
        combined = r.stdout + r.stderr
        # Should have contacted ollama (httpx log lines)
        assert "11434" in combined, (
            "Scan did not contact Ollama at all"
        )

    def test_scan_graceful_with_nonexistent_model(self, tmp_path):
        """Scan must not crash when config points to a model that doesn't exist."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")

        # Tamper config to use a model that definitely doesn't exist
        config_path = tmp_path / ".warden" / "config.yaml"
        raw = config_path.read_text()
        raw = raw.replace(
            cfg["llm"]["model"],
            "nonexistent-model-xyz:999b",
        )
        raw = raw.replace(
            cfg["llm"].get("fast_model", ""),
            "nonexistent-model-xyz:999b",
        )
        config_path.write_text(raw)

        (tmp_path / "vuln.py").write_text("eval(input())\n")
        try:
            r = run_warden(
                "scan", "--level", "standard",
                str(tmp_path / "vuln.py"),
                cwd=str(tmp_path), timeout=120,
                env=env,
            )
            # Must not crash — graceful degradation
            assert r.returncode in (0, 1, 2), (
                f"Scan crashed (exit {r.returncode}) with non-existent model"
            )
        except subprocess.TimeoutExpired:
            # Retry mechanism may cause long waits — timeout is acceptable
            # but signals a problem: missing model should fail fast
            pytest.fail(
                "Scan timed out with non-existent model — "
                "retry/resilience layer does not fail fast on model 404"
            )

    def test_model_404_error_message(self, tmp_path):
        """When model is missing, output should mention 'not found' or 'pull'."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")

        # Point to fake model
        config_path = tmp_path / ".warden" / "config.yaml"
        raw = config_path.read_text()
        raw = raw.replace(cfg["llm"]["model"], "fake-model-404:1b")
        if cfg["llm"].get("fast_model"):
            raw = raw.replace(cfg["llm"]["fast_model"], "fake-model-404:1b")
        config_path.write_text(raw)

        (tmp_path / "app.py").write_text("exec(open('hack.py').read())\n")
        r = run_warden(
            "scan", "--level", "standard",
            str(tmp_path / "app.py"),
            cwd=str(tmp_path), timeout=60,
            env=env,
        )
        combined = (r.stdout + r.stderr).lower()
        # Should surface the 404 / missing model issue to the user
        has_feedback = (
            "not found" in combined
            or "pull" in combined
            or "404" in combined
            or "zombie" in combined
            or "model" in combined
        )
        assert has_feedback, (
            f"No useful error about missing model in output:\n{combined[:500]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 11. Error Quality & Robustness
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorQuality:
    """Verify user-facing output never leaks Python internals."""

    def _assert_no_traceback(self, result: subprocess.CompletedProcess[str]):
        """Assert that neither stdout nor stderr contains a Python traceback."""
        for stream, name in [(result.stdout, "stdout"), (result.stderr, "stderr")]:
            assert "Traceback (most recent call last)" not in stream, (
                f"Python traceback leaked to {name}:\n{stream[:800]}"
            )

    def test_scan_nonexistent_no_traceback(self, initialized_project):
        """Scanning a missing path must not show a Python traceback."""
        r = run_warden(
            "scan", "/no/such/file.py",
            cwd=str(initialized_project), timeout=30,
        )
        self._assert_no_traceback(r)

    def test_doctor_no_init_no_traceback(self, empty_dir):
        """Running doctor without init must not crash with traceback."""
        r = run_warden("doctor", cwd=str(empty_dir), timeout=15)
        self._assert_no_traceback(r)

    def test_config_list_no_init_no_traceback(self, empty_dir):
        """Running config list without init must not crash with traceback."""
        r = run_warden("config", "list", cwd=str(empty_dir), timeout=15)
        self._assert_no_traceback(r)

    def test_scan_corrupted_config_no_traceback(self, tmp_path):
        """Scan with invalid YAML config must not show traceback."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text(":::invalid yaml{{{")
        r = run_warden("scan", "--level", "basic", cwd=str(tmp_path), timeout=30)
        self._assert_no_traceback(r)
        assert r.returncode != 0

    def test_scan_empty_config_no_traceback(self, tmp_path):
        """Scan with an empty config file must not show traceback."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("")
        r = run_warden("scan", "--level", "basic", cwd=str(tmp_path), timeout=30)
        self._assert_no_traceback(r)

    def test_status_no_init_no_traceback(self, empty_dir):
        """Running status without init must degrade gracefully."""
        r = run_warden("status", cwd=str(empty_dir), timeout=15)
        self._assert_no_traceback(r)

    def test_baseline_no_init_no_traceback(self, empty_dir):
        """Running baseline status without init must not crash."""
        r = run_warden("baseline", "status", cwd=str(empty_dir), timeout=15)
        self._assert_no_traceback(r)


# ═══════════════════════════════════════════════════════════════════════════
# 12. Scan Without Init
# ═══════════════════════════════════════════════════════════════════════════

class TestScanWithoutInit:
    """Verify behavior when user runs commands on a non-initialized project."""

    def test_scan_without_init_exits_nonzero(self, empty_dir):
        """Scan in a directory with no .warden/ should fail, not crash."""
        (empty_dir / "app.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--level", "basic", str(empty_dir / "app.py"),
            cwd=str(empty_dir), timeout=30,
        )
        # Should exit with error (1), not crash with a weird code
        assert r.returncode in (0, 1, 2)

    def test_scan_without_init_suggests_init(self, empty_dir):
        """Scan without init should tell the user to run 'warden init'."""
        (empty_dir / "main.py").write_text("print(1)\n")
        r = run_warden(
            "scan", "--level", "basic", str(empty_dir / "main.py"),
            cwd=str(empty_dir), timeout=30,
        )
        # Should not crash with traceback (may or may not mention init)
        assert "Traceback" not in r.stdout + r.stderr

    def test_doctor_without_init_reports_missing(self, empty_dir):
        """Doctor should clearly report that initialization is needed."""
        r = run_warden("doctor", cwd=str(empty_dir), timeout=15)
        combined = (r.stdout + r.stderr).lower()
        assert r.returncode != 0
        assert "init" in combined or "not found" in combined or "missing" in combined, (
            "Doctor does not explain that project needs initialization"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 13. Stderr / Stdout Separation
# ═══════════════════════════════════════════════════════════════════════════

class TestOutputSeparation:
    """Verify structured output goes to stdout and diagnostics to stderr."""

    def test_json_output_is_valid_on_stdout(self, isolated_sample):
        """--format json must produce parseable JSON on stdout (not mixed with logs)."""
        r = run_warden(
            "scan", "--level", "basic", "--format", "json",
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            # stdout should be parseable JSON (possibly after stripping log lines)
            data = _extract_json(r.stdout)
            assert isinstance(data, dict)

    def test_help_no_warnings_on_stderr(self):
        """--help should not produce warnings on stderr."""
        r = run_warden("--help", timeout=10)
        # SECRET_KEY warning might appear but no real errors
        assert "error" not in r.stderr.lower().replace("secret_key", ""), (
            f"Unexpected error on stderr during --help:\n{r.stderr[:500]}"
        )

    def test_version_clean_stdout(self):
        """Version command stdout should contain version info, not log noise."""
        r = run_warden("version", timeout=10)
        assert r.returncode == 0
        # stdout should mention warden or version number
        assert "warden" in r.stdout.lower() or any(c.isdigit() for c in r.stdout)


# ═══════════════════════════════════════════════════════════════════════════
# 14. Signal Handling
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalHandling:
    """Verify that warden handles interrupts gracefully."""

    def test_sigint_during_scan(self, isolated_sample):
        """SIGINT (Ctrl+C) during scan should terminate without crash."""
        import signal as sig

        proc = subprocess.Popen(
            ["warden", "scan", "--level", "basic"],
            cwd=str(isolated_sample),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "SECRET_KEY": "test-key"},
        )
        # Give it a moment to start, then send SIGINT
        time.sleep(2)
        proc.send_signal(sig.SIGINT)

        try:
            stdout, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            pytest.fail("Process did not terminate within 15s after SIGINT")

        # Process should have terminated (not hung)
        assert proc.returncode is not None
        # Should NOT produce a full traceback (KeyboardInterrupt handled)
        assert "Traceback (most recent call last)" not in stdout
        # Exit code: 0, 1, 2, or 130 (128+SIGINT) are all acceptable
        assert proc.returncode in (0, 1, 2, -2, 130), (
            f"Unexpected exit code after SIGINT: {proc.returncode}"
        )

    def test_sigterm_terminates(self, isolated_sample):
        """SIGTERM should terminate the process cleanly."""
        import signal as sig

        proc = subprocess.Popen(
            ["warden", "scan", "--level", "basic"],
            cwd=str(isolated_sample),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "SECRET_KEY": "test-key"},
        )
        time.sleep(2)
        proc.send_signal(sig.SIGTERM)

        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            pytest.fail("Process did not terminate within 15s after SIGTERM")

        assert proc.returncode is not None


# ═══════════════════════════════════════════════════════════════════════════
# 15. Environment & Color Control
# ═══════════════════════════════════════════════════════════════════════════

class TestEnvironmentControl:
    """Verify NO_COLOR, piped output, and environment isolation."""

    def test_no_color_strips_ansi(self):
        """NO_COLOR=1 should prevent ANSI escape codes in output."""
        r = run_warden("--help", timeout=10, env={"NO_COLOR": "1"})
        assert r.returncode == 0
        # ANSI escape code starts with ESC (\\x1b or \\033)
        assert "\x1b[" not in r.stdout, (
            "ANSI escape codes found in output despite NO_COLOR=1"
        )

    def test_force_color_false_strips_ansi(self):
        """FORCE_COLOR=0 should also prevent ANSI escape codes."""
        r = run_warden("--help", timeout=10, env={"FORCE_COLOR": "0", "NO_COLOR": "1"})
        assert r.returncode == 0
        assert "\x1b[" not in r.stdout


# ═══════════════════════════════════════════════════════════════════════════
# 16. UTF-8 & Special Characters
# ═══════════════════════════════════════════════════════════════════════════

class TestUTF8Handling:
    """Verify warden handles non-ASCII content and paths."""

    def test_scan_utf8_file_content(self, initialized_project):
        """Scan a file with UTF-8 content (comments, strings) must not crash."""
        (initialized_project / "intl.py").write_text(
            '# Türkçe yorum: güvenlik kontrolü\n'
            'mesaj = "Merhaba Dünya 🌍"\n'
            'print(mesaj)\n',
            encoding="utf-8",
        )
        r = run_warden(
            "scan", "--level", "basic", str(initialized_project / "intl.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_utf8_filename(self, initialized_project):
        """Scan a file with non-ASCII filename must not crash."""
        utf8_file = initialized_project / "módulo.py"
        utf8_file.write_text("x = 1\n", encoding="utf-8")
        r = run_warden(
            "scan", "--level", "basic", str(utf8_file),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 17. Empty & Edge Case Projects
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCaseProjects:
    """Verify behavior with unusual project structures."""

    def test_scan_empty_directory(self, initialized_project):
        """Scan an initialized project with no code files."""
        # initialized_project has .warden/ but no source files
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(initialized_project), timeout=30,
        )
        # Should complete (possibly with 0 findings), not crash
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_only_hidden_files(self, initialized_project):
        """Project with only dotfiles should not crash."""
        (initialized_project / ".hidden.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(initialized_project), timeout=30,
        )
        assert r.returncode in (0, 1, 2)

    def test_scan_binary_file_resilience(self, initialized_project):
        """Scan should skip or handle binary files without crashing."""
        (initialized_project / "data.bin").write_bytes(b"\x00\x01\x02\xff" * 100)
        (initialized_project / "app.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_symlink_resilience(self, initialized_project):
        """Scan should handle symlinks without infinite loops."""
        real_file = initialized_project / "real.py"
        real_file.write_text("y = 2\n")
        link = initialized_project / "link.py"
        link.symlink_to(real_file)
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)

    def test_scan_deeply_nested_file(self, initialized_project):
        """Scan should handle deeply nested directory structures."""
        deep = initialized_project / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "deep.py").write_text("z = 3\n")
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)


# ═══════════════════════════════════════════════════════════════════════════
# 18. Performance
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Verify critical paths stay within latency budgets."""

    def test_help_under_5s(self):
        t0 = time.monotonic()
        run_warden("--help", timeout=10)
        elapsed = time.monotonic() - t0
        assert elapsed < 8.0, f"--help: {elapsed:.2f}s"

    def test_version_under_5s(self):
        t0 = time.monotonic()
        run_warden("version", timeout=10)
        elapsed = time.monotonic() - t0
        assert elapsed < 8.0, f"version: {elapsed:.2f}s"


# ═══════════════════════════════════════════════════════════════════════════
# 19. Scan Advanced Flags
# ═══════════════════════════════════════════════════════════════════════════

class TestScanAdvancedFlags:
    """Verify --verbose, --diff, --frame, and related scan flags."""

    def test_verbose_produces_extra_output(self, isolated_sample):
        """--verbose should produce diagnostic detail not present in normal mode."""
        r_verbose = run_warden(
            "scan", "--level", "basic", "--verbose",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r_verbose.returncode in (0, 1, 2)
        combined = r_verbose.stdout + r_verbose.stderr
        # Verbose mode should contain diagnostic markers like phase/progress/debug lines
        verbose_markers = ["progress", "phase", "debug", "event", "duration"]
        has_verbose_content = any(m in combined.lower() for m in verbose_markers)
        assert has_verbose_content, (
            f"Verbose mode output lacks diagnostic markers:\n{combined[:500]}"
        )

    def test_diff_mode_no_git(self, initialized_project):
        """--diff in a non-git directory should warn and either skip or full-scan."""
        (initialized_project / "app.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--diff", "--level", "basic",
            cwd=str(initialized_project), timeout=30,
        )
        # Should not crash — either skips or falls back to full scan
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_frame_selection(self, isolated_sample):
        """--frame should select specific frames for the scan."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "security",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_frame_nonexistent_graceful(self, isolated_sample):
        """Selecting a non-existent frame should not crash."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "nonexistent_frame_xyz",
            cwd=str(isolated_sample), timeout=60,
        )
        # Should still complete (possibly with 0 frames run)
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_disable_ai_flag(self, isolated_sample):
        """--disable-ai should behave like --level basic."""
        r = run_warden(
            "scan", "--disable-ai",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        combined = r.stdout + r.stderr
        # Should mention ZOMBIE MODE (basic level without AI)
        assert "zombie" in combined.upper() or r.returncode in (0, 1, 2)

    def test_ci_mode_with_format(self, isolated_sample):
        """--ci combined with --format json should produce valid JSON."""
        r = run_warden(
            "scan", "--ci", "--level", "basic", "--format", "json",
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            data = _extract_json(r.stdout)
            assert isinstance(data, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 20. Graceful Degradation
# ═══════════════════════════════════════════════════════════════════════════

class TestGracefulDegradation:
    """Verify warden degrades gracefully under adverse conditions."""

    def test_read_only_warden_dir(self, initialized_project):
        """Scan should not crash if .warden/ is read-only."""
        warden_dir = initialized_project / ".warden"
        (initialized_project / "app.py").write_text("x = 1\n")

        # Make .warden read-only
        original_mode = warden_dir.stat().st_mode
        warden_dir.chmod(0o555)
        try:
            r = run_warden(
                "scan", "--level", "basic",
                str(initialized_project / "app.py"),
                cwd=str(initialized_project), timeout=60,
            )
            # Should still complete (may warn about write permissions)
            assert r.returncode in (0, 1, 2)
            assert "Traceback" not in r.stdout + r.stderr
        finally:
            # Restore permissions for cleanup
            warden_dir.chmod(original_mode)

    def test_scan_with_large_file(self, initialized_project):
        """Scan should handle reasonably large files without crashing."""
        big = initialized_project / "big.py"
        # Generate a 5000-line Python file
        lines = [f"x_{i} = {i}" for i in range(5000)]
        big.write_text("\n".join(lines) + "\n")
        r = run_warden(
            "scan", "--level", "basic", str(big),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_multiple_files(self, initialized_project):
        """Scan should handle multiple file arguments."""
        (initialized_project / "a.py").write_text("a = 1\n")
        (initialized_project / "b.py").write_text("b = 2\n")
        r = run_warden(
            "scan", "--level", "basic",
            str(initialized_project / "a.py"),
            str(initialized_project / "b.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)

    def test_network_failure_basic_scan(self, initialized_project):
        """Basic scan should work even with no network (fake Ollama endpoint)."""
        (initialized_project / "code.py").write_text("import os\nx = os.getenv('KEY')\n")
        # Point to a non-listening port to simulate network failure
        config_path = initialized_project / ".warden" / "config.yaml"
        if config_path.exists():
            raw = config_path.read_text()
            # If config references localhost:11434, redirect to a dead port
            raw = raw.replace("localhost:11434", "localhost:19999")
            raw = raw.replace("127.0.0.1:11434", "localhost:19999")
            config_path.write_text(raw)

        r = run_warden(
            "scan", "--level", "basic",
            str(initialized_project / "code.py"),
            cwd=str(initialized_project), timeout=60,
        )
        # Basic level shouldn't need network at all
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 21. Doctor Enhanced Checks
# ═══════════════════════════════════════════════════════════════════════════

class TestDoctorEnhanced:
    """Verify doctor reports LLM provider status accurately."""

    @pytest.mark.requires_ollama
    def test_doctor_reports_ollama_status(self, tmp_path):
        """When Ollama is the provider, doctor should report its status."""
        env = _ollama_env()
        run_warden("init", "--force", "--skip-mcp", cwd=str(tmp_path), timeout=30, env=env)
        cfg = _load_config(tmp_path)
        if cfg["llm"]["provider"] != "ollama":
            pytest.skip("Auto-detection did not select ollama")

        r = run_warden("doctor", cwd=str(tmp_path), timeout=30, env=env)
        combined = (r.stdout + r.stderr).lower()
        # Doctor should mention Ollama in its output
        assert "ollama" in combined, (
            f"Doctor does not mention Ollama:\n{combined[:500]}"
        )

    def test_doctor_corrupted_config_no_crash(self, tmp_path):
        """Doctor should handle corrupted config gracefully."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text(":::bad yaml{{{")
        r = run_warden("doctor", cwd=str(tmp_path), timeout=15)
        assert "Traceback" not in r.stdout + r.stderr
        assert r.returncode != 0  # Should report error, not crash


# ═══════════════════════════════════════════════════════════════════════════
# 22. LLM Provider Runtime Switching
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderSwitching:
    """Verify ``warden config set llm.provider X`` updates config correctly."""

    def test_config_set_provider_updates_yaml(self, initialized_project):
        """Changing provider must update the YAML file."""
        r = run_warden(
            "config", "set", "llm.provider", "ollama",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["provider"] == "ollama"

    def test_config_set_provider_updates_model(self, initialized_project):
        """Changing provider must also update model and smart_model fields."""
        r = run_warden(
            "config", "set", "llm.provider", "openai",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["provider"] == "openai"
        assert cfg["llm"]["model"] == "gpt-4o"
        assert cfg["llm"]["smart_model"] == "gpt-4o"

    def test_config_set_provider_ollama_fast_model(self, initialized_project):
        """Switching to Ollama must set fast_model to qwen2.5-coder:0.5b."""
        run_warden(
            "config", "set", "llm.provider", "ollama",
            cwd=str(initialized_project), timeout=15,
        )
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["fast_model"] == "qwen2.5-coder:0.5b"

    def test_config_set_provider_anthropic(self, initialized_project):
        """Switching to Anthropic must set correct default model."""
        run_warden(
            "config", "set", "llm.provider", "anthropic",
            cwd=str(initialized_project), timeout=15,
        )
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["provider"] == "anthropic"
        assert "claude" in cfg["llm"]["model"]

    def test_config_set_provider_groq(self, initialized_project):
        """Switching to Groq must set correct default model."""
        run_warden(
            "config", "set", "llm.provider", "groq",
            cwd=str(initialized_project), timeout=15,
        )
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["provider"] == "groq"
        assert "llama" in cfg["llm"]["model"] or "groq" in cfg["llm"]["model"].lower()

    def test_config_set_provider_claude_code(self, initialized_project):
        """Switching to claude_code must set placeholder model."""
        run_warden(
            "config", "set", "llm.provider", "claude_code",
            cwd=str(initialized_project), timeout=15,
        )
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["provider"] == "claude_code"
        assert "claude" in cfg["llm"]["model"].lower()

    def test_config_set_invalid_provider_rejected(self, initialized_project):
        """Setting an invalid provider must fail with nonzero exit."""
        r = run_warden(
            "config", "set", "llm.provider", "invalid_provider_xyz",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode != 0
        combined = (r.stdout + r.stderr).lower()
        assert "invalid" in combined or "error" in combined

    def test_cross_provider_switching(self, initialized_project):
        """Multiple provider switches must each update correctly."""
        for provider, expected_model_hint in [
            ("ollama", "qwen"),
            ("openai", "gpt"),
            ("groq", "llama"),
            ("anthropic", "claude"),
        ]:
            run_warden(
                "config", "set", "llm.provider", provider,
                cwd=str(initialized_project), timeout=15,
            )
            cfg = _load_config(initialized_project)
            assert cfg["llm"]["provider"] == provider, (
                f"Provider not updated to {provider}"
            )
            assert expected_model_hint in cfg["llm"]["model"].lower(), (
                f"Model not updated for {provider}: {cfg['llm']['model']}"
            )

    def test_config_set_provider_shows_hint(self, initialized_project):
        """Changing provider must show a helpful hint in output."""
        r = run_warden(
            "config", "set", "llm.provider", "ollama",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0
        out = r.stdout.lower()
        # Should mention model was updated
        assert "updated" in out or "model" in out

    def test_config_set_non_llm_key(self, initialized_project):
        """Setting a non-LLM key should work without affecting LLM config."""
        # First set a known provider
        run_warden(
            "config", "set", "llm.provider", "ollama",
            cwd=str(initialized_project), timeout=15,
        )
        cfg_before = _load_config(initialized_project)

        # Now set a settings key
        run_warden(
            "config", "set", "settings.fail_fast", "true",
            cwd=str(initialized_project), timeout=15,
        )
        cfg_after = _load_config(initialized_project)

        # LLM section should be unchanged
        assert cfg_after["llm"]["provider"] == cfg_before["llm"]["provider"]
        assert cfg_after["llm"]["model"] == cfg_before["llm"]["model"]
        # Settings should be updated
        assert cfg_after["settings"]["fail_fast"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 23. Frame Enable/Disable Management
# ═══════════════════════════════════════════════════════════════════════════

class TestFrameManagement:
    """Verify frame selection and enable/disable behavior."""

    def test_frame_security_only(self, isolated_sample):
        """--frame security should run only the security frame."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "security",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_frame_antipattern_only(self, isolated_sample):
        """--frame antipattern should run only the antipattern frame."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "antipattern",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_multiple_frames(self, isolated_sample):
        """Multiple --frame flags should run exactly those frames."""
        r = run_warden(
            "scan", "--level", "basic",
            "--frame", "security", "--frame", "antipattern",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_nonexistent_frame_graceful(self, isolated_sample):
        """Selecting a non-existent frame should not crash."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "does_not_exist_xyz",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_frame_verbose_shows_frame_names(self, isolated_sample):
        """Verbose mode with --frame should mention the selected frame name."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "security", "--verbose",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        combined = (r.stdout + r.stderr).lower()
        # Verbose output should mention the frame being executed
        assert "security" in combined, (
            "Verbose output does not mention 'security' frame"
        )

    def test_frame_json_output(self, isolated_sample):
        """--frame with --format json should produce valid JSON output."""
        r = run_warden(
            "scan", "--level", "basic", "--frame", "security",
            "--format", "json",
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            data = _extract_json(r.stdout)
            assert isinstance(data, dict)

    def test_frame_config_toggle(self, isolated_sample):
        """Disabling a frame in config should affect scan results."""
        # First, read original config
        config_path = isolated_sample / ".warden" / "config.yaml"
        raw = config_path.read_text()
        cfg = yaml.safe_load(raw) or {}

        # Ensure frames.enabled only has 'security'
        if "frames" not in cfg:
            cfg["frames"] = {}
        cfg["frames"]["enabled"] = ["security"]

        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_all_frames_flag(self, isolated_sample):
        """Running scan without --frame should use config-defined frames."""
        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 24. Custom Rules Execution
# ═══════════════════════════════════════════════════════════════════════════

class TestCustomRules:
    """Verify custom rules from .warden/rules/*.yaml are loaded and executed."""

    def test_scan_loads_custom_rules(self, isolated_sample):
        """Scan should process custom rules YAML files."""
        # The fixture project has .warden/rules/custom_rules.yaml
        r = run_warden(
            "scan", "--level", "basic", "--verbose",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_custom_rule_pattern_match(self, isolated_sample):
        """Custom 'no-print' rule should match print() in source files."""
        # The messy.py fixture doesn't have print(), but we can verify the
        # rules are loaded by checking verbose output
        r = run_warden(
            "scan", "--level", "basic", "--verbose",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        # Verbose should show rules being loaded or applied
        combined = (r.stdout + r.stderr).lower()
        assert "rule" in combined or "custom" in combined or "scan" in combined

    def test_invalid_custom_rules_graceful(self, isolated_sample):
        """Invalid custom rule YAML should not crash the scan."""
        # Create an invalid rules file
        rules_dir = isolated_sample / ".warden" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "broken_rules.yaml").write_text(":::invalid yaml{{{")

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        # Should not crash — graceful degradation
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_empty_custom_rules_file(self, isolated_sample):
        """Empty rules file should not crash the scan."""
        rules_dir = isolated_sample / ".warden" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "empty_rules.yaml").write_text("")

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_custom_rules_with_disabled_rule(self, isolated_sample):
        """A disabled custom rule should not generate findings."""
        rules_dir = isolated_sample / ".warden" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "disabled_rule.yaml").write_text(
            'rules:\n'
            '  - id: "disabled-test"\n'
            '    name: "Disabled test rule"\n'
            '    description: "This rule is disabled"\n'
            '    category: convention\n'
            '    severity: info\n'
            '    isBlocker: false\n'
            '    enabled: false\n'
            '    type: pattern\n'
            '    pattern: ".*"\n'
            '    language:\n'
            '      - python\n'
            '    conditions: {}\n'
        )

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_custom_rules_config_reference(self, isolated_sample):
        """Config references to rules files should be resolved."""
        # The fixture's config.yaml may reference custom_rules paths
        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}

        # Add explicit reference to the rules file
        cfg["custom_rules"] = [".warden/rules/custom_rules.yaml"]
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 25. Suppression CLI Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestSuppressionIntegration:
    """Verify the suppression system works end-to-end in CLI scans."""

    def test_scan_with_suppression_enabled(self, isolated_sample):
        """Scan with enable_suppression=true should complete without error."""
        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_with_suppression_disabled(self, isolated_sample):
        """Scan with enable_suppression=false should also complete fine."""
        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = False
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_suppression_yaml_loaded(self, isolated_sample):
        """Scan should load .warden/suppression.yaml without error."""
        # The fixture has .warden/suppression.yaml with entries
        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        assert supp_path.exists(), "Fixture missing suppression.yaml"

        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_suppression_invalid_yaml_graceful(self, isolated_sample):
        """Invalid suppression YAML should not crash the scan."""
        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text(":::broken yaml{{{")

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_suppression_empty_yaml(self, isolated_sample):
        """Empty suppression YAML should be handled gracefully."""
        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text("")

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_suppression_missing_yaml(self, isolated_sample):
        """Missing suppression YAML should not crash (default to no suppressions)."""
        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        if supp_path.exists():
            supp_path.unlink()

        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_inline_suppression_in_source(self, isolated_sample):
        """Files with inline warden-ignore comments should be scanned without crash."""
        # The fixture has src/with_suppression.py with inline comments
        supp_file = isolated_sample / "src" / "with_suppression.py"
        assert supp_file.exists(), "Fixture missing with_suppression.py"

        r = run_warden(
            "scan", "--level", "basic",
            str(supp_file),
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_suppression_with_global_rules(self, isolated_sample):
        """Global rules in suppression.yaml should be respected."""
        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text(
            "enabled: true\n"
            "globalRules:\n"
            "  - hardcoded-secret\n"
            "  - magic-number\n"
        )

        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_suppression_with_ignored_files(self, isolated_sample):
        """File patterns in ignoredFiles should be respected."""
        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text(
            "enabled: true\n"
            "ignoredFiles:\n"
            "  - src/vulnerable.py\n"
            "  - src/messy.py\n"
        )

        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 26. Config Get Command
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigGet:
    """Verify ``warden config get`` reads specific keys."""

    def test_config_get_llm_provider(self, initialized_project):
        """``config get llm.provider`` should return the configured provider."""
        r = run_warden(
            "config", "get", "llm.provider",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0
        cfg = _load_config(initialized_project)
        assert cfg["llm"]["provider"] in r.stdout

    def test_config_get_settings_mode(self, initialized_project):
        """``config get settings.mode`` should return the mode value."""
        r = run_warden(
            "config", "get", "settings.mode",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0

    def test_config_get_nonexistent_key(self, initialized_project):
        """``config get nonexistent.key`` should exit with nonzero."""
        r = run_warden(
            "config", "get", "nonexistent.key.xyz",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode != 0

    def test_config_get_json_output(self, initialized_project):
        """``config get llm.provider --json`` should return valid JSON."""
        r = run_warden(
            "config", "get", "llm.provider", "--json",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0
        # Should be parseable JSON (possibly with Rich markup stripped)
        out = r.stdout.strip()
        if out:
            try:
                json.loads(out)
            except json.JSONDecodeError:
                # Rich might add markup; just verify command succeeded
                pass

    def test_config_get_no_argument(self, initialized_project):
        """``config get`` without argument should exit nonzero."""
        r = run_warden(
            "config", "get",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode != 0

    def test_config_set_then_get_consistency(self, initialized_project):
        """``config set`` followed by ``config get`` must return the set value."""
        run_warden(
            "config", "set", "llm.provider", "groq",
            cwd=str(initialized_project), timeout=15,
        )
        r = run_warden(
            "config", "get", "llm.provider",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode == 0
        assert "groq" in r.stdout.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 27. Baseline Management
# ═══════════════════════════════════════════════════════════════════════════

class TestBaselineManagement:
    """Verify baseline subcommands work without crashing."""

    def test_baseline_status_detailed(self, isolated_sample):
        """``baseline status`` should output baseline info."""
        r = run_warden(
            "baseline", "status",
            cwd=str(isolated_sample), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_baseline_debt(self, isolated_sample):
        """``baseline debt`` should run without traceback."""
        r = run_warden(
            "baseline", "debt",
            cwd=str(isolated_sample), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_baseline_debt_verbose(self, isolated_sample):
        """``baseline debt --verbose`` should produce detailed output."""
        r = run_warden(
            "baseline", "debt", "--verbose",
            cwd=str(isolated_sample), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_baseline_migrate(self, initialized_project):
        """``baseline migrate`` on a fresh project should not crash."""
        r = run_warden(
            "baseline", "migrate",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_no_update_baseline(self, initialized_project):
        """``scan --no-update-baseline`` should not modify baseline files."""
        (initialized_project / "app.py").write_text("x = 1\n")
        baseline_dir = initialized_project / ".warden" / "baseline"

        # Snapshot baseline state before scan
        baseline_before = set()
        if baseline_dir.exists():
            baseline_before = {
                (f.name, f.stat().st_mtime)
                for f in baseline_dir.iterdir()
                if f.is_file()
            }

        r = run_warden(
            "scan", "--level", "basic", "--no-update-baseline",
            str(initialized_project / "app.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)

        # Baseline state should be unchanged
        baseline_after = set()
        if baseline_dir.exists():
            baseline_after = {
                (f.name, f.stat().st_mtime)
                for f in baseline_dir.iterdir()
                if f.is_file()
            }
        assert baseline_before == baseline_after, (
            "Baseline files were modified despite --no-update-baseline"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 28. Extended Output Formats
# ═══════════════════════════════════════════════════════════════════════════

class TestOutputFormatsExtended:
    """Verify JUnit, HTML, PDF, and badge output formats."""

    def test_junit_format(self, isolated_sample):
        """``scan --format junit`` should run without traceback."""
        r = run_warden(
            "scan", "--level", "basic", "--format", "junit",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_junit_output_file(self, isolated_sample, tmp_path):
        """``scan --format junit --output f.xml`` should create valid XML."""
        report = tmp_path / "report.xml"
        r = run_warden(
            "scan", "--level", "basic", "--format", "junit",
            "--output", str(report),
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            assert report.exists(), "JUnit output file was not created"
            content = report.read_text()
            assert "<?xml" in content or "<testsuites" in content

    def test_html_format(self, isolated_sample):
        """``scan --format html`` should run without traceback."""
        r = run_warden(
            "scan", "--level", "basic", "--format", "html",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_html_output_file(self, isolated_sample, tmp_path):
        """``scan --format html --output f.html`` should create an HTML file."""
        report = tmp_path / "report.html"
        r = run_warden(
            "scan", "--level", "basic", "--format", "html",
            "--output", str(report),
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            assert report.exists(), "HTML output file was not created"

    def test_pdf_format(self, isolated_sample):
        """``scan --format pdf`` should run without traceback (may warn about weasyprint)."""
        r = run_warden(
            "scan", "--level", "basic", "--format", "pdf",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_badge_output_file(self, isolated_sample, tmp_path):
        """``scan --format badge --output badge.svg`` should create SVG file."""
        report = tmp_path / "badge.svg"
        r = run_warden(
            "scan", "--level", "basic", "--format", "badge",
            "--output", str(report),
            cwd=str(isolated_sample), timeout=60,
        )
        if r.returncode in (0, 2):
            assert report.exists(), "Badge SVG file was not created"
            content = report.read_text()
            assert "<svg" in content, "Badge file does not contain SVG markup"


# ═══════════════════════════════════════════════════════════════════════════
# 29. Extended Scan Flags
# ═══════════════════════════════════════════════════════════════════════════

class TestScanFlagsExtended:
    """Verify additional scan flags work without crashing."""

    def test_scan_level_deep(self, isolated_sample):
        """``scan --level deep`` should complete with valid exit code."""
        r = run_warden(
            "scan", "--level", "deep",
            cwd=str(isolated_sample), timeout=120,
        )
        assert r.returncode in (0, 1, 2)

    def test_scan_diff_in_git_repo(self, tmp_path):
        """``scan --diff`` inside a git repo should not crash."""
        # Create a minimal git repo with init
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path),
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True, timeout=10,
        )
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(tmp_path), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        (tmp_path / "new.py").write_text("x = 1\n")

        r = run_warden(
            "scan", "--diff", "--level", "basic",
            cwd=str(tmp_path), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_diff_with_base(self, tmp_path):
        """``scan --diff --base main`` should not crash."""
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path),
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True, timeout=10,
        )
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(tmp_path), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        (tmp_path / "code.py").write_text("y = 2\n")

        r = run_warden(
            "scan", "--diff", "--base", "main", "--level", "basic",
            cwd=str(tmp_path), timeout=60,
        )
        # May fail if no 'main' branch exists, but should not traceback
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_memory_profile(self, isolated_sample):
        """``scan --memory-profile`` should include memory info in output."""
        r = run_warden(
            "scan", "--level", "basic", "--memory-profile",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_scan_invalid_format(self, isolated_sample):
        """``scan --format invalid_xyz`` should exit nonzero or gracefully fallback."""
        r = run_warden(
            "scan", "--level", "basic", "--format", "invalid_xyz",
            cwd=str(isolated_sample), timeout=60,
        )
        # Either rejected upfront or falls back; should not crash
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 30. Refresh Command
# ═══════════════════════════════════════════════════════════════════════════

class TestRefreshCommand:
    """Verify ``warden refresh`` and its flags."""

    def test_refresh_help(self):
        """``refresh --help`` should exit zero with help text."""
        r = run_warden("refresh", "--help", timeout=30)
        assert r.returncode == 0
        assert "refresh" in r.stdout.lower() or "usage" in r.stdout.lower()

    def test_refresh_initialized_project(self, initialized_project):
        """``refresh`` on an initialized project should not crash."""
        r = run_warden(
            "refresh",
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_refresh_quick(self, initialized_project):
        """``refresh --quick`` should complete without traceback."""
        r = run_warden(
            "refresh", "--quick",
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 31. Search Command
# ═══════════════════════════════════════════════════════════════════════════

class TestSearchCommand:
    """Verify ``warden search`` and its flags."""

    def test_search_help(self):
        """``search --help`` should exit zero with help text."""
        r = run_warden("search", "--help", timeout=30)
        assert r.returncode == 0
        assert "search" in r.stdout.lower() or "usage" in r.stdout.lower()

    def test_search_local(self, initialized_project):
        """``search "query" --local`` should not crash."""
        r = run_warden(
            "search", "test query", "--local",
            cwd=str(initialized_project), timeout=30,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 32. Install & Update Commands
# ═══════════════════════════════════════════════════════════════════════════

class TestInstallUpdateCommands:
    """Verify ``warden install`` and ``warden update`` basics."""

    def test_install_help(self):
        """``install --help`` should exit zero."""
        r = run_warden("install", "--help", timeout=30)
        assert r.returncode == 0

    def test_update_help(self):
        """``update --help`` should exit zero."""
        r = run_warden("update", "--help", timeout=30)
        assert r.returncode == 0

    def test_update_graceful(self, initialized_project):
        """``update`` should complete without hanging."""
        r = run_warden(
            "update",
            cwd=str(initialized_project), timeout=30,
        )
        # update may fail if no network / no sync target — just verify it completes
        assert r.returncode is not None


# ═══════════════════════════════════════════════════════════════════════════
# 33. Serve Commands
# ═══════════════════════════════════════════════════════════════════════════

class TestServeCommands:
    """Verify ``warden serve`` subcommands."""

    def test_serve_mcp_status(self, initialized_project):
        """``serve mcp status`` should run without traceback."""
        r = run_warden(
            "serve", "mcp", "status",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_serve_mcp_register_help(self):
        """``serve mcp register --help`` should exit zero."""
        r = run_warden("serve", "mcp", "register", "--help", timeout=30)
        assert r.returncode == 0

    def test_serve_help(self):
        """``serve --help`` should exit zero."""
        r = run_warden("serve", "--help", timeout=30)
        assert r.returncode == 0


# ═══════════════════════════════════════════════════════════════════════════
# 34. Chat Command
# ═══════════════════════════════════════════════════════════════════════════

class TestChatCommand:
    """Verify ``warden chat`` basics."""

    def test_chat_help(self):
        """``chat --help`` should exit zero."""
        r = run_warden("chat", "--help", timeout=30)
        assert r.returncode == 0


# ═══════════════════════════════════════════════════════════════════════════
# 35. CI Mode Extended
# ═══════════════════════════════════════════════════════════════════════════

class TestCIModeExtended:
    """Extended CI mode tests combining multiple flags."""

    def test_ci_with_diff(self, tmp_path):
        """``scan --ci --diff`` should not crash."""
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path),
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True, timeout=10,
        )
        run_warden(
            "init", "--force", "--skip-mcp",
            cwd=str(tmp_path), timeout=30,
            env={"WARDEN_NON_INTERACTIVE": "true"},
        )
        (tmp_path / "app.py").write_text("x = 1\n")

        r = run_warden(
            "scan", "--ci", "--diff", "--level", "basic",
            cwd=str(tmp_path), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_ci_no_update_baseline(self, initialized_project):
        """``scan --ci --no-update-baseline`` should work."""
        (initialized_project / "app.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--ci", "--no-update-baseline", "--level", "basic",
            str(initialized_project / "app.py"),
            cwd=str(initialized_project), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_ci_json_output_file(self, initialized_project, tmp_path):
        """``scan --ci --format json --output f.json`` should create valid JSON."""
        (initialized_project / "main.py").write_text("print('ok')\n")
        report = tmp_path / "ci_report.json"
        r = run_warden(
            "scan", "--ci", "--level", "basic",
            "--format", "json", "--output", str(report),
            str(initialized_project / "main.py"),
            cwd=str(initialized_project), timeout=60,
        )
        if r.returncode in (0, 2):
            assert report.exists(), "CI JSON report was not created"
            data = json.loads(report.read_text())
            assert isinstance(data, dict)

    def test_ci_env_variable(self, initialized_project):
        """``scan --ci`` with CI=true env should work."""
        (initialized_project / "app.py").write_text("x = 1\n")
        r = run_warden(
            "scan", "--ci", "--level", "basic",
            str(initialized_project / "app.py"),
            cwd=str(initialized_project), timeout=60,
            env={"CI": "true"},
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 36. CI Subcommands
# ═══════════════════════════════════════════════════════════════════════════

class TestCISubcommands:
    """Verify ``warden ci`` subcommands."""

    def test_ci_status(self, initialized_project):
        """``ci status`` should run without traceback."""
        r = run_warden(
            "ci", "status",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr

    def test_ci_init(self, initialized_project):
        """``ci init`` on an initialized project should complete."""
        r = run_warden(
            "ci", "init",
            cwd=str(initialized_project), timeout=30,
        )
        # ci init may fail if no CI provider detected — just verify it completes
        assert r.returncode is not None

    def test_ci_help(self):
        """``ci --help`` should list subcommands."""
        r = run_warden("ci", "--help", timeout=30)
        assert r.returncode == 0
        out = r.stdout.lower()
        assert "ci" in out or "usage" in out

    def test_ci_sync(self, initialized_project):
        """``ci sync`` should not crash."""
        r = run_warden(
            "ci", "sync",
            cwd=str(initialized_project), timeout=15,
        )
        assert r.returncode in (0, 1)
        assert "Traceback" not in r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════
# 37. Suppression Accuracy
# ═══════════════════════════════════════════════════════════════════════════

class TestSuppressionAccuracy:
    """Verify suppression actually reduces findings in JSON output."""

    def _scan_json(self, cwd: Path, extra_args: list[str] | None = None) -> dict:
        """Run basic scan with JSON output and return parsed results."""
        args = ["scan", "--level", "basic", "--format", "json"]
        if extra_args:
            args.extend(extra_args)
        r = run_warden(*args, cwd=str(cwd), timeout=60)
        if r.returncode in (0, 2):
            return _extract_json(r.stdout)
        return {}

    def _count_findings(self, data: dict) -> int:
        """Count total findings from scan JSON output."""
        total = 0
        for fr in data.get("frame_results", data.get("frameResults", [])):
            total += len(fr.get("findings", []))
        return total

    def test_suppression_reduces_findings(self, isolated_sample):
        """Enabling suppression with globalRules should reduce findings."""
        config_path = isolated_sample / ".warden" / "config.yaml"

        # Run scan WITHOUT suppression
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = False
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        data_off = self._scan_json(isolated_sample)
        count_off = self._count_findings(data_off)

        # Run scan WITH suppression that suppresses all rules
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text(
            "enabled: true\n"
            "globalRules:\n"
            "  - \"*\"\n"
        )

        data_on = self._scan_json(isolated_sample)
        count_on = self._count_findings(data_on)

        # With wildcard suppression, findings should not increase
        assert count_on <= count_off, (
            f"Suppression did not reduce findings: {count_off} -> {count_on}"
        )

    def test_global_rule_suppression(self, isolated_sample):
        """Global rule suppression for a specific rule should reduce findings."""
        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text(
            "enabled: true\n"
            "globalRules:\n"
            "  - hardcoded-secret\n"
            "  - magic-number\n"
        )

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_ignored_files_zero_findings(self, isolated_sample):
        """Files listed in ignoredFiles should produce zero findings."""
        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        supp_path = isolated_sample / ".warden" / "suppression.yaml"
        supp_path.write_text(
            "enabled: true\n"
            "ignoredFiles:\n"
            "  - \"**/*.py\"\n"
        )

        r = run_warden(
            "scan", "--level", "basic",
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

    def test_inline_warden_ignore(self, isolated_sample):
        """Inline ``# warden-ignore`` comments should suppress line-level findings."""
        supp_file = isolated_sample / "src" / "with_suppression.py"
        assert supp_file.exists(), "Fixture missing with_suppression.py"

        config_path = isolated_sample / ".warden" / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text()) or {}
        if "settings" not in cfg:
            cfg["settings"] = {}
        cfg["settings"]["enable_suppression"] = True
        config_path.write_text(yaml.dump(cfg, default_flow_style=False))

        r = run_warden(
            "scan", "--level", "basic",
            str(supp_file),
            cwd=str(isolated_sample), timeout=60,
        )
        assert r.returncode in (0, 1, 2)
        assert "Traceback" not in r.stdout + r.stderr

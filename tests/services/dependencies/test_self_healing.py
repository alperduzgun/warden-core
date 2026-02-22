"""
Tests for warden.services.dependencies.self_healing (backward compatibility)

Verifies the backward-compatible wrapper still works. The actual logic
has been moved to warden.self_healing module.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.services.dependencies.self_healing import (
    DiagnosticResult,
    ErrorCategory,
    SelfHealingDiagnostic,
    _IMPORT_TO_PIP,
    reset_heal_attempts,
)


@pytest.fixture(autouse=True)
def _reset_attempts(tmp_path):
    """Reset healing attempt counters before each test."""
    reset_heal_attempts()
    # Patch Path.cwd so orchestrator uses tmp_path (avoids cache pollution)
    original_cwd = _Path.cwd
    _Path.cwd = staticmethod(lambda: tmp_path)
    yield
    _Path.cwd = original_cwd
    reset_heal_attempts()


from pathlib import Path as _Path  # noqa: E402


# ── Error Classification ──────────────────────────────────────────────────


class TestClassifyError:
    """Test error type classification."""

    def test_module_not_found_error(self):
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named 'tiktoken'")
        assert diag._classify_error(err) == ErrorCategory.MODULE_NOT_FOUND

    def test_import_error(self):
        diag = SelfHealingDiagnostic()
        err = ImportError("cannot import name 'foo' from 'bar'")
        assert diag._classify_error(err) == ErrorCategory.IMPORT_ERROR

    def test_permission_error(self):
        diag = SelfHealingDiagnostic()
        err = PermissionError("Permission denied: '/etc/shadow'")
        assert diag._classify_error(err) == ErrorCategory.PERMISSION_ERROR

    def test_timeout_error(self):
        diag = SelfHealingDiagnostic()
        err = TimeoutError("connection timed out")
        assert diag._classify_error(err) == ErrorCategory.TIMEOUT

    def test_timeout_in_message(self):
        diag = SelfHealingDiagnostic()
        err = Exception("Operation timed out after 30s")
        assert diag._classify_error(err) == ErrorCategory.TIMEOUT

    def test_external_service_error(self):
        diag = SelfHealingDiagnostic()
        err = ConnectionRefusedError("Connection refused")
        assert diag._classify_error(err) == ErrorCategory.EXTERNAL_SERVICE

    def test_external_service_in_message(self):
        diag = SelfHealingDiagnostic()
        err = Exception("503 Service Unavailable")
        assert diag._classify_error(err) == ErrorCategory.EXTERNAL_SERVICE

    def test_rate_limit_error(self):
        diag = SelfHealingDiagnostic()
        err = Exception("rate limit exceeded")
        assert diag._classify_error(err) == ErrorCategory.EXTERNAL_SERVICE

    def test_config_error(self):
        diag = SelfHealingDiagnostic()
        err = Exception("invalid config value for 'provider'")
        assert diag._classify_error(err) == ErrorCategory.CONFIG_ERROR

    def test_key_error_as_config(self):
        diag = SelfHealingDiagnostic()
        err = KeyError("missing key 'api_key'")
        assert diag._classify_error(err) == ErrorCategory.CONFIG_ERROR

    def test_unknown_error(self):
        diag = SelfHealingDiagnostic()
        err = RuntimeError("something unexpected happened")
        assert diag._classify_error(err) == ErrorCategory.UNKNOWN


# ── Module Extraction ─────────────────────────────────────────────────────


class TestExtractModule:
    """Test module name extraction from ImportError messages."""

    def test_no_module_named(self):
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named 'tiktoken'")
        assert diag._extract_module_from_import_error(err) == "tiktoken"

    def test_no_module_named_dotted(self):
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named 'sentence_transformers.util'")
        assert diag._extract_module_from_import_error(err) == "sentence_transformers"

    def test_no_module_named_no_quotes(self):
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named tiktoken")
        assert diag._extract_module_from_import_error(err) == "tiktoken"

    def test_cannot_import_name(self):
        diag = SelfHealingDiagnostic()
        err = ImportError("cannot import name 'Tokenizer' from 'tiktoken'")
        assert diag._extract_module_from_import_error(err) == "Tokenizer"

    def test_unrecognized_message(self):
        diag = SelfHealingDiagnostic()
        err = ImportError("something weird happened")
        assert diag._extract_module_from_import_error(err) is None


# ── LLM Response Parsing ─────────────────────────────────────────────────


class TestParseLlmFix:
    """Test extracting package names from LLM diagnosis text."""

    def test_install_directive(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "INSTALL: tiktoken"
        assert diag._parse_llm_fix(diagnosis) == ["tiktoken"]

    def test_multiple_install_directives(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "INSTALL: tiktoken\nINSTALL: sentence-transformers"
        assert diag._parse_llm_fix(diagnosis) == ["tiktoken", "sentence-transformers"]

    def test_pip_install_in_text(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "You should run: pip install tiktoken"
        assert diag._parse_llm_fix(diagnosis) == ["tiktoken"]

    def test_both_formats(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "INSTALL: tiktoken\nAlternatively, pip install pyyaml"
        result = diag._parse_llm_fix(diagnosis)
        assert "tiktoken" in result
        assert "pyyaml" in result

    def test_no_packages_found(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "The error is caused by a misconfiguration in your YAML file."
        assert diag._parse_llm_fix(diagnosis) == []

    def test_deduplicates_packages(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "INSTALL: tiktoken\npip install tiktoken"
        assert diag._parse_llm_fix(diagnosis) == ["tiktoken"]

    def test_install_with_extras(self):
        diag = SelfHealingDiagnostic()
        diagnosis = "INSTALL: transformers[torch]"
        assert diag._parse_llm_fix(diagnosis) == ["transformers[torch]"]


# ── Static Install ────────────────────────────────────────────────────────


class TestTryPipInstall:
    """Test pip install safety and execution."""

    def test_rejects_unsafe_names(self):
        diag = SelfHealingDiagnostic()
        assert diag._try_pip_install("rm -rf /") is False
        assert diag._try_pip_install("pkg; echo pwned") is False
        assert diag._try_pip_install("") is False

    def test_accepts_valid_names(self):
        diag = SelfHealingDiagnostic()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert diag._try_pip_install("tiktoken") is True

    @patch("subprocess.run")
    def test_install_failure_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"error")
        diag = SelfHealingDiagnostic()
        assert diag._try_pip_install("nonexistent-package") is False

    @patch("subprocess.run", side_effect=Exception("subprocess failed"))
    def test_install_exception_returns_false(self, mock_run):
        diag = SelfHealingDiagnostic()
        assert diag._try_pip_install("bad-package") is False


# ── Full Diagnosis Flow ──────────────────────────────────────────────────


class TestDiagnoseAndFix:
    """Test end-to-end diagnosis and fix flow."""

    @pytest.mark.asyncio
    async def test_import_error_static_fix(self):
        """ImportError with known module should attempt static pip install."""
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named 'tiktoken'")

        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=True,
        ):
            result = await diag.diagnose_and_fix(err, context="scan")

        assert result.fixed is True
        assert result.should_retry is True
        assert "tiktoken" in result.packages_installed

    @pytest.mark.asyncio
    async def test_import_error_with_pip_name_mapping(self):
        """Import name should be mapped to pip name from _IMPORT_TO_PIP."""
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named 'yaml'")

        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=True,
        ):
            result = await diag.diagnose_and_fix(err, context="scan")

        assert result.fixed is True

    @pytest.mark.asyncio
    async def test_import_error_static_fail_llm_success(self):
        """When static install fails, should fall through to LLM diagnosis."""
        diag = SelfHealingDiagnostic()
        err = ModuleNotFoundError("No module named 'obscure_pkg'")

        call_count = 0

        def side_effect(pkg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False  # Static install fails
            return True  # LLM-suggested install succeeds

        with (
            patch(
                "warden.self_healing.strategies.import_healer._try_pip_install",
                side_effect=side_effect,
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._try_pip_install",
                side_effect=side_effect,
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value="INSTALL: obscure-pkg",
            ),
        ):
            result = await diag.diagnose_and_fix(err, context="scan")

        assert result.fixed is True
        assert "obscure-pkg" in result.packages_installed

    @pytest.mark.asyncio
    async def test_timeout_error_no_llm_call(self):
        """Timeout errors should return fast without calling LLM."""
        diag = SelfHealingDiagnostic()
        err = TimeoutError("connection timed out")

        result = await diag.diagnose_and_fix(err)

        assert result.fixed is False
        assert result.error_category == ErrorCategory.TIMEOUT
        assert "timed out" in result.diagnosis.lower()

    @pytest.mark.asyncio
    async def test_external_service_error_no_llm_call(self):
        """External service errors should return fast without calling LLM."""
        diag = SelfHealingDiagnostic()
        err = ConnectionRefusedError("Connection refused")

        result = await diag.diagnose_and_fix(err)

        assert result.fixed is False
        assert result.error_category == ErrorCategory.EXTERNAL_SERVICE

    @pytest.mark.asyncio
    async def test_permission_error_no_llm_call(self):
        """Permission errors should return fast without calling LLM."""
        diag = SelfHealingDiagnostic()
        err = PermissionError("Permission denied")

        result = await diag.diagnose_and_fix(err)

        assert result.fixed is False
        assert result.error_category == ErrorCategory.PERMISSION_ERROR

    @pytest.mark.asyncio
    async def test_unknown_error_llm_diagnosis(self):
        """Unknown errors should be sent to LLM for diagnosis."""
        diag = SelfHealingDiagnostic()
        err = RuntimeError("something strange happened")

        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value="The error is caused by a corrupted cache. Delete .warden/cache/ and retry.",
        ):
            result = await diag.diagnose_and_fix(err)

        assert result.fixed is False
        assert "corrupted cache" in result.diagnosis

    @pytest.mark.asyncio
    async def test_unknown_error_llm_suggests_package(self):
        """LLM diagnosis with INSTALL: directive should trigger pip install."""
        diag = SelfHealingDiagnostic()
        err = RuntimeError("something that needs a package")

        with (
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value="INSTALL: some-tool",
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._try_pip_install",
                return_value=True,
            ),
        ):
            result = await diag.diagnose_and_fix(err)

        assert result.fixed is True
        assert "some-tool" in result.packages_installed

    @pytest.mark.asyncio
    async def test_llm_unavailable_fallback(self):
        """When LLM is unavailable, should return generic diagnosis."""
        diag = SelfHealingDiagnostic()
        err = RuntimeError("unknown failure")

        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value=None,
        ):
            result = await diag.diagnose_and_fix(err)

        assert result.fixed is False
        assert "RuntimeError" in result.diagnosis
        assert result.suggested_action is not None

    @pytest.mark.asyncio
    async def test_max_attempts_protection(self):
        """Should stop retrying after max attempts reached."""
        diag = SelfHealingDiagnostic(max_attempts=1)
        err = ModuleNotFoundError("No module named 'tiktoken'")

        with (
            patch(
                "warden.self_healing.strategies.import_healer._try_pip_install",
                return_value=False,
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value=None,
            ),
        ):
            result1 = await diag.diagnose_and_fix(err)
            result2 = await diag.diagnose_and_fix(err)

        assert "Max healing attempts" in result2.diagnosis
        assert result2.fixed is False

    @pytest.mark.asyncio
    async def test_different_errors_have_separate_counters(self):
        """Different errors should have independent attempt counters."""
        diag = SelfHealingDiagnostic(max_attempts=1)
        err1 = ModuleNotFoundError("No module named 'pkg_a'")
        err2 = ModuleNotFoundError("No module named 'pkg_b'")

        with (
            patch(
                "warden.self_healing.strategies.import_healer._try_pip_install",
                return_value=False,
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value=None,
            ),
        ):
            result1 = await diag.diagnose_and_fix(err1)
            result2 = await diag.diagnose_and_fix(err2)

        assert "Max healing attempts" not in result1.diagnosis
        assert "Max healing attempts" not in result2.diagnosis


# ── LLM Diagnosis ────────────────────────────────────────────────────────


class TestAskLlmDiagnosis:
    """Test LLM interaction for error diagnosis."""

    @pytest.mark.asyncio
    async def test_llm_called_with_correct_prompt(self):
        """LLM should receive error details in the prompt."""
        diag = SelfHealingDiagnostic()
        err = RuntimeError("test error")

        mock_response = MagicMock()
        mock_response.content = "INSTALL: test-pkg"

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = True
        mock_client.complete_async.return_value = mock_response

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await diag._ask_llm_diagnosis(err, "traceback text", "test context")

        assert result == "INSTALL: test-pkg"
        mock_client.complete_async.assert_called_once()
        call_kwargs = mock_client.complete_async.call_args
        prompt = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("prompt", "")
        assert "RuntimeError" in prompt
        assert "test error" in prompt

    @pytest.mark.asyncio
    async def test_llm_unavailable_returns_none(self):
        """Should return None if LLM is not available."""
        diag = SelfHealingDiagnostic()
        err = RuntimeError("test")

        mock_client = AsyncMock()
        mock_client.is_available_async.return_value = False

        with patch("warden.llm.factory.create_client", return_value=mock_client):
            result = await diag._ask_llm_diagnosis(err, "tb", "ctx")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        """Should return None if LLM raises an exception."""
        diag = SelfHealingDiagnostic()
        err = RuntimeError("test")

        with patch(
            "warden.llm.factory.create_client",
            side_effect=Exception("LLM factory failed"),
        ):
            result = await diag._ask_llm_diagnosis(err, "tb", "ctx")

        assert result is None


# ── Import-to-Pip Mapping ────────────────────────────────────────────────


class TestImportToPipMapping:
    """Test the _IMPORT_TO_PIP dictionary."""

    def test_common_mappings_exist(self):
        assert _IMPORT_TO_PIP["yaml"] == "pyyaml"
        assert _IMPORT_TO_PIP["cv2"] == "opencv-python"
        assert _IMPORT_TO_PIP["PIL"] == "Pillow"
        assert _IMPORT_TO_PIP["sklearn"] == "scikit-learn"
        assert _IMPORT_TO_PIP["bs4"] == "beautifulsoup4"

    def test_all_values_are_strings(self):
        for key, value in _IMPORT_TO_PIP.items():
            assert isinstance(key, str)
            assert isinstance(value, str)


# ── resolve_with_llm Bridge ──────────────────────────────────────────────


class TestResolveWithLlm:
    """Test the bridge function in auto_resolver."""

    @pytest.mark.asyncio
    async def test_bridge_delegates_to_diagnostic(self):
        from warden.services.dependencies.auto_resolver import resolve_with_llm

        err = ModuleNotFoundError("No module named 'tiktoken'")

        with patch(
            "warden.self_healing.SelfHealingOrchestrator"
        ) as MockDiag:
            mock_instance = AsyncMock()
            mock_instance.diagnose_and_fix.return_value = DiagnosticResult(
                fixed=True,
                diagnosis="Installed tiktoken",
                packages_installed=["tiktoken"],
                should_retry=True,
            )
            MockDiag.return_value = mock_instance

            result = await resolve_with_llm(err, context="test")

        assert result.fixed is True
        mock_instance.diagnose_and_fix.assert_called_once()

    @pytest.mark.asyncio
    async def test_bridge_handles_exception(self):
        from warden.services.dependencies.auto_resolver import resolve_with_llm

        err = RuntimeError("test")

        with patch(
            "warden.self_healing.SelfHealingOrchestrator",
            side_effect=Exception("factory broke"),
        ):
            result = await resolve_with_llm(err)

        assert result.fixed is False
        assert "Self-healing unavailable" in result.diagnosis


# ── DiagnosticResult ─────────────────────────────────────────────────────


class TestDiagnosticResult:
    """Test DiagnosticResult dataclass."""

    def test_defaults(self):
        result = DiagnosticResult()
        assert result.fixed is False
        assert result.diagnosis == ""
        assert result.packages_installed == []
        assert result.should_retry is False
        assert result.suggested_action is None
        assert result.error_category == ErrorCategory.UNKNOWN

    def test_custom_values(self):
        result = DiagnosticResult(
            fixed=True,
            diagnosis="Fixed it",
            packages_installed=["pkg1", "pkg2"],
            should_retry=True,
            suggested_action="Run again",
            error_category=ErrorCategory.IMPORT_ERROR,
        )
        assert result.fixed is True
        assert len(result.packages_installed) == 2
        assert result.error_category == ErrorCategory.IMPORT_ERROR

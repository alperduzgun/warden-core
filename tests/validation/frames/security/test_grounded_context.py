"""Tests for Codebase-Grounded LLM Analysis (Tier 2 Enhancement).

Covers:
  T1.1 - Framework detection appears in LLM prompt context
  T1.2 - Dependency graph (forward/reverse) appears in LLM prompt context
  T1.3 - Batch processor accepts and passes through semantic_context
  T2.1 - Code graph symbols for the analysed file appear in LLM prompt context
  T2.2 - Taint paths with transformations/sanitizers are formatted with full detail
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analysis.domain.code_graph import CodeGraph, EdgeRelation, SymbolEdge, SymbolKind, SymbolNode
from warden.pipeline.domain.intelligence import ProjectIntelligence
from warden.validation.domain.frame import CodeFile, Finding
from warden.validation.frames.security.frame import SecurityFrame
from warden.validation.frames.security.batch_processor import (
    batch_verify_security_findings,
    _verify_security_batch,
)

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

SIMPLE_PYTHON_CODE = """\
import sqlite3

def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    conn = sqlite3.connect("mydb.db")
    cursor = conn.cursor()
    cursor.execute(query)
    return cursor.fetchone()
"""


def _make_code_file(path: str = "src/app.py", content: str = SIMPLE_PYTHON_CODE) -> CodeFile:
    return CodeFile(path=path, content=content, language="python")


def _make_security_frame() -> SecurityFrame:
    """Create a SecurityFrame bypassing the internal check registration."""
    frame = SecurityFrame.__new__(SecurityFrame)
    frame.frame_id = "security"
    frame.name = "Security Analysis"
    frame.config = {}
    frame._taint_paths = {}
    # Provide a minimal checks registry so execute_async doesn't crash
    from warden.validation.domain.check import CheckRegistry

    frame.checks = CheckRegistry()
    return frame


def _make_mock_context(
    *,
    forward: dict[str, list[str]] | None = None,
    reverse: dict[str, list[str]] | None = None,
    code_graph: CodeGraph | None = None,
    project_root: Path | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics PipelineContext fields."""
    ctx = MagicMock()
    ctx.dependency_graph_forward = forward or {}
    ctx.dependency_graph_reverse = reverse or {}
    ctx.code_graph = code_graph
    ctx.project_root = project_root
    ctx.taint_paths = {}
    return ctx


def _make_llm_service(findings: list[dict] | None = None) -> AsyncMock:
    """Return an AsyncMock that emulates llm_service.analyze_security_async."""
    svc = AsyncMock()
    svc.analyze_security_async = AsyncMock(return_value={"findings": findings or []})
    return svc


def _make_project_intelligence(
    *,
    frameworks: list[str] | None = None,
    entry_points: list[str] | None = None,
    auth_patterns: list[str] | None = None,
    critical_sinks: list[str] | None = None,
) -> ProjectIntelligence:
    pi = ProjectIntelligence()
    pi.detected_frameworks = frameworks or []
    pi.entry_points = entry_points or []
    pi.auth_patterns = auth_patterns or []
    pi.critical_sinks = critical_sinks or []
    return pi


# ---------------------------------------------------------------------------
# Taint mock helpers
# ---------------------------------------------------------------------------


@dataclass
class _MockTaintSource:
    name: str
    node_type: str = "call"
    line: int = 5
    confidence: float = 0.9


@dataclass
class _MockTaintSink:
    name: str
    sink_type: str = "SQL-value"
    line: int = 20


@dataclass
class _MockTaintPath:
    source: _MockTaintSource
    sink: _MockTaintSink
    transformations: list[str] = field(default_factory=list)
    sanitizers: list[str] = field(default_factory=list)
    is_sanitized: bool = False
    confidence: float = 0.85

    @property
    def sink_type(self) -> str:
        return self.sink.sink_type

    def to_json(self) -> dict:
        return {
            "source": {"name": self.source.name, "line": self.source.line},
            "sink": {"name": self.sink.name, "type": self.sink_type, "line": self.sink.line},
            "transformations": self.transformations,
            "sanitizers": self.sanitizers,
            "is_sanitized": self.is_sanitized,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# T1.1 – Framework Detection in LLM Prompts
# ---------------------------------------------------------------------------


class TestT1_1_FrameworkDetection:
    """Framework names must reach the LLM prompt when ProjectIntelligence is set."""

    @pytest.mark.asyncio
    async def test_framework_appears_in_llm_prompt(self):
        """detect_frameworks list is embedded verbatim in the prompt text."""
        frame = _make_security_frame()
        frame.project_intelligence = _make_project_intelligence(
            frameworks=["flask", "sqlalchemy"],
        )
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file()
        ctx = _make_mock_context()

        # Stub heavy helpers so only the LLM call path runs
        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        call_args = frame.llm_service.analyze_security_async.call_args
        assert call_args is not None, "analyze_security_async was not called"
        prompt_text: str = call_args[0][0]  # first positional arg is the prompt
        assert "flask" in prompt_text
        assert "sqlalchemy" in prompt_text

    @pytest.mark.asyncio
    async def test_framework_label_present_in_prompt(self):
        """The 'Framework:' label must appear in the prompt section."""
        frame = _make_security_frame()
        frame.project_intelligence = _make_project_intelligence(
            frameworks=["django"],
        )
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Framework:" in prompt_text
        assert "django" in prompt_text

    @pytest.mark.asyncio
    async def test_no_framework_section_when_empty(self):
        """When no frameworks are detected the 'Framework:' section is absent."""
        frame = _make_security_frame()
        frame.project_intelligence = _make_project_intelligence(frameworks=[])
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Framework:" not in prompt_text

    @pytest.mark.asyncio
    async def test_no_project_intelligence_attribute_does_not_crash(self):
        """Frame without project_intelligence attribute runs cleanly."""
        frame = _make_security_frame()
        # Deliberately do NOT set frame.project_intelligence
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            result = await frame.execute_async(code_file, context=ctx)

        assert result is not None


# ---------------------------------------------------------------------------
# T1.2 – Dependency Graph Context in LLM Prompts
# ---------------------------------------------------------------------------


class TestT1_2_DependencyGraphContext:
    """Dependency graph forward/reverse edges must appear in the prompt."""

    @pytest.mark.asyncio
    async def test_forward_deps_appear_in_prompt(self):
        """'Depends on:' line is present when forward deps exist for the file."""
        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path="src/app.py")
        ctx = _make_mock_context(
            forward={"src/app.py": ["src/db.py", "src/models.py"]},
            reverse={},
            project_root=None,
        )

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Depends on:" in prompt_text
        assert "src/db.py" in prompt_text

    @pytest.mark.asyncio
    async def test_reverse_deps_appear_in_prompt(self):
        """'Depended by:' line is present when reverse deps exist for the file."""
        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path="src/auth.py")
        ctx = _make_mock_context(
            forward={},
            reverse={"src/auth.py": ["src/api.py", "src/views.py"]},
            project_root=None,
        )

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Depended by:" in prompt_text
        assert "src/api.py" in prompt_text

    @pytest.mark.asyncio
    async def test_both_directions_appear_when_present(self):
        """Both forward and reverse edges appear together in the prompt."""
        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path="src/service.py")
        ctx = _make_mock_context(
            forward={"src/service.py": ["src/repo.py"]},
            reverse={"src/service.py": ["src/router.py"]},
        )

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Depends on:" in prompt_text
        assert "Depended by:" in prompt_text

    @pytest.mark.asyncio
    async def test_no_dep_section_when_file_not_in_graph(self):
        """No dep lines appear when the analysed file has no graph entries."""
        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path="src/orphan.py")
        ctx = _make_mock_context(forward={}, reverse={})

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Depends on:" not in prompt_text
        assert "Depended by:" not in prompt_text

    @pytest.mark.asyncio
    async def test_no_crash_when_context_is_none(self):
        """Frame handles context=None gracefully (standalone mode).

        TaintAnalyzer is imported lazily inside execute_async so we patch the
        module it lives in rather than the frame module.
        """
        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
            # Taint analyzer is imported lazily; patch at its definition site
            patch(
                "warden.validation.frames.security._internal.taint_analyzer.TaintAnalyzer",
                side_effect=ImportError("stubbed"),
            ),
        ):
            result = await frame.execute_async(code_file, context=None)

        assert result is not None


# ---------------------------------------------------------------------------
# T1.3 – Batch Processor Context Preservation
# ---------------------------------------------------------------------------


class TestT1_3_BatchProcessorContext:
    """batch_verify_security_findings must accept and forward semantic_context."""

    @pytest.mark.asyncio
    async def test_batch_function_accepts_semantic_context_param(self):
        """The function signature accepts semantic_context without raising."""
        llm_svc = AsyncMock()
        llm_svc.send_async = AsyncMock(return_value=MagicMock(success=False, error_message="stub"))

        result = await batch_verify_security_findings(
            findings_map={},
            code_files=[],
            llm_service=llm_svc,
            semantic_context="Framework: flask",
        )
        # Empty input → empty output, no exception
        assert result == {}

    @pytest.mark.asyncio
    async def test_semantic_context_forwarded_to_batch_verifier(self):
        """semantic_context content is included in the LLM batch prompt."""
        finding = Finding(
            id="sec-sql-0",
            severity="high",
            message="[SQL Injection] Tainted query",
            location="src/db.py:10",
        )
        code_file = _make_code_file(path="src/db.py")
        findings_map = {"src/db.py": [finding]}

        captured_requests: list = []

        async def _fake_send(req):
            captured_requests.append(req)
            return MagicMock(success=False, error_message="no LLM")

        llm_svc = MagicMock()
        llm_svc.send_with_tools_async = _fake_send

        await batch_verify_security_findings(
            findings_map=findings_map,
            code_files=[code_file],
            llm_service=llm_svc,
            semantic_context="Framework: fastapi\nEntry points: main.py",
        )

        assert captured_requests, "LLM service was never called"
        prompt_text: str = captured_requests[0].user_message
        assert "Framework: fastapi" in prompt_text

    def test_build_batch_context_includes_framework(self):
        """_build_batch_context returns a string that contains the framework name."""
        frame = _make_security_frame()
        frame.project_intelligence = _make_project_intelligence(
            frameworks=["flask"],
            entry_points=["app.py"],
            auth_patterns=["jwt"],
        )
        ctx_str = frame._build_batch_context()
        assert "flask" in ctx_str
        assert "app.py" in ctx_str

    def test_build_batch_context_empty_when_no_intelligence(self):
        """_build_batch_context returns empty string when no ProjectIntelligence."""
        frame = _make_security_frame()
        # No project_intelligence attribute
        ctx_str = frame._build_batch_context()
        assert ctx_str == ""

    def test_build_batch_context_empty_intelligence(self):
        """_build_batch_context returns empty string when intelligence has no data."""
        frame = _make_security_frame()
        frame.project_intelligence = _make_project_intelligence()  # all empty lists
        ctx_str = frame._build_batch_context()
        assert ctx_str == ""

    @pytest.mark.asyncio
    async def test_execute_batch_async_passes_context_to_batch_verify(self):
        """execute_batch_async calls batch_verify_security_findings with the built context."""
        frame = _make_security_frame()
        frame.project_intelligence = _make_project_intelligence(frameworks=["django"])
        frame.llm_service = MagicMock()
        frame.llm_service.send_async = AsyncMock(return_value=MagicMock(success=False, error_message="stub"))

        code_files = [_make_code_file()]

        with patch(
            "warden.validation.frames.security.frame.batch_verify_security_findings",
            new_callable=AsyncMock,
        ) as mock_batch:
            # Return value must match the findings_map structure
            mock_batch.return_value = {code_files[0].path: []}
            await frame.execute_batch_async(code_files)

        mock_batch.assert_awaited_once()
        _, kwargs = mock_batch.call_args
        sem_ctx: str = kwargs.get("semantic_context", "")
        assert "django" in sem_ctx


# ---------------------------------------------------------------------------
# T2.1 – Symbol Context in LLM Prompts
# ---------------------------------------------------------------------------


class TestT2_1_SymbolContextInPrompts:
    """Symbols from the code graph for the analysed file must appear in the prompt."""

    def _build_code_graph(self, file_path: str) -> CodeGraph:
        graph = CodeGraph()
        node = SymbolNode(
            fqn=f"{file_path}::UserService",
            name="UserService",
            kind=SymbolKind.CLASS,
            file_path=file_path,
            line=10,
            module="app.services",
        )
        graph.add_node(node)
        return graph

    @pytest.mark.asyncio
    async def test_symbol_name_appears_in_prompt(self):
        """Class symbol name is included in the LLM prompt via code graph."""
        file_path = "src/services.py"
        graph = self._build_code_graph(file_path)

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path=file_path)
        ctx = _make_mock_context(code_graph=graph)

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "UserService" in prompt_text

    @pytest.mark.asyncio
    async def test_code_graph_symbols_section_label_present(self):
        """'[Code Graph Symbols]:' section header appears in the prompt."""
        file_path = "src/auth.py"
        graph = self._build_code_graph(file_path)

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path=file_path)
        ctx = _make_mock_context(code_graph=graph)

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "[Code Graph Symbols]:" in prompt_text

    @pytest.mark.asyncio
    async def test_symbol_kind_appears_in_prompt(self):
        """Symbol kind (e.g. 'class') appears alongside the symbol name."""
        file_path = "src/utils.py"
        graph = CodeGraph()
        graph.add_node(
            SymbolNode(
                fqn=f"{file_path}::validate_input",
                name="validate_input",
                kind=SymbolKind.FUNCTION,
                file_path=file_path,
                line=3,
            )
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path=file_path)
        ctx = _make_mock_context(code_graph=graph)

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "function" in prompt_text
        assert "validate_input" in prompt_text

    @pytest.mark.asyncio
    async def test_no_symbol_section_when_code_graph_is_none(self):
        """No '[Code Graph Symbols]:' section when context.code_graph is None."""
        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file()
        ctx = _make_mock_context(code_graph=None)

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "[Code Graph Symbols]:" not in prompt_text

    @pytest.mark.asyncio
    async def test_symbols_from_other_files_not_leaked(self):
        """Symbols belonging to a different file must NOT appear in the prompt."""
        graph = CodeGraph()
        # Symbol belongs to a different file
        graph.add_node(
            SymbolNode(
                fqn="src/other.py::OtherClass",
                name="OtherClass",
                kind=SymbolKind.CLASS,
                file_path="src/other.py",
                line=1,
            )
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path="src/target.py")
        ctx = _make_mock_context(code_graph=graph)

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "OtherClass" not in prompt_text

    @pytest.mark.asyncio
    async def test_decorator_metadata_appears_in_prompt(self):
        """Decorator metadata stored in SymbolNode.metadata appears in the prompt."""
        file_path = "src/views.py"
        graph = CodeGraph()
        graph.add_node(
            SymbolNode(
                fqn=f"{file_path}::login_view",
                name="login_view",
                kind=SymbolKind.FUNCTION,
                file_path=file_path,
                line=15,
                metadata={"decorators": ["app.route", "login_required"]},
            )
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        code_file = _make_code_file(path=file_path)
        ctx = _make_mock_context(code_graph=graph)

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        # Decorators are prefixed with "@" in format_file_symbols_for_prompt
        assert "@app.route" in prompt_text or "app.route" in prompt_text


# ---------------------------------------------------------------------------
# T2.2 – Enhanced Taint Detail in LLM Prompts
# ---------------------------------------------------------------------------


class TestT2_2_EnhancedTaintDetail:
    """Taint paths with transformations and sanitizers get full formatting."""

    @pytest.mark.asyncio
    async def test_transformation_chain_appears_in_prompt(self):
        """Transformation chain ('via [...]') is emitted in the prompt for unsanitized paths."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="request.args", line=5),
            sink=_MockTaintSink(name="cursor.execute", line=20),
            transformations=["f-string", "str.format"],
            is_sanitized=False,
            confidence=0.9,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "f-string" in prompt_text
        assert "str.format" in prompt_text
        # The 'via' keyword is used to introduce transformations
        assert "via" in prompt_text

    @pytest.mark.asyncio
    async def test_sanitizer_list_appears_in_sanitized_path(self):
        """Sanitizer names appear in the lower-risk 'Sanitized Paths' section."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="request.form", line=8),
            sink=_MockTaintSink(name="cursor.execute", line=30),
            sanitizers=["parameterized_query"],
            is_sanitized=True,
            confidence=0.5,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "parameterized_query" in prompt_text
        assert "sanitized by" in prompt_text

    @pytest.mark.asyncio
    async def test_source_and_sink_names_in_prompt(self):
        """Source and sink names always appear in the taint section."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="sys.argv", line=3),
            sink=_MockTaintSink(name="os.system", sink_type="CMD-argument", line=15),
            is_sanitized=False,
            confidence=0.88,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "sys.argv" in prompt_text
        assert "os.system" in prompt_text

    @pytest.mark.asyncio
    async def test_confidence_score_appears_in_prompt(self):
        """Confidence score is emitted next to each unsanitized taint path."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="request.json", line=12),
            sink=_MockTaintSink(name="eval", sink_type="CODE-execution", line=25),
            is_sanitized=False,
            confidence=0.95,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "confidence=0.95" in prompt_text

    @pytest.mark.asyncio
    async def test_unsanitized_section_header_present(self):
        """High-Risk taint section header is emitted when unsanitized paths exist."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="request.args", line=5),
            sink=_MockTaintSink(name="cursor.execute", line=20),
            is_sanitized=False,
            confidence=0.85,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "Taint Analysis" in prompt_text
        assert "HIGH RISK" in prompt_text

    @pytest.mark.asyncio
    async def test_no_taint_section_when_all_paths_sanitized(self):
        """HIGH RISK section absent when every taint path is sanitized."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="request.form", line=4),
            sink=_MockTaintSink(name="cursor.execute", line=18),
            sanitizers=["prepared_statement"],
            is_sanitized=True,
            confidence=0.4,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        assert "HIGH RISK" not in prompt_text

    @pytest.mark.asyncio
    async def test_multiple_transformations_formatted_with_arrow_separator(self):
        """Multiple transformations are joined with ' -> ' arrow notation."""
        taint_path = _MockTaintPath(
            source=_MockTaintSource(name="os.environ", line=2),
            sink=_MockTaintSink(name="subprocess.run", sink_type="CMD-argument", line=14),
            transformations=["strip", "lower", "join"],
            is_sanitized=False,
            confidence=0.80,
        )

        frame = _make_security_frame()
        frame.llm_service = _make_llm_service()
        frame._taint_paths = {"src/app.py": [taint_path]}
        code_file = _make_code_file()
        ctx = _make_mock_context()

        with (
            patch("warden.validation.frames.security.frame.extract_ast_context", return_value={}),
            patch("warden.validation.frames.security.frame.analyze_data_flow", return_value={}),
        ):
            await frame.execute_async(code_file, context=ctx)

        prompt_text = frame.llm_service.analyze_security_async.call_args[0][0]
        # Arrow separator between transformations
        assert " -> " in prompt_text
        assert "strip" in prompt_text


# ---------------------------------------------------------------------------
# format_file_symbols_for_prompt – unit tests (no IO, no LLM)
# ---------------------------------------------------------------------------


class TestFormatFileSymbolsForPrompt:
    """Direct unit tests for the symbol formatter helper."""

    def test_returns_empty_when_no_matching_symbols(self):
        from warden.analysis.services.symbol_context_formatter import format_file_symbols_for_prompt

        graph = CodeGraph()
        # Add a node for a *different* file
        graph.add_node(
            SymbolNode(
                fqn="other.py::Foo",
                name="Foo",
                kind=SymbolKind.CLASS,
                file_path="other.py",
                line=1,
            )
        )
        result = format_file_symbols_for_prompt(graph, "target.py")
        assert result == ""

    def test_returns_section_with_symbol_name(self):
        from warden.analysis.services.symbol_context_formatter import format_file_symbols_for_prompt

        graph = CodeGraph()
        graph.add_node(
            SymbolNode(
                fqn="api.py::PaymentHandler",
                name="PaymentHandler",
                kind=SymbolKind.CLASS,
                file_path="api.py",
                line=5,
            )
        )
        result = format_file_symbols_for_prompt(graph, "api.py")
        assert "PaymentHandler" in result
        assert "[Code Graph Symbols]:" in result

    def test_includes_bases_when_present(self):
        from warden.analysis.services.symbol_context_formatter import format_file_symbols_for_prompt

        graph = CodeGraph()
        graph.add_node(
            SymbolNode(
                fqn="app.py::AdminView",
                name="AdminView",
                kind=SymbolKind.CLASS,
                file_path="app.py",
                line=8,
                bases=["BaseView", "LoginRequired"],
            )
        )
        result = format_file_symbols_for_prompt(graph, "app.py")
        assert "BaseView" in result
        assert "LoginRequired" in result

    def test_partial_path_match(self):
        """Symbols match when file_path is a suffix of the requested path."""
        from warden.analysis.services.symbol_context_formatter import format_file_symbols_for_prompt

        graph = CodeGraph()
        graph.add_node(
            SymbolNode(
                fqn="src/auth.py::AuthMiddleware",
                name="AuthMiddleware",
                kind=SymbolKind.CLASS,
                file_path="src/auth.py",
                line=1,
            )
        )
        # Query with a longer path that ends with the node's file_path
        result = format_file_symbols_for_prompt(graph, "/home/user/project/src/auth.py")
        assert "AuthMiddleware" in result

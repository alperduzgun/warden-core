"""
Tests for warden.pipeline.application.orchestrator.pipeline_phase_runner

Covers:
1. execute_all_phases — phase orchestration with enable/disable flags
2. _apply_manual_frame_override — manual frame selection
3. _finalize_pipeline_status — blocker/non-blocker logic + LLM usage
4. _check_phase_preconditions — pre-condition checks for phase transitions
5. _populate_project_intelligence — auth_patterns and entry_points from AST
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.pipeline.application.orchestrator.pipeline_phase_runner import (
    AUTH_DECORATOR_NAMES,
    ROUTE_DECORATOR_NAMES,
    PipelinePhaseRunner,
)
from warden.pipeline.domain.enums import AnalysisLevel, PipelineStatus
from warden.pipeline.domain.models import PipelineConfig

from .conftest import (
    make_code_file,
    make_context,
    make_finding,
    make_frame_result,
    make_pipeline,
)


def _make_runner(config=None, **kwargs):
    """Create a PipelinePhaseRunner with mock collaborators."""
    phase_executor = kwargs.pop("phase_executor", AsyncMock())
    frame_executor = kwargs.pop("frame_executor", AsyncMock())
    frame_executor.frames = kwargs.pop("frames_list", [])
    post_processor = kwargs.pop("post_processor", MagicMock())
    post_processor.verify_findings_async = AsyncMock()
    post_processor.apply_baseline = MagicMock()

    return PipelinePhaseRunner(
        config=config or PipelineConfig(),
        phase_executor=phase_executor,
        frame_executor=frame_executor,
        post_processor=post_processor,
        **kwargs,
    )


def _make_ast_node(node_type, name=None, decorators=None, line=1, children=None):
    """Create a lightweight mock ASTNode for testing."""
    from warden.ast.domain.enums import ASTNodeType
    from warden.ast.domain.models import ASTNode, SourceLocation

    attrs = {}
    if decorators is not None:
        attrs["decorators"] = decorators

    return ASTNode(
        node_type=ASTNodeType(node_type),
        name=name,
        location=SourceLocation(
            file_path="test.py",
            start_line=line,
            start_column=0,
            end_line=line,
            end_column=0,
        ),
        children=children or [],
        attributes=attrs,
    )


def _make_parse_result(ast_root):
    """Create a mock ParseResult wrapping an ASTNode root."""
    mock = MagicMock()
    mock.ast_root = ast_root
    return mock


# ---------------------------------------------------------------------------
# execute_all_phases
# ---------------------------------------------------------------------------


class TestExecuteAllPhases:
    """Phase orchestration with enable/disable flags."""

    @pytest.mark.asyncio
    async def test_all_phases_called(self):
        """All phases enabled → each executor method called once."""
        config = PipelineConfig(
            enable_pre_analysis=True,
            enable_analysis=True,
            enable_validation=True,
            enable_fortification=True,
            enable_cleaning=True,
            enable_issue_validation=True,
            use_llm=True,
            analysis_level=AnalysisLevel.STANDARD,
        )
        pe = AsyncMock()
        fe = AsyncMock()
        fe.frames = ["security"]
        pp = MagicMock()
        pp.verify_findings_async = AsyncMock()
        pp.apply_baseline = MagicMock()

        runner = PipelinePhaseRunner(
            config=config,
            phase_executor=pe,
            frame_executor=fe,
            post_processor=pp,
        )

        ctx = make_context()
        ctx.selected_frames = ["security"]
        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        files = [make_code_file()]

        await runner.execute_all_phases(ctx, files, pipeline)

        pe.execute_pre_analysis_async.assert_awaited_once()
        pe.execute_triage_async.assert_awaited_once()
        pe.execute_analysis_async.assert_awaited_once()
        pe.execute_classification_async.assert_awaited_once()
        fe.execute_validation_with_strategy_async.assert_awaited_once()
        pe.execute_fortification_async.assert_awaited_once()
        pe.execute_cleaning_async.assert_awaited_once()
        pp.verify_findings_async.assert_awaited_once()
        pp.apply_baseline.assert_called_once()

    @pytest.mark.asyncio
    async def test_pre_analysis_skipped_when_disabled(self):
        """enable_pre_analysis=False → not called."""
        config = PipelineConfig(
            enable_pre_analysis=False,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_pre_analysis_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_triage_skipped_for_basic(self):
        """analysis_level=BASIC → triage not called."""
        config = PipelineConfig(
            analysis_level=AnalysisLevel.BASIC,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_triage_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validation_skipped_when_disabled(self):
        """enable_validation=False → frame executor not called."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        fe = AsyncMock()
        fe.frames = []
        runner = _make_runner(config=config, frame_executor=fe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        fe.execute_validation_with_strategy_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fortification_skipped_when_disabled(self):
        """enable_fortification=False → not called."""
        config = PipelineConfig(
            enable_fortification=False,
            enable_validation=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_fortification_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleaning_skipped_when_disabled(self):
        """enable_cleaning=False → not called."""
        config = PipelineConfig(
            enable_cleaning=False,
            enable_validation=False,
            enable_fortification=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_cleaning_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verification_called_when_enabled(self):
        """enable_issue_validation=True → post_processor.verify_findings_async called."""
        config = PipelineConfig(
            enable_issue_validation=True,
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pp = MagicMock()
        pp.verify_findings_async = AsyncMock()
        pp.apply_baseline = MagicMock()
        runner = _make_runner(config=config, post_processor=pp)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pp.verify_findings_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# _apply_manual_frame_override
# ---------------------------------------------------------------------------


class TestManualFrameOverride:
    """Manual frame selection via CLI override."""

    @pytest.mark.asyncio
    async def test_override_sets_context_fields(self):
        """frames_to_execute sets selected_frames + reasoning."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        runner = _make_runner(config=config)

        ctx = make_context()
        frames = ["security", "resilience"]
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline(), frames_to_execute=frames)

        assert ctx.selected_frames == ["security", "resilience"]
        assert "manually" in ctx.classification_reasoning.lower()

    @pytest.mark.asyncio
    async def test_override_skips_classification(self):
        """Manual override → classification executor not called."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline(), frames_to_execute=["security"])

        pe.execute_classification_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_override_runs_classification(self):
        """frames_to_execute=None → classification called."""
        config = PipelineConfig(
            enable_validation=False,
            enable_fortification=False,
            enable_cleaning=False,
        )
        pe = AsyncMock()
        runner = _make_runner(config=config, phase_executor=pe)

        ctx = make_context()
        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        pe.execute_classification_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# _finalize_pipeline_status
# ---------------------------------------------------------------------------


class TestFinalizePipelineStatus:
    """Pipeline status determination after execution."""

    def test_blocker_failures_set_failed(self):
        """is_blocker=True + failed → FAILED."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")], is_blocker=True)},
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner()
        runner._finalize_pipeline_status(ctx, pipeline)

        assert pipeline.status == PipelineStatus.FAILED

    def test_non_blocker_set_completed_with_failures(self):
        """is_blocker=False + failed → COMPLETED_WITH_FAILURES."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [make_finding("F1")], is_blocker=False)},
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner()
        runner._finalize_pipeline_status(ctx, pipeline)

        assert pipeline.status == PipelineStatus.COMPLETED_WITH_FAILURES

    def test_no_failures_set_completed(self):
        """All passed → COMPLETED."""
        ctx = make_context()
        ctx.frame_results = {
            "sec": {"result": make_frame_result("sec", [])},
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner()
        runner._finalize_pipeline_status(ctx, pipeline)

        assert pipeline.status == PipelineStatus.COMPLETED

    def test_llm_usage_captured(self):
        """llm_service.get_usage() → context tokens populated."""
        ctx = make_context()
        ctx.frame_results = {}

        llm = MagicMock()
        llm.get_usage.return_value = {
            "total_tokens": 1000,
            "prompt_tokens": 600,
            "completion_tokens": 400,
            "request_count": 5,
        }

        pipeline = make_pipeline(status=PipelineStatus.RUNNING)
        runner = _make_runner(llm_service=llm)
        runner._finalize_pipeline_status(ctx, pipeline)

        assert ctx.total_tokens == 1000
        assert ctx.prompt_tokens == 600
        assert ctx.completion_tokens == 400
        assert ctx.request_count == 5


# ---------------------------------------------------------------------------
# _check_phase_preconditions (PHASE-GAP-4)
# ---------------------------------------------------------------------------


class TestPhasePreconditionChecks:
    """Pre-condition gate checks before each phase transition."""

    def test_validation_precondition_passes_with_selected_frames(self):
        """selected_frames populated → Validation pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = ["security", "resilience"]

        assert runner._check_phase_preconditions("Validation", ctx) is True
        assert len(ctx.warnings) == 0

    def test_validation_precondition_warns_when_selected_frames_is_none(self):
        """selected_frames is None → Validation pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = None

        result = runner._check_phase_preconditions("Validation", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "selected_frames" in ctx.warnings[0]
        assert "Classification" in ctx.warnings[0]

    def test_validation_precondition_passes_with_empty_list(self):
        """selected_frames is [] (Classification ran, selected nothing) → True.

        An empty list means the producing phase ran but produced no frames,
        which is a valid (if unusual) result.  Only None signals a skipped phase.
        """
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = []

        assert runner._check_phase_preconditions("Validation", ctx) is True
        assert len(ctx.warnings) == 0

    def test_fortification_precondition_passes_with_findings(self):
        """findings and frame_results populated → Fortification pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = [{"id": "F1", "severity": "high"}]
        ctx.frame_results = {"sec": {"result": "ok"}}

        assert runner._check_phase_preconditions("Fortification", ctx) is True
        assert len(ctx.warnings) == 0

    def test_fortification_precondition_warns_when_findings_is_none(self):
        """findings is None → Fortification pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None
        ctx.frame_results = {}

        result = runner._check_phase_preconditions("Fortification", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "findings" in ctx.warnings[0]
        assert "Validation" in ctx.warnings[0]

    def test_fortification_precondition_warns_when_frame_results_is_none(self):
        """frame_results is None → Fortification pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = []
        ctx.frame_results = None

        result = runner._check_phase_preconditions("Fortification", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "frame_results" in ctx.warnings[0]

    def test_fortification_precondition_warns_on_both_none(self):
        """Both findings and frame_results None → two warnings."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None
        ctx.frame_results = None

        result = runner._check_phase_preconditions("Fortification", ctx)

        assert result is False
        assert len(ctx.warnings) == 2

    def test_fortification_precondition_passes_with_empty_findings(self):
        """findings is [] (Validation ran, found nothing) → True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = []
        ctx.frame_results = {}

        assert runner._check_phase_preconditions("Fortification", ctx) is True
        assert len(ctx.warnings) == 0

    def test_verification_precondition_passes_with_findings(self):
        """findings populated → Verification pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = [{"id": "F1"}]

        assert runner._check_phase_preconditions("Verification", ctx) is True
        assert len(ctx.warnings) == 0

    def test_verification_precondition_warns_when_findings_is_none(self):
        """findings is None → Verification pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None

        result = runner._check_phase_preconditions("Verification", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "findings" in ctx.warnings[0]

    def test_cleaning_precondition_passes_with_findings(self):
        """findings populated → Cleaning pre-check returns True."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = []

        assert runner._check_phase_preconditions("Cleaning", ctx) is True
        assert len(ctx.warnings) == 0

    def test_cleaning_precondition_warns_when_findings_is_none(self):
        """findings is None → Cleaning pre-check returns False + warning."""
        runner = _make_runner()
        ctx = make_context()
        ctx.findings = None

        result = runner._check_phase_preconditions("Cleaning", ctx)

        assert result is False
        assert len(ctx.warnings) == 1
        assert "findings" in ctx.warnings[0]

    def test_unknown_phase_returns_true(self):
        """Unknown phase name → no checks, returns True."""
        runner = _make_runner()
        ctx = make_context()

        assert runner._check_phase_preconditions("UnknownPhase", ctx) is True
        assert len(ctx.warnings) == 0

    def test_precondition_does_not_raise(self):
        """Pre-condition failures must never raise — only warn."""
        runner = _make_runner()
        ctx = make_context()
        ctx.selected_frames = None
        ctx.findings = None
        ctx.frame_results = None

        # Should not raise for any phase
        for phase in ["Validation", "Verification", "Fortification", "Cleaning"]:
            runner._check_phase_preconditions(phase, ctx)

        # Warnings accumulated but no exceptions raised
        assert len(ctx.warnings) > 0

    @pytest.mark.asyncio
    async def test_pipeline_continues_despite_failed_precondition(self):
        """Validation still executes even when selected_frames is None.

        The pre-condition check logs a warning but does NOT block execution.
        """
        config = PipelineConfig(
            enable_validation=True,
            enable_fortification=False,
            enable_cleaning=False,
        )
        fe = AsyncMock()
        fe.frames = ["security"]
        runner = _make_runner(config=config, frame_executor=fe)

        ctx = make_context()
        # Simulate Classification that failed to populate selected_frames
        ctx.selected_frames = None

        await runner.execute_all_phases(ctx, [make_code_file()], make_pipeline())

        # Validation should still be called despite the warning
        fe.execute_validation_with_strategy_async.assert_awaited_once()
        # A warning should have been recorded
        assert any("selected_frames" in w for w in ctx.warnings)


# ---------------------------------------------------------------------------
# _populate_project_intelligence — auth_patterns and entry_points from AST
# ---------------------------------------------------------------------------


class TestPopulateProjectIntelligence:
    """Auth pattern extraction and entry point enhancement from AST."""

    def test_auth_patterns_extracted_from_function_decorators(self):
        """Functions with auth decorators populate intel.auth_patterns."""
        # Build a minimal AST: module -> function with @login_required
        func_node = _make_ast_node(
            "function",
            name="dashboard_view",
            decorators=["login_required"],
            line=10,
        )
        root = _make_ast_node("module", children=[func_node])

        ctx = make_context()
        ctx.ast_cache = {"views.py": _make_parse_result(root)}

        runner = _make_runner()
        code_files = [make_code_file(path="views.py")]
        runner._populate_project_intelligence(ctx, code_files)

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 1
        assert intel.auth_patterns[0]["pattern"] == "login_required"
        assert intel.auth_patterns[0]["type"] == "decorator"
        assert intel.auth_patterns[0]["function"] == "dashboard_view"
        assert intel.auth_patterns[0]["file"] == "views.py"
        assert intel.auth_patterns[0]["line"] == 10

    def test_multiple_auth_decorators_on_same_function(self):
        """A function with multiple auth decorators creates multiple entries."""
        func_node = _make_ast_node(
            "function",
            name="admin_panel",
            decorators=["login_required", "permission_required('admin')"],
            line=20,
        )
        root = _make_ast_node("module", children=[func_node])

        ctx = make_context()
        ctx.ast_cache = {"admin.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="admin.py")])

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 2
        patterns = {p["pattern"] for p in intel.auth_patterns}
        assert "login_required" in patterns
        assert "permission_required" in patterns

    def test_auth_patterns_from_class_decorators(self):
        """Classes with auth decorators populate intel.auth_patterns."""
        class_node = _make_ast_node(
            "class",
            name="SecureView",
            decorators=["requires_auth"],
            line=5,
        )
        root = _make_ast_node("module", children=[class_node])

        ctx = make_context()
        ctx.ast_cache = {"views.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="views.py")])

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 1
        assert intel.auth_patterns[0]["pattern"] == "requires_auth"
        assert intel.auth_patterns[0]["class"] == "SecureView"

    def test_route_decorators_add_function_level_entry_points(self):
        """Functions with route decorators appear as file::func entry points."""
        func_node = _make_ast_node(
            "function",
            name="get_users",
            decorators=["app.get('/users')"],
            line=15,
        )
        root = _make_ast_node("module", children=[func_node])

        ctx = make_context()
        ctx.ast_cache = {"api.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="api.py")])

        intel = ctx.project_intelligence
        assert "api.py::get_users" in intel.entry_points

    def test_filename_heuristic_entry_points_preserved(self):
        """Filename-based entry points still work (app.py, main.py, etc.)."""
        root = _make_ast_node("module")

        ctx = make_context()
        ctx.ast_cache = {"app.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="app.py")])

        intel = ctx.project_intelligence
        assert "app.py" in intel.entry_points

    def test_no_duplicate_entry_points(self):
        """Same file::func entry point is not added twice."""
        func1 = _make_ast_node("function", name="index", decorators=["route('/')"], line=5)
        func2 = _make_ast_node("function", name="index", decorators=["get('/')"], line=5)
        root = _make_ast_node("module", children=[func1, func2])

        ctx = make_context()
        ctx.ast_cache = {"web.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="web.py")])

        intel = ctx.project_intelligence
        # Should appear only once
        func_entries = [ep for ep in intel.entry_points if ep == "web.py::index"]
        assert len(func_entries) == 1

    def test_non_auth_decorators_ignored(self):
        """Decorators that are not auth-related do not populate auth_patterns."""
        func_node = _make_ast_node(
            "function",
            name="cached_view",
            decorators=["cache_page(60)", "staticmethod"],
            line=10,
        )
        root = _make_ast_node("module", children=[func_node])

        ctx = make_context()
        ctx.ast_cache = {"views.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="views.py")])

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 0

    def test_empty_ast_cache(self):
        """Empty ast_cache does not crash; intel is still created."""
        ctx = make_context()
        ctx.ast_cache = {}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file()])

        intel = ctx.project_intelligence
        assert intel.total_files == 1
        assert intel.auth_patterns == []
        assert isinstance(intel.entry_points, list)

    def test_legacy_dict_ast_data_still_works(self):
        """Dict-based AST cache entries (legacy) still populate sinks."""
        ctx = make_context()
        ctx.ast_cache = {
            "db.py": {
                "input_sources": [{"source": "request.args", "line": 5}],
                "dangerous_calls": [{"function": "cursor.execute", "line": 10}],
                "sql_queries": [],
            }
        }

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="db.py")])

        intel = ctx.project_intelligence
        assert len(intel.input_sources) == 1
        assert intel.input_sources[0]["source"] == "request.args"
        assert len(intel.critical_sinks) == 1
        assert intel.critical_sinks[0]["type"] == "SQL"

    def test_dotted_auth_decorator_name(self):
        """Dotted decorator like 'flask_login.login_required' is detected."""
        func_node = _make_ast_node(
            "function",
            name="profile",
            decorators=["flask_login.login_required"],
            line=30,
        )
        root = _make_ast_node("module", children=[func_node])

        ctx = make_context()
        ctx.ast_cache = {"profile.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="profile.py")])

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 1
        assert intel.auth_patterns[0]["pattern"] == "flask_login.login_required"

    def test_mixed_auth_and_route_decorators(self):
        """Function with both auth and route decorators populates both fields."""
        func_node = _make_ast_node(
            "function",
            name="protected_endpoint",
            decorators=["app.post('/api/data')", "jwt_required"],
            line=25,
        )
        root = _make_ast_node("module", children=[func_node])

        ctx = make_context()
        ctx.ast_cache = {"api.py": _make_parse_result(root)}

        runner = _make_runner()
        runner._populate_project_intelligence(ctx, [make_code_file(path="api.py")])

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 1
        assert intel.auth_patterns[0]["pattern"] == "jwt_required"
        assert "api.py::protected_endpoint" in intel.entry_points

    def test_multiple_files_aggregate_patterns(self):
        """Auth patterns and entry points aggregate across multiple files."""
        func1 = _make_ast_node("function", name="login", decorators=["route('/login')"], line=5)
        root1 = _make_ast_node("module", children=[func1])

        func2 = _make_ast_node("function", name="secret", decorators=["token_required"], line=10)
        root2 = _make_ast_node("module", children=[func2])

        ctx = make_context()
        ctx.ast_cache = {
            "auth.py": _make_parse_result(root1),
            "secure.py": _make_parse_result(root2),
        }

        runner = _make_runner()
        runner._populate_project_intelligence(
            ctx,
            [make_code_file(path="auth.py"), make_code_file(path="secure.py")],
        )

        intel = ctx.project_intelligence
        assert len(intel.auth_patterns) == 1
        assert intel.auth_patterns[0]["file"] == "secure.py"
        assert "auth.py::login" in intel.entry_points

    def test_parse_result_without_ast_root_skipped(self):
        """ParseResult with ast_root=None is safely skipped."""
        mock_result = MagicMock()
        mock_result.ast_root = None

        ctx = make_context()
        ctx.ast_cache = {"broken.py": mock_result}

        runner = _make_runner()
        # Should not raise
        runner._populate_project_intelligence(ctx, [make_code_file(path="broken.py")])

        intel = ctx.project_intelligence
        assert intel.auth_patterns == []


class TestAuthDecoratorConstants:
    """Verify the AUTH_DECORATOR_NAMES and ROUTE_DECORATOR_NAMES constants."""

    def test_auth_decorator_names_is_frozenset(self):
        assert isinstance(AUTH_DECORATOR_NAMES, frozenset)

    def test_common_auth_decorators_present(self):
        for name in [
            "login_required",
            "jwt_required",
            "token_required",
            "permission_required",
            "requires_auth",
            "auth_required",
        ]:
            assert name in AUTH_DECORATOR_NAMES, f"{name} missing from AUTH_DECORATOR_NAMES"

    def test_route_decorator_names_is_frozenset(self):
        assert isinstance(ROUTE_DECORATOR_NAMES, frozenset)

    def test_common_route_decorators_present(self):
        for name in ["route", "get", "post", "put", "delete", "app.route", "app.get"]:
            assert name in ROUTE_DECORATOR_NAMES, f"{name} missing from ROUTE_DECORATOR_NAMES"

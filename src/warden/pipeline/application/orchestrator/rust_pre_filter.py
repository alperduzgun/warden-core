"""
Rust-based pre-filtering for validation frames.

Handles high-performance pre-filtering using Rust validation engine.
"""

import time
from pathlib import Path
from typing import Any, List, Optional

from warden.pipeline.domain.models import FrameResult, PipelineConfig
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.application.rust_validation_engine import RustValidationEngine
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)


class RustPreFilter:
    """Handles Rust-based pre-filtering of code files."""

    def __init__(self, config: PipelineConfig | None = None, rule_validator: Any | None = None):
        self.config = config or PipelineConfig()
        self.rule_validator = rule_validator

    async def run_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Run global high-performance pre-filtering using Rust engine."""
        project_root = getattr(context, 'project_root', Path.cwd())
        engine = RustValidationEngine(project_root)

        import warden
        package_root = Path(warden.__file__).parent
        rule_paths = [
            package_root / "rules/defaults/python/security.yaml",
            package_root / "rules/defaults/javascript/security.yaml",
        ]

        logger.info("debug_rule_paths", package_root=str(package_root))
        for path in rule_paths:
            exists = path.exists()
            logger.info("debug_rule_path_check", path=str(path), exists=exists)
            if exists:
                await engine.load_rules_from_yaml_async(path)

        if self.rule_validator and self.rule_validator.rules:
            regex_rules = [r for r in self.rule_validator.rules if r.pattern and r.type != 'ai']
            if regex_rules:
                engine.add_custom_rules(regex_rules)

        if not engine.rust_rules:
            logger.debug("no_global_rust_rules_and_no_custom_regex_rules_skipping_scan")
            return

        file_paths = [Path(cf.path) for cf in code_files]

        try:
            findings = await engine.scan_project_async(file_paths)
            if findings:
                total_hits = len(findings)
                logger.info("rust_scan_raw_hits", count=total_hits)

                from warden.validation.application.alpha_judgment import AlphaJudgment
                alpha = AlphaJudgment(config=self.config.dict() if hasattr(self.config, 'dict') else {})

                filtered_findings = alpha.evaluate(findings, code_files)

                if filtered_findings:
                    logger.info("rust_pre_filtering_found_issues",
                              raw=total_hits,
                              filtered=len(filtered_findings))

                    frame_id = "system_security_rules"
                    frame_result = FrameResult(
                        frame_id=frame_id,
                        frame_name="System Security Rules (Rust)",
                        status="failed",
                        duration=0.1,
                        issues_found=len(filtered_findings),
                        is_blocker=any(f.severity == 'critical' for f in filtered_findings),
                        findings=filtered_findings,
                        metadata={
                            "engine": "rust",
                            "raw_hits": total_hits,
                            "filtered_hits": len(filtered_findings)
                        }
                    )

                    if not hasattr(context, 'frame_results') or context.frame_results is None:
                        context.frame_results = {}

                    context.frame_results[frame_id] = {
                        'result': frame_result,
                        'pre_violations': [],
                        'post_violations': []
                    }
                else:
                    logger.info("alpha_judgment_filtered_all_hits", raw=total_hits)

        except Exception as e:
            logger.error("rust_pre_filtering_failed", error=str(e), error_type=type(e).__name__)

"""
Warden Spec Frame - API Contract Extraction and Gap Analysis.

Extracts API contracts from multiple platforms and identifies gaps
between what consumers expect and what providers offer.

Key Features:
- Extracts contracts from code using tree-sitter (no manual documentation)
- Compares consumer expectations vs provider capabilities
- Generates findings for missing operations, type mismatches, etc.

Dependencies:
- Requires 'architectural' frame to run first (for project context)
- Requires 'platforms' config with at least 2 platforms defined

Configuration (.warden/config.yaml):
    frames:
      spec:
        platforms:
          - name: mobile
            path: ../invoice-mobile
            type: flutter
            role: consumer
          - name: backend
            path: ../invoice-api
            type: spring
            role: provider

Author: Warden Team
Version: 1.0.0
"""

import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from warden.validation.frames.spec.models import (
    Contract,
    PlatformConfig,
    PlatformRole,
    ContractGap,
    GapSeverity,
    SpecAnalysisResult,
)
from warden.validation.frames.spec.extractors.base import get_extractor
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SpecFrame(ValidationFrame):
    """
    API Contract Specification Frame.

    Extracts contracts from consumer and provider platforms,
    then identifies gaps between them.

    Skip Conditions:
    - No 'platforms' config defined
    - Less than 2 platforms configured
    - No consumer/provider pair found
    - Required frames not executed
    """

    # Required metadata
    name = "API Contract Spec"
    description = "Extract and compare API contracts between platforms"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW  # Run after other frames
    scope = FrameScope.PROJECT_LEVEL
    is_blocker = False
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    # Frame dependencies
    requires_frames = ["architectural"]  # Need architectural context
    requires_config = ["platforms"]  # Need platforms configuration
    requires_context = []  # project_context is optional but helpful

    def __init__(self, config: Dict[str, Any] | None = None):
        """
        Initialize SpecFrame.

        Args:
            config: Frame configuration with 'platforms' list
        """
        super().__init__(config)

        # Parse platform configurations
        self.platforms: List[PlatformConfig] = []
        self._parse_platforms_config()

    def _parse_platforms_config(self) -> None:
        """Parse platforms from config."""
        if not self.config:
            return

        platforms_data = self.config.get("platforms", [])
        for p in platforms_data:
            try:
                platform = PlatformConfig.from_dict(p)
                self.platforms.append(platform)
            except Exception as e:
                logger.warning(
                    "platform_config_parse_error",
                    platform=p.get("name", "unknown"),
                    error=str(e),
                )

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute spec analysis.

        Note: This frame operates at PROJECT_LEVEL, so code_file
        is typically the project root or a representative file.

        Args:
            code_file: Code file (project context)

        Returns:
            FrameResult with contract gap findings
        """
        start_time = time.perf_counter()

        logger.info(
            "spec_frame_started",
            platforms_configured=len(self.platforms),
        )

        # Validate configuration
        validation_result = self._validate_configuration()
        if validation_result:
            return validation_result

        findings: List[Finding] = []
        metadata: Dict[str, Any] = {
            "platforms_analyzed": [],
            "contracts_extracted": 0,
            "gaps_found": 0,
        }

        try:
            # Get consumer and provider platforms
            consumers = [p for p in self.platforms if p.role == PlatformRole.CONSUMER]
            providers = [p for p in self.platforms if p.role == PlatformRole.PROVIDER]

            if not consumers or not providers:
                return self._create_skip_result(
                    "No consumer/provider pair found. "
                    "Configure at least one consumer and one provider platform."
                )

            # Extract contracts from each platform
            contracts: Dict[str, Contract] = {}

            for platform in self.platforms:
                contract = await self._extract_contract(platform)
                if contract:
                    contracts[platform.name] = contract
                    metadata["contracts_extracted"] += 1
                    metadata["platforms_analyzed"].append({
                        "name": platform.name,
                        "type": platform.platform_type.value,
                        "role": platform.role.value,
                        "operations": len(contract.operations),
                        "models": len(contract.models),
                    })

            # Compare contracts (consumer vs provider)
            for consumer in consumers:
                consumer_contract = contracts.get(consumer.name)
                if not consumer_contract:
                    continue

                for provider in providers:
                    provider_contract = contracts.get(provider.name)
                    if not provider_contract:
                        continue

                    # Analyze gaps
                    result = self._analyze_gaps(
                        consumer_contract,
                        provider_contract,
                        consumer.name,
                        provider.name,
                    )

                    # Convert gaps to findings
                    for gap in result.gaps:
                        finding = self._gap_to_finding(gap)
                        findings.append(finding)
                        metadata["gaps_found"] += 1

            # Determine status
            if any(f.severity == "critical" for f in findings):
                status = "failed"
            elif findings:
                status = "warning"
            else:
                status = "passed"

            duration = time.perf_counter() - start_time

            logger.info(
                "spec_frame_completed",
                status=status,
                findings=len(findings),
                duration=f"{duration:.2f}s",
            )

            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status=status,
                duration=duration,
                issues_found=len(findings),
                is_blocker=False,
                findings=findings,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(
                "spec_frame_error",
                error=str(e),
                error_type=type(e).__name__,
            )

            duration = time.perf_counter() - start_time
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="error",
                duration=duration,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    def _validate_configuration(self) -> Optional[FrameResult]:
        """
        Validate frame configuration.

        Returns:
            FrameResult with skip status if invalid, None if valid
        """
        # Check platforms configured
        if not self.platforms:
            return self._create_skip_result(
                "No platforms configured. "
                "Add 'platforms' list to .warden/config.yaml under frames.spec"
            )

        # Check minimum 2 platforms
        if len(self.platforms) < 2:
            return self._create_skip_result(
                f"At least 2 platforms required, found {len(self.platforms)}. "
                "Configure a consumer and provider platform."
            )

        # Check platform paths exist
        for platform in self.platforms:
            platform_path = Path(platform.path)
            if not platform_path.is_absolute():
                # Resolve relative to current project
                platform_path = Path.cwd() / platform.path

            if not platform_path.exists():
                return self._create_skip_result(
                    f"Platform path not found: {platform.path} ({platform.name})"
                )

        return None

    def _create_skip_result(self, reason: str) -> FrameResult:
        """Create a skip result with reason."""
        logger.info("spec_frame_skipped", reason=reason)

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="skipped",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
            metadata={
                "skip_reason": reason,
                "help": "See documentation for spec frame configuration",
            },
        )

    async def _extract_contract(self, platform: PlatformConfig) -> Optional[Contract]:
        """
        Extract contract from a platform.

        Args:
            platform: Platform configuration

        Returns:
            Contract or None if extraction fails
        """
        # Resolve platform path
        platform_path = Path(platform.path)
        if not platform_path.is_absolute():
            platform_path = Path.cwd() / platform.path

        # Get appropriate extractor
        extractor = get_extractor(
            platform.platform_type,
            platform_path,
            platform.role,
        )

        if not extractor:
            logger.warning(
                "no_extractor_available",
                platform=platform.name,
                type=platform.platform_type.value,
            )
            # Return empty contract for now (extractors to be implemented)
            return Contract(
                name=platform.name,
                extracted_from=platform.platform_type.value,
            )

        try:
            contract = await extractor.extract()
            contract.name = platform.name
            contract.extracted_from = platform.platform_type.value
            return contract

        except Exception as e:
            logger.error(
                "contract_extraction_failed",
                platform=platform.name,
                error=str(e),
            )
            return None

    def _analyze_gaps(
        self,
        consumer: Contract,
        provider: Contract,
        consumer_name: str,
        provider_name: str,
    ) -> SpecAnalysisResult:
        """
        Analyze gaps between consumer and provider contracts.

        Args:
            consumer: Consumer contract (what frontend expects)
            provider: Provider contract (what backend offers)
            consumer_name: Consumer platform name
            provider_name: Provider platform name

        Returns:
            SpecAnalysisResult with gaps
        """
        result = SpecAnalysisResult(
            consumer_contract=consumer,
            provider_contract=provider,
            total_consumer_operations=len(consumer.operations),
            total_provider_operations=len(provider.operations),
        )

        # Get operation names
        consumer_ops = {op.name for op in consumer.operations}
        provider_ops = {op.name for op in provider.operations}

        # Find missing operations (consumer expects, provider missing)
        missing = consumer_ops - provider_ops
        for op_name in missing:
            consumer_op = consumer.get_operation(op_name)
            result.gaps.append(ContractGap(
                gap_type="missing_operation",
                severity=GapSeverity.CRITICAL,
                message=f"[GAP] {consumer_name} expects '{op_name}' but {provider_name} doesn't provide it",
                detail=f"Operation type: {consumer_op.operation_type.value}" if consumer_op else None,
                consumer_platform=consumer_name,
                provider_platform=provider_name,
                operation_name=op_name,
                consumer_file=consumer_op.source_file if consumer_op else None,
                consumer_line=consumer_op.source_line if consumer_op else None,
            ))
            result.missing_operations += 1

        # Find unused operations (provider has, consumer doesn't use)
        unused = provider_ops - consumer_ops
        for op_name in unused:
            provider_op = provider.get_operation(op_name)
            result.gaps.append(ContractGap(
                gap_type="unused_operation",
                severity=GapSeverity.LOW,
                message=f"[UNUSED] {provider_name} provides '{op_name}' but {consumer_name} doesn't use it",
                consumer_platform=consumer_name,
                provider_platform=provider_name,
                operation_name=op_name,
                provider_file=provider_op.source_file if provider_op else None,
                provider_line=provider_op.source_line if provider_op else None,
            ))
            result.unused_operations += 1

        # Find matched operations and check for type mismatches
        matched = consumer_ops & provider_ops
        result.matched_operations = len(matched)

        for op_name in matched:
            consumer_op = consumer.get_operation(op_name)
            provider_op = provider.get_operation(op_name)

            if consumer_op and provider_op:
                # Check input type mismatch
                if consumer_op.input_type != provider_op.input_type:
                    result.gaps.append(ContractGap(
                        gap_type="type_mismatch",
                        severity=GapSeverity.HIGH,
                        message=f"[TYPE] Input type mismatch for '{op_name}'",
                        detail=f"Consumer expects '{consumer_op.input_type}', provider uses '{provider_op.input_type}'",
                        consumer_platform=consumer_name,
                        provider_platform=provider_name,
                        operation_name=op_name,
                    ))
                    result.type_mismatches += 1

                # Check output type mismatch
                if consumer_op.output_type != provider_op.output_type:
                    result.gaps.append(ContractGap(
                        gap_type="type_mismatch",
                        severity=GapSeverity.HIGH,
                        message=f"[TYPE] Output type mismatch for '{op_name}'",
                        detail=f"Consumer expects '{consumer_op.output_type}', provider returns '{provider_op.output_type}'",
                        consumer_platform=consumer_name,
                        provider_platform=provider_name,
                        operation_name=op_name,
                    ))
                    result.type_mismatches += 1

        return result

    def _gap_to_finding(self, gap: ContractGap) -> Finding:
        """
        Convert a ContractGap to a Finding.

        Args:
            gap: Contract gap

        Returns:
            Finding object
        """
        location = ""
        if gap.consumer_file:
            location = gap.consumer_file
            if gap.consumer_line:
                location += f":{gap.consumer_line}"
        elif gap.provider_file:
            location = gap.provider_file
            if gap.provider_line:
                location += f":{gap.provider_line}"

        return Finding(
            id=f"{self.frame_id}-{gap.gap_type}-{gap.operation_name or 'unknown'}",
            severity=gap.severity.value,
            message=gap.message,
            location=location or "project-level",
            detail=gap.detail,
            code=None,
        )

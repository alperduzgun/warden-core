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
    SpecAnalysisResult,
)
from warden.validation.frames.spec.extractors.base import (
    get_extractor,
    ExtractorResilienceConfig,
)
from warden.validation.frames.spec.analyzer import GapAnalyzer, GapAnalyzerConfig
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import (
    with_timeout,
    OperationTimeoutError,
)

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
    requires_frames = []  # No dependencies - can run standalone
    requires_config = ["platforms"]  # Need platforms configuration
    requires_context = ["project_context"]  # Required for monorepo auto-detection

    def __init__(self, config: Dict[str, Any] | None = None, llm_service: Optional[Any] = None, semantic_search_service: Optional[Any] = None):
        """
        Initialize SpecFrame.

        Args:
            config: Frame configuration with 'platforms' list and optional 'suppressions'
        """
        super().__init__(config)
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
        # Parse platform configurations
        self.platforms: List[PlatformConfig] = []
        self._parse_platforms_config()
        # Load suppressions from config
        self._load_suppressions()

    async def cleanup(self) -> None:
        """
        Global Memory Hygiene: Release resources from all extractors.
        """
        logger.debug("spec_frame_cleanup_started")
        # In the future, we can iterate over platform extractors and call their own cleanup
        await super().cleanup()

    def _parse_platforms_config(self) -> None:
        """
        Parse platforms from config OR auto-detect from project_context.

        Auto-detection (monorepo):
        - If project_context.project_type == MONOREPO
        - Uses PlatformDetector to scan subdirectories
        - Automatically configures all detected platforms

        Manual config (fallback):
        - Reads from config['platforms']
        - Validates each platform configuration

        Validation:
        - Required fields: name, path, type, role
        - type must be valid PlatformType enum value
        - role must be valid PlatformRole enum value

        On error:
        - Logs detailed error with platform name and config
        - Continues to next platform (graceful degradation)
        - Invalid platforms are skipped
        """
        # Check for monorepo auto-detection
        if self.project_context:
            from warden.analysis.domain.project_context import ProjectType
            
            if self.project_context.project_type == ProjectType.MONOREPO:
                logger.info(
                    "monorepo_detected_auto_scanning",
                    project_root=self.project_context.project_root,
                )
                # Auto-detect platforms asynchronously
                # Note: This will be called from execute_async, so we defer to there
                return
        
        # Fallback to manual config
        if not self.config:
            return

        platforms_data = self.config.get("platforms", [])
        for p in platforms_data:
            try:
                platform = PlatformConfig.from_dict(p)
                self.platforms.append(platform)
                logger.debug(
                    "platform_config_parsed",
                    platform=platform.name,
                    type=platform.platform_type.value,
                    role=platform.role.value,
                )
            except ValueError as e:
                # Validation error - log with clear details
                logger.error(
                    "platform_config_validation_error",
                    platform=p.get("name", "unknown"),
                    config=p,
                    error=str(e),
                )
            except Exception as e:
                # Unexpected error - log with type for debugging
                logger.error(
                    "platform_config_parse_error",
                    platform=p.get("name", "unknown"),
                    config=p,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    def _load_suppressions(self) -> None:
        """
        Load suppression rules from frame configuration.

        Suppressions follow the standard Warden format:
            suppressions:
              - rule: "spec:missing_operation:createUser"
                files: ["src/api/*.py"]
                reason: "Legacy endpoint, being refactored"
              - rule: "spec:type_mismatch:*"
                files: ["*"]
                reason: "Type system migration in progress"

        Suppression key format:
            "spec:{gap_type}:{operation_name}"

        Examples:
            - "spec:missing_operation:deleteUser"
            - "spec:type_mismatch:getUserById"
            - "spec:*:*" (suppress all spec gaps)
        """
        self.suppressions: List[Dict[str, Any]] = []
        if not self.config:
            return

        suppressions_data = self.config.get("suppressions", [])
        if suppressions_data:
            self.suppressions = suppressions_data
            logger.info(
                "spec_suppressions_loaded",
                count=len(self.suppressions),
            )

    def _is_gap_suppressed(self, gap: ContractGap) -> bool:
        """
        Check if a gap is suppressed by configuration rules.

        Matches against suppression rules using:
        1. Suppression key: "spec:{gap_type}:{operation_name}"
        2. Wildcard support: "spec:*:*", "spec:missing_operation:*"
        3. File pattern matching (if gap has source file)

        Args:
            gap: Contract gap to check

        Returns:
            True if gap is suppressed, False otherwise
        """
        if not self.suppressions:
            return False

        gap_key = gap.get_suppression_key()
        gap_file = gap.consumer_file or gap.provider_file

        for suppression in self.suppressions:
            rule = suppression.get("rule", "")

            # Check rule match (supports wildcards)
            if not self._match_suppression_rule(rule, gap_key):
                continue

            # Check file pattern match if files specified
            files = suppression.get("files", [])
            if files and gap_file:
                import fnmatch
                if not any(fnmatch.fnmatch(gap_file, pattern) for pattern in files):
                    continue
            elif files and not gap_file:
                # Suppression has file patterns, but gap has no file - skip
                continue

            # Match found
            logger.debug(
                "gap_suppressed",
                gap_key=gap_key,
                suppression_rule=rule,
                reason=suppression.get("reason", "No reason provided"),
            )
            return True

        return False

    def _match_suppression_rule(self, rule: str, gap_key: str) -> bool:
        """
        Match suppression rule against gap key with wildcard support.

        Rules:
        - "spec:missing_operation:createUser" (exact match)
        - "spec:missing_operation:*" (all missing operations)
        - "spec:*:*" (all spec gaps)
        - "*" (all gaps)

        Args:
            rule: Suppression rule pattern
            gap_key: Gap suppression key

        Returns:
            True if rule matches gap_key
        """
        # Wildcard "*" matches everything
        if rule == "*":
            return True

        # Exact match
        if rule == gap_key:
            return True

        # Pattern matching with wildcards
        import fnmatch
        return fnmatch.fnmatch(gap_key, rule)

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute spec analysis asynchronously.

        Note: This frame operates at PROJECT_LEVEL, so code_file
        is typically the project root or a representative file.

        Args:
            code_file: Code file (project context)

        Returns:
            FrameResult with contract gap findings
        """
        return await self.execute(code_file)

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

        # Auto-detect platforms for monorepos if not already configured
        if self.project_context and not self.platforms:
            from warden.analysis.domain.project_context import ProjectType
            
            if self.project_context.project_type == ProjectType.MONOREPO:
                logger.info("monorepo_auto_detection_starting")
                await self._auto_detect_platforms()

        # Validate configuration
        validation_result = self._validate_configuration()
        if validation_result:
            return validation_result

        findings: List[Finding] = []
        metadata: Dict[str, Any] = {
            "platforms_analyzed": [],
            "contracts_extracted": 0,
            "gaps_found": 0,
            "suppressed_gaps": 0,
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
            all_gaps: List[ContractGap] = []

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

            # Gap analysis timeout config (SECURITY: Prevent DOS via expensive analysis)
            gap_analysis_timeout = self.config.get("gap_analysis_timeout", 120) if self.config else 120

            # Compare contracts (consumer vs provider)
            for consumer in consumers:
                consumer_contract = contracts.get(consumer.name)
                if not consumer_contract:
                    continue

                for provider in providers:
                    provider_contract = contracts.get(provider.name)
                    if not provider_contract:
                        continue

                    # Analyze gaps with timeout protection
                    try:
                        result = await with_timeout(
                            self._analyze_gaps(
                                consumer_contract,
                                provider_contract,
                                consumer.name,
                                provider.name,
                            ),
                            gap_analysis_timeout,
                            f"gap_analysis_{consumer.name}_vs_{provider.name}",
                        )

                        # Convert gaps to findings (filter suppressed gaps)
                        for gap in result.gaps:
                            # Check if gap is suppressed
                            if self._is_gap_suppressed(gap):
                                metadata["suppressed_gaps"] += 1
                                logger.info(
                                    "gap_suppressed_by_config",
                                    gap_type=gap.gap_type,
                                    operation=gap.operation_name,
                                    suppression_key=gap.get_suppression_key(),
                                )
                                continue

                            # Not suppressed - create finding
                            finding = self._gap_to_finding(gap)
                            findings.append(finding)
                            all_gaps.append(gap)
                            metadata["gaps_found"] += 1

                        # Track successful analysis
                        if "timeout_occurred" not in metadata:
                            metadata["timeout_occurred"] = False

                    except OperationTimeoutError:
                        # RESILIENCE: Graceful degradation on timeout
                        logger.error(
                            "gap_analysis_timeout",
                            consumer=consumer.name,
                            provider=provider.name,
                            timeout_seconds=gap_analysis_timeout,
                        )

                        # Create warning finding for timeout
                        timeout_finding = Finding(
                            id=f"{self.frame_id}-timeout-{consumer.name}-{provider.name}",
                            severity="warning",
                            message=f"Gap analysis timed out comparing {consumer.name} vs {provider.name}",
                            location="project-level",
                            detail=f"Analysis exceeded {gap_analysis_timeout}s timeout. "
                                   f"Partial results may be incomplete. "
                                   f"Consider increasing 'gap_analysis_timeout' config or optimizing contract size.",
                            code=None,
                        )
                        findings.append(timeout_finding)

                        # Track timeout in metadata
                        metadata["timeout_occurred"] = True
                        metadata["timeout_seconds"] = gap_analysis_timeout
                        metadata["timeout_pair"] = f"{consumer.name}_vs_{provider.name}"


            # Enrich project_context with findings
            self.enrich_project_context(contracts, all_gaps if 'all_gaps' in locals() else [], metadata)

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

    def _get_project_root(self) -> Path:
        """
        Get project root directory.

        Returns:
            Path to project root (where .warden directory is located)
        """
        # Look for .warden directory to identify project root
        current = Path.cwd()
        while current != current.parent:
            if (current / ".warden").exists():
                return current
            current = current.parent

        # Fallback to cwd if .warden not found
        logger.warning("project_root_not_found", fallback=str(Path.cwd()))
        return Path.cwd()

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

        # Get project root for resolving relative paths
        project_root = self._get_project_root()

        # Check platform paths exist
        for platform in self.platforms:
            platform_path = Path(platform.path)
            if not platform_path.is_absolute():
                # Resolve relative to project root (not cwd)
                platform_path = project_root / platform.path

            if not platform_path.exists():
                return self._create_skip_result(
                    f"Platform path not found: {platform.path} "
                    f"(resolved to: {platform_path.absolute()}) ({platform.name})"
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
        Extract contract from a platform with resilience patterns.

        Applies:
        - Timeout: Prevents indefinite hangs on large codebases
        - Graceful Degradation: Returns partial results if possible

        Args:
            platform: Platform configuration

        Returns:
            Contract or None if extraction fails completely
        """
        # Get project root for resolving relative paths
        project_root = self._get_project_root()

        # Resolve platform path
        platform_path = Path(platform.path)
        if not platform_path.is_absolute():
            # Resolve relative to project root (not cwd)
            platform_path = project_root / platform.path

        logger.debug(
            "resolving_platform_path",
            platform=platform.name,
            configured_path=platform.path,
            resolved_path=str(platform_path.absolute())
        )

        # Get resilience config from frame config if available
        resilience_config = ExtractorResilienceConfig()
        if self.config:
            res_config = self.config.get("resilience", {})
            if "parse_timeout" in res_config:
                resilience_config.parse_timeout = res_config["parse_timeout"]
            if "extraction_timeout" in res_config:
                resilience_config.extraction_timeout = res_config["extraction_timeout"]
            if "retry_max_attempts" in res_config:
                resilience_config.retry_max_attempts = res_config["retry_max_attempts"]
            if "max_concurrent_files" in res_config:
                resilience_config.max_concurrent_files = res_config["max_concurrent_files"]

        # Get appropriate extractor with resilience config
        extractor = get_extractor(
            platform.platform_type,
            platform_path,
            platform.role,
            resilience_config,
            llm_service=self.llm_service,  # Pass LLM for AI extraction
            semantic_search_service=self.semantic_search_service,  # Pass Vector DB for context
        )

        if not extractor:
            logger.warning(
                "no_extractor_available",
                platform=platform.name,
                type=platform.platform_type.value,
            )
            # Graceful degradation: Return empty contract instead of None
            return Contract(
                name=platform.name,
                extracted_from=platform.platform_type.value,
            )

        try:
            # Apply timeout to entire extraction process
            contract = await with_timeout(
                extractor.extract(),
                resilience_config.extraction_timeout,
                f"extract_{platform.name}",
            )
            contract.name = platform.name
            contract.extracted_from = platform.platform_type.value

            # Log extraction stats for observability
            stats = extractor.get_extraction_stats()
            logger.info(
                "contract_extraction_completed",
                platform=platform.name,
                operations=len(contract.operations),
                models=len(contract.models),
                **stats,
            )

            return contract

        except OperationTimeoutError:
            logger.error(
                "contract_extraction_timeout",
                platform=platform.name,
                timeout=resilience_config.extraction_timeout,
            )
            # Graceful degradation: Return empty contract with warning
            return self._create_degraded_contract(
                platform,
                f"Extraction timed out after {resilience_config.extraction_timeout}s",
            )

        except Exception as e:
            logger.error(
                "contract_extraction_failed",
                platform=platform.name,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Graceful degradation: Return empty contract with warning
            return self._create_degraded_contract(
                platform,
                f"Extraction failed: {str(e)}",
            )

    def _create_degraded_contract(
        self,
        platform: PlatformConfig,
        warning: str,
    ) -> Contract:
        """
        Create a degraded contract for graceful failure handling.

        Instead of returning None (which would skip the platform entirely),
        return an empty contract with metadata about the failure.
        This allows partial analysis to continue.

        Args:
            platform: Platform configuration
            warning: Warning message about degradation

        Returns:
            Empty contract with degradation metadata
        """
        logger.warning(
            "contract_degraded",
            platform=platform.name,
            warning=warning,
        )

        return Contract(
            name=platform.name,
            extracted_from=platform.platform_type.value,
            metadata={
                "degraded": True,
                "warning": warning,
                "platform_type": platform.platform_type.value,
                "platform_role": platform.role.value,
            },
        )

    async def _analyze_gaps(
        self,
        consumer: Contract,
        provider: Contract,
        consumer_name: str,
        provider_name: str,
    ) -> SpecAnalysisResult:
        """
        Analyze gaps between consumer and provider contracts.

        Uses GapAnalyzer for comprehensive comparison including:
        - Fuzzy operation name matching (getUsers ↔ fetchUsers)
        - Type compatibility checks (int ↔ number)
        - Model field comparison
        - Enum value comparison

        Note: Now async to support async semantic matching.

        Args:
            consumer: Consumer contract (what frontend expects)
            provider: Provider contract (what backend offers)
            consumer_name: Consumer platform name
            provider_name: Provider platform name

        Returns:
            SpecAnalysisResult with gaps
        """
        # Get analyzer config from frame config if available
        analyzer_config = GapAnalyzerConfig()

        if self.config:
            gap_config = self.config.get("gap_analysis", {})
            if "fuzzy_threshold" in gap_config:
                analyzer_config.fuzzy_match_threshold = gap_config["fuzzy_threshold"]
            if "enable_fuzzy" in gap_config:
                analyzer_config.enable_fuzzy_matching = gap_config["enable_fuzzy"]

        from warden.validation.frames.spec.analyzer import GapAnalyzer

        analyzer = GapAnalyzer(
            config=analyzer_config,  # Use the analyzer_config created above
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service
        )
        return await analyzer.analyze(
            consumer=consumer,
            provider=provider,
            consumer_platform=consumer_name,
            provider_platform=provider_name,
        )

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

    async def _auto_detect_platforms(self) -> None:
        """
        Auto-detect platforms in monorepo using PlatformDetector.
        
        Scans subdirectories for platform signatures (pubspec.yaml, package.json, etc.)
        and automatically configures detected platforms.
        """
        from warden.validation.frames.spec.platform_detector import PlatformDetector
        from pathlib import Path
        
        if not self.project_context:
            logger.warning("auto_detect_platforms_no_context")
            return
        
        project_root = Path(self.project_context.project_root)
        
        logger.info(
            "platform_auto_detection_started",
            project_root=str(project_root),
        )
        
        try:
            detector = PlatformDetector(
                max_depth=2,  # Don't scan too deep
                min_confidence=0.6,  # Require reasonable confidence
            )
            
            detected = await detector.detect_projects_async(project_root)
            
            logger.info(
                "platforms_detected",
                count=len(detected),
                platforms=[{"name": p.name, "type": p.platform_type.value, "role": p.role.value} for p in detected],
            )
            
            # Convert detected projects to PlatformConfig
            for project in detected:
                platform = PlatformConfig(
                    name=project.name,
                    path=project.path,
                    platform_type=project.platform_type,
                    role=project.role,
                )
                self.platforms.append(platform)
                
                logger.debug(
                    "platform_auto_configured",
                    name=project.name,
                    type=project.platform_type.value,
                    role=project.role.value,
                    confidence=project.confidence,
                )
        
        except Exception as e:
            logger.error(
                "platform_auto_detection_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

    def enrich_project_context(
        self,
        contracts: Dict[str, Contract],
        gaps: List[ContractGap],
        metadata: Dict[str, Any],
    ) -> None:
        """
        Enrich project_context with SpecFrame findings.
        
        Writes back discovered information to project_context so downstream
        frames can access:
        - Detected platforms and their metadata
        - Extracted API contracts
        - Contract gaps and drift analysis
        
        Args:
            contracts: Extracted contracts by platform name
            gaps: Detected contract gaps
            metadata: Analysis metadata
        """
        if not self.project_context:
            return
        
        # Create spec_analysis section in project_context
        spec_data = {
            "platforms": [
                {
                    "name": p.name,
                    "type": p.platform_type.value,
                    "role": p.role.value,
                    "path": p.path,
                }
                for p in self.platforms
            ],
            "contracts": {
                name: {
                    "operations_count": len(contract.operations),
                    "models_count": len(contract.models),
                    "enums_count": len(contract.enums),
                    "operations": [
                        {
                            "name": op.name,
                            "method": op.metadata.get('http_method', 'N/A'),
                            "path": op.metadata.get('endpoint', 'N/A'),
                        }
                        for op in contract.operations
                    ],
                }
                for name, contract in contracts.items()
            },
            "gaps": [
                {
                    "type": gap.gap_type,
                    "operation": gap.operation_name,
                    "severity": gap.severity.value,
                    "consumer": gap.consumer_platform,
                    "provider": gap.provider_platform,
                }
                for gap in gaps
            ],
            "metadata": metadata,
        }
        
        # Store in project_context
        self.project_context.spec_analysis = spec_data
        
        logger.info(
            "project_context_enriched",
            platforms=len(self.platforms),
            contracts=len(contracts),
            gaps=len(gaps),
        )

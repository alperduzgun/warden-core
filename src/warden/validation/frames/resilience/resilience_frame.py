"""
Chaos Engineering Analysis Frame.

Applies chaos engineering principles to code:
1. Detect external dependencies (network, DB, files, queues)
2. Simulate failure scenarios (timeout, error, resource exhaustion)
3. Identify MISSING resilience patterns (not validate existing ones)

Philosophy: "Everything will fail. The question is HOW and WHEN."
The LLM acts as a chaos engineer, deciding what failures to simulate
based on the code's context and dependencies.
"""

import re
import time
from typing import List, Dict, Any, Optional

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
from warden.shared.infrastructure.logging import get_logger
from warden.llm.providers.base import ILlmClient

logger = get_logger(__name__)

# =============================================================================
# LANGUAGE-SPECIFIC PATTERNS
# =============================================================================

# Chaos triggers by language (external dependencies that can fail)
CHAOS_TRIGGERS_BY_LANGUAGE: Dict[str, Dict[str, re.Pattern]] = {
    "python": {
        "network_calls": re.compile(r'\b(requests\.|httpx\.|aiohttp\.|urllib|grpc\.|ClientSession)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(cursor\.|execute\(|query\(|session\.|\.commit\(|\.rollback\(|sqlalchemy|asyncpg|psycopg)', re.IGNORECASE),
        "file_io": re.compile(r'\b(open\(|Path\(|\.read\(|\.write\(|os\.path|shutil\.|aiofiles)', re.IGNORECASE),
        "external_process": re.compile(r'\b(subprocess\.|Popen|os\.system|asyncio\.create_subprocess)', re.IGNORECASE),
        "async_operations": re.compile(r'\basync\s+def\b|\bawait\b', re.IGNORECASE),
        "message_queues": re.compile(r'\b(kafka|rabbitmq|redis|celery|pubsub|pika|aiokafka|aioredis)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(boto3|azure|gcloud|s3\.|dynamodb|lambda_client)', re.IGNORECASE),
    },
    "typescript": {
        "network_calls": re.compile(r'\b(fetch\(|axios\.|HttpClient|got\(|request\(|ky\.|superagent)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(query\(|execute\(|prisma\.|typeorm|sequelize|knex|mongoose)', re.IGNORECASE),
        "file_io": re.compile(r'\b(readFile|writeFile|fs\.|createReadStream|createWriteStream)', re.IGNORECASE),
        "external_process": re.compile(r'\b(spawn\(|exec\(|execSync|child_process|execa)', re.IGNORECASE),
        "async_operations": re.compile(r'\basync\s+function|\basync\s*\(|\bawait\b|\.then\(|Promise\.\w+', re.IGNORECASE),
        "message_queues": re.compile(r'\b(kafka|rabbitmq|redis|bull|amqplib|ioredis|pubsub)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(AWS\.|S3Client|DynamoDB|@aws-sdk|@azure|@google-cloud)', re.IGNORECASE),
    },
    "javascript": {
        "network_calls": re.compile(r'\b(fetch\(|axios\.|HttpClient|got\(|request\(|XMLHttpRequest)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(query\(|execute\(|mongoose|sequelize|knex|mongodb)', re.IGNORECASE),
        "file_io": re.compile(r'\b(readFile|writeFile|fs\.|createReadStream|createWriteStream)', re.IGNORECASE),
        "external_process": re.compile(r'\b(spawn\(|exec\(|execSync|child_process)', re.IGNORECASE),
        "async_operations": re.compile(r'\basync\s+function|\basync\s*\(|\bawait\b|\.then\(|Promise\.\w+', re.IGNORECASE),
        "message_queues": re.compile(r'\b(kafka|rabbitmq|redis|bull|amqplib)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(AWS\.|S3|DynamoDB|aws-sdk|azure|gcloud)', re.IGNORECASE),
    },
    "go": {
        "network_calls": re.compile(r'\b(http\.Get|http\.Post|http\.Client|grpc\.|net\.Dial|resty\.)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(sql\.Open|db\.Query|db\.Exec|gorm\.|sqlx\.|pgx\.)', re.IGNORECASE),
        "file_io": re.compile(r'\b(os\.Open|os\.Create|ioutil\.|bufio\.|io\.Read|io\.Write)', re.IGNORECASE),
        "external_process": re.compile(r'\b(exec\.Command|os\.StartProcess)', re.IGNORECASE),
        "async_operations": re.compile(r'\bgo\s+func|\bgo\s+\w+\(|<-\s*chan|\bchan\b', re.IGNORECASE),
        "message_queues": re.compile(r'\b(kafka|rabbitmq|redis|nats|amqp)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(aws\.|s3\.Client|dynamodb|lambda|azure|gcloud)', re.IGNORECASE),
    },
    "java": {
        "network_calls": re.compile(r'\b(HttpClient|RestTemplate|WebClient|OkHttp|Feign|HttpURLConnection)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(JdbcTemplate|EntityManager|Session\.|PreparedStatement|ResultSet|JPA|Hibernate)', re.IGNORECASE),
        "file_io": re.compile(r'\b(FileInputStream|FileOutputStream|Files\.|BufferedReader|BufferedWriter|Path\.)', re.IGNORECASE),
        "external_process": re.compile(r'\b(ProcessBuilder|Runtime\.exec|Process\b)', re.IGNORECASE),
        "async_operations": re.compile(r'\b(CompletableFuture|@Async|ExecutorService|Future<|Mono<|Flux<)', re.IGNORECASE),
        "message_queues": re.compile(r'\b(KafkaTemplate|RabbitTemplate|JmsTemplate|RedisTemplate|@KafkaListener)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(AmazonS3|DynamoDB|S3Client|AWSLambda|AzureStorage)', re.IGNORECASE),
    },
    "rust": {
        "network_calls": re.compile(r'\b(reqwest::|hyper::|surf::|Client::new|HttpClient|tonic::)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(sqlx::|diesel::|rusqlite::|tokio_postgres|mongodb::)', re.IGNORECASE),
        "file_io": re.compile(r'\b(File::open|File::create|std::fs::|tokio::fs::)', re.IGNORECASE),
        "external_process": re.compile(r'\b(Command::new|std::process::)', re.IGNORECASE),
        "async_operations": re.compile(r'\basync\s+fn|\bawait\b|\.await|tokio::|async_std::', re.IGNORECASE),
        "message_queues": re.compile(r'\b(kafka|rdkafka|lapin|redis::)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(aws_sdk|rusoto|s3::|dynamodb::)', re.IGNORECASE),
    },
    "csharp": {
        "network_calls": re.compile(r'\b(HttpClient|WebClient|RestClient|HttpWebRequest|Refit)', re.IGNORECASE),
        "database_ops": re.compile(r'\b(SqlConnection|DbContext|IDbConnection|Dapper|EntityFramework)', re.IGNORECASE),
        "file_io": re.compile(r'\b(File\.|StreamReader|StreamWriter|FileStream|Path\.)', re.IGNORECASE),
        "external_process": re.compile(r'\b(Process\.Start|ProcessStartInfo)', re.IGNORECASE),
        "async_operations": re.compile(r'\basync\s+Task|\bawait\b|Task<|ValueTask<', re.IGNORECASE),
        "message_queues": re.compile(r'\b(IServiceBus|RabbitMQ|MassTransit|NServiceBus|StackExchange\.Redis)', re.IGNORECASE),
        "cloud_services": re.compile(r'\b(AmazonS3|IAmazonDynamoDB|BlobClient|Azure\.)', re.IGNORECASE),
    },
}

# Resilience patterns by language
RESILIENCE_PATTERNS_BY_LANGUAGE: Dict[str, Dict[str, re.Pattern]] = {
    "python": {
        "try_except": re.compile(r'\btry\s*:', re.MULTILINE),
        "retry": re.compile(r'@retry|tenacity|backoff|retrying|with_retry', re.IGNORECASE),
        "timeout": re.compile(r'timeout=|@timeout|asyncio\.wait_for|async_timeout', re.IGNORECASE),
        "circuit_breaker": re.compile(r'circuit.?breaker|pybreaker|CircuitBreaker', re.IGNORECASE),
        "fallback": re.compile(r'\bfallback|@fallback|\.get\([^,]+,\s*[^)]+\)|or\s+default', re.IGNORECASE),
        "health_check": re.compile(r'health.?check|liveness|readiness|/health', re.IGNORECASE),
    },
    "typescript": {
        "try_catch": re.compile(r'\btry\s*\{', re.MULTILINE),
        "retry": re.compile(r'retry\(|p-retry|async-retry|axios-retry|got\.retry', re.IGNORECASE),
        "timeout": re.compile(r'timeout:|AbortController|Promise\.race|setTimeout', re.IGNORECASE),
        "circuit_breaker": re.compile(r'circuit.?breaker|opossum|cockatiel', re.IGNORECASE),
        "fallback": re.compile(r'\.catch\(|fallback|default:|Promise\.resolve|\?\?', re.IGNORECASE),
        "health_check": re.compile(r'health.?check|liveness|readiness|/health', re.IGNORECASE),
    },
    "javascript": {
        "try_catch": re.compile(r'\btry\s*\{', re.MULTILINE),
        "retry": re.compile(r'retry\(|p-retry|async-retry|axios-retry', re.IGNORECASE),
        "timeout": re.compile(r'timeout:|AbortController|Promise\.race|setTimeout', re.IGNORECASE),
        "circuit_breaker": re.compile(r'circuit.?breaker|opossum', re.IGNORECASE),
        "fallback": re.compile(r'\.catch\(|fallback|default:|Promise\.resolve', re.IGNORECASE),
        "health_check": re.compile(r'health.?check|liveness|readiness|/health', re.IGNORECASE),
    },
    "go": {
        "recover": re.compile(r'\brecover\(\)|\bdefer\b', re.MULTILINE),
        "retry": re.compile(r'retry\.|Retry\(|backoff\.|avast/retry', re.IGNORECASE),
        "timeout": re.compile(r'context\.WithTimeout|time\.After|ctx\.Done', re.IGNORECASE),
        "circuit_breaker": re.compile(r'circuit.?breaker|gobreaker|hystrix', re.IGNORECASE),
        "fallback": re.compile(r'fallback|default\s*:', re.IGNORECASE),
        "health_check": re.compile(r'health.?check|liveness|readiness|/health', re.IGNORECASE),
    },
    "java": {
        "try_catch": re.compile(r'\btry\s*\{', re.MULTILINE),
        "retry": re.compile(r'@Retry|@Retryable|RetryTemplate|resilience4j\.retry', re.IGNORECASE),
        "timeout": re.compile(r'@Timeout|\.timeout\(|CompletableFuture\.orTimeout|Duration\.of', re.IGNORECASE),
        "circuit_breaker": re.compile(r'@CircuitBreaker|CircuitBreakerRegistry|Resilience4j|Hystrix', re.IGNORECASE),
        "fallback": re.compile(r'@Fallback|fallbackMethod|\.onErrorResume', re.IGNORECASE),
        "health_check": re.compile(r'@HealthIndicator|HealthCheck|/actuator/health', re.IGNORECASE),
    },
    "rust": {
        "result_handling": re.compile(r'\?;|\.unwrap\(|\.expect\(|match\s+.*\{.*Err', re.MULTILINE),
        "retry": re.compile(r'retry::|tokio-retry|backoff::', re.IGNORECASE),
        "timeout": re.compile(r'timeout\(|tokio::time::timeout|async_std::future::timeout', re.IGNORECASE),
        "circuit_breaker": re.compile(r'circuit.?breaker|failsafe-rs', re.IGNORECASE),
        "fallback": re.compile(r'\.unwrap_or|\.unwrap_or_else|\.unwrap_or_default', re.IGNORECASE),
        "health_check": re.compile(r'health.?check|liveness|readiness|/health', re.IGNORECASE),
    },
    "csharp": {
        "try_catch": re.compile(r'\btry\s*\{', re.MULTILINE),
        "retry": re.compile(r'Polly\.Retry|\.WaitAndRetry|IAsyncPolicy|RetryPolicy', re.IGNORECASE),
        "timeout": re.compile(r'\.Timeout\(|CancellationToken|TimeSpan\.From', re.IGNORECASE),
        "circuit_breaker": re.compile(r'CircuitBreaker|Polly\.CircuitBreaker|\.AdvancedCircuitBreaker', re.IGNORECASE),
        "fallback": re.compile(r'\.Fallback|FallbackPolicy|\?\?\s*=|default\(', re.IGNORECASE),
        "health_check": re.compile(r'IHealthCheck|AddHealthChecks|/health', re.IGNORECASE),
    },
}

# Fallback patterns (language-agnostic)
CHAOS_TRIGGERS_GENERIC = {
    "network_calls": re.compile(r'\b(http|https|fetch|request|client|api|endpoint)', re.IGNORECASE),
    "database_ops": re.compile(r'\b(query|execute|select|insert|update|delete|database|db)', re.IGNORECASE),
    "file_io": re.compile(r'\b(read|write|file|open|close|stream)', re.IGNORECASE),
    "async_operations": re.compile(r'\b(async|await|promise|future|concurrent|parallel)', re.IGNORECASE),
    "message_queues": re.compile(r'\b(queue|kafka|rabbit|redis|pubsub|message)', re.IGNORECASE),
    "cloud_services": re.compile(r'\b(aws|azure|gcp|s3|blob|lambda|cloud)', re.IGNORECASE),
}

RESILIENCE_PATTERNS_GENERIC = {
    "error_handling": re.compile(r'\b(try|catch|except|error|exception|throw|raise)', re.IGNORECASE),
    "retry": re.compile(r'\b(retry|retries|backoff|exponential)', re.IGNORECASE),
    "timeout": re.compile(r'\b(timeout|deadline|cancel|abort)', re.IGNORECASE),
    "circuit_breaker": re.compile(r'\b(circuit|breaker|bulkhead|rate.?limit)', re.IGNORECASE),
    "fallback": re.compile(r'\b(fallback|default|backup|failover)', re.IGNORECASE),
}


class ResilienceFrame(ValidationFrame):
    """
    Chaos Engineering Analysis Frame.

    Applies chaos engineering principles: simulate failures, find missing resilience.

    APPROACH:
    1. Detect chaos triggers (external dependencies that can fail)
    2. Let LLM simulate failure scenarios based on context
    3. Report MISSING resilience patterns (timeout, retry, circuit breaker, fallback)

    The LLM acts as a chaos engineer - it decides what to test based on the code.
    """

    # Metadata
    name = "Chaos Engineering Analysis"
    description = "Chaos engineering: simulate failures, find missing resilience patterns."
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False  # Not blocking for now as it's advisory
    version = "2.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize Resilience Frame."""
        super().__init__(config)
        
        # Load System Prompt
        try:
            from warden.llm.prompts.resilience import CHAOS_SYSTEM_PROMPT
            self.system_prompt = CHAOS_SYSTEM_PROMPT
        except ImportError:
            logger.warning("resilience_prompt_import_failed")
            self.system_prompt = "You are a Resilience Engineer."

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute resilience analysis on code file.

        Strategy: LSP pre-analysis (cheap) → LLM deep analysis (expensive, only if needed)

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "resilience_analysis_started",
            file_path=code_file.path,
            language=code_file.language,
            has_llm_service=hasattr(self, 'llm_service'),
        )

        findings: List[Finding] = []

        # STEP 1: Quick pre-analysis - detect chaos triggers (external dependencies)
        pattern_findings, chaos_context = await self._pre_analyze_patterns(code_file)
        findings.extend(pattern_findings)

        worth_chaos_analysis = bool(chaos_context.get("triggers"))

        # STEP 2: LSP-based structural analysis (cheap, if file has dependencies)
        if worth_chaos_analysis:
            # Enrich context with cross-file info (callers, callees)
            await self._enrich_context_with_cross_file(code_file, chaos_context)

            lsp_findings = await self._analyze_with_lsp(code_file)
            findings.extend(lsp_findings)

        # STEP 3: LLM chaos engineering analysis (AI decides what to check)
        # CHAOS APPROACH: If file has external dependencies → LLM simulates failures
        # LLM will decide what resilience patterns are NEEDED (not validate existing ones)
        if hasattr(self, 'llm_service') and self.llm_service and worth_chaos_analysis:
            llm_findings = await self._analyze_with_llm(code_file, chaos_context)
            findings.extend(llm_findings)
        elif not worth_chaos_analysis:
            logger.debug("resilience_no_external_deps_skipping", file=code_file.path)

        # Determine status
        status = self._determine_status(findings)

        duration = time.perf_counter() - start_time

        logger.info(
            "resilience_analysis_completed",
            file_path=code_file.path,
            status=status,
            total_findings=len(findings),
            duration=f"{duration:.2f}s",
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings,
            metadata={
                "method": "chaos_engineering",
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
                "chaos_triggers": chaos_context.get("triggers", {}),
                "existing_patterns": chaos_context.get("existing_patterns", {}),
            },
        )

    def _get_patterns_for_language(self, language: str) -> tuple[Dict[str, re.Pattern], Dict[str, re.Pattern]]:
        """Get chaos triggers and resilience patterns for a specific language."""
        # Normalize language name
        lang_map = {
            "python": "python",
            "py": "python",
            "typescript": "typescript",
            "ts": "typescript",
            "javascript": "javascript",
            "js": "javascript",
            "go": "go",
            "golang": "go",
            "java": "java",
            "rust": "rust",
            "rs": "rust",
            "csharp": "csharp",
            "cs": "csharp",
            "c#": "csharp",
        }
        normalized = lang_map.get(language.lower(), language.lower())

        # Get language-specific patterns or fall back to generic
        chaos_patterns = CHAOS_TRIGGERS_BY_LANGUAGE.get(normalized, CHAOS_TRIGGERS_GENERIC)
        resilience_patterns = RESILIENCE_PATTERNS_BY_LANGUAGE.get(normalized, RESILIENCE_PATTERNS_GENERIC)

        return chaos_patterns, resilience_patterns

    async def _pre_analyze_patterns(self, code_file: CodeFile) -> tuple[List[Finding], Dict[str, Any]]:
        """
        Quick pattern-based pre-analysis for chaos engineering.

        CHAOS ENGINEERING APPROACH:
        - Don't look for "retry/timeout exists" → that's pattern validation
        - Look for "external dependencies exist" → that needs chaos analysis
        - LLM decides what resilience patterns are NEEDED, not what EXISTS

        Supports: Python, TypeScript, JavaScript, Go, Java, Rust, C#

        Returns:
            (findings, chaos_context): Findings and context for LLM (triggers, existing patterns)
        """
        findings: List[Finding] = []
        content = code_file.content

        # Get language-specific patterns
        chaos_patterns, resilience_patterns = self._get_patterns_for_language(code_file.language)

        # Count chaos triggers (things that CAN fail)
        trigger_counts: Dict[str, int] = {}
        for trigger_name, pattern in chaos_patterns.items():
            matches = pattern.findall(content)
            if matches:
                trigger_counts[trigger_name] = len(matches)

        # Also count existing resilience patterns (for context, not gating)
        resilience_counts: Dict[str, int] = {}
        for pattern_name, pattern in resilience_patterns.items():
            matches = pattern.findall(content)
            if matches:
                resilience_counts[pattern_name] = len(matches)

        # Quick structural findings (language-aware)
        lang = code_file.language.lower()

        # Check for try without catch/except based on language
        if lang in ("python", "py"):
            try_count = len(re.findall(r'\btry\s*:', content))
            except_count = len(re.findall(r'\bexcept\b.*:', content))
        elif lang in ("typescript", "ts", "javascript", "js", "java", "csharp", "cs", "c#"):
            try_count = len(re.findall(r'\btry\s*\{', content))
            except_count = len(re.findall(r'\bcatch\s*\(', content))
        elif lang in ("go", "golang"):
            # Go uses explicit error checking, not try/catch
            try_count = 0
            except_count = 0
        elif lang in ("rust", "rs"):
            # Rust uses Result/Option, check for unhandled ?
            try_count = len(re.findall(r'\?;', content))
            except_count = len(re.findall(r'match\s+.*\{.*Err|\.unwrap_or|\.expect\(', content, re.DOTALL))
        else:
            # Generic fallback
            try_count = len(re.findall(r'\btry\b', content, re.IGNORECASE))
            except_count = len(re.findall(r'\b(catch|except|rescue)\b', content, re.IGNORECASE))

        if try_count > 0 and except_count == 0:
            findings.append(Finding(
                id=f"{self.frame_id}-bare-try",
                severity="medium",
                message="Error handling structure without proper catch/recovery detected",
                location=f"{code_file.path}:1",
                detail="Consider adding proper error handling for resilience",
                code=None
            ))

        # Build chaos context for LLM
        chaos_context: Dict[str, Any] = {
            "triggers": trigger_counts,  # What can fail
            "existing_patterns": resilience_counts,  # What protection exists
            "dependencies": list(trigger_counts.keys()),  # For LLM prompt
            "cross_file": {},  # Will be enriched by LSP
        }

        logger.debug("resilience_pre_analysis_complete",
                    file=code_file.path,
                    chaos_triggers=trigger_counts,
                    resilience_patterns=resilience_counts,
                    findings=len(findings))

        return findings, chaos_context

    async def _enrich_context_with_cross_file(self, code_file: CodeFile, chaos_context: Dict[str, Any]) -> None:
        """
        Enrich chaos context with cross-file information using LSP.

        Adds:
        - callers: Files/functions that call into this file (blast radius)
        - callees: External files this code depends on (failure sources)
        """
        try:
            from warden.lsp import get_semantic_analyzer
            import asyncio

            analyzer = get_semantic_analyzer()

            # Find exported functions (public API of this file) - language-aware
            lang = code_file.language.lower()
            if lang in ("python", "py"):
                func_pattern = re.compile(r'^(?:async\s+)?def\s+([a-z_][a-z0-9_]*)\s*\(', re.MULTILINE)
            elif lang in ("typescript", "ts", "javascript", "js"):
                func_pattern = re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(', re.MULTILINE)
            elif lang in ("go", "golang"):
                func_pattern = re.compile(r'^func\s+(\w+)\s*\(', re.MULTILINE)
            elif lang in ("java", "csharp", "cs", "c#"):
                func_pattern = re.compile(r'(?:public|protected)\s+(?:async\s+)?(?:static\s+)?\w+\s+(\w+)\s*\(', re.MULTILINE)
            elif lang in ("rust", "rs"):
                func_pattern = re.compile(r'^pub\s+(?:async\s+)?fn\s+(\w+)', re.MULTILINE)
            else:
                func_pattern = re.compile(r'\bfunction\s+(\w+)\s*\(|\bdef\s+(\w+)\s*\(', re.MULTILINE)

            matches = func_pattern.finditer(code_file.content)
            public_funcs = []
            for m in matches:
                # Get the first non-None group
                func_name = next((g for g in m.groups() if g), None)
                if func_name and not func_name.startswith('_'):
                    public_funcs.append(func_name)

            callers_info = []
            callees_info = []

            # Sample up to 3 public functions (avoid slow analysis)
            for func_name in public_funcs[:3]:
                # Find the function line
                match = re.search(rf'^(?:async\s+)?def\s+{func_name}\s*\(', code_file.content, re.MULTILINE)
                if match:
                    line_num = code_file.content[:match.start()].count('\n')

                    try:
                        # Get callers (who depends on this function?)
                        callers = await asyncio.wait_for(
                            analyzer.get_callers_async(code_file.path, line_num, 4, content=code_file.content),
                            timeout=5.0
                        )
                        if callers:
                            callers_info.extend([
                                {"func": func_name, "caller": c.name, "file": c.location}
                                for c in callers[:3]  # Limit
                            ])

                        # Get callees (what does this function call?)
                        callees = await asyncio.wait_for(
                            analyzer.get_callees_async(code_file.path, line_num, 4, content=code_file.content),
                            timeout=5.0
                        )
                        if callees:
                            callees_info.extend([
                                {"func": func_name, "callee": c.name, "file": c.location}
                                for c in callees[:3]  # Limit
                            ])
                    except asyncio.TimeoutError:
                        continue

            chaos_context["cross_file"] = {
                "callers": callers_info,  # Blast radius
                "callees": callees_info,  # Failure sources
                "public_functions": public_funcs[:5],
            }

            logger.debug("resilience_cross_file_enriched",
                        file=code_file.path,
                        callers=len(callers_info),
                        callees=len(callees_info))

        except ImportError:
            logger.debug("resilience_lsp_not_available_for_enrichment")
        except Exception as e:
            logger.warning("resilience_cross_file_enrichment_failed", error=str(e))

    async def _analyze_with_lsp(self, code_file: CodeFile) -> List[Finding]:
        """
        Use LSP for structural resilience analysis (cheap, before LLM).

        Checks:
        1. Unused error handlers (dead code)
        2. Fallback functions not connected
        3. Retry/timeout decorators on wrong functions
        4. Async functions calling external APIs without timeout (no LSP needed)

        Uses 10s timeout per LSP call to fail fast.
        """
        import asyncio
        findings: List[Finding] = []

        # Check 4 doesn't need LSP - do it first (instant)
        self._check_async_without_timeout_sync(code_file, findings)

        try:
            from warden.lsp import get_semantic_analyzer

            analyzer = get_semantic_analyzer()

            # Run LSP checks with individual timeouts (fail fast)
            lsp_timeout = 10.0  # 10s per check, not 30s

            # Collect all checks to run
            checks = [
                self._check_unused_handlers(analyzer, code_file, findings),
                self._check_unused_fallbacks(analyzer, code_file, findings),
                self._check_decorated_functions(analyzer, code_file, findings),
            ]

            # Run with timeout - if LSP is slow, skip gracefully
            try:
                await asyncio.wait_for(
                    asyncio.gather(*checks, return_exceptions=True),
                    timeout=lsp_timeout * 3  # Total timeout for all checks
                )
            except asyncio.TimeoutError:
                logger.warning("resilience_lsp_timeout_skipping", file=code_file.path)

            logger.debug("resilience_lsp_analysis_complete",
                        file=code_file.path,
                        findings=len(findings))

        except ImportError:
            logger.debug("resilience_lsp_not_available")
        except Exception as e:
            logger.warning("resilience_lsp_analysis_error", error=str(e))

        return findings

    def _check_async_without_timeout_sync(self, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check async functions calling external services without timeout (multi-language)."""
        content = code_file.content
        lang = code_file.language.lower()

        # Language-specific patterns for async functions with external calls
        if lang in ("python", "py"):
            pattern = re.compile(
                r'async\s+def\s+(\w+)\s*\([^)]*\)[^:]*:'
                r'(?:(?!async\s+def).)*?'
                r'(?:await\s+(?:self\.)?(?:client|http|session|request|api|fetch)\.\w+)',
                re.DOTALL
            )
            timeout_indicators = ['wait_for', 'timeout=', '@timeout', 'async_timeout']
        elif lang in ("typescript", "ts", "javascript", "js"):
            pattern = re.compile(
                r'async\s+(?:function\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{'
                r'(?:(?!async\s+function|async\s+\w+\s*=).)*?'
                r'(?:await\s+(?:fetch|axios|got|request|http)\b)',
                re.DOTALL
            )
            timeout_indicators = ['AbortController', 'timeout:', 'Promise.race', 'signal:']
        elif lang in ("go", "golang"):
            pattern = re.compile(
                r'func\s+(\w+)\s*\([^)]*\)[^{]*\{'
                r'(?:(?!func\s+).)*?'
                r'(?:http\.(?:Get|Post|Do)|\.(?:Get|Post)\()',
                re.DOTALL
            )
            timeout_indicators = ['context.WithTimeout', 'context.WithDeadline', 'time.After', 'ctx.Done']
        elif lang in ("java",):
            pattern = re.compile(
                r'(?:public|private|protected)\s+(?:async\s+)?\w+\s+(\w+)\s*\([^)]*\)[^{]*\{'
                r'(?:(?!(?:public|private|protected)\s+).)*?'
                r'(?:HttpClient|RestTemplate|WebClient)',
                re.DOTALL
            )
            timeout_indicators = ['.timeout(', 'Duration.of', '@Timeout', 'CompletableFuture.orTimeout']
        elif lang in ("rust", "rs"):
            pattern = re.compile(
                r'(?:pub\s+)?async\s+fn\s+(\w+)[^{]*\{'
                r'(?:(?!async\s+fn).)*?'
                r'(?:reqwest::|hyper::|\.get\(|\.post\()',
                re.DOTALL
            )
            timeout_indicators = ['timeout(', 'tokio::time::timeout']
        elif lang in ("csharp", "cs", "c#"):
            pattern = re.compile(
                r'(?:public|private|protected)\s+async\s+Task[^(]*\s+(\w+)\s*\([^)]*\)[^{]*\{'
                r'(?:(?!(?:public|private|protected)\s+).)*?'
                r'(?:HttpClient|WebClient)',
                re.DOTALL
            )
            timeout_indicators = ['.Timeout', 'CancellationToken', 'TimeSpan']
        else:
            # Skip for unsupported languages
            return

        for match in pattern.finditer(content):
            func_name = match.group(1)
            func_content = match.group(0)
            line_num = content[:match.start()].count('\n')

            # Check if this function has timeout
            has_timeout = any(indicator in func_content for indicator in timeout_indicators)
            # Also check decorators/attributes before function
            prefix = content[max(0, match.start()-100):match.start()]
            has_timeout = has_timeout or any(indicator in prefix for indicator in timeout_indicators)

            if not has_timeout:
                findings.append(Finding(
                    id=f"{self.frame_id}-async-no-timeout-{line_num}",
                    severity="medium",
                    message=f"Async function '{func_name}' calls external service without timeout",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="External API calls should have timeouts to prevent hanging",
                    code=func_name
                ))

    async def _check_unused_handlers(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check for error handlers that are never called."""
        exception_pattern = re.compile(r'def\s+(handle_\w*error|on_\w*error|_handle_exception|error_callback)\s*\(')

        for match in exception_pattern.finditer(code_file.content):
            func_name = match.group(1)
            line_num = code_file.content[:match.start()].count('\n')

            is_used = await analyzer.is_symbol_used_async(
                code_file.path, line_num, match.start(1) - match.start(),
                content=code_file.content
            )

            if is_used is False:
                findings.append(Finding(
                    id=f"{self.frame_id}-unused-handler-{line_num}",
                    severity="medium",
                    message=f"Error handler '{func_name}' is defined but never called",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="Dead error handler - ensure it's connected to the error handling flow",
                    code=func_name
                ))

    async def _check_unused_fallbacks(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check for fallback functions that are never called."""
        fallback_pattern = re.compile(r'def\s+(fallback_\w+|get_default_\w+|_fallback)\s*\(')

        for match in fallback_pattern.finditer(code_file.content):
            func_name = match.group(1)
            line_num = code_file.content[:match.start()].count('\n')

            is_used = await analyzer.is_symbol_used_async(
                code_file.path, line_num, match.start(1) - match.start(),
                content=code_file.content
            )

            if is_used is False:
                findings.append(Finding(
                    id=f"{self.frame_id}-unused-fallback-{line_num}",
                    severity="medium",
                    message=f"Fallback function '{func_name}' is defined but never used",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="Fallback should be called in error handling paths",
                    code=func_name
                ))

    async def _check_decorated_functions(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check if @retry/@timeout decorated functions are actually called."""
        # Find functions with resilience decorators
        decorated_pattern = re.compile(r'@(?:retry|timeout|circuit_?breaker)\s*(?:\([^)]*\))?\s*\n\s*(?:async\s+)?def\s+(\w+)')

        for match in decorated_pattern.finditer(code_file.content):
            func_name = match.group(1)
            line_num = code_file.content[:match.end()].count('\n')

            is_used = await analyzer.is_symbol_used_async(
                code_file.path, line_num, 4,  # After 'def '
                content=code_file.content
            )

            if is_used is False:
                findings.append(Finding(
                    id=f"{self.frame_id}-unused-decorated-{line_num}",
                    severity="low",
                    message=f"Decorated function '{func_name}' has resilience decorator but is never called",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="Function with @retry/@timeout/@circuit_breaker is dead code",
                    code=func_name
                ))

    async def _check_async_without_timeout(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check async functions that call external services without timeout."""
        # Find async functions that likely call external APIs
        external_call_pattern = re.compile(
            r'async\s+def\s+(\w+)\s*\([^)]*\)[^:]*:'
            r'(?:(?!async\s+def).)*?'  # Content until next async def
            r'(?:await\s+(?:self\.)?(?:client|http|session|request|api|fetch)\.\w+)',
            re.DOTALL
        )

        content = code_file.content

        for match in external_call_pattern.finditer(content):
            func_name = match.group(1)
            func_content = match.group(0)
            line_num = content[:match.start()].count('\n')

            # Check if this function has timeout wrapper
            has_timeout = (
                'wait_for' in func_content or
                'timeout=' in func_content or
                '@timeout' in content[max(0, match.start()-50):match.start()]
            )

            if not has_timeout:
                findings.append(Finding(
                    id=f"{self.frame_id}-async-no-timeout-{line_num}",
                    severity="medium",
                    message=f"Async function '{func_name}' calls external service without timeout",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="External API calls should have timeouts to prevent hanging",
                    code=func_name
                ))

    async def _analyze_with_llm(self, code_file: CodeFile, chaos_context: Optional[Dict[str, Any]] = None) -> List[Finding]:
        """
        Analyze code using LLM for chaos engineering (expensive, context-aware).

        Args:
            code_file: Code to analyze
            chaos_context: Detected triggers and existing patterns from pre-analysis
        """
        from warden.llm.prompts.resilience import CHAOS_SYSTEM_PROMPT, generate_chaos_request
        from warden.llm.types import LlmRequest, AnalysisResult

        findings: List[Finding] = []
        try:
            logger.info("resilience_llm_analysis_started",
                       file=code_file.path,
                       triggers=chaos_context.get("triggers") if chaos_context else None)

            client: ILlmClient = self.llm_service

            # Pass chaos context to LLM so it knows what dependencies to focus on
            request = LlmRequest(
                system_prompt=CHAOS_SYSTEM_PROMPT,
                user_message=generate_chaos_request(
                    code_file.content,
                    code_file.language,
                    code_file.path,
                    context=chaos_context
                ),
                temperature=0.0,  # Idempotency (deterministic scenarios)
            )
            
            response = await client.send_async(request)
            
            if response.success and response.content:
                # Use robust shared JSON parser
                from warden.shared.utils.json_parser import parse_json_from_llm
                json_data = parse_json_from_llm(response.content)
                
                if json_data:
                    try:
                        # Parse result with Pydantic
                        result = AnalysisResult.from_json(json_data)
                        
                        for issue in result.issues:
                            findings.append(Finding(
                                id=f"{self.frame_id}-resilience-{issue.line}",
                                severity=issue.severity,
                                message=issue.title,
                                location=f"{code_file.path}:{issue.line}",
                                detail=f"{issue.description}\n\nSuggestion: {issue.suggestion}",
                                code=issue.evidence_quote
                            ))
                        
                        logger.info("resilience_llm_analysis_completed", 
                                  findings=len(findings), 
                                  confidence=result.confidence,
                                  resilience_score=result.score)
                                  
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning("resilience_llm_parsing_failed", error=str(e), content_preview=response.content[:100])
                else:
                    logger.warning("resilience_llm_response_not_json", content_preview=response.content[:100])
            else:
                 logger.warning("resilience_llm_request_failed", error=response.error_message)

        except (RuntimeError, AttributeError, ValueError) as e:
            logger.error("resilience_llm_error", error=str(e))
            
        return findings

    def _determine_status(self, findings: List[Finding]) -> str:
        """Determine frame status based on findings."""
        if not findings:
            return "passed"

        critical_count = sum(1 for f in findings if f.severity == "critical")
        high_count = sum(1 for f in findings if f.severity == "high")

        if critical_count > 0:
            return "failed"
        elif high_count > 0:
            return "warning"
        
        return "passed"

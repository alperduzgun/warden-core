"""
Service Abstraction Detector.

Detects project-specific service abstractions (like SecretManager, ConfigLoader)
and their responsibilities for context-aware consistency enforcement.
"""

from typing import Dict, List, Optional, Set, Any, Tuple
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
import structlog
import json

from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage, ASTNodeType
from warden.analysis.domain.project_context import ProjectContext
from warden.llm.factory import create_client
from warden.llm.config import LlmConfiguration
from warden.llm.types import LlmRequest

logger = structlog.get_logger(__name__)


class ServiceCategory(Enum):
    """Category of service abstraction."""
    SECRET_MANAGEMENT = "secret_management"
    CONFIG_MANAGEMENT = "config_management"
    DATABASE_ACCESS = "database_access"
    LOGGING = "logging"
    CACHING = "caching"
    HTTP_CLIENT = "http_client"
    MESSAGE_QUEUE = "message_queue"
    FILE_STORAGE = "file_storage"
    AUTHENTICATION = "authentication"
    CUSTOM = "custom"


@dataclass
class ServiceAbstraction:
    """Represents a detected service abstraction in the project."""
    
    # Basic info
    name: str  # Class name (e.g., "SecretManager")
    file_path: str  # File where it's defined
    category: ServiceCategory = ServiceCategory.CUSTOM
    
    # What the service handles
    responsibilities: List[str] = field(default_factory=list)
    # e.g., ["secret access", "API key retrieval"]
    
    # Bypass patterns - what NOT to use when this service exists
    bypass_patterns: List[str] = field(default_factory=list)
    # e.g., ["os.getenv", "os.environ.get"] for SecretManager
    
    # Keywords that indicate this service should be used
    responsibility_keywords: List[str] = field(default_factory=list)
    # e.g., ["API_KEY", "SECRET", "TOKEN", "PASSWORD"]
    
    # Methods exposed by this service
    public_methods: List[str] = field(default_factory=list)
    
    # Confidence in detection (0.0 to 1.0)
    confidence: float = 0.0
    
    # Documentation/description from docstring
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "file_path": self.file_path,
            "category": self.category.value,
            "responsibilities": self.responsibilities,
            "bypass_patterns": self.bypass_patterns,
            "responsibility_keywords": self.responsibility_keywords,
            "public_methods": self.public_methods,
            "confidence": self.confidence,
            "description": self.description,
        }


# Known patterns for detecting service categories
SERVICE_PATTERNS = {
    ServiceCategory.SECRET_MANAGEMENT: {
        "class_patterns": ["SecretManager", "SecretProvider", "VaultClient", "KeyManager", "CredentialManager"],
        "method_patterns": ["get_secret", "load_secret", "retrieve_secret", "get_credential"],
        "bypass_patterns": ["os.getenv", "os.environ.get", "os.environ["],
        "keywords": ["API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "KEY_VAULT"],
    },
    ServiceCategory.CONFIG_MANAGEMENT: {
        "class_patterns": ["ConfigLoader", "ConfigManager", "SettingsProvider", "ConfigService", "AppConfig"],
        "method_patterns": ["get_config", "load_config", "get_setting", "get_value"],
        "bypass_patterns": ["yaml.safe_load", "json.load", "toml.load", "configparser"],
        "keywords": ["CONFIG", "SETTING", "CONFIGURATION"],
    },
    ServiceCategory.DATABASE_ACCESS: {
        "class_patterns": ["DatabasePool", "ConnectionManager", "DBClient", "Repository", "DataAccess"],
        "method_patterns": ["get_connection", "execute", "query", "find", "save"],
        "bypass_patterns": ["psycopg2.connect", "pymysql.connect", "sqlite3.connect"],
        "keywords": ["DATABASE", "DB", "CONNECTION", "QUERY"],
    },
    ServiceCategory.LOGGING: {
        "class_patterns": ["LoggingService", "LogManager", "AppLogger", "CustomLogger"],
        "method_patterns": ["log", "info", "debug", "error", "warn"],
        "bypass_patterns": ["print(", "print ("],
        "keywords": ["LOG", "LOGGING"],
    },
    ServiceCategory.CACHING: {
        "class_patterns": ["CacheService", "CacheManager", "RedisClient", "MemcacheClient"],
        "method_patterns": ["get", "set", "cache", "invalidate", "clear"],
        "bypass_patterns": [],
        "keywords": ["CACHE", "REDIS", "MEMCACHE"],
    },
    ServiceCategory.HTTP_CLIENT: {
        "class_patterns": ["HttpClient", "ApiClient", "RequestService", "RestClient"],
        "method_patterns": ["get", "post", "put", "delete", "request"],
        "bypass_patterns": ["requests.get", "requests.post", "urllib.request"],
        "keywords": ["HTTP", "API", "REQUEST"],
    },
}


class ServiceAbstractionDetector:
    """
    Detects service abstractions in a project for context-aware consistency enforcement.
    
    This detector:
    1. Scans project files using the best available AST provider
    2. Matches against known service patterns
    3. Extracts responsibilities from docstrings and method names
    4. Identifies bypass patterns that should be avoided when these services exist
    """
    
    def __init__(
        self, 
        project_root: Path, 
        project_context: Optional[ProjectContext] = None,
        llm_config: Optional[LlmConfiguration] = None
    ) -> None:
        """
        Initialize detector.
        
        Args:
            project_root: Root directory of the project
            project_context: Optional project context for language detection
            llm_config: Optional LLM configuration for bypass synthesis
        """
        self.project_root = Path(project_root)
        self.project_context = project_context
        self.abstractions: Dict[str, ServiceAbstraction] = {}
        
        # Initialize AST registry
        self.registry = ASTProviderRegistry()
        self._registry_initialized = False
        
        # Initialize LLM
        try:
            self.llm = create_client(llm_config) if llm_config else create_client()
        except Exception as e:
            logger.debug("llm_client_creation_failed_for_detector", error=str(e))
            self.llm = None
    
    async def _ensure_registry(self) -> None:
        """Ensure AST registry is initialized and loaded."""
        if not self._registry_initialized:
            await self.registry.discover_providers()
            self._registry_initialized = True
    
    async def detect_async(self) -> Dict[str, ServiceAbstraction]:
        """
        Detect service abstractions in the project.
        
        Returns:
            Dictionary mapping class name to ServiceAbstraction
        """
        await self._ensure_registry()
        
        logger.info("service_abstraction_detection_started", project=str(self.project_root))
        
        # Determine languages to scan
        languages = self._get_scan_languages()
        
        # Find all relevant files
        project_files = self._find_project_files(languages)
        
        for file_path, language in project_files:
            try:
                await self._analyze_file_async(file_path, language)
            except Exception as e:
                logger.debug("file_analysis_failed", file=str(file_path), error=str(e))
        
        # Post-process: enrich with LLM-synthesized bypass rules if possible
        await self._synthesize_bypass_rules_async()
        
        # Enrich with local context
        self._enrich_abstractions()
        
        logger.info(
            "service_abstraction_detection_completed",
            detected_count=len(self.abstractions),
            categories=[a.category.value for a in self.abstractions.values()],
        )
        
        return self.abstractions

    def _get_scan_languages(self) -> List[CodeLanguage]:
        """Determine which languages to scan based on project context."""
        if self.project_context and self.project_context.primary_language:
            primary = self.project_context.primary_language.lower()
            try:
                return [CodeLanguage(primary)]
            except ValueError:
                pass
        
        # Fallback to common languages
        return [CodeLanguage.PYTHON, CodeLanguage.TYPESCRIPT, CodeLanguage.JAVASCRIPT, CodeLanguage.GO]

    def _find_project_files(self, languages: List[CodeLanguage]) -> List[Tuple[Path, CodeLanguage]]:
        """Find relevant project files for the given languages."""
        lang_extensions = {
            CodeLanguage.PYTHON: [".py"],
            CodeLanguage.TYPESCRIPT: [".ts", ".tsx"],
            CodeLanguage.JAVASCRIPT: [".js", ".jsx"],
            CodeLanguage.GO: [".go"],
            CodeLanguage.JAVA: [".java"],
        }
        
        excluded_patterns = [
            "node_modules", "venv", ".venv", "env", "__pycache__",
            "dist", "build", ".git", ".tox", ".mypy_cache", "vendor",
        ]
        
        files = []
        for lang in languages:
            extensions = lang_extensions.get(lang, [])
            for ext in extensions:
                for file_path in self.project_root.rglob(f"*{ext}"):
                    if any(excl in str(file_path) for excl in excluded_patterns):
                        continue
                    if "test" in file_path.name.lower() or file_path.name.startswith("test_"):
                        continue
                    files.append((file_path, lang))
        
        return files

    async def _analyze_file_async(self, file_path: Path, language: CodeLanguage) -> None:
        """Analyze a file using the appropriate AST provider."""
        provider = self.registry.get_provider(language)
        if not provider:
            return

        content = file_path.read_text(encoding="utf-8", errors="ignore")
        result = await provider.parse(content, language, str(file_path))
        
        if not result.ast_root:
            return

        # Find classes and interfaces
        type_nodes = []
        type_nodes.extend(result.ast_root.find_nodes(ASTNodeType.CLASS))
        type_nodes.extend(result.ast_root.find_nodes(ASTNodeType.INTERFACE))
        
        for node in type_nodes:
            abstraction = self._analyze_node(node, file_path, content, language)
            if abstraction and abstraction.confidence > 0.3:
                # If we find a class/interface with the same name, the most detailed one wins
                existing = self.abstractions.get(abstraction.name)
                if not existing or abstraction.confidence > existing.confidence:
                    self.abstractions[abstraction.name] = abstraction

    def _analyze_node(
        self, 
        node: Any, # ASTNode
        file_path: Path,
        file_content: str,
        language: CodeLanguage
    ) -> Optional[ServiceAbstraction]:
        """Analyze a class or interface node for service abstraction characteristics."""
        name = node.name
        logger.debug("analyzing_service_candidate", node_type=node.node_type.value, name=name)
        if not name or name.startswith("_"):
            return None

        # Detect category based on name
        category, category_confidence = self._detect_category_from_name(name)
        
        # Check if it looks like a service
        service_suffixes = ["Service", "Manager", "Provider", "Client", "Handler", "Factory", "Repository"]
        if category == ServiceCategory.CUSTOM and category_confidence < 0.5:
            if not any(name.endswith(suffix) for suffix in service_suffixes):
                return None

        # Extract methods
        method_nodes = node.find_nodes(ASTNodeType.METHOD)
        if not method_nodes:
            # Fallback: check children for functions which might be methods in some parsers
            method_nodes = [c for c in node.children if c.node_type == ASTNodeType.FUNCTION]
            
        public_methods = [m.name for m in method_nodes if m.name and not m.name.startswith("_")]
        
        # Extract description (docstrings are often in attributes or as comments)
        description = node.attributes.get("docstring") or ""
        if not description and node.children:
            # Check first child if it's a literal string (docstring pattern)
            first_child = node.children[0]
            if first_child.node_type == ASTNodeType.LITERAL and isinstance(first_child.value, str):
                description = first_child.value

        # Create abstraction
        abstraction = ServiceAbstraction(
            name=name,
            file_path=str(file_path.relative_to(self.project_root)),
            category=category,
            public_methods=public_methods,
            description=description[:200] if description else "",
            confidence=category_confidence,
        )
        
        # Set bypass patterns and keywords
        if category in SERVICE_PATTERNS:
            patterns = SERVICE_PATTERNS[category]
            abstraction.bypass_patterns = patterns.get("bypass_patterns", [])
            abstraction.responsibility_keywords = patterns.get("keywords", [])
            
            # Boost confidence for expected methods
            method_patterns = patterns.get("method_patterns", [])
            matching_methods = sum(1 for m in public_methods if any(p in m.lower() for p in method_patterns))
            if matching_methods > 0:
                abstraction.confidence = min(1.0, abstraction.confidence + 0.2)
        
        return abstraction
    
    async def _synthesize_bypass_rules_async(self) -> None:
        """Use LLM to synthesize bypass rules for detected services."""
        if not self.llm or not self.abstractions:
            return

        logger.info("synthesizing_bypass_rules", count=len(self.abstractions))
        
        # Collect services that need rules
        services_to_analyze = []
        for name, abs_info in self.abstractions.items():
            # If it's a known category, it already has some rules, but LLM can refine or find new ones
            services_to_analyze.append({
                "name": name,
                "category": abs_info.category.value,
                "methods": abs_info.public_methods[:10],
                "description": abs_info.description
            })
            
        if not services_to_analyze:
            return

        prompt = f"""Analyze the following service abstractions detected in a software project.
For each service, identify the exact external libraries or global functions it is likely abstracting.
Generate specific 'Bypass Rules' (e.g., regex patterns or library names) that should NOT be used directly when this service exists.

SERVICES:
{json.dumps(services_to_analyze, indent=2)}

TASK:
1. For each service, suggest 2-3 specific bypass patterns (e.g. "import stripe", "os.getenv").
2. Identify 2-3 specific responsibility keywords.

Return strictly JSON:
{{
  "abstractions": [
    {{
      "name": "ServiceName",
      "bypass_patterns": ["pattern1", "pattern2"],
      "keywords": ["kw1", "kw2"]
    }}
  ]
}}"""

        try:
            request = LlmRequest(
                system_prompt="You are an expert security and architectural analyzer. Help identify when developers bypass project-specific abstractions.",
                user_message=prompt,
                max_tokens=1000,
                temperature=0.0
            )
            
            response = await self.llm.send_async(request)
            data = self._parse_json(response.content)
            
            for item in data.get("abstractions", []):
                name = item.get("name")
                if name in self.abstractions:
                    # Merge LLM suggestions with existing patterns
                    new_patterns = item.get("bypass_patterns", [])
                    self.abstractions[name].bypass_patterns = list(set(self.abstractions[name].bypass_patterns + new_patterns))
                    
                    new_kws = item.get("keywords", [])
                    self.abstractions[name].responsibility_keywords = list(set(self.abstractions[name].responsibility_keywords + new_kws))
                    
            logger.info("bypass_rules_synthesized", count=len(data.get("abstractions", [])))
            
        except Exception as e:
            logger.error("bypass_rule_synthesis_failed", error=str(e))

    def _parse_json(self, content: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM response content."""
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(content[start:end])
        except Exception:
            pass
        return {}

    def _enrich_abstractions(self) -> None:
        """Enrich detected abstractions with additional context."""
        for abstraction in self.abstractions.values():
            # Generate responsibilities from methods and description
            responsibilities = []
            
            if abstraction.category == ServiceCategory.SECRET_MANAGEMENT:
                responsibilities.append("Manages secret and credential access")
                responsibilities.append("Provides environment-aware secret loading")
            elif abstraction.category == ServiceCategory.CONFIG_MANAGEMENT:
                responsibilities.append("Manages application configuration")
            elif abstraction.category == ServiceCategory.DATABASE_ACCESS:
                responsibilities.append("Manages database connections and queries")
            
            # Add method-based responsibilities
            for method in abstraction.public_methods[:5]:
                if not method.startswith("_"):
                    responsibilities.append(f"Provides {method.replace('_', ' ')} functionality")
            
            abstraction.responsibilities = responsibilities[:5]  # Limit to 5

    def _detect_category_from_name(self, class_name: str) -> Tuple[ServiceCategory, float]:
        """Detect service category from class name."""
        name_lower = class_name.lower()
        
        for category, patterns in SERVICE_PATTERNS.items():
            for pattern in patterns["class_patterns"]:
                if pattern.lower() in name_lower or name_lower in pattern.lower():
                    return category, 0.8
        
        # Generic service detection
        if any(suffix in class_name for suffix in ["Service", "Manager", "Provider"]):
            return ServiceCategory.CUSTOM, 0.5
        
        return ServiceCategory.CUSTOM, 0.3


# Convenience function for standalone usage
async def detect_service_abstractions(project_root: Path, project_context: Optional[ProjectContext] = None) -> Dict[str, ServiceAbstraction]:
    """
    Detect service abstractions in a project.
    
    Args:
        project_root: Root directory of the project
        project_context: Optional project context
        
    Returns:
        Dictionary mapping class name to ServiceAbstraction
    """
    detector = ServiceAbstractionDetector(project_root, project_context)
    return await detector.detect_async()

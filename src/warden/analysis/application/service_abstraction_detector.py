"""
Service Abstraction Detector.

Detects project-specific service abstractions (like SecretManager, ConfigLoader)
and their responsibilities for context-aware consistency enforcement.
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import structlog

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
    1. Scans all Python files for class definitions
    2. Matches against known service patterns
    3. Extracts responsibilities from docstrings and method names
    4. Identifies bypass patterns that should be avoided when these services exist
    
    Example:
        detector = ServiceAbstractionDetector(project_root)
        abstractions = await detector.detect_async()
        
        for name, abstraction in abstractions.items():
            print(f"{name}: {abstraction.category.value}")
            print(f"  Bypass patterns: {abstraction.bypass_patterns}")
    """
    
    def __init__(self, project_root: Path) -> None:
        """
        Initialize detector.
        
        Args:
            project_root: Root directory of the project
        """
        self.project_root = Path(project_root)
        self.abstractions: Dict[str, ServiceAbstraction] = {}
    
    async def detect_async(self) -> Dict[str, ServiceAbstraction]:
        """
        Detect service abstractions in the project.
        
        Returns:
            Dictionary mapping class name to ServiceAbstraction
        """
        logger.info("service_abstraction_detection_started", project=str(self.project_root))
        
        # Find all Python files (excluding vendor/test directories)
        python_files = self._find_python_files()
        
        for file_path in python_files:
            try:
                self._analyze_file(file_path)
            except Exception as e:
                logger.debug("file_analysis_failed", file=str(file_path), error=str(e))
        
        # Post-process: enrich with additional context
        self._enrich_abstractions()
        
        logger.info(
            "service_abstraction_detection_completed",
            detected_count=len(self.abstractions),
            categories=[a.category.value for a in self.abstractions.values()],
        )
        
        return self.abstractions
    
    def _find_python_files(self) -> List[Path]:
        """Find all Python files in the project, excluding vendor/test dirs."""
        excluded_patterns = [
            "node_modules", "venv", ".venv", "env", "__pycache__",
            "dist", "build", ".git", ".tox", ".mypy_cache",
        ]
        
        python_files = []
        for py_file in self.project_root.rglob("*.py"):
            # Skip excluded directories
            if any(excl in str(py_file) for excl in excluded_patterns):
                continue
            # Skip test files for now (focus on source code)
            if "test" in py_file.name.lower() and py_file.name.startswith("test_"):
                continue
            python_files.append(py_file)
        
        return python_files
    
    def _analyze_file(self, file_path: Path) -> None:
        """Analyze a Python file for service abstractions."""
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                abstraction = self._analyze_class(node, file_path, content)
                if abstraction and abstraction.confidence > 0.3:
                    self.abstractions[abstraction.name] = abstraction
    
    def _analyze_class(
        self, 
        node: ast.ClassDef, 
        file_path: Path,
        file_content: str
    ) -> Optional[ServiceAbstraction]:
        """Analyze a class definition for service abstraction characteristics."""
        class_name = node.name
        
        # Skip private/internal classes
        if class_name.startswith("_"):
            return None
        
        # Detect category based on class name
        category, category_confidence = self._detect_category_from_name(class_name)
        if category == ServiceCategory.CUSTOM and category_confidence < 0.5:
            # Also check if it looks like a service (ends with Service, Manager, Provider, etc.)
            service_suffixes = ["Service", "Manager", "Provider", "Client", "Handler", "Factory", "Repository"]
            if not any(class_name.endswith(suffix) for suffix in service_suffixes):
                return None
        
        # Extract method names
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        public_methods = [m for m in methods if not m.startswith("_")]
        
        # Extract docstring
        docstring = ast.get_docstring(node) or ""
        
        # Create abstraction
        abstraction = ServiceAbstraction(
            name=class_name,
            file_path=str(file_path.relative_to(self.project_root)),
            category=category,
            public_methods=public_methods,
            description=docstring[:200] if docstring else "",
            confidence=category_confidence,
        )
        
        # Set bypass patterns and keywords from known patterns
        if category in SERVICE_PATTERNS:
            patterns = SERVICE_PATTERNS[category]
            abstraction.bypass_patterns = patterns["bypass_patterns"]
            abstraction.responsibility_keywords = patterns["keywords"]
        
        # Boost confidence if methods match expected patterns
        if category in SERVICE_PATTERNS:
            method_patterns = SERVICE_PATTERNS[category]["method_patterns"]
            matching_methods = sum(1 for m in public_methods if any(p in m for p in method_patterns))
            if matching_methods > 0:
                abstraction.confidence = min(1.0, abstraction.confidence + 0.2)
        
        return abstraction
    
    def _detect_category_from_name(self, class_name: str) -> tuple[ServiceCategory, float]:
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


# Convenience function for standalone usage
async def detect_service_abstractions(project_root: Path) -> Dict[str, ServiceAbstraction]:
    """
    Detect service abstractions in a project.
    
    Args:
        project_root: Root directory of the project
        
    Returns:
        Dictionary mapping class name to ServiceAbstraction
    """
    detector = ServiceAbstractionDetector(project_root)
    return await detector.detect_async()

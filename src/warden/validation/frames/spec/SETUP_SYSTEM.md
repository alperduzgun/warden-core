# SpecFrame Setup System

Comprehensive documentation for the SpecFrame automatic setup and configuration system.

## Overview

The SpecFrame Setup System provides automatic detection, validation, and configuration of platforms for API contract analysis. It eliminates manual configuration by scanning the filesystem and intelligently detecting project types.

## Architecture

The system consists of three core modules:

```
┌─────────────────────┐
│ Platform Detector   │ ← Scans filesystem, detects projects
└──────────┬──────────┘
           │
           v
┌─────────────────────┐
│ Config Validator    │ ← Validates configurations
└──────────┬──────────┘
           │
           v
┌─────────────────────┐
│ Setup Wizard        │ ← Orchestrates discovery → validation → generation → save
└─────────────────────┘
```

## Module 1: Platform Detector

**File:** `platform_detector.py`

### Purpose

Automatically scans directory trees to detect projects and suggest platform types based on signature files and content patterns.

### Key Classes

#### `DetectedProject`

A dataclass representing a detected project:

```python
@dataclass
class DetectedProject:
    name: str                    # Project name (from directory)
    path: str                    # Absolute path to project root
    platform_type: PlatformType  # Suggested platform (flutter, spring, etc.)
    confidence: float            # Confidence score (0.0-1.0)
    role: PlatformRole          # Suggested role (consumer/provider/both)
    evidence: List[str]         # Files/patterns that led to detection
    metadata: Dict[str, str]    # Additional metadata (versions, etc.)
```

#### `PlatformDetector`

Main detector class:

```python
class PlatformDetector:
    def __init__(
        self,
        max_depth: int = 3,
        min_confidence: float = 0.5,
        exclude_dirs: Optional[Set[str]] = None,
    ):
        """
        Args:
            max_depth: Maximum directory depth to search
            min_confidence: Minimum confidence threshold (0.0-1.0)
            exclude_dirs: Directories to skip (node_modules, .git, etc.)
        """

    async def detect_projects_async(
        self,
        search_path: str | Path,
    ) -> List[DetectedProject]:
        """
        Detect projects in directory tree.

        Returns:
            List of detected projects sorted by confidence
        """
```

### Supported Platforms

The detector recognizes 15+ platform types:

**Mobile/Frontend:**
- Flutter (pubspec.yaml with flutter dependency)
- React (package.json with react)
- React Native (package.json with react-native)
- Angular (package.json with @angular/core)
- Vue (package.json with vue)
- Swift (Swift Package Manager)
- Kotlin (build.gradle.kts)

**Backend:**
- Spring Boot (pom.xml or build.gradle with spring-boot)
- FastAPI (requirements.txt with fastapi)
- Django (requirements.txt with Django, manage.py)
- NestJS (package.json with @nestjs/core)
- Express (package.json with express)
- ASP.NET Core (.csproj with Microsoft.AspNetCore)
- Go (go.mod)
- Gin (go.mod with gin-gonic)
- Echo (go.mod with labstack/echo)

### Detection Algorithm

1. **File Signature Matching**
   - Checks for required files (pubspec.yaml, package.json, pom.xml, etc.)
   - Scores based on file presence (weighted)

2. **Content Pattern Matching**
   - Reads file contents (size-limited for safety)
   - Searches for platform-specific patterns (e.g., "flutter:" in pubspec.yaml)
   - Scores based on pattern matches

3. **Exclusion Pattern Checking**
   - Reduces confidence if exclusion patterns found
   - Example: React Native detection excludes if "expo" found in package.json

4. **Confidence Calculation**
   - Weighted average: 40% file presence + 60% pattern matches
   - Applies platform-specific weight multiplier
   - Applies exclusion penalty if applicable

5. **Role Suggestion**
   - Mobile/Frontend → consumer
   - Backend frameworks → provider
   - BFF patterns (Next.js with /api, Nuxt with /server) → both

### Usage Example

```python
from warden.validation.frames.spec.platform_detector import PlatformDetector

detector = PlatformDetector(
    max_depth=3,
    min_confidence=0.7,
)

projects = await detector.detect_projects_async("../")

for project in projects:
    print(f"Found {project.platform_type.value} at {project.path}")
    print(f"  Role: {project.role.value}")
    print(f"  Confidence: {project.confidence:.0%}")
    print(f"  Evidence: {', '.join(project.evidence)}")
```

## Module 2: Config Validator

**File:** `validation.py`

### Purpose

Validates platform configurations with comprehensive checks and provides actionable error messages with suggestions.

### Key Classes

#### `ValidationIssue`

Represents a single validation issue:

```python
@dataclass
class ValidationIssue:
    severity: IssueSeverity     # error/warning/info
    message: str                # Human-readable description
    field: str                  # Configuration field that caused issue
    suggestion: Optional[str]   # Suggested fix or action
    platform_name: Optional[str] # Platform name (if platform-specific)
```

#### `ValidationResult`

Result of validation:

```python
@dataclass
class ValidationResult:
    is_valid: bool
    issues: List[ValidationIssue]
    metadata: dict

    @property
    def has_errors(self) -> bool: ...
    @property
    def has_warnings(self) -> bool: ...
    @property
    def error_count(self) -> int: ...
    @property
    def warning_count(self) -> int: ...
```

#### `SpecConfigValidator`

Main validator class:

```python
class SpecConfigValidator:
    def __init__(self, project_root: Optional[Path] = None):
        """
        Args:
            project_root: Project root (for resolving relative paths)
        """

    def validate_platforms(
        self,
        platforms: List[dict],
    ) -> ValidationResult:
        """
        Validate platform configurations.

        Returns:
            ValidationResult with issues and metadata
        """
```

### Validation Checks

1. **Minimum Platforms**
   - At least 2 platforms required
   - Error if fewer than 2

2. **Required Fields**
   - name: Platform identifier
   - path: Path to project root
   - type: Platform type (must be valid PlatformType enum)
   - role: Platform role (must be valid PlatformRole enum)
   - Error for each missing field

3. **Path Validation**
   - Path must exist
   - Path must be a directory (not a file)
   - Path must be readable
   - Resolves relative paths relative to project root

4. **Platform Type Validation**
   - Must be valid PlatformType enum value
   - Lists valid options in error message

5. **Role Validation**
   - Must be valid PlatformRole enum value
   - Lists valid options in error message

6. **Consumer/Provider Pairing**
   - At least one consumer required
   - At least one provider required
   - Error if either missing

7. **Duplicate Detection**
   - Error for duplicate platform names
   - Warning for duplicate paths (may be intentional for multiple extractors)

8. **Project Size Warning**
   - Warning if project has >10,000 files
   - Suggests excluding build/vendor directories

### Usage Example

```python
from warden.validation.frames.spec.validation import SpecConfigValidator

validator = SpecConfigValidator()

platforms = [
    {
        "name": "mobile",
        "path": "../invoice-mobile",
        "type": "flutter",
        "role": "consumer",
    },
    {
        "name": "backend",
        "path": "../invoice-api",
        "type": "spring-boot",
        "role": "provider",
    },
]

result = validator.validate_platforms(platforms)

if not result.is_valid:
    print(f"Validation failed with {result.error_count} errors:")
    for issue in result.issues:
        print(f"  [{issue.severity.value}] {issue.message}")
        if issue.suggestion:
            print(f"    Suggestion: {issue.suggestion}")
```

## Module 3: Setup Wizard

**File:** `setup_wizard.py`

### Purpose

Orchestrates the complete setup process: discovery → validation → configuration generation → persistence.

### Key Classes

#### `SetupWizardConfig`

Configuration for the wizard:

```python
@dataclass
class SetupWizardConfig:
    search_path: str = ".."
    max_depth: int = 3
    min_confidence: float = 0.7
    exclude_dirs: Optional[Set[str]] = None
    auto_suggest_roles: bool = True
```

#### `PlatformSetupInput`

Manual platform configuration input:

```python
@dataclass
class PlatformSetupInput:
    name: str
    path: str
    platform_type: str
    role: str
    description: Optional[str] = None
```

#### `SetupWizard`

Main wizard class:

```python
class SetupWizard:
    def __init__(
        self,
        config: Optional[SetupWizardConfig] = None,
        project_root: Optional[Path] = None,
    ):
        """Initialize setup wizard."""

    async def discover_projects_async(
        self,
        search_path: Optional[str] = None,
    ) -> List[DetectedProject]:
        """Discover projects automatically."""

    def validate_setup(
        self,
        projects: List[DetectedProject] | List[PlatformSetupInput],
    ) -> ValidationResult:
        """Validate detected or manual configurations."""

    def generate_config(
        self,
        projects: List[DetectedProject] | List[PlatformSetupInput],
        include_metadata: bool = True,
    ) -> Dict:
        """Generate YAML configuration."""

    def save_config(
        self,
        config: Dict,
        merge: bool = True,
        backup: bool = True,
    ) -> Path:
        """Save configuration to .warden/config.yaml."""

    def create_interactive_summary(
        self,
        projects: List[DetectedProject],
        validation: Optional[ValidationResult] = None,
    ) -> str:
        """Create human-readable summary for CLI output."""
```

### Wizard Workflow

```
1. DISCOVERY
   ├─ Scan filesystem using PlatformDetector
   ├─ Detect projects based on signatures
   ├─ Deduplicate (keep highest confidence)
   └─ Return List[DetectedProject]

2. VALIDATION
   ├─ Convert projects to platform configs
   ├─ Validate using SpecConfigValidator
   └─ Return ValidationResult

3. GENERATION
   ├─ Convert projects to YAML structure
   ├─ Add default settings (gap_analysis, resilience)
   ├─ Optionally include metadata (confidence, evidence)
   └─ Return configuration dict

4. PERSISTENCE
   ├─ Create .warden directory if needed
   ├─ Backup existing config if requested
   ├─ Merge with existing config if requested
   ├─ Write YAML to .warden/config.yaml
   └─ Return Path to saved config
```

### Generated Configuration Format

```yaml
frames:
  spec:
    platforms:
      - name: mobile
        path: ../invoice-mobile
        type: flutter
        role: consumer
        _metadata:  # Optional
          confidence: 0.95
          evidence:
            - pubspec.yaml
          version: "1.0.0"

      - name: backend
        path: ../invoice-api
        type: spring-boot
        role: provider
        _metadata:
          confidence: 0.90
          evidence:
            - pom.xml

    gap_analysis:
      fuzzy_threshold: 0.8
      enable_fuzzy: true

    resilience:
      extraction_timeout: 300
      gap_analysis_timeout: 120
```

### Usage Example

```python
from warden.validation.frames.spec.setup_wizard import SetupWizard, SetupWizardConfig

# Configure wizard
config = SetupWizardConfig(
    search_path="../",
    max_depth=3,
    min_confidence=0.7,
)

wizard = SetupWizard(config=config)

# Complete workflow
projects = await wizard.discover_projects_async()
print(f"Discovered {len(projects)} projects")

validation = wizard.validate_setup(projects)
if not validation.is_valid:
    print(f"Validation failed: {validation.error_count} errors")
    return

config_dict = wizard.generate_config(projects, include_metadata=True)
config_path = wizard.save_config(config_dict, merge=True, backup=True)

print(f"Configuration saved to {config_path}")
```

## Integration Points

### CLI Integration (Future)

The modules are designed for CLI integration:

```bash
# Auto-setup
warden spec setup --auto

# Manual setup
warden spec setup --manual

# Validate existing config
warden spec validate

# Show detected projects
warden spec detect --path ../
```

### MCP Integration (Future)

The modules support MCP tool integration:

```json
{
  "tool": "spec_setup_detect",
  "parameters": {
    "search_path": "../",
    "max_depth": 3
  }
}
```

## Error Handling

### Platform Detector

- Gracefully handles permission errors (logs warning, continues)
- Handles large files (10MB size limit for pattern matching)
- Handles malformed files (JSON decode errors, etc.)
- Validates search paths (raises ValueError for nonexistent paths)

### Config Validator

- Returns ValidationResult (never raises exceptions)
- Provides actionable suggestions for every error
- Distinguishes between errors (blocking) and warnings (non-blocking)

### Setup Wizard

- Handles YAML parsing errors (overwrites invalid configs)
- Creates directories as needed (.warden)
- Deduplicates detected projects (prefers higher confidence)
- Merges with existing configs (preserves other frames)

## Testing

Comprehensive test suites are provided:

- `tests/validation/frames/spec/test_platform_detector.py` (20+ tests)
- `tests/validation/frames/spec/test_validation.py` (25+ tests)
- `tests/validation/frames/spec/test_setup_wizard.py` (20+ tests)

### Running Tests

```bash
# Run all spec setup tests
pytest tests/validation/frames/spec/

# Run specific module tests
pytest tests/validation/frames/spec/test_platform_detector.py -v
pytest tests/validation/frames/spec/test_validation.py -v
pytest tests/validation/frames/spec/test_setup_wizard.py -v

# Run integration test
python3 test_spec_setup_modules.py
```

## Performance Characteristics

### Platform Detector

- **Time Complexity:** O(n × m) where n = directories, m = signature checks
- **Space Complexity:** O(p) where p = detected projects
- **Optimizations:**
  - Respects max_depth to limit recursion
  - Excludes common directories (node_modules, .git)
  - Size-limited file reads (10MB max)
  - Async I/O for parallel scanning

### Config Validator

- **Time Complexity:** O(p × c) where p = platforms, c = checks per platform
- **Space Complexity:** O(i) where i = validation issues
- **Optimizations:**
  - Early exit on missing required fields
  - File existence checks before reading
  - Path resolution caching

### Setup Wizard

- **Time Complexity:** O(d + v + g) where d = detection, v = validation, g = generation
- **Space Complexity:** O(p) where p = projects
- **Optimizations:**
  - Deduplication reduces redundant processing
  - YAML generation is linear in platform count
  - Deep merge is optimized for typical config sizes

## Logging

All modules use structured logging via `structlog`:

```python
logger.info(
    "platform_detection_started",
    search_path=str(search_path),
    max_depth=self.max_depth,
)

logger.debug(
    "project_detected",
    path=str(directory),
    platform=detection.platform_type.value,
    confidence=detection.confidence,
)
```

Log levels:
- `debug`: Detailed detection/validation steps
- `info`: High-level operations (started, completed)
- `warning`: Non-fatal issues (permission errors, large projects)
- `error`: Fatal issues (should not occur in normal operation)

## Future Enhancements

### Planned Features

1. **Machine Learning Confidence**
   - Train on known projects to improve confidence scoring
   - Learn organization-specific patterns

2. **Custom Signatures**
   - User-defined platform signatures
   - Organization-specific frameworks

3. **Interactive CLI Wizard**
   - Step-by-step guided setup
   - Confirmation prompts for detected projects
   - Role override options

4. **Import from Existing Configs**
   - Import from swagger.yaml, openapi.json
   - Import from docker-compose.yml
   - Import from package manager lock files

5. **Performance Optimization**
   - Parallel directory scanning
   - Incremental detection (cache results)
   - Smart path prioritization

## Security Considerations

1. **Path Traversal Prevention**
   - All paths resolved and validated
   - Symlink handling (follows, but validates target)

2. **Resource Limits**
   - Max file size for pattern matching (10MB)
   - Max search depth (configurable)
   - Max projects to count (10,000 file limit warning)

3. **Input Validation**
   - Enum validation for platform types and roles
   - Path existence and readability checks
   - YAML parsing with safe_load

4. **Privacy**
   - Structured logging with PII redaction
   - No external network calls during detection
   - Local-only file access

## Troubleshooting

### Detection Issues

**Problem:** Projects not detected

**Solutions:**
- Lower `min_confidence` threshold
- Increase `max_depth`
- Check if directory is in `exclude_dirs`
- Verify signature files exist (pubspec.yaml, package.json, etc.)

### Validation Issues

**Problem:** Valid config marked as invalid

**Solutions:**
- Check error messages for specific issues
- Verify paths are relative to project root (where .warden is)
- Ensure platform type and role are valid enum values
- Check for duplicate names/paths

### Configuration Issues

**Problem:** Config merge overwrites important settings

**Solutions:**
- Use `merge=False` to replace entire config
- Manually edit `.warden/config.yaml`
- Restore from `.warden/config.yaml.backup`

## Contributing

When adding new platform support:

1. Add enum value to `PlatformType` in `models.py`
2. Add signature to `PLATFORM_SIGNATURES` in `platform_detector.py`
3. Add tests to `test_platform_detector.py`
4. Update this documentation

## References

- SpecFrame Documentation: `/docs/SPEC_FRAME.md`
- Frame System: `/docs/FRAME_SYSTEM.md`
- Platform Models: `src/warden/validation/frames/spec/models.py`

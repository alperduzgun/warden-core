import sys
from pathlib import Path

# Add src to path
sys.path.append("src")

from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher

project_root = Path("/Users/alper/Documents/Development/Personal/warden-core")
matcher = IgnoreMatcher(project_root)

test_file = project_root / "tests/ast_tests/__init__.py"
is_ignored = matcher.should_ignore_file(test_file)

print(f"File: {test_file}")
print(f"Is Ignored: {is_ignored}")

# Check patterns loaded
print(f"Path Patterns: {matcher._path_patterns}")

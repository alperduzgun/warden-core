
import pytest
from pathlib import Path
from warden.reports.generator import ReportGenerator

# Try to import hypothesis, behave gently if missing
try:
    from hypothesis import given, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

@pytest.fixture
def generator():
    return ReportGenerator()

@pytest.mark.skipif(not HAS_HYPOTHESIS, reason="Hypothesis not installed")
@given(
    # Fuzz widely varying path strings
    st.lists(
        st.one_of(
            st.text(min_size=1), 
            st.from_regex(r"^/[a-z0-9]+/[a-z0-9]+$", fullmatch=True)
        ), 
        min_size=1, max_size=10
    )
)
def test_sanitize_paths_fuzzing(generator, paths):
    """
    Property: Sanitization should NEVER crash, regardless of input complexity.
    It should return a structure where potentially sensitive root paths are obscured (if matched).
    """
    data = {"files": paths}
    # We use a fake root that is likely to be found in some regex generated paths if we force it,
    # or we just rely on resilience: it shouldn't raise Exception.
    
    try:
        generator._sanitize_paths(data, base_path=Path("/tmp/root"))
    except Exception as e:
        pytest.fail(f"Sanitization crashed on input {paths}: {e}")

def test_sanitize_paths_strict_relativization(generator):
    """
    Verify strict pathlib logic.
    """ # 
    root = Path("/Users/test/project")
    data = {
        "abs_path": "/Users/test/project/src/main.py",
        "outside_path": "/etc/passwd",
        "messy_string": "Error in /Users/test/project/src/utils.py line 10"
    }
    
    generator._sanitize_paths(data, base_path=root)
    
    # Strictly inside -> relative
    assert data["abs_path"] == "src/main.py"
    
    # Outside -> untouched (strict safety) or minimally sanitized?
    # Logic says: if root in string -> replace.
    # "/etc/passwd" does NOT contain "/Users/test/project", so validly untouched.
    assert data["outside_path"] == "/etc/passwd"
    
    # String containment -> text replacement
    # "src/utils.py" is relative, so it should replace the root part.
    assert "src/utils.py" in data["messy_string"]
    assert "/Users/test/project" not in data["messy_string"]

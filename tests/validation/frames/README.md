# Validation Frames Tests

Organized test suite for all validation frames.

## Directory Structure

```
tests/validation/frames/
├── README.md (this file)
├── __init__.py
│
├── chaos/
│   ├── __init__.py
│   └── test_chaos_frame.py          # Chaos Engineering Frame tests
│
├── security/
│   ├── __init__.py
│   └── test_security_frame.py       # Security Analysis Frame tests
│
├── orphan/
│   ├── __init__.py
│   ├── test_orphan_frame.py         # Orphan Frame orchestrator tests
│   ├── test_orphan_detector.py      # AST-based detector tests (TODO)
│   └── test_llm_orphan_filter.py    # LLM-powered filter tests ✅
│
├── gitchanges/
│   ├── __init__.py
│   └── test_gitchanges_frame.py     # Git Changes Frame tests
│
└── content_rules/
    ├── __init__.py
    └── test_content_rules.py        # Content Rules tests
```

## Running Tests

### Run all frame tests:
```bash
pytest tests/validation/frames/ -v
```

### Run specific frame tests:
```bash
# Orphan frame tests
pytest tests/validation/frames/orphan/ -v

# Security frame tests
pytest tests/validation/frames/security/ -v

# Chaos frame tests
pytest tests/validation/frames/chaos/ -v
```

### Run with coverage:
```bash
pytest tests/validation/frames/ --cov=src/warden/validation/frames --cov-report=html
```

## Test Organization

Each frame has its own directory with:
- `__init__.py` - Package marker
- `test_<frame_name>.py` - Main frame tests
- Additional test files for complex frames (e.g., orphan)

### Orphan Frame (Most Complex)

The orphan frame has multiple components:

1. **`test_orphan_frame.py`** - OrphanFrame orchestrator tests
   - Tests integration between AST detector and LLM filter
   - Config handling (use_llm_filter option)
   - Report generation

2. **`test_llm_orphan_filter.py`** - LLM filter tests ✅ NEW!
   - Intelligent false positive filtering
   - Language-agnostic support
   - Error handling and fallbacks
   - Batch processing
   - JSON parsing

3. **`test_orphan_detector.py`** - AST detector tests (TODO)
   - Basic AST analysis
   - Unused imports detection
   - Unreferenced functions/classes
   - Dead code detection

## Adding New Frame Tests

To add tests for a new frame:

1. Create directory:
   ```bash
   mkdir tests/validation/frames/<frame_name>
   ```

2. Create `__init__.py`:
   ```python
   """<Frame Name> Tests"""
   ```

3. Create test file:
   ```python
   # tests/validation/frames/<frame_name>/test_<frame_name>.py
   import pytest

   class Test<FrameName>:
       def test_basic_functionality(self):
           # Your tests here
           pass
   ```

4. Run tests:
   ```bash
   pytest tests/validation/frames/<frame_name>/ -v
   ```

## Test Standards

All frame tests should include:

- ✅ Basic functionality tests
- ✅ Edge case handling
- ✅ Error handling
- ✅ Configuration options
- ✅ Integration with ValidationFrame base class
- ✅ Panel JSON compatibility (where applicable)

## Continuous Integration

Tests run automatically on:
- Pull requests
- Commits to `dev` branch
- Scheduled nightly runs

## Notes

- Tests are organized by frame for clarity
- Each frame can have multiple test files if complex
- Use fixtures in `conftest.py` for shared test data
- Mock external dependencies (LLM, API calls, etc.)

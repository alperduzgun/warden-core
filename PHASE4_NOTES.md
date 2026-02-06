# Phase 4 Cleanup Items

## ID 18: Delete dead code
- Remove retry_check.py (unused)

## ID 32: Dockerfile optimization
- Verify multi-stage build efficient
- Ensure builder stage not in runtime

## ID 34: Rust safety
- Replace .unwrap() with proper Result handling in warden_rust/src/lib.rs

## ID 41: PDF Generation error handling
- Check weasyprint available
- Raise error if missing

## ID 82: Add docstrings
- Document public methods with parsing-friendly docstrings

## ID 11: Pin dependencies
- Update pyproject.toml to use == instead of ^

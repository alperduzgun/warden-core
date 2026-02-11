"""
Security Frame (Backward Compatibility Wrapper)

This module re-exports SecurityFrame from the refactored structure
to maintain backward compatibility with existing imports.

New structure:
- frame.py: Main SecurityFrame class
- ast_analyzer.py: Tree-sitter AST analysis for structural vulnerability detection
- data_flow_analyzer.py: LSP-based data flow analysis for taint tracking
- batch_processor.py: Batch LLM processing for findings verification

Public API (unchanged):
    from warden.validation.frames.security.security_frame import SecurityFrame

    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
"""

# Re-export SecurityFrame from the refactored module
from .frame import SecurityFrame

__all__ = ["SecurityFrame"]

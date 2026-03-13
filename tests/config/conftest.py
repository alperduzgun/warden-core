"""
Config test suite conftest.

The source modules warden.config.yaml_validator and warden.config.yaml_parser
import `get_frame_by_id` from warden.validation.domain.frame, but that
function is not yet exported from the domain module (it lives on the
FrameRegistry infrastructure class).

This conftest injects a stub into the module *before* any test in this
package imports the source under test, preventing ImportError at collection
time.  Individual tests that care about the return value of get_frame_by_id
must patch it themselves using:

    with patch("warden.config.yaml_validator.get_frame_by_id", ...):
        ...
"""

import sys
import types
from unittest.mock import MagicMock

# Only inject if the real module does not already export the symbol.
_frame_module_name = "warden.validation.domain.frame"
if _frame_module_name in sys.modules:
    _frame_mod = sys.modules[_frame_module_name]
else:
    # Import the real module first so all its classes are available.
    import importlib
    _frame_mod = importlib.import_module(_frame_module_name)

if not hasattr(_frame_mod, "get_frame_by_id"):
    # Stub returns None by default (unknown frame ID).  Tests that need a
    # valid frame object must patch the symbol on the consuming module.
    _frame_mod.get_frame_by_id = MagicMock(return_value=None)

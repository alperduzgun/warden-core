"""Auto-derive schema version from dataclass or Pydantic model field signatures.

Used by cache modules (findings_cache, triage_cache) to detect when the
cached model's field layout has changed and automatically invalidate stale
entries -- removing the need for developers to bump a manual constant.

The derived version is an 8-character hex digest of the model's field names
and type annotations, so any addition, removal, or type change produces a
different version string.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any


def derive_schema_version(cls: type) -> str:
    """Return a short hex digest that changes when *cls*'s field signature changes.

    Supports both standard ``@dataclass`` classes (via ``dataclasses.fields``)
    and Pydantic ``BaseModel`` subclasses (via ``model_fields``).

    The digest is based on ``(field_name, annotation_repr)`` pairs sorted by
    name to ensure deterministic output regardless of declaration order.
    """
    fields: list[tuple[str, str]] = _extract_fields(cls)
    # Sort by name for determinism (declaration order may vary across versions)
    fields.sort()
    raw = str(fields).encode()
    return hashlib.md5(raw).hexdigest()[:8]


def _extract_fields(cls: type) -> list[tuple[str, str]]:
    """Extract ``(name, type_repr)`` pairs from a dataclass or Pydantic model."""
    # 1. Try standard dataclass
    if dataclasses.is_dataclass(cls):
        return [(f.name, str(f.type)) for f in dataclasses.fields(cls)]  # type: ignore[arg-type]

    # 2. Try Pydantic BaseModel (v2 API)
    model_fields: dict[str, Any] | None = getattr(cls, "model_fields", None)
    if model_fields is not None:
        return [(name, str(info.annotation)) for name, info in model_fields.items()]

    msg = f"{cls.__name__} is neither a dataclass nor a Pydantic BaseModel"
    raise TypeError(msg)

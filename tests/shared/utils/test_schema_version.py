"""Tests for derive_schema_version utility."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, Field

from warden.shared.utils.schema_version import derive_schema_version


# ---------------------------------------------------------------------------
# Fixtures: simple dataclass and Pydantic model families
# ---------------------------------------------------------------------------


@dataclass
class _SampleDC:
    name: str
    value: int
    flag: bool = False


@dataclass
class _SampleDCExtra:
    """Same as _SampleDC but with an extra field."""

    name: str
    value: int
    flag: bool = False
    extra: str = ""


@dataclass
class _SampleDCRetyped:
    """Same field names as _SampleDC but 'value' changed from int to str."""

    name: str
    value: str
    flag: bool = False


class _SamplePydantic(BaseModel):
    name: str
    score: float = Field(default=0.0)


class _SamplePydanticExtra(BaseModel):
    name: str
    score: float = Field(default=0.0)
    tag: str = ""


class _SamplePydanticRetyped(BaseModel):
    name: str
    score: int = Field(default=0)


# ===========================================================================
# Tests
# ===========================================================================


class TestDeriveSchemaVersion:
    """derive_schema_version produces stable, distinct digests."""

    def test_deterministic_for_dataclass(self) -> None:
        v1 = derive_schema_version(_SampleDC)
        v2 = derive_schema_version(_SampleDC)
        assert v1 == v2

    def test_deterministic_for_pydantic(self) -> None:
        v1 = derive_schema_version(_SamplePydantic)
        v2 = derive_schema_version(_SamplePydantic)
        assert v1 == v2

    def test_returns_8_char_hex(self) -> None:
        v = derive_schema_version(_SampleDC)
        assert isinstance(v, str)
        assert len(v) == 8
        int(v, 16)  # must be valid hex

    def test_adding_field_changes_version_dataclass(self) -> None:
        v_base = derive_schema_version(_SampleDC)
        v_extra = derive_schema_version(_SampleDCExtra)
        assert v_base != v_extra

    def test_changing_type_changes_version_dataclass(self) -> None:
        v_base = derive_schema_version(_SampleDC)
        v_retyped = derive_schema_version(_SampleDCRetyped)
        assert v_base != v_retyped

    def test_adding_field_changes_version_pydantic(self) -> None:
        v_base = derive_schema_version(_SamplePydantic)
        v_extra = derive_schema_version(_SamplePydanticExtra)
        assert v_base != v_extra

    def test_changing_type_changes_version_pydantic(self) -> None:
        v_base = derive_schema_version(_SamplePydantic)
        v_retyped = derive_schema_version(_SamplePydanticRetyped)
        assert v_base != v_retyped

    def test_raises_for_plain_class(self) -> None:
        class _PlainClass:
            x: int = 0

        with pytest.raises(TypeError, match="neither a dataclass nor a Pydantic BaseModel"):
            derive_schema_version(_PlainClass)

    def test_works_with_real_finding(self) -> None:
        """Sanity check: derives a version from the actual Finding dataclass."""
        from warden.validation.domain.frame import Finding

        v = derive_schema_version(Finding)
        assert isinstance(v, str)
        assert len(v) == 8

    def test_works_with_real_triage_decision(self) -> None:
        """Sanity check: derives a version from the actual TriageDecision model."""
        from warden.analysis.domain.triage_models import TriageDecision

        v = derive_schema_version(TriageDecision)
        assert isinstance(v, str)
        assert len(v) == 8

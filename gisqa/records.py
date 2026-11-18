"""Data shapes shared by the adapters, rules and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Union

Oid = Union[int, str]
Bounds = Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class GeometryInfo:
    """What the rules need to know about a geometry, computed by an adapter.

    Measurements are in meters / square meters regardless of the source
    coordinate system; bounds are in WGS84 degrees. ``None`` means "not
    applicable or unknown" (e.g. area of a point).
    """

    is_null: bool = False
    is_empty: bool = False
    validity_error: Optional[str] = None
    area_m2: Optional[float] = None
    length_m: Optional[float] = None
    bounds_wgs84: Optional[Bounds] = None
    fingerprint: Optional[str] = None

    @classmethod
    def null(cls) -> "GeometryInfo":
        return cls(is_null=True)


@dataclass(frozen=True)
class Record:
    oid: Oid
    attributes: Dict[str, Any] = field(default_factory=dict)
    geometry: GeometryInfo = field(default_factory=GeometryInfo)


@dataclass(frozen=True)
class Issue:
    rule: str
    severity: Severity
    oid: Oid
    message: str
    field: str = ""
    value: Any = None

    def as_row(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "oid": self.oid,
            "field": self.field,
            "value": "" if self.value is None else str(self.value),
            "message": self.message,
        }

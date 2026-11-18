"""Individual checks. Each rule sees one record at a time; rules that compare
records (duplicates) keep state and report as they go."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from .config import QAConfig
from .records import Issue, Record, Severity


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _get(record: Record, field: str) -> Any:
    """Case-insensitive attribute lookup (ArcGIS and OGR differ on case)."""
    if field in record.attributes:
        return record.attributes[field]
    lower = field.lower()
    for key, value in record.attributes.items():
        if key.lower() == lower:
            return value
    return None


class Rule:
    name = "rule"

    def check(self, record: Record) -> List[Issue]:
        raise NotImplementedError


class GeometryRule(Rule):
    """Null, empty and invalid geometry. Later geometry rules skip bad shapes."""

    name = "geometry"

    def __init__(self, check_validity: bool) -> None:
        self.check_validity = check_validity

    def check(self, record: Record) -> List[Issue]:
        geometry = record.geometry
        if geometry.is_null:
            return [Issue("null_geometry", Severity.ERROR, record.oid, "Feature has no geometry")]
        if geometry.is_empty:
            return [Issue("empty_geometry", Severity.ERROR, record.oid, "Geometry is empty")]
        if self.check_validity and geometry.validity_error:
            return [
                Issue("invalid_geometry", Severity.ERROR, record.oid, f"Invalid geometry: {geometry.validity_error}")
            ]
        return []


class SizeRule(Rule):
    name = "size"

    def __init__(self, min_area_m2: Optional[float], min_length_m: Optional[float]) -> None:
        self.min_area_m2 = min_area_m2
        self.min_length_m = min_length_m

    def check(self, record: Record) -> List[Issue]:
        geometry = record.geometry
        issues = []
        if self.min_area_m2 is not None and geometry.area_m2 is not None and geometry.area_m2 < self.min_area_m2:
            issues.append(
                Issue(
                    "sliver_polygon",
                    Severity.WARNING,
                    record.oid,
                    f"Area {geometry.area_m2:,.1f} m² is below {self.min_area_m2:,.1f} m²",
                    value=round(geometry.area_m2, 2),
                )
            )
        if self.min_length_m is not None and geometry.length_m is not None and geometry.length_m < self.min_length_m:
            issues.append(
                Issue(
                    "short_line",
                    Severity.WARNING,
                    record.oid,
                    f"Length {geometry.length_m:,.1f} m is below {self.min_length_m:,.1f} m",
                    value=round(geometry.length_m, 2),
                )
            )
        return issues


class ExtentRule(Rule):
    name = "extent"

    def __init__(self, extent) -> None:
        self.xmin, self.ymin, self.xmax, self.ymax = extent

    def check(self, record: Record) -> List[Issue]:
        bounds = record.geometry.bounds_wgs84
        if bounds is None:
            return []
        xmin, ymin, xmax, ymax = bounds
        if xmin < self.xmin or ymin < self.ymin or xmax > self.xmax or ymax > self.ymax:
            hint = " (latitude/longitude swapped?)" if _looks_swapped(bounds, self) else ""
            return [
                Issue(
                    "outside_extent",
                    Severity.ERROR,
                    record.oid,
                    f"Feature is outside the expected area{hint}",
                    value=f"{xmin:.5f},{ymin:.5f},{xmax:.5f},{ymax:.5f}",
                )
            ]
        return []


def _looks_swapped(bounds, extent: ExtentRule) -> bool:
    xmin, ymin, xmax, ymax = bounds
    return extent.xmin <= ymin <= extent.xmax and extent.ymin <= xmin <= extent.ymax


class DuplicateGeometryRule(Rule):
    name = "duplicate_geometry"

    def __init__(self) -> None:
        self.seen: Dict[str, Any] = {}

    def check(self, record: Record) -> List[Issue]:
        fingerprint = record.geometry.fingerprint
        if not fingerprint:
            return []
        first = self.seen.setdefault(fingerprint, record.oid)
        if first != record.oid:
            return [
                Issue(
                    "duplicate_geometry", Severity.WARNING, record.oid, f"Same geometry as feature {first}", value=first
                )
            ]
        return []


class UniqueKeyRule(Rule):
    name = "duplicate_key"

    def __init__(self, field: str) -> None:
        self.field = field
        self.seen: Dict[Any, Any] = {}

    def check(self, record: Record) -> List[Issue]:
        value = _get(record, self.field)
        if is_blank(value):
            return []  # reported by RequiredFieldsRule if required
        key = value.strip().upper() if isinstance(value, str) else value
        first = self.seen.setdefault(key, record.oid)
        if first != record.oid:
            return [
                Issue(
                    "duplicate_key",
                    Severity.ERROR,
                    record.oid,
                    f"{self.field} duplicates feature {first}",
                    field=self.field,
                    value=value,
                )
            ]
        return []


class RequiredFieldsRule(Rule):
    name = "required_field"

    def __init__(self, fields: Iterable[str]) -> None:
        self.fields = list(fields)

    def check(self, record: Record) -> List[Issue]:
        return [
            Issue("required_field", Severity.ERROR, record.oid, f"{name} is empty", field=name)
            for name in self.fields
            if is_blank(_get(record, name))
        ]


class PatternRule(Rule):
    name = "pattern"

    def __init__(self, patterns: Dict[str, str]) -> None:
        self.patterns = {name: re.compile(pattern) for name, pattern in patterns.items()}

    def check(self, record: Record) -> List[Issue]:
        issues = []
        for name, pattern in self.patterns.items():
            value = _get(record, name)
            if is_blank(value):
                continue
            text = _as_text(value)
            if not pattern.fullmatch(text):
                issues.append(
                    Issue(
                        "pattern",
                        Severity.ERROR,
                        record.oid,
                        f"{name} does not match the expected format",
                        field=name,
                        value=value,
                    )
                )
        return issues


def _as_text(value: Any) -> str:
    # Whole-number floats (common for numeric IDs read from shapefiles) lose the ".0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class AllowedValuesRule(Rule):
    name = "allowed_values"

    def __init__(self, allowed: Dict[str, List[Any]]) -> None:
        self.allowed = {name: {_normalize(v) for v in values} for name, values in allowed.items()}

    def check(self, record: Record) -> List[Issue]:
        issues = []
        for name, allowed in self.allowed.items():
            value = _get(record, name)
            if is_blank(value):
                continue
            if _normalize(value) not in allowed:
                issues.append(
                    Issue(
                        "allowed_values",
                        Severity.ERROR,
                        record.oid,
                        f"{name} has a value outside the allowed list",
                        field=name,
                        value=value,
                    )
                )
        return issues


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class RangeRule(Rule):
    name = "range"

    def __init__(self, ranges) -> None:
        self.ranges = ranges

    def check(self, record: Record) -> List[Issue]:
        issues = []
        for name, bounds in self.ranges.items():
            value = _get(record, name)
            if is_blank(value):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                issues.append(
                    Issue("range", Severity.ERROR, record.oid, f"{name} is not a number", field=name, value=value)
                )
                continue
            if bounds.min is not None and number < bounds.min:
                issues.append(
                    Issue(
                        "range",
                        Severity.ERROR,
                        record.oid,
                        f"{name} is below the minimum {bounds.min:g}",
                        field=name,
                        value=value,
                    )
                )
            elif bounds.max is not None and number > bounds.max:
                issues.append(
                    Issue(
                        "range",
                        Severity.ERROR,
                        record.oid,
                        f"{name} is above the maximum {bounds.max:g}",
                        field=name,
                        value=value,
                    )
                )
        return issues


class FutureDateRule(Rule):
    name = "future_date"

    def __init__(self, fields: Iterable[str], today: Optional[date] = None) -> None:
        self.fields = list(fields)
        self.today = today or date.today()

    def check(self, record: Record) -> List[Issue]:
        issues = []
        for name in self.fields:
            value = _get(record, name)
            if is_blank(value):
                continue
            parsed = to_date(value)
            if parsed is None:
                issues.append(
                    Issue("future_date", Severity.ERROR, record.oid, f"{name} is not a date", field=name, value=value)
                )
            elif parsed > self.today:
                issues.append(
                    Issue(
                        "future_date",
                        Severity.WARNING,
                        record.oid,
                        f"{name} is in the future",
                        field=name,
                        value=parsed.isoformat(),
                    )
                )
        return issues


def to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):  # pandas Timestamp
        return value.to_pydatetime().date()
    if isinstance(value, str):
        text = value.strip()
        for parse in (
            lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")),
            lambda t: datetime.strptime(t, "%m/%d/%Y"),
        ):
            try:
                return parse(text).date()
            except ValueError:
                continue
    return None


def build_rules(config: QAConfig, today: Optional[date] = None) -> List[Rule]:
    """Rules in the order they run. Geometry checks come first."""
    rules: List[Rule] = [GeometryRule(config.check_geometry_validity)]
    if config.min_area_m2 is not None or config.min_length_m is not None:
        rules.append(SizeRule(config.min_area_m2, config.min_length_m))
    if config.extent_wgs84:
        rules.append(ExtentRule(config.extent_wgs84))
    if config.check_duplicate_geometry:
        rules.append(DuplicateGeometryRule())
    if config.key_field:
        rules.append(UniqueKeyRule(config.key_field))
    if config.required_fields:
        rules.append(RequiredFieldsRule(config.required_fields))
    if config.patterns:
        rules.append(PatternRule(config.patterns))
    if config.allowed_values:
        rules.append(AllowedValuesRule(config.allowed_values))
    if config.ranges:
        rules.append(RangeRule(config.ranges))
    if config.no_future_dates:
        rules.append(FutureDateRule(config.no_future_dates, today))
    return rules

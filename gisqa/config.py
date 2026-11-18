"""Rules configuration: a small JSON file describing what "good data" means."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .records import Bounds


class ConfigError(ValueError):
    """The rules file or tool options are invalid."""


@dataclass(frozen=True)
class NumericRange:
    min: Optional[float] = None
    max: Optional[float] = None


@dataclass(frozen=True)
class QAConfig:
    name: str = "Data quality check"
    #: Field whose values must be unique (e.g. FOLIO, PERMIT_NO)
    key_field: Optional[str] = None
    #: Fields that must not be null or blank
    required_fields: List[str] = field(default_factory=list)
    #: Field -> regular expression the whole value must match
    patterns: Dict[str, str] = field(default_factory=dict)
    #: Field -> list of permitted values (coded domains can be added automatically in ArcGIS)
    allowed_values: Dict[str, List[Any]] = field(default_factory=dict)
    #: Field -> {"min": x, "max": y}
    ranges: Dict[str, NumericRange] = field(default_factory=dict)
    #: Date fields whose values must not be in the future
    no_future_dates: List[str] = field(default_factory=list)
    #: Polygons smaller than this (square meters) are flagged as slivers
    min_area_m2: Optional[float] = None
    #: Lines shorter than this (meters) are flagged
    min_length_m: Optional[float] = None
    #: Expected data extent in WGS84 degrees: xmin, ymin, xmax, ymax
    extent_wgs84: Optional[Bounds] = None
    check_geometry_validity: bool = True
    check_duplicate_geometry: bool = True

    def fields_used(self) -> List[str]:
        """Attribute fields the rules read, in a stable order."""
        names: List[str] = []
        candidates = [
            self.key_field,
            *self.required_fields,
            *self.patterns,
            *self.allowed_values,
            *self.ranges,
            *self.no_future_dates,
        ]
        for name in candidates:
            if name and name not in names:
                names.append(name)
        return names

    def missing_fields(self, available: Sequence[str]) -> List[str]:
        lookup = {f.lower() for f in available}
        return [f for f in self.fields_used() if f.lower() not in lookup]

    def with_overrides(self, **changes: Any) -> "QAConfig":
        """Tool parameters extend or replace values from the rules file."""
        merged: Dict[str, Any] = {}
        for key, value in changes.items():
            if value is None or value == [] or value == {}:
                continue
            current = getattr(self, key)
            if isinstance(current, list):
                merged[key] = list(dict.fromkeys([*current, *value]))
            elif isinstance(current, dict):
                merged[key] = {**current, **value}
            else:
                merged[key] = value
        return _validated(replace(self, **merged))


_KNOWN_KEYS = {f.name for f in fields(QAConfig)} | {"extent", "min_area", "min_length"}


def load_config(source: Union[str, Path, Dict[str, Any]]) -> QAConfig:
    """Load from a JSON file path or an already-parsed dict."""
    if isinstance(source, dict):
        data = source
    else:
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ConfigError(f"Rules file not found: {source}") from error
        except json.JSONDecodeError as error:
            raise ConfigError(f"Rules file is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("Rules file must contain a JSON object")

    unknown = sorted(set(data) - _KNOWN_KEYS)
    if unknown:
        raise ConfigError(f"Unknown setting(s): {', '.join(unknown)}")

    extent = data.get("extent_wgs84", data.get("extent"))
    config = QAConfig(
        name=str(data.get("name", QAConfig.name)),
        key_field=data.get("key_field") or None,
        required_fields=list(data.get("required_fields", [])),
        patterns=dict(data.get("patterns", {})),
        allowed_values={k: list(v) for k, v in data.get("allowed_values", {}).items()},
        ranges={k: NumericRange(v.get("min"), v.get("max")) for k, v in data.get("ranges", {}).items()},
        no_future_dates=list(data.get("no_future_dates", [])),
        min_area_m2=data.get("min_area_m2", data.get("min_area")),
        min_length_m=data.get("min_length_m", data.get("min_length")),
        extent_wgs84=_parse_extent(extent),
        check_geometry_validity=bool(data.get("check_geometry_validity", True)),
        check_duplicate_geometry=bool(data.get("check_duplicate_geometry", True)),
    )
    return _validated(config)


def _parse_extent(value: Any) -> Optional[Bounds]:
    if value is None:
        return None
    if isinstance(value, dict):
        try:
            value = [value["xmin"], value["ymin"], value["xmax"], value["ymax"]]
        except KeyError as error:
            raise ConfigError("extent needs xmin, ymin, xmax and ymax") from error
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ConfigError("extent must be [xmin, ymin, xmax, ymax]")
    xmin, ymin, xmax, ymax = (float(v) for v in value)
    if not (-180 <= xmin < xmax <= 180 and -90 <= ymin < ymax <= 90):
        raise ConfigError("extent must be WGS84 degrees with min < max (longitude first)")
    return (xmin, ymin, xmax, ymax)


def _validated(config: QAConfig) -> QAConfig:
    for name, pattern in config.patterns.items():
        try:
            re.compile(pattern)
        except re.error as error:
            raise ConfigError(f"Invalid pattern for {name}: {error}") from error
    for name, bounds in config.ranges.items():
        if bounds.min is None and bounds.max is None:
            raise ConfigError(f"Range for {name} needs a min, a max, or both")
        if bounds.min is not None and bounds.max is not None and bounds.min > bounds.max:
            raise ConfigError(f"Range for {name} has min greater than max")
    for label, value in (("min_area_m2", config.min_area_m2), ("min_length_m", config.min_length_m)):
        if value is not None and (not isinstance(value, (int, float)) or value <= 0):
            raise ConfigError(f"{label} must be a positive number")
    return config

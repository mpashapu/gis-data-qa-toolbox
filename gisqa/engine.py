"""Runs the configured rules over a stream of records."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

from .config import ConfigError, QAConfig
from .records import Issue, Record, Severity
from .rules import GeometryRule, build_rules


@dataclass
class QAResult:
    config_name: str
    records_checked: int = 0
    issues: List[Issue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity is Severity.WARNING)

    @property
    def records_with_issues(self) -> int:
        return len({issue.oid for issue in self.issues})

    @property
    def pass_rate(self) -> float:
        if not self.records_checked:
            return 1.0
        return 1 - self.records_with_issues / self.records_checked

    def counts_by_rule(self) -> Dict[str, int]:
        return dict(Counter(issue.rule for issue in self.issues).most_common())

    def summary(self) -> Dict[str, object]:
        return {
            "name": self.config_name,
            "records_checked": self.records_checked,
            "records_with_issues": self.records_with_issues,
            "pass_rate": round(self.pass_rate, 4),
            "errors": self.error_count,
            "warnings": self.warning_count,
            "issues_by_rule": self.counts_by_rule(),
        }


def run_checks(
    records: Iterable[Record],
    config: QAConfig,
    available_fields: Optional[Sequence[str]] = None,
    today: Optional[date] = None,
) -> QAResult:
    """Check every record. Raises ConfigError if configured fields don't exist,
    because silently skipping a misspelled field would report false passes."""
    if available_fields is not None:
        missing = config.missing_fields(available_fields)
        if missing:
            raise ConfigError(f"Field(s) not in the dataset: {', '.join(missing)}")

    rules = build_rules(config, today)
    result = QAResult(config_name=config.name)
    for record in records:
        result.records_checked += 1
        geometry_ok = True
        for rule in rules:
            # Measuring or comparing a null/empty/invalid shape only adds noise,
            # but attribute rules still run
            if not geometry_ok and rule.name in _GEOMETRY_DEPENDENT_RULES:
                continue
            found = rule.check(record)
            result.issues.extend(found)
            if found and isinstance(rule, GeometryRule):
                geometry_ok = False
    return result


_GEOMETRY_DEPENDENT_RULES = {"size", "extent", "duplicate_geometry"}

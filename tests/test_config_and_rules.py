from datetime import date, datetime

import pytest

from gisqa.config import ConfigError, QAConfig, load_config
from gisqa.engine import run_checks
from gisqa.records import GeometryInfo, Record, Severity

GOOD = GeometryInfo(area_m2=900.0, bounds_wgs84=(-80.20, 25.76, -80.19, 25.77), fingerprint="a")
TODAY = date(2026, 11, 16)


def rec(oid, geometry=GOOD, **attributes):
    return Record(oid=oid, attributes=attributes, geometry=geometry)


def rules_of(result):
    return sorted((issue.oid, issue.rule) for issue in result.issues)


# ---------- config ----------


def test_load_config_accepts_aliases_and_dict_extent():
    config = load_config({"min_area": 25, "extent": {"xmin": -81, "ymin": 25, "xmax": -80, "ymax": 26}})
    assert config.min_area_m2 == 25
    assert config.extent_wgs84 == (-81.0, 25.0, -80.0, 26.0)


@pytest.mark.parametrize(
    "data, message",
    [
        ({"key_feild": "FOLIO"}, "Unknown setting"),
        ({"patterns": {"ZIP": "[0-9"}}, "Invalid pattern"),
        ({"ranges": {"YEAR": {}}}, "needs a min"),
        ({"ranges": {"YEAR": {"min": 10, "max": 1}}}, "min greater than max"),
        ({"extent": [-80, 26, -81, 25]}, "min < max"),  # note: a swapped Florida box is still valid WGS84
        ({"min_area_m2": -5}, "positive"),
    ],
)
def test_load_config_rejects_bad_settings(data, message):
    with pytest.raises(ConfigError, match=message):
        load_config(data)


def test_load_config_from_file_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(bad)


def test_overrides_extend_lists_and_dicts_but_skip_empty_values():
    config = QAConfig(required_fields=["A"], allowed_values={"X": [1]})
    merged = config.with_overrides(
        required_fields=["B", "A"], allowed_values={"Y": [2]}, key_field=None, min_area_m2=10
    )
    assert merged.required_fields == ["A", "B"]
    assert merged.allowed_values == {"X": [1], "Y": [2]}
    assert merged.key_field is None
    assert merged.min_area_m2 == 10


def test_missing_fields_are_reported_before_checking():
    config = QAConfig(required_fields=["FOLIO", "SITE_ADDR"])
    assert config.missing_fields(["folio", "ZIP"]) == ["SITE_ADDR"]
    with pytest.raises(ConfigError, match="SITE_ADDR"):
        run_checks([], config, available_fields=["FOLIO"])


# ---------- geometry rules ----------


def test_bad_geometry_skips_geometry_rules_but_not_attribute_rules():
    config = QAConfig(required_fields=["NAME"], min_area_m2=50, extent_wgs84=(-81, 25, -80, 26))
    result = run_checks(
        [
            rec(1, GeometryInfo.null(), NAME=""),
            rec(2, GeometryInfo(is_empty=True), NAME="ok"),
            rec(3, GeometryInfo(validity_error="Self-intersection", area_m2=1.0, fingerprint="x"), NAME="ok"),
        ],
        config,
    )
    assert rules_of(result) == [
        (1, "null_geometry"),
        (1, "required_field"),
        (2, "empty_geometry"),
        (3, "invalid_geometry"),
    ]


def test_validity_check_can_be_disabled():
    config = QAConfig(check_geometry_validity=False)
    result = run_checks([rec(1, GeometryInfo(validity_error="Ring Self-intersection", fingerprint="z"))], config)
    assert result.issues == []


def test_sliver_and_short_line_thresholds():
    config = QAConfig(min_area_m2=50, min_length_m=5)
    result = run_checks(
        [
            rec(1, GeometryInfo(area_m2=49.9, fingerprint="1")),
            rec(2, GeometryInfo(area_m2=50.0, fingerprint="2")),
            rec(3, GeometryInfo(length_m=1.2, fingerprint="3")),
        ],
        config,
    )
    assert rules_of(result) == [(1, "sliver_polygon"), (3, "short_line")]
    assert all(i.severity is Severity.WARNING for i in result.issues)


def test_outside_extent_detects_swapped_coordinates():
    config = QAConfig(extent_wgs84=(-80.88, 25.13, -80.11, 25.98))
    swapped = GeometryInfo(bounds_wgs84=(25.76, -80.20, 25.77, -80.19), fingerprint="s")
    elsewhere = GeometryInfo(bounds_wgs84=(-82.5, 27.9, -82.4, 28.0), fingerprint="t")  # Tampa
    result = run_checks([rec(1, swapped), rec(2, elsewhere)], config)
    messages = {i.oid: i.message for i in result.issues}
    assert "swapped" in messages[1]
    assert "swapped" not in messages[2]


def test_duplicate_geometry_points_to_first_feature():
    result = run_checks([rec(1), rec(2), rec(3, GeometryInfo(fingerprint="other"))], QAConfig())
    (issue,) = result.issues
    assert (issue.oid, issue.rule, issue.value) == (2, "duplicate_geometry", 1)


# ---------- attribute rules ----------


def test_duplicate_key_is_case_and_space_insensitive():
    config = QAConfig(key_field="FOLIO", check_duplicate_geometry=False)
    result = run_checks([rec(1, FOLIO="AB1"), rec(2, FOLIO=" ab1 "), rec(3, FOLIO=None), rec(4, FOLIO=None)], config)
    assert rules_of(result) == [(2, "duplicate_key")]


def test_required_fields_treat_whitespace_as_blank_and_zero_as_present():
    config = QAConfig(required_fields=["A", "B", "C"], check_duplicate_geometry=False)
    result = run_checks([rec(1, A="  ", B=0, C=None)], config)
    assert [i.field for i in result.issues] == ["A", "C"]


def test_pattern_full_match_and_float_ids():
    config = QAConfig(patterns={"ZIP": r"\d{5}"}, check_duplicate_geometry=False)
    result = run_checks([rec(1, ZIP="33130"), rec(2, ZIP="33130-1234"), rec(3, ZIP=33130.0), rec(4, ZIP="")], config)
    assert rules_of(result) == [(2, "pattern")]


def test_allowed_values_normalizes_whitespace_and_numbers():
    config = QAConfig(allowed_values={"USE": ["RES", 1]}, check_duplicate_geometry=False)
    result = run_checks([rec(1, USE=" RES "), rec(2, USE=1.0), rec(3, USE="res")], config)
    assert rules_of(result) == [(3, "allowed_values")]


def test_ranges_and_non_numbers():
    config = load_config({"ranges": {"YEAR": {"min": 1850, "max": 2026}}, "check_duplicate_geometry": False})
    result = run_checks([rec(1, YEAR=1849), rec(2, YEAR="2026"), rec(3, YEAR="unknown"), rec(4, YEAR=2027)], config)
    assert rules_of(result) == [(1, "range"), (3, "range"), (4, "range")]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-11-16", None),
        ("2026-11-17", "future_date"),
        ("12/25/2030", "future_date"),
        (datetime(2027, 1, 1, 9, 30), "future_date"),
        (date(2020, 1, 1), None),
        ("2027-01-01T00:00:00Z", "future_date"),
        ("not a date", "future_date"),
    ],
)
def test_future_dates(value, expected):
    config = QAConfig(no_future_dates=["D"], check_duplicate_geometry=False)
    result = run_checks([rec(1, D=value)], config, today=TODAY)
    assert [i.rule for i in result.issues] == ([expected] if expected else [])


def test_unparseable_date_is_an_error_but_future_date_is_a_warning():
    config = QAConfig(no_future_dates=["D"], check_duplicate_geometry=False)
    result = run_checks([rec(1, D="soon"), rec(2, D="2099-01-01")], config, today=TODAY)
    assert [i.severity for i in result.issues] == [Severity.ERROR, Severity.WARNING]


def test_attribute_lookup_is_case_insensitive():
    config = QAConfig(required_fields=["site_addr"], check_duplicate_geometry=False)
    assert run_checks([rec(1, SITE_ADDR="1 MAIN ST")], config).issues == []


# ---------- summary ----------


def test_summary_counts():
    config = QAConfig(required_fields=["A"], check_duplicate_geometry=False)
    result = run_checks([rec(1, A=""), rec(2, A="x"), rec(3, GeometryInfo.null(), A="")], config)
    summary = result.summary()
    assert summary["records_checked"] == 3
    assert summary["records_with_issues"] == 2
    assert summary["errors"] == 3
    assert summary["pass_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert summary["issues_by_rule"] == {"required_field": 2, "null_geometry": 1}

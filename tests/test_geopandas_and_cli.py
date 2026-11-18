import csv
import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from gisqa.cli import main
from gisqa.geopandas_adapter import read_records

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SAMPLE = EXAMPLES / "sample_parcels.geojson"
RULES = EXAMPLES / "parcels_rules.json"

# The planted problem in each sample parcel (see examples/make_sample_data.py)
EXPECTED = {
    3: "invalid_geometry",
    5: "duplicate_geometry",
    6: "duplicate_key",
    7: "required_field",
    8: "pattern",
    9: "allowed_values",
    10: "range",
    11: "future_date",
    12: "sliver_polygon",
    13: "outside_extent",
    14: "null_geometry",
}


def run_cli(tmp_path, *extra):
    code = main([str(SAMPLE), "--rules", str(RULES), "--oid-field", "PARCEL_ID", "--out", str(tmp_path), *extra])
    with open(tmp_path / "sample_parcels_qa_issues.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return code, rows


def test_sample_finds_exactly_the_planted_problems(tmp_path):
    code, rows = run_cli(tmp_path)
    found = {int(r["oid"]): r["rule"] for r in rows}
    assert found == EXPECTED
    assert len(rows) == len(EXPECTED)  # nothing flagged twice, clean parcels pass
    assert code == 1  # errors present


def test_reports_are_written(tmp_path):
    run_cli(tmp_path)
    summary = json.loads((tmp_path / "sample_parcels_qa_summary.json").read_text())
    assert summary["records_checked"] == 20
    assert summary["records_with_issues"] == 11
    html = (tmp_path / "sample_parcels_qa.html").read_text()
    assert "FAIL" in html and "Self-intersection" in html


def test_fail_on_never_exits_zero(tmp_path):
    code, _ = run_cli(tmp_path, "--fail-on", "never")
    assert code == 0


def test_misspelled_field_is_a_usage_error(tmp_path, capsys):
    code = main([str(SAMPLE), "--required", "SITE_ADDRESS", "--out", str(tmp_path)])
    assert code == 2
    assert "SITE_ADDRESS" in capsys.readouterr().err


def test_missing_dataset_is_a_usage_error(tmp_path):
    assert main([str(tmp_path / "nope.gpkg"), "--out", str(tmp_path)]) == 2


def test_geodesic_measurements_from_projected_data(tmp_path):
    # A 100 m x 50 m polygon and a 250 m line in Florida State Plane East (feet)
    feet = 3.280833333
    x, y = 920_000.0, 520_000.0
    frame = gpd.GeoDataFrame(
        {"NAME": ["lot", "road"]},
        geometry=[
            Polygon([(x, y), (x + 100 * feet, y), (x + 100 * feet, y + 50 * feet), (x, y + 50 * feet)]),
            LineString([(x, y), (x + 250 * feet, y)]),
        ],
        crs="EPSG:2236",
    )
    path = tmp_path / "projected.gpkg"
    frame.to_file(path, layer="things")

    records, fields, count = read_records(str(path), layer="things")
    lot, road = list(records)
    assert fields == ["NAME"] and count == 2
    assert lot.geometry.area_m2 == pytest.approx(5000, rel=0.002)
    assert road.geometry.length_m == pytest.approx(250, rel=0.002)
    xmin, ymin, _, _ = lot.geometry.bounds_wgs84
    assert -81 < xmin < -80 and 25 < ymin < 26.5  # reprojected to WGS84 lon/lat


def test_same_shape_with_different_start_vertex_is_a_duplicate(tmp_path):
    a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    b = Polygon([(1, 1), (0, 1), (0, 0), (1, 0)])  # same square, rotated vertex order
    path = tmp_path / "dupes.geojson"
    gpd.GeoDataFrame({"ID": [1, 2]}, geometry=[a, b], crs="EPSG:4326").to_file(path)
    first, second = list(read_records(str(path))[0])
    assert first.geometry.fingerprint == second.geometry.fingerprint

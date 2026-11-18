"""Exercises GISDataQA.pyt against tests/fake_arcpy.py (see that file's caveat)."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fake_arcpy import Domain, Field, Geometry, make_fake_arcpy

ROOT = Path(__file__).resolve().parent.parent
DATASET = "C:/data/city.gdb/Parcels"
SQUARE = [(-80.20, 25.76), (-80.199, 25.76), (-80.199, 25.761), (-80.20, 25.761)]


@pytest.fixture
def arcpy(monkeypatch):
    fake = make_fake_arcpy()
    monkeypatch.setitem(sys.modules, "arcpy", fake)
    monkeypatch.delitem(sys.modules, "gisqa.arcpy_adapter", raising=False)
    return fake


@pytest.fixture
def toolbox(arcpy):
    loader = importlib.machinery.SourceFileLoader("GISDataQA", str(ROOT / "GISDataQA.pyt"))
    spec = importlib.util.spec_from_loader("GISDataQA", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_toolbox_exposes_one_tool_with_expected_parameters(toolbox):
    assert [t.__name__ for t in toolbox.Toolbox().tools] == ["CheckDataQuality"]
    params = toolbox.CheckDataQuality().getParameterInfo()
    names = [p.name for p in params]
    assert names == [
        "in_features",
        "rules_file",
        "key_field",
        "required_fields",
        "min_area",
        "use_domains",
        "report_folder",
        "issues_table",
        "error_count",
    ]
    assert params[toolbox.RULES_FILE].filter.list == ["json"]
    assert params[toolbox.REQUIRED_FIELDS].multiValue
    assert params[toolbox.REQUIRED_FIELDS].parameterDependencies == ["in_features"]
    assert params[toolbox.USE_DOMAINS].value is True
    assert params[toolbox.ERROR_COUNT].parameterType == "Derived"


def test_update_messages_validates_rules_file_and_area(toolbox, tmp_path):
    bad = tmp_path / "rules.json"
    bad.write_text('{"unknown_setting": 1}')
    tool = toolbox.CheckDataQuality()
    params = tool.getParameterInfo()
    params[toolbox.RULES_FILE].value, params[toolbox.RULES_FILE].altered = str(bad), True
    params[toolbox.MIN_AREA].value = 0
    tool.updateMessages(params)
    assert "Unknown setting" in params[toolbox.RULES_FILE].errorMessage
    assert params[toolbox.MIN_AREA].errorMessage


def test_execute_end_to_end(toolbox, arcpy, tmp_path):
    arcpy.datasets[DATASET] = {
        "shapeType": "Polygon",
        "fields": [Field("FOLIO"), Field("SITE_ADDR"), Field("LAND_USE", domain="LandUse")],
        "rows": [
            (1, Geometry(SQUARE, area=900.0), {"FOLIO": "0141370071240", "SITE_ADDR": "1 A ST", "LAND_USE": "RES"}),
            (
                2,
                Geometry([(x + 0.01, y) for x, y in SQUARE], area=900.0),
                {"FOLIO": "0141370071250", "SITE_ADDR": "2 A ST", "LAND_USE": "RES"},
            ),
            (
                3,
                Geometry([(x + 0.02, y) for x, y in SQUARE], area=12.0),
                {"FOLIO": "0141370071260", "SITE_ADDR": "", "LAND_USE": "COM"},
            ),
            (4, None, {"FOLIO": "0141370071240", "SITE_ADDR": "4 A ST", "LAND_USE": "ZZZ"}),
        ],
    }
    arcpy.domains["C:/data/city.gdb"] = [Domain("LandUse", {"RES": "Residential", "COM": "Commercial"})]
    arcpy.geometry_problems[DATASET] = [(2, "self intersections")]

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"name": "Parcels", "patterns": {"FOLIO": "\\d{13}"}}))
    tool = toolbox.CheckDataQuality()
    params = tool.getParameterInfo()
    params[toolbox.IN_FEATURES].value = DATASET
    params[toolbox.RULES_FILE].value = str(rules)
    params[toolbox.KEY_FIELD].value = "FOLIO"
    params[toolbox.REQUIRED_FIELDS].value = ["SITE_ADDR"]
    params[toolbox.MIN_AREA].value = 50.0
    params[toolbox.REPORT_FOLDER].value = str(tmp_path / "reports")
    params[toolbox.ISSUES_TABLE].value = "memory/qa_issues"

    tool.execute(params, None)

    issues = {(r["FEATURE_OID"], r["RULE"]) for r in arcpy.tables["memory/qa_issues"]["rows"]}
    assert issues == {
        (2, "invalid_geometry"),  # from Check Geometry
        (3, "sliver_polygon"),  # 12 m² < 50 m² from the tool parameter
        (3, "required_field"),  # SITE_ADDR from the tool parameter
        (4, "null_geometry"),
        (4, "duplicate_key"),  # FOLIO repeats feature 1
        (4, "allowed_values"),  # ZZZ not in the LandUse coded domain
    }
    assert params[toolbox.ERROR_COUNT].value == 5  # everything except the sliver warning
    assert (tmp_path / "reports" / "Parcels_qa.html").exists()
    assert "memory/gisqa_check_geometry" not in arcpy.tables  # temp table cleaned up
    messages = " ".join(m for _, m in arcpy.messages)
    assert "coded value domains on: LAND_USE" in messages


def test_execute_reports_misspelled_field(toolbox, arcpy, tmp_path):
    arcpy.datasets[DATASET] = {"shapeType": "Polygon", "fields": [Field("FOLIO")], "rows": []}
    tool = toolbox.CheckDataQuality()
    params = tool.getParameterInfo()
    params[toolbox.IN_FEATURES].value = DATASET
    params[toolbox.REQUIRED_FIELDS].value = ["FOLIO_NO"]
    params[toolbox.USE_DOMAINS].value = False
    params[toolbox.REPORT_FOLDER].value = str(tmp_path)
    with pytest.raises(arcpy.ExecuteError, match="FOLIO_NO"):
        tool.execute(params, None)


def test_geometry_info_measures_by_shape_type(arcpy):
    from gisqa.arcpy_adapter import geometry_info

    wgs84 = arcpy.SpatialReference(4326)
    assert geometry_info(None, "Polygon", None, wgs84).is_null
    assert geometry_info(Geometry([]), "Polygon", None, wgs84).is_empty
    polygon = geometry_info(Geometry(SQUARE, area=900.0), "Polygon", None, wgs84)
    assert polygon.area_m2 == 900.0 and polygon.length_m is None
    assert polygon.bounds_wgs84 == (-80.20, 25.76, -80.199, 25.761)
    line = geometry_info(Geometry(SQUARE[:2], length=100.0), "Polyline", "short", wgs84)
    assert line.length_m == 100.0 and line.validity_error == "short"

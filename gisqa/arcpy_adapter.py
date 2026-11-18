"""Read features with arcpy (ArcGIS Pro). Imported only inside the toolbox."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterator, List, Sequence

import arcpy  # noqa: F401  (available inside ArcGIS Pro)

from .records import Bounds, GeometryInfo, Issue, Record


def list_fields(in_features: str) -> List[str]:
    return [f.name for f in arcpy.ListFields(in_features) if f.type not in ("OID", "Geometry")]


def geometry_errors(in_features: str) -> Dict[int, str]:
    """Runs the Check Geometry tool (OGC rules) and returns {OID: problem}."""
    out_table = os.path.join("memory", "gisqa_check_geometry")
    try:
        arcpy.management.CheckGeometry(in_features, out_table, "OGC")
        problems: Dict[int, str] = {}
        with arcpy.da.SearchCursor(out_table, ["FEATURE_ID", "PROBLEM"]) as cursor:
            for oid, problem in cursor:
                problems.setdefault(oid, problem)
        return problems
    finally:
        if arcpy.Exists(out_table):
            arcpy.management.Delete(out_table)


def coded_domain_values(in_features: str) -> Dict[str, List[Any]]:
    """{field: [codes]} for fields with coded value domains. Shapefiles have none."""
    try:
        desc = arcpy.Describe(in_features)
        workspace = os.path.dirname(desc.catalogPath)
        if arcpy.Describe(workspace).dataType == "FeatureDataset":
            workspace = os.path.dirname(workspace)
        domains = {d.name: d for d in arcpy.da.ListDomains(workspace) if d.domainType == "CodedValue"}
    except Exception:  # noqa: BLE001 - layers from services, shapefiles, etc.
        return {}
    return {
        field.name: list(domains[field.domain].codedValues.keys())
        for field in arcpy.ListFields(in_features)
        if field.domain and field.domain in domains
    }


def read_records(in_features: str, fields: Sequence[str], validity: Dict[int, str]) -> Iterator[Record]:
    shape_type = arcpy.Describe(in_features).shapeType  # Polygon, Polyline, Point, Multipoint
    wgs84 = arcpy.SpatialReference(4326)
    with arcpy.da.SearchCursor(in_features, ["OID@", "SHAPE@", *fields]) as cursor:
        for oid, geometry, *values in cursor:
            yield Record(
                oid=oid,
                attributes=dict(zip(fields, values)),
                geometry=geometry_info(geometry, shape_type, validity.get(oid), wgs84),
            )


def geometry_info(geometry, shape_type: str, validity_error, wgs84) -> GeometryInfo:
    if geometry is None:
        return GeometryInfo.null()
    if geometry.pointCount == 0:
        return GeometryInfo(is_empty=True)

    area = length = None
    if shape_type == "Polygon":
        area = geometry.getArea("GEODESIC", "SQUAREMETERS")
    elif shape_type == "Polyline":
        length = geometry.getLength("GEODESIC", "METERS")

    return GeometryInfo(
        validity_error=validity_error,
        area_m2=area,
        length_m=length,
        bounds_wgs84=_wgs84_bounds(geometry, wgs84),
        fingerprint=hashlib.sha1(geometry.WKB).hexdigest(),  # exact duplicates
    )


def _wgs84_bounds(geometry, wgs84) -> Bounds:
    extent = geometry.projectAs(wgs84).extent
    return (extent.XMin, extent.YMin, extent.XMax, extent.YMax)


def write_issue_table(issues: Sequence[Issue], out_table: str) -> None:
    folder, name = os.path.split(out_table)
    arcpy.management.CreateTable(folder, name)
    for field_name, field_type, length in (
        ("RULE", "TEXT", 40),
        ("SEVERITY", "TEXT", 10),
        ("FEATURE_OID", "LONG", None),
        ("FIELD_NAME", "TEXT", 64),
        ("VALUE", "TEXT", 255),
        ("MESSAGE", "TEXT", 255),
    ):
        arcpy.management.AddField(out_table, field_name, field_type, field_length=length)
    with arcpy.da.InsertCursor(
        out_table, ["RULE", "SEVERITY", "FEATURE_OID", "FIELD_NAME", "VALUE", "MESSAGE"]
    ) as cursor:
        for issue in issues:
            row = issue.as_row()
            cursor.insertRow(
                (row["rule"], row["severity"], int(issue.oid), row["field"], row["value"][:255], row["message"][:255])
            )

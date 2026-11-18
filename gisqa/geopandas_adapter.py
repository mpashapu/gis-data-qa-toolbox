"""Read any OGR-supported dataset (GeoPackage, shapefile, GeoJSON, file
geodatabase) with GeoPandas. No ArcGIS license needed."""

from __future__ import annotations

import hashlib
import warnings
from typing import Iterator, List, Optional, Tuple

import geopandas as gpd
import shapely
from pyproj import Geod

from .records import GeometryInfo, Record

# Geodesic measurement on the WGS84 ellipsoid (same idea as arcpy's "GEODESIC"
# option). Picking a single projected CRS for the whole dataset is fragile:
# one far-away feature (e.g. swapped coordinates) shifts the chosen UTM zone
# and distorts every other measurement.
GEOD = Geod(ellps="WGS84")


def read_records(
    path: str,
    layer: Optional[str] = None,
    oid_field: Optional[str] = None,
) -> Tuple[Iterator[Record], List[str], int]:
    """Returns (records, attribute field names, feature count)."""
    frame = gpd.read_file(path, layer=layer)
    geometry_name = frame.geometry.name
    fields = [c for c in frame.columns if c != geometry_name]
    return _iter_records(frame, fields, oid_field), fields, len(frame)


def _iter_records(frame: gpd.GeoDataFrame, fields: List[str], oid_field: Optional[str]) -> Iterator[Record]:
    geometries = frame.geometry.values
    wgs84 = _to_wgs84(frame)
    for position, (attributes, geometry) in enumerate(zip(frame[fields].to_dict("records"), geometries)):
        oid = attributes.get(oid_field) if oid_field else position + 1
        attributes = {k: (None if _is_missing(v) else v) for k, v in attributes.items()}
        yield Record(
            oid=oid,
            attributes=attributes,
            geometry=_geometry_info(geometry, wgs84[position] if wgs84 is not None else None),
        )


def _to_wgs84(frame: gpd.GeoDataFrame):
    if frame.crs is None:
        warnings.warn("Dataset has no coordinate system: areas, lengths and extent checks are skipped.", stacklevel=2)
        return None
    return frame.geometry.to_crs(4326).values


def _geometry_info(geometry, wgs84_geometry) -> GeometryInfo:
    if geometry is None:
        return GeometryInfo.null()
    if geometry.is_empty:
        return GeometryInfo(is_empty=True)

    reason = shapely.is_valid_reason(geometry)
    kind = geometry.geom_type
    area = length = None
    if wgs84_geometry is not None:
        if kind in ("Polygon", "MultiPolygon"):
            area = abs(GEOD.geometry_area_perimeter(wgs84_geometry)[0])
        elif kind in ("LineString", "MultiLineString"):
            length = GEOD.geometry_length(wgs84_geometry)

    return GeometryInfo(
        validity_error=None if reason == "Valid Geometry" else reason,
        area_m2=area,
        length_m=length,
        bounds_wgs84=tuple(float(b) for b in wgs84_geometry.bounds) if wgs84_geometry is not None else None,
        # Normalized so the same shape with a different start vertex still matches
        fingerprint=hashlib.sha1(shapely.normalize(geometry).wkb).hexdigest(),
    )


def _is_missing(value) -> bool:
    try:
        return value is None or (value != value)  # NaN / NaT
    except (TypeError, ValueError):
        return False

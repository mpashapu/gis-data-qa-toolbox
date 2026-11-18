"""Writes examples/sample_parcels.geojson: synthetic parcels with planted problems.

Every feature is invented. The problems are deliberate, one per kind, so the
report shows what each rule catches.
"""

import json
from pathlib import Path

LAT_PER_M = 1 / 111_320
LON_PER_M = 1 / 100_300  # about right at 25.8°N


def square(lon, lat, width_m=30, height_m=30):
    w, h = width_m * LON_PER_M, height_m * LAT_PER_M
    ring = [[lon, lat], [lon + w, lat], [lon + w, lat + h], [lon, lat + h], [lon, lat]]
    return {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in ring]]}


def parcel(
    oid,
    geometry,
    folio,
    addr="100 SAMPLE ST",
    zip_code="33130",
    land_use="RES",
    year_built=1995,
    sale_date="2021-06-15",
):
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "PARCEL_ID": oid,
            "FOLIO": folio,
            "SITE_ADDR": addr,
            "ZIP": zip_code,
            "LAND_USE": land_use,
            "YEAR_BUILT": year_built,
            "SALE_DATE": sale_date,
        },
    }


base = (-80.2000, 25.7600)
grid = [square(base[0] + i * 0.0006, base[1] + j * 0.0005) for j in range(4) for i in range(5)]
bow_tie = {
    "type": "Polygon",
    "coordinates": [[[-80.205, 25.75], [-80.2047, 25.7503], [-80.2047, 25.75], [-80.205, 25.7503], [-80.205, 25.75]]],
}
swapped = square(25.7650, -80.1950)  # latitude and longitude swapped

features = [
    parcel(1, grid[0], "0141370071240"),  # clean (note the leading zero)
    parcel(2, grid[1], "0141370071250", land_use="COM"),  # clean
    parcel(3, bow_tie, "0141370071260"),  # invalid geometry (self-intersection)
    parcel(4, grid[2], "0141370071270"),  # clean
    parcel(5, grid[2], "0141370071280"),  # duplicate geometry of 4
    parcel(6, grid[3], "0141370071240"),  # duplicate FOLIO of 1
    parcel(7, grid[4], "0141370071300", addr=""),  # missing required SITE_ADDR
    parcel(8, grid[5], "30-4011-005-0010"),  # FOLIO in the wrong format
    parcel(9, grid[6], "0141370071320", land_use="XYZ"),  # not an allowed land use
    parcel(10, grid[7], "0141370071330", year_built=2099),  # year out of range
    parcel(11, grid[8], "0141370071340", sale_date="2099-01-01"),  # sale date in the future
    parcel(12, square(-80.1990, 25.7640, 2, 3), "0141370071350"),  # sliver: 2 m x 3 m
    parcel(13, swapped, "0141370071360"),  # outside extent (swapped coordinates)
    parcel(14, None, "0141370071370"),  # no geometry
] + [parcel(15 + k, grid[9 + k], f"01413700714{k:02d}") for k in range(6)]  # clean

collection = {
    "type": "FeatureCollection",
    "name": "sample_parcels",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    "features": features,
}
out = Path(__file__).with_name("sample_parcels.geojson")
out.write_text(json.dumps(collection, indent=1))
print(f"Wrote {len(features)} features to {out}")

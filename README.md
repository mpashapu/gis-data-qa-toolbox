# GIS Data QA Toolbox

![CI](https://github.com/mpashapu/gis-data-qa-toolbox/actions/workflows/ci.yml/badge.svg)

Rule-based data quality checks for GIS feature data, available two ways:

- **ArcGIS Pro toolbox** (`GISDataQA.pyt`): a geoprocessing tool with
  parameters, messages and an optional issues table, built on arcpy
- **Command line** (`gisqa`): the same rules on GeoPackages, shapefiles,
  GeoJSON or file geodatabases using GeoPandas, with no ArcGIS license

Both feed one rules engine, so a dataset gets the same verdict whether it's
checked on a GIS analyst's desktop or in a nightly job.

[Sample report](docs/sample_report.html) (synthetic parcels with one planted
problem of each kind).

## What it checks

| Rule | Severity | Catches |
|---|---|---|
| `null_geometry` / `empty_geometry` | Error | Records with no shape |
| `invalid_geometry` | Error | Self-intersections, bad rings (Check Geometry in ArcGIS, Shapely validity in open source) |
| `outside_extent` | Error | Features outside the expected area, with a hint when latitude/longitude look swapped |
| `sliver_polygon` / `short_line` | Warning | Polygons under N m², lines under N m (geodesic measurement) |
| `duplicate_geometry` | Warning | The same shape loaded twice |
| `duplicate_key` | Error | Repeated IDs (folio, permit number); case- and space-insensitive |
| `required_field` | Error | Null or blank required values |
| `pattern` | Error | Values not in the expected format (e.g. 13-digit folio, 5-digit ZIP) |
| `allowed_values` | Error | Values outside a list, or outside the field's **coded value domain** (ArcGIS) |
| `range` | Error | Numbers outside min/max, or not numbers at all |
| `future_date` | Warning | Dates in the future (Error if the value isn't a date) |

Each run writes:

- `*_issues.csv`: one row per issue (rule, severity, feature ID, field, value, message)
- `*_summary.json`: counts and pass rate, for dashboards or CI
- `*.html`: a readable report with an explanation and suggested fix for each rule

## Rules file

A small JSON file describes what "good data" means for a dataset:

```json
{
  "name": "Parcels QA",
  "key_field": "FOLIO",
  "required_fields": ["FOLIO", "SITE_ADDR", "ZIP"],
  "patterns": { "FOLIO": "\\d{13}", "ZIP": "\\d{5}" },
  "allowed_values": { "LAND_USE": ["RES", "COM", "IND", "GOV", "VAC"] },
  "ranges": { "YEAR_BUILT": { "min": 1850, "max": 2026 } },
  "no_future_dates": ["SALE_DATE"],
  "min_area_m2": 50,
  "extent_wgs84": [-80.88, 25.13, -80.11, 25.98]
}
```

Unknown settings, invalid regular expressions, and fields that don't exist in
the dataset are reported as errors **before** checking starts. A misspelled
field name never produces a false "pass".

## ArcGIS Pro

1. Download or clone this repository. Keep `GISDataQA.pyt` and the `gisqa`
   folder together.
2. In ArcGIS Pro: **Catalog → Toolboxes → Add Toolbox**, then pick
   `GISDataQA.pyt`.
3. Open **Check Data Quality** and set:
   - **Input Features**: a layer or feature class
   - **Rules File**: optional JSON (above)
   - **Unique ID Field**, **Required Fields**, **Minimum Polygon Area**:
     optional, added on top of the rules file
   - **Check Coded Value Domains**: on by default; reads the geodatabase's
     coded domains automatically
   - **Report Folder**, and optionally an **Issues Table** to join back to
     the features

The tool runs **Check Geometry** (OGC) for validity, measures geodesically
(`GEODESIC`, square meters), and returns the error count as an output, so it
can be chained in ModelBuilder (e.g. stop a publishing model when errors > 0).
A Basic license is enough.

## Command line (no ArcGIS)

```bash
pip install ".[open]"

gisqa parcels.gpkg --layer parcels --rules parcels_rules.json --out qa_reports
gisqa permits.shp --key-field PERMIT_NO --required ADDRESS,ISSUE_DATE
gisqa city.gdb --layer Hydrants --rules hydrants.json --fail-on warning
```

Exit codes: `0` passed, `1` issues at or above `--fail-on` (default
`error`), `2` configuration or read problem. That makes it usable as a gate in
CI pipelines or scheduled jobs.

Try it on the sample:

```bash
gisqa examples/sample_parcels.geojson --rules examples/parcels_rules.json --oid-field PARCEL_ID
```

## Design notes

- **One engine, two adapters.** `gisqa.rules` and `gisqa.engine` don't import
  any GIS library. Adapters turn features into plain records: geometry
  facts (valid? area in m²? WGS84 bounds? fingerprint) plus attributes.
  Rules are easy to test, and adding a source (e.g. a REST feature service)
  means writing one adapter.
- **Geodesic measurement.** The open-source adapter measures area and length
  on the WGS84 ellipsoid (`pyproj.Geod`), matching arcpy's `GEODESIC` option.
  An earlier version projected everything to one auto-chosen UTM zone. A
  single feature with swapped coordinates shifted that choice and doubled
  every area in the dataset. The sample data keeps such a feature as a
  regression test.
- **Noise control.** When a geometry is null, empty or invalid, the
  geometry-dependent rules (size, extent, duplicates) skip that feature, but
  attribute rules still run.
- **Duplicates.** Shapes are normalized before fingerprinting in the
  open-source adapter, so the same polygon with a different starting vertex
  still matches. The arcpy adapter flags exact duplicates.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

42 tests:

- every rule, including edge cases (whitespace-only values, float IDs from
  shapefiles, several date formats)
- config validation
- the CLI end-to-end on the sample, which must find exactly the planted
  problems and nothing else
- geodesic measurement from State Plane (feet) data
- the toolbox: parameters, validation messages and a full `execute()` run

The toolbox tests run against `tests/fake_arcpy.py`, a small stand-in that
records what the tool calls. It verifies the toolbox's own logic in CI; final
verification is a run inside ArcGIS Pro.

## License

[MIT](LICENSE) © 2026 Malla Reddy Pashapu

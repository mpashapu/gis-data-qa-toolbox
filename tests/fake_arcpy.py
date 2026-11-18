"""A small stand-in for arcpy, so the toolbox's plumbing can be tested in CI.

It implements only what GISDataQA.pyt and gisqa.arcpy_adapter call. It checks
our parameter handling and data flow, not ArcGIS itself. Run the toolbox in
ArcGIS Pro for that.
"""

import os
import types
from contextlib import contextmanager


class ExecuteError(Exception):
    pass


class _Filter:
    def __init__(self):
        self.list = []


class Parameter:
    def __init__(
        self, displayName=None, name=None, datatype=None, parameterType=None, direction=None, multiValue=False, **_
    ):
        self.displayName, self.name, self.datatype = displayName, name, datatype
        self.parameterType, self.direction, self.multiValue = parameterType, direction, multiValue
        self.filter = _Filter()
        self.parameterDependencies = []
        self.value = None
        self.altered = False
        self.errorMessage = None

    @property
    def valueAsText(self):
        if self.value is None:
            return None
        if isinstance(self.value, (list, tuple)):
            return ";".join(str(v) for v in self.value)
        return str(self.value)

    def setErrorMessage(self, message):
        self.errorMessage = message


class Extent:
    def __init__(self, xmin, ymin, xmax, ymax):
        self.XMin, self.YMin, self.XMax, self.YMax = xmin, ymin, xmax, ymax


class Geometry:
    """Coordinates are already WGS84, so projectAs returns the same shape."""

    def __init__(self, coords, area=None, length=None):
        self.coords = coords
        self.pointCount = len(coords)
        self._area, self._length = area, length
        self.WKB = repr(coords).encode()

    def getArea(self, method, units):
        assert (method, units) == ("GEODESIC", "SQUAREMETERS")
        return self._area

    def getLength(self, method, units):
        assert (method, units) == ("GEODESIC", "METERS")
        return self._length

    def projectAs(self, spatial_reference):
        return self

    @property
    def extent(self):
        xs = [c[0] for c in self.coords]
        ys = [c[1] for c in self.coords]
        return Extent(min(xs), min(ys), max(xs), max(ys))


class Field:
    def __init__(self, name, type="String", domain=""):
        self.name, self.type, self.domain = name, type, domain


class Domain:
    def __init__(self, name, coded_values):
        self.name, self.domainType, self.codedValues = name, "CodedValue", coded_values


def make_fake_arcpy():
    arcpy = types.ModuleType("arcpy")
    arcpy.Parameter = Parameter
    arcpy.ExecuteError = ExecuteError
    arcpy.messages = []
    arcpy.datasets = {}  # path -> {"shapeType", "fields", "rows": [(oid, geometry, attrs)], "workspace"}
    arcpy.tables = {}  # path -> {"fields": [...], "rows": [...]}
    arcpy.domains = {}  # workspace -> [Domain]
    arcpy.geometry_problems = {}  # dataset path -> [(oid, problem)]

    arcpy.AddMessage = lambda m: arcpy.messages.append(("info", m))
    arcpy.AddWarning = lambda m: arcpy.messages.append(("warning", m))
    arcpy.AddError = lambda m: arcpy.messages.append(("error", m))
    arcpy.SpatialReference = lambda wkid: types.SimpleNamespace(factoryCode=wkid)
    arcpy.Exists = lambda path: path in arcpy.tables
    arcpy.ValidateTableName = lambda name, *_: name

    def ListFields(path):
        return [Field("OBJECTID", "OID"), Field("Shape", "Geometry"), *arcpy.datasets[path]["fields"]]

    def Describe(path):
        if path in arcpy.datasets:
            return types.SimpleNamespace(
                shapeType=arcpy.datasets[path]["shapeType"],
                catalogPath=path,
                baseName=os.path.basename(path),
                dataType="FeatureClass",
            )
        return types.SimpleNamespace(dataType="Workspace", catalogPath=path)

    arcpy.ListFields = ListFields
    arcpy.Describe = Describe

    def CheckGeometry(in_features, out_table, method):
        assert method == "OGC"
        arcpy.tables[out_table] = {
            "fields": ["FEATURE_ID", "PROBLEM"],
            "rows": [dict(FEATURE_ID=o, PROBLEM=p) for o, p in arcpy.geometry_problems.get(in_features, [])],
        }

    def CreateTable(folder, name):
        arcpy.tables[os.path.join(folder, name)] = {"fields": [], "rows": []}

    def AddField(table, name, field_type, field_length=None):
        arcpy.tables[table]["fields"].append(name)

    arcpy.management = types.SimpleNamespace(
        CheckGeometry=CheckGeometry,
        Delete=lambda path: arcpy.tables.pop(path, None),
        CreateTable=CreateTable,
        AddField=AddField,
    )

    @contextmanager
    def SearchCursor(path, fields):
        if path in arcpy.datasets:

            def row(oid, geometry, attrs):
                lookup = {"OID@": oid, "SHAPE@": geometry, **attrs}
                return tuple(lookup.get(f) for f in fields)

            yield iter([row(*r) for r in arcpy.datasets[path]["rows"]])
        else:
            yield iter([tuple(r[f] for f in fields) for r in arcpy.tables[path]["rows"]])

    class InsertCursor:
        def __init__(self, path, fields):
            self.path, self.fields = path, fields

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def insertRow(self, values):
            arcpy.tables[self.path]["rows"].append(dict(zip(self.fields, values)))

    arcpy.da = types.SimpleNamespace(
        SearchCursor=SearchCursor,
        InsertCursor=InsertCursor,
        ListDomains=lambda workspace: arcpy.domains.get(workspace, []),
    )
    return arcpy

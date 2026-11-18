"""Rule-based data quality checks for GIS feature data.

The rules engine has no GIS dependencies. Two adapters feed it records:
``gisqa.arcpy_adapter`` (ArcGIS Pro) and ``gisqa.geopandas_adapter``
(open source, no license needed).
"""

from .config import ConfigError, QAConfig, load_config
from .engine import QAResult, run_checks
from .records import GeometryInfo, Issue, Record, Severity

__all__ = [
    "ConfigError",
    "GeometryInfo",
    "Issue",
    "QAConfig",
    "QAResult",
    "Record",
    "Severity",
    "load_config",
    "run_checks",
]

__version__ = "1.0.0"

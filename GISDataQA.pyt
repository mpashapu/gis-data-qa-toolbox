# -*- coding: utf-8 -*-
"""ArcGIS Pro Python toolbox: rule-based data quality checks.

Add to a project with Catalog > Toolboxes > Add Toolbox, pointing at this
file. The gisqa package must sit next to it (as in this repository).
"""

import os
import sys

import arcpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gisqa.arcpy_adapter import (  # noqa: E402
    coded_domain_values,
    geometry_errors,
    list_fields,
    read_records,
    write_issue_table,
)
from gisqa.config import ConfigError, QAConfig, load_config  # noqa: E402
from gisqa.engine import run_checks  # noqa: E402
from gisqa.report import write_reports  # noqa: E402

# Parameter positions, so execute() and updateMessages() stay in sync
IN_FEATURES, RULES_FILE, KEY_FIELD, REQUIRED_FIELDS, MIN_AREA, USE_DOMAINS, REPORT_FOLDER, ISSUES_TABLE, ERROR_COUNT = (
    range(9)
)


class Toolbox:
    def __init__(self):
        self.label = "GIS Data QA"
        self.alias = "gisqa"
        self.tools = [CheckDataQuality]


class CheckDataQuality:
    def __init__(self):
        self.label = "Check Data Quality"
        self.description = (
            "Checks features against data quality rules (geometry validity, slivers, extent, duplicates, "
            "required fields, formats, coded domains, ranges and dates) and writes CSV, JSON and HTML reports."
        )

    def getParameterInfo(self):
        in_features = arcpy.Parameter(
            displayName="Input Features",
            name="in_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )

        rules_file = arcpy.Parameter(
            displayName="Rules File (JSON)",
            name="rules_file",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        rules_file.filter.list = ["json"]

        key_field = arcpy.Parameter(
            displayName="Unique ID Field",
            name="key_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input",
        )
        key_field.parameterDependencies = [in_features.name]

        required_fields = arcpy.Parameter(
            displayName="Required Fields",
            name="required_fields",
            datatype="Field",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        required_fields.parameterDependencies = [in_features.name]

        min_area = arcpy.Parameter(
            displayName="Minimum Polygon Area (square meters)",
            name="min_area",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )

        use_domains = arcpy.Parameter(
            displayName="Check Coded Value Domains",
            name="use_domains",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        use_domains.value = True

        report_folder = arcpy.Parameter(
            displayName="Report Folder",
            name="report_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )

        issues_table = arcpy.Parameter(
            displayName="Issues Table (optional)",
            name="issues_table",
            datatype="DETable",
            parameterType="Optional",
            direction="Output",
        )

        error_count = arcpy.Parameter(
            displayName="Error Count",
            name="error_count",
            datatype="GPLong",
            parameterType="Derived",
            direction="Output",
        )

        return [
            in_features,
            rules_file,
            key_field,
            required_fields,
            min_area,
            use_domains,
            report_folder,
            issues_table,
            error_count,
        ]

    def isLicensed(self):
        return True  # Basic license is enough

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        rules = parameters[RULES_FILE]
        if rules.altered and rules.valueAsText:
            try:
                load_config(rules.valueAsText)
            except ConfigError as error:
                rules.setErrorMessage(str(error))
        min_area = parameters[MIN_AREA]
        if min_area.value is not None and min_area.value <= 0:
            min_area.setErrorMessage("Minimum area must be greater than 0.")
        return

    def execute(self, parameters, messages):
        in_features = parameters[IN_FEATURES].valueAsText
        config = build_config(parameters)

        if parameters[USE_DOMAINS].value:
            domains = coded_domain_values(in_features)
            if domains:
                arcpy.AddMessage(f"Checking coded value domains on: {', '.join(domains)}")
                config = config.with_overrides(allowed_values=domains)

        validity = {}
        if config.check_geometry_validity:
            arcpy.AddMessage("Running Check Geometry (OGC)...")
            validity = geometry_errors(in_features)

        arcpy.AddMessage("Checking features...")
        try:
            result = run_checks(
                read_records(in_features, config.fields_used(), validity),
                config,
                available_fields=list_fields(in_features),
            )
        except ConfigError as error:
            arcpy.AddError(str(error))
            raise arcpy.ExecuteError(str(error)) from error

        basename = arcpy.ValidateTableName(arcpy.Describe(in_features).baseName) + "_qa"
        paths = write_reports(result, parameters[REPORT_FOLDER].valueAsText, basename)
        if parameters[ISSUES_TABLE].valueAsText:
            write_issue_table(result.issues, parameters[ISSUES_TABLE].valueAsText)

        summary = result.summary()
        arcpy.AddMessage(
            f"{summary['records_checked']} features checked, {summary['records_with_issues']} with issues "
            f"({result.error_count} errors, {result.warning_count} warnings)."
        )
        for rule, count in result.counts_by_rule().items():
            arcpy.AddMessage(f"  {rule}: {count}")
        arcpy.AddMessage(f"Report: {paths['html']}")
        if result.error_count:
            arcpy.AddWarning(f"{result.error_count} errors found. See the report for details.")

        parameters[ERROR_COUNT].value = result.error_count
        return

    def postExecute(self, parameters):
        return


def build_config(parameters) -> QAConfig:
    """Rules file first, then tool parameters on top."""
    rules_path = parameters[RULES_FILE].valueAsText
    config = load_config(rules_path) if rules_path else QAConfig(name="Data quality check")
    required = parameters[REQUIRED_FIELDS].valueAsText
    return config.with_overrides(
        key_field=parameters[KEY_FIELD].valueAsText,
        required_fields=required.split(";") if required else None,
        min_area_m2=parameters[MIN_AREA].value,
    )

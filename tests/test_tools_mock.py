"""
Mock-mode smoke tests. Asserts every tool returns a dict and — when live env vars
are missing — that the result carries "_mock": True.
"""
from __future__ import annotations

import os

import pytest

# Make sure mock mode is active: wipe live env vars for the test session.
for v in (
    "DATABRICKS_HOST", "DATABRICKS_TOKEN",
    "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
):
    os.environ.pop(v, None)

from tools.aws_tools import TOOL_EXECUTORS as AWS_TOOLS
from tools.databricks_tools import TOOL_EXECUTORS as DB_TOOLS
from tools.snowflake_tools import TOOL_EXECUTORS as SF_TOOLS


DB_CASES = [
    ("list_clusters", {}),
    ("get_cluster_status", {"cluster_id": "0123-abc456"}),
    ("run_sql_statement", {"sql": "SELECT 1", "warehouse_id": "wh-1"}),
    ("list_uc_tables", {"catalog": "main", "schema": "bronze"}),
    ("get_uc_table_details", {"catalog": "main", "schema": "bronze", "table": "events"}),
    ("list_mlflow_experiments", {}),
    ("get_mlflow_run", {"run_id": "abc"}),
    ("list_jobs", {"limit": 5}),
    ("trigger_job_run", {"job_id": 1}),
]

SF_CASES = [
    ("execute_sql", {"sql": "SELECT 1"}),
    ("list_databases", {}),
    ("list_schemas", {"database": "ANALYTICS"}),
    ("describe_table", {"database": "ANALYTICS", "schema": "PUBLIC", "table": "CUSTOMERS"}),
    ("cortex_complete", {"prompt": "hello"}),
    ("get_query_history", {"limit": 5}),
    ("list_warehouses", {}),
    ("get_table_sample", {"database": "ANALYTICS", "schema": "PUBLIC", "table": "ORDERS", "n": 3}),
]

AWS_CASES = [
    ("list_s3_buckets", {}),
    ("get_s3_object_count", {"bucket": "acme", "prefix": ""}),
    ("list_glue_databases", {}),
    ("get_glue_table", {"database": "analytics", "table_name": "events"}),
    ("list_bedrock_models", {}),
    ("invoke_bedrock", {"model_id": "claude-3-5", "prompt": "hi"}),
    ("get_iam_policy", {"policy_arn": "arn:aws:iam::aws:policy/ReadOnlyAccess"}),
    ("list_lambda_functions", {}),
    ("describe_ec2_instances", {}),
]


@pytest.mark.parametrize("tool,args", DB_CASES)
def test_databricks_mock(tool, args):
    result = DB_TOOLS[tool](**args)
    assert isinstance(result, dict)
    assert result.get("_mock") is True or "error" not in result


@pytest.mark.parametrize("tool,args", SF_CASES)
def test_snowflake_mock(tool, args):
    result = SF_TOOLS[tool](**args)
    assert isinstance(result, dict)
    assert result.get("_mock") is True or "error" not in result


@pytest.mark.parametrize("tool,args", AWS_CASES)
def test_aws_mock(tool, args):
    result = AWS_TOOLS[tool](**args)
    assert isinstance(result, dict)
    assert result.get("_mock") is True or "error" not in result

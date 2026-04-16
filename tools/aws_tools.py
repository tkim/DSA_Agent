"""
AWS tool executors + Ollama tool schemas.

When AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY are not set, every tool returns a mock.
"""
from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from tools._common import env_ready, run_with_timeout, tool_wrapper

load_dotenv()

_LIVE_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


def _client(service: str, region: str | None = None):
    import boto3
    return boto3.client(service, region_name=region or os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


# --- list_s3_buckets ---------------------------------------------------------
@tool_wrapper("list_s3_buckets")
def list_s3_buckets() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "buckets": [
                {"name": "acme-raw-us-east-1",       "creation_date": "2024-01-01T00:00:00Z", "region": "us-east-1"},
                {"name": "acme-processed-us-east-1", "creation_date": "2024-01-01T00:00:00Z", "region": "us-east-1"},
            ],
        }

    def _live():
        s3 = _client("s3")
        buckets = s3.list_buckets().get("Buckets", [])
        out = []
        for b in buckets:
            try:
                loc = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint") or "us-east-1"
            except Exception:
                loc = "unknown"
            out.append({"name": b["Name"], "creation_date": b["CreationDate"].isoformat(), "region": loc})
        return out

    return {"buckets": run_with_timeout(_live)}


# --- get_s3_object_count -----------------------------------------------------
@tool_wrapper("get_s3_object_count")
def get_s3_object_count(bucket: str, prefix: str = "") -> dict:
    if not env_ready(*_LIVE_ENV):
        return {"_mock": True, "object_count": 12345, "total_size_bytes": 4_567_890_123,
                "bucket": bucket, "prefix": prefix}

    def _live():
        s3 = _client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        count = 0
        size = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                count += 1
                size += obj.get("Size", 0)
        return {"object_count": count, "total_size_bytes": size, "bucket": bucket, "prefix": prefix}

    return run_with_timeout(_live)


# --- list_glue_databases -----------------------------------------------------
@tool_wrapper("list_glue_databases")
def list_glue_databases() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "databases": [
                {"name": "analytics_bronze", "description": "Raw ingested data"},
                {"name": "analytics_silver", "description": "Cleaned data"},
            ],
        }

    def _live():
        glue = _client("glue")
        resp = glue.get_databases()
        return [{"name": d["Name"], "description": d.get("Description", "")} for d in resp.get("DatabaseList", [])]

    return {"databases": run_with_timeout(_live)}


# --- get_glue_table ----------------------------------------------------------
@tool_wrapper("get_glue_table")
def get_glue_table(database: str, table_name: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "name": table_name,
            "columns": [{"name": "id", "type": "bigint"}, {"name": "ts", "type": "timestamp"}],
            "location": f"s3://acme-raw-us-east-1/{database}/{table_name}/",
            "row_count": 2_500_000,
        }

    def _live():
        glue = _client("glue")
        t = glue.get_table(DatabaseName=database, Name=table_name)["Table"]
        cols = t.get("StorageDescriptor", {}).get("Columns", [])
        return {
            "name": t["Name"],
            "columns": [{"name": c["Name"], "type": c["Type"]} for c in cols],
            "location": t.get("StorageDescriptor", {}).get("Location", ""),
            "row_count": int(t.get("Parameters", {}).get("recordCount", 0) or 0),
        }

    return run_with_timeout(_live)


# --- list_bedrock_models -----------------------------------------------------
@tool_wrapper("list_bedrock_models")
def list_bedrock_models() -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "models": [
                {"model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                 "provider": "anthropic", "modalities": ["TEXT"]},
                {"model_id": "amazon.titan-embed-text-v2:0",
                 "provider": "amazon", "modalities": ["TEXT"]},
            ],
        }

    def _live():
        br = _client("bedrock")
        models = br.list_foundation_models().get("modelSummaries", [])
        return [
            {"model_id": m["modelId"], "provider": m.get("providerName", ""),
             "modalities": m.get("outputModalities", [])}
            for m in models
        ]

    return {"models": run_with_timeout(_live)}


# --- invoke_bedrock ----------------------------------------------------------
@tool_wrapper("invoke_bedrock")
def invoke_bedrock(model_id: str, prompt: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {"_mock": True, "response": f"[mock Bedrock {model_id}] {prompt[:60]}...",
                "input_tokens": len(prompt.split())}

    def _live():
        br = _client("bedrock-runtime")
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = br.invoke_model(modelId=model_id, body=body)
        payload = json.loads(resp["body"].read())
        text = ""
        for block in payload.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        usage = payload.get("usage", {})
        return {"response": text, "input_tokens": usage.get("input_tokens", 0)}

    return run_with_timeout(_live)


# --- get_iam_policy ----------------------------------------------------------
@tool_wrapper("get_iam_policy")
def get_iam_policy(policy_arn: str) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "policy_name": policy_arn.split("/")[-1],
            "document": {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "*"}
                ],
            },
        }

    def _live():
        iam = _client("iam")
        p = iam.get_policy(PolicyArn=policy_arn)["Policy"]
        v = iam.get_policy_version(PolicyArn=policy_arn, VersionId=p["DefaultVersionId"])["PolicyVersion"]
        return {"policy_name": p["PolicyName"], "document": v["Document"]}

    return run_with_timeout(_live)


# --- list_lambda_functions ---------------------------------------------------
@tool_wrapper("list_lambda_functions")
def list_lambda_functions(region: str | None = None) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "functions": [
                {"name": "etl-trigger",    "runtime": "python3.12", "memory_mb": 512},
                {"name": "api-handler",    "runtime": "nodejs20.x", "memory_mb": 1024},
            ],
        }

    def _live():
        lam = _client("lambda", region=region)
        fns = lam.list_functions().get("Functions", [])
        return [
            {"name": f["FunctionName"], "runtime": f.get("Runtime", ""), "memory_mb": int(f.get("MemorySize", 0))}
            for f in fns
        ]

    return {"functions": run_with_timeout(_live)}


# --- describe_ec2_instances --------------------------------------------------
@tool_wrapper("describe_ec2_instances")
def describe_ec2_instances(filters: list | None = None) -> dict:
    if not env_ready(*_LIVE_ENV):
        return {
            "_mock": True,
            "instances": [
                {"instance_id": "i-0abc123", "state": "running", "type": "t3.medium", "az": "us-east-1a"},
                {"instance_id": "i-0def456", "state": "stopped", "type": "m5.large",  "az": "us-east-1b"},
            ],
        }

    def _live():
        ec2 = _client("ec2")
        kwargs = {"Filters": filters} if filters else {}
        res = ec2.describe_instances(**kwargs).get("Reservations", [])
        out = []
        for r in res:
            for inst in r.get("Instances", []):
                out.append({
                    "instance_id": inst["InstanceId"],
                    "state": inst["State"]["Name"],
                    "type": inst["InstanceType"],
                    "az": inst["Placement"]["AvailabilityZone"],
                })
        return out

    return {"instances": run_with_timeout(_live)}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_s3_buckets",
            "description": "List all S3 buckets and their regions",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_s3_object_count",
            "description": "Count objects and total bytes under an S3 bucket + prefix",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket": {"type": "string"},
                    "prefix": {"type": "string", "default": ""},
                },
                "required": ["bucket"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_glue_databases",
            "description": "List Glue Data Catalog databases",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_glue_table",
            "description": "Get a Glue Data Catalog table definition",
            "parameters": {
                "type": "object",
                "properties": {
                    "database": {"type": "string"},
                    "table_name": {"type": "string"},
                },
                "required": ["database", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bedrock_models",
            "description": "List Amazon Bedrock foundation models",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invoke_bedrock",
            "description": "Invoke a Bedrock model with a prompt",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["model_id", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_iam_policy",
            "description": "Get an IAM policy document by ARN",
            "parameters": {
                "type": "object",
                "properties": {"policy_arn": {"type": "string"}},
                "required": ["policy_arn"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_lambda_functions",
            "description": "List Lambda functions in a region",
            "parameters": {
                "type": "object",
                "properties": {"region": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_ec2_instances",
            "description": "Describe EC2 instances, optionally filtered",
            "parameters": {
                "type": "object",
                "properties": {"filters": {"type": "array", "items": {"type": "object"}}},
                "required": [],
            },
        },
    },
]


TOOL_EXECUTORS = {
    "list_s3_buckets": list_s3_buckets,
    "get_s3_object_count": get_s3_object_count,
    "list_glue_databases": list_glue_databases,
    "get_glue_table": get_glue_table,
    "list_bedrock_models": list_bedrock_models,
    "invoke_bedrock": invoke_bedrock,
    "get_iam_policy": get_iam_policy,
    "list_lambda_functions": list_lambda_functions,
    "describe_ec2_instances": describe_ec2_instances,
}

# fetch_docs.ps1 — one-shot bootstrap of the full RAG corpus for all three
# platforms, then build the ChromaDB collections.
#
# This is a thin front-end over rag/refresher.py, which is the single source of
# truth for which docs we track and is ALSO what runs automatically on every
# `python cli.py` launch to keep the corpus current (SHA-tracked, incremental).
# Running this script does a full forced fetch + re-ingest — use it for first-
# time setup or to rebuild everything from scratch.
#
#   Databricks : delta-io/delta docs (docs/src/content/docs/*.mdx)
#   Snowflake  : connector/snowpark READMEs + sfquickstarts guides
#   AWS        : botocore service definitions + amazon-s3/glue user guides,
#                PLUS boto3 SDK client references (generated below)

$ErrorActionPreference = "Stop"

$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

New-Item -ItemType Directory -Force -Path "rag\docs\databricks","rag\docs\snowflake","rag\docs\aws" | Out-Null

# --- AWS: boto3 SDK client references (pydoc) -------------------------------
# Generated locally from the installed boto3; the refresher below adds the
# SHA-tracked botocore + awsdocs sources on top. Both live in rag/docs/aws and
# are embedded together, so this must run BEFORE the refresher's aws re-ingest.
Write-Host "Generating AWS boto3 SDK reference docs..." -ForegroundColor Cyan
& $py -c @"
import boto3, pydoc, os
os.makedirs('rag/docs/aws', exist_ok=True)
for svc in ['s3','glue','bedrock-runtime','iam','lambda','ec2']:
    try:
        c = boto3.client(svc, region_name='us-east-1')
        doc = pydoc.render_doc(type(c), renderer=pydoc.plaintext)
        path = f'rag/docs/aws/boto3_{svc.replace(\"-\",\"_\")}.txt'
        open(path,'w',encoding='utf-8').write(doc)
        print(f'  OK {path}')
    except Exception as e:
        print(f'  SKIP {svc}: {e}')
"@

# --- All tracked sources + build the store ---------------------------------
# --force re-fetches every source regardless of stored SHA and re-ingests all
# three collections (the aws pass picks up the boto3 files generated above).
Write-Host "`nFetching tracked docs and rebuilding ChromaDB (this can take a few minutes)..." -ForegroundColor Cyan
& $py -m rag.refresher --force

Write-Host "`nDone. All three collections are current. Launch with: $py cli.py" -ForegroundColor Green

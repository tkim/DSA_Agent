$dirs = "rag\docs\databricks","rag\docs\snowflake","rag\docs\aws"
$dirs | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

# Delta Lake moved their docs into an Astro site (docs/src/content/docs/*.mdx).
# The old raw paths (/docs/source/*.md) are gone. These are the current files.
$deltaBase = "https://raw.githubusercontent.com/delta-io/delta/master/docs/src/content/docs"

Write-Host "Fetching Databricks/Delta Lake docs..." -ForegroundColor Cyan
@(
    @{ Uri = "$deltaBase/quick-start.mdx";            Out = "rag\docs\databricks\delta_quick_start.mdx" }
    @{ Uri = "$deltaBase/best-practices.mdx";         Out = "rag\docs\databricks\delta_best_practices.mdx" }
    @{ Uri = "$deltaBase/delta-batch.mdx";            Out = "rag\docs\databricks\delta_batch.mdx" }
    @{ Uri = "$deltaBase/concurrency-control.mdx";    Out = "rag\docs\databricks\delta_concurrency.mdx" }
    @{ Uri = "$deltaBase/delta-update.mdx";           Out = "rag\docs\databricks\delta_update.mdx" }
    @{ Uri = "$deltaBase/delta-faq.mdx";              Out = "rag\docs\databricks\delta_faq.mdx" }
    @{ Uri = "$deltaBase/versioning.mdx";             Out = "rag\docs\databricks\delta_versioning.mdx" }
    @{ Uri = "$deltaBase/delta-clustering.mdx";       Out = "rag\docs\databricks\delta_clustering.mdx" }
) | ForEach-Object {
    try   { Invoke-WebRequest -Uri $_.Uri -OutFile $_.Out -EA Stop; Write-Host "  OK $($_.Out)" }
    catch { Write-Warning "  SKIP $($_.Out): $($_.Exception.Message)" }
}

Write-Host "`nFetching Snowflake docs..." -ForegroundColor Cyan
@(
    @{ Uri = "https://raw.githubusercontent.com/snowflakedb/snowflake-connector-python/main/README.md"
       Out = "rag\docs\snowflake\connector_python_readme.md" }
    @{ Uri = "https://raw.githubusercontent.com/snowflakedb/snowpark-python/main/README.md"
       Out = "rag\docs\snowflake\snowpark_python_readme.md" }
    @{ Uri = "https://raw.githubusercontent.com/Snowflake-Labs/sfquickstarts/master/site/sfguides/src/getting-started-snowflake-python-api/getting-started-snowflake-python-api.md"
       Out = "rag\docs\snowflake\getting_started_python_api.md" }
    @{ Uri = "https://raw.githubusercontent.com/Snowflake-Labs/sfquickstarts/master/site/sfguides/src/data-engineering-with-snowpark-python-intro/data-engineering-with-snowpark-python-intro.md"
       Out = "rag\docs\snowflake\data_engineering_snowpark.md" }
    @{ Uri = "https://raw.githubusercontent.com/Snowflake-Labs/sfquickstarts/master/site/sfguides/src/getting-started-iceberg-tables/getting-started-iceberg-tables.md"
       Out = "rag\docs\snowflake\iceberg_tables.md" }
) | ForEach-Object {
    try   { Invoke-WebRequest -Uri $_.Uri -OutFile $_.Out -EA Stop; Write-Host "  OK $($_.Out)" }
    catch { Write-Warning "  SKIP $($_.Out): $($_.Exception.Message)" }
}

Write-Host "`nGenerating AWS Boto3 reference docs..." -ForegroundColor Cyan
# Use the project venv python so boto3 resolves correctly.
$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
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

Write-Host "`nDone. Run: .\.venv\Scripts\python.exe -m rag.ingestor --all" -ForegroundColor Green

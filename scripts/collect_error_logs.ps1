param()

$outDir = Join-Path -Path (Get-Location) -ChildPath "logs"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

Write-Host "Collecting last 500 lines of odoo logs..."
docker compose logs --tail=500 odoo | Out-File -Encoding utf8 (Join-Path $outDir 'odoo.log')
Write-Host "Saved odoo logs to $outDir\odoo.log"

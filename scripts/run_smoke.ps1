param()

# Load .env file (search project root)
$envFile = Join-Path -Path $PSScriptRoot -ChildPath "..\.env"
if (-not (Test-Path $envFile)) { $envFile = Join-Path -Path (Get-Location) -ChildPath ".env" }
if (-not (Test-Path $envFile)) { Write-Error ".env not found. Create .env in project root."; exit 1 }

Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    $pair = $_ -split '=',2
    if ($pair.Length -eq 2) {
        $name = $pair[0].Trim()
        $value = $pair[1].Trim()
        if ($value.Length -ge 2) {
            if (($value.StartsWith("'") -and $value.EndsWith("'")) -or ($value.StartsWith('"') -and $value.EndsWith('"'))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        Set-Item -Path Env:$name -Value $value
    }
}

Write-Host "Running smoke upgrade for DB $env:ODOO_DB ..."
$odooCmd = "odoo -d $env:ODOO_DB -u dms_core --stop-after-init --db_host=$env:ODOO_DB_HOST --db_port=$env:ODOO_DB_PORT --db_user=$env:ODOO_DB_USER --db_password=$env:ODOO_DB_PASSWORD"

docker compose exec -T odoo bash -lc $odooCmd

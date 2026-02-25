#!/usr/bin/env pwsh
Param(
  [int]$ODOO_PORT = 8069,
  [int]$TIMEOUT = 180
)

$end = (Get-Date).AddSeconds($TIMEOUT)
$url = "http://localhost:$ODOO_PORT/web/login"

while ((Get-Date) -lt $end) {
  try {
    $resp = Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 5 -ErrorAction Stop
    $status = $resp.StatusCode
  } catch {
    $status = 0
  }
  if ($status -eq 200 -or $status -eq 302 -or $status -eq 303) {
    Write-Output "OK: received $status from $url"
    exit 0
  }
  Start-Sleep -Seconds 2
}

Write-Error "ERROR: Odoo did not become ready within ${TIMEOUT}s"
exit 1

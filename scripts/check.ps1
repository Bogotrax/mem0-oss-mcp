<#
.SYNOPSIS
  Health-Check + optionaler MCP-Smoke-Test (add_memory + search_memories).

.EXAMPLE
  .\check.ps1
  .\check.ps1 -Token mcp_xxx...
#>
param([string]$Token = "")

Write-Host "== Health ==" -ForegroundColor Cyan
try {
    Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 15 | ConvertTo-Json
}
catch {
    Write-Warning "Health-Endpoint nicht erreichbar: $($_.Exception.Message)"
    exit 1
}

if ($Token) {
    Write-Host "`n== MCP Smoke-Test ==" -ForegroundColor Cyan
    $compose = Join-Path $PSScriptRoot "..\docker-compose.yml"
    docker compose -f $compose exec mem0-mcp python smoke_test.py --token $Token
}
else {
    Write-Host "(MCP-Smoke-Test uebersprungen - mit -Token <mcp_...> ausfuehren)"
}
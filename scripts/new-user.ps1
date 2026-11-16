<#
.SYNOPSIS
  Legt einen Invite-Code für einen neuen Nutzer an (oder mit -DirectToken direkt ein Token).

.EXAMPLE
  .\new-user.ps1 -UserId max -Name "Max"
  .\new-user.ps1 -UserId bojan -DirectToken
#>
param(
    [Parameter(Mandatory = $true)][string]$UserId,
    [string]$Name = "",
    [switch]$DirectToken
)

$compose = Join-Path $PSScriptRoot "..\docker-compose.yml"

if ($DirectToken) {
    docker compose -f $compose exec mem0-mcp python manage.py token --user-id $UserId --name $Name
}
else {
    docker compose -f $compose exec mem0-mcp python manage.py invite --user-id $UserId --name $Name
    Write-Host ""
    Write-Host "Kollege registriert sich einmalig unter http://<server>:8000/register mit dem Code." -ForegroundColor Cyan
}
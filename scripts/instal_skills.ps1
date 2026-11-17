$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

Write-Host "Installing SimAssist Codex skills..."

npx skills@latest add multica-ai/andrej-karpathy-skills -a codex -y
if ($LASTEXITCODE -ne 0) { throw "Karpathy skills installation failed" }

npx skills@latest add mattpocock/skills -a codex -y
if ($LASTEXITCODE -ne 0) { throw "Matt Pocock skills installation failed" }

npx skills@latest add nextlevelbuilder/ui-ux-pro-max-skill -a codex -y
if ($LASTEXITCODE -ne 0) { throw "UI/UX skills installation failed" }

Write-Host "All skills installed successfully!"
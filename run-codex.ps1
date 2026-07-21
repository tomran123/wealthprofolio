# Launch OpenAI Codex in this workspace using ChatGPT OAuth.
#
# Usage:   .\run-codex.ps1
#          .\run-codex.ps1 "create a portfolio dashboard"

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'Codex CLI is not installed. Install it with: npm install -g @openai/codex'
}

Write-Host 'OpenAI Codex -> ChatGPT (latest available model)' -ForegroundColor Green
& codex -C $root `
    -c 'model_provider="openai"' `
    -c 'forced_login_method="chatgpt"' `
    @args

exit $LASTEXITCODE
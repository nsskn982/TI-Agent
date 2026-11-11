<#
.SYNOPSIS
    One-shot Windows setup for TI Agent: Python venv + Ollama.
.EXAMPLE
    .\scripts\setup.ps1
    .\scripts\setup.ps1 -OllamaModel qwen2.5:3b
    .\scripts\setup.ps1 -SkipOllama
#>
[CmdletBinding()]
param(
    [string]$OllamaModel = "qwen2.5:7b",
    [switch]$SkipPython,
    [switch]$SkipOllama
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

if (-not $SkipPython) {
    Step "Python virtual environment"
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $py) { throw "Python 3.11+ not found on PATH." }
    $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ([version]$version -lt [version]"3.11") { throw "Python 3.11+ required, found $version." }

    if (-not (Test-Path ".venv")) { & python -m venv .venv }
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
    & $venvPy -m pip install --upgrade pip
    if (Test-Path "requirements.txt") {
        & $venvPy -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
    } else {
        Write-Warning "requirements.txt not found; skipping package install."
    }

    if ((Test-Path ".env.example") -and -not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example - fill in your keys." -ForegroundColor Yellow
    } elseif (Test-Path ".env") {
        Write-Host ".env already exists; left unchanged."
    }
}

if (-not $SkipOllama) {
    Step "Ollama settings (user environment)"
    $settings = [ordered]@{
        OLLAMA_FLASH_ATTENTION = "1"
        OLLAMA_KV_CACHE_TYPE   = "q8_0"
        OLLAMA_CONTEXT_LENGTH  = "8192"
        OLLAMA_KEEP_ALIVE      = "5m"
        OLLAMA_HOST            = "0.0.0.0:11434"
    }
    foreach ($k in $settings.Keys) {
        [Environment]::SetEnvironmentVariable($k, $settings[$k], "User")
        Set-Item -Path "Env:$k" -Value $settings[$k]
        Write-Host "  $k=$($settings[$k])"
    }

    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $ollama) {
        Write-Warning "Ollama not found. Install from https://ollama.com/download, then re-run with -SkipPython."
    } else {
        Step "Pulling $OllamaModel"
        & ollama pull $OllamaModel
        if ($LASTEXITCODE -ne 0) { throw "ollama pull failed." }
        Write-Host "Restart Ollama so the new settings apply, then check 'ollama ps' shows 100% GPU." -ForegroundColor Yellow
    }
}

Step "Done"

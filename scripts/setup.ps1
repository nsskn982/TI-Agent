<#
.SYNOPSIS
    One-shot Windows setup for TI Agent: Python venv + Ollama.
.EXAMPLE
    .\scripts\setup.ps1
    .\scripts\setup.ps1 -OllamaModel qwen3.5:2b
    .\scripts\setup.ps1 -SkipOllama
#>
[CmdletBinding()]
param(
    [string]$OllamaModel = "qwen3.5:4b",
    [switch]$SkipPython,
    [switch]$SkipOllama
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# PowerShell 5.1 turns any stderr output from native tools (e.g. Ollama's progress
# spinner) into a terminating error under "Stop". Run them under "Continue" and
# check the exit code instead.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Exe @Arguments 2>&1 | Where-Object { $_ -is [string] } | Out-Host } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

if (-not $SkipPython) {
    Step "Python virtual environment"
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $py) { throw "Python 3.11+ not found on PATH." }
    $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ([version]$version -lt [version]"3.11") { throw "Python 3.11+ required, found $version." }

    if (-not (Test-Path ".venv")) { & python -m venv .venv }
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
    Invoke-Native $venvPy @("-m", "pip", "install", "--upgrade", "pip") "pip upgrade"
    if (Test-Path "requirements.txt") {
        Invoke-Native $venvPy @("-m", "pip", "install", "-r", "requirements.txt") "pip install"
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
        OLLAMA_CONTEXT_LENGTH  = "16384"
        OLLAMA_KEEP_ALIVE      = "5m"
        OLLAMA_HOST            = "127.0.0.1:11434"   # local only; 0.0.0.0 would expose the model to the network
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
        Step "Pulling $OllamaModel and creating trading-analyst (text-only)"
        & (Join-Path $PSScriptRoot "create_model.ps1") -BaseModel $OllamaModel
        Write-Host "Restart Ollama so the new settings apply, then check 'ollama ps' shows 100% GPU." -ForegroundColor Yellow
    }
}

Step "Done"

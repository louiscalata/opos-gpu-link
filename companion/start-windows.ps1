# Plug-and-play launcher for Windows. Ctrl-C stops it and unloads the model.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$py = $env:OPOS_GPU_LINK_PYTHON
$pyArgs = @()
if (-not $py) {
  if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py"; $pyArgs = @("-3") }
  elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = "python" }
}
if (-not $py) {
  Write-Host "GPU Link needs Python 3.10 or newer."
  Write-Host "Install it with:  winget install Python.Python.3.12   (or from https://www.python.org/downloads/)"
  exit 1
}
# Show-day default: --offline (no downloads). --prefetch is the at-home way to fetch.
$extra = @()
$hasPrefetch = $false
$hasOffline = $false
foreach ($a in $args) {
  if ($a -eq "--prefetch") { $hasPrefetch = $true }
  if ($a -eq "--offline" -or $a -eq "--no-download") { $hasOffline = $true }
}
if (-not $hasPrefetch -and -not $hasOffline) { $extra = @("--offline") }
& $py @pyArgs -B gpu_link_autosetup.py @extra @args
exit $LASTEXITCODE

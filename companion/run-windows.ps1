# Start the approved headless PC companion. @args passes repeatable
# --extra-model entries through unchanged. No installs.
$python = if ($env:OPOS_GPU_LINK_PYTHON) { $env:OPOS_GPU_LINK_PYTHON } else { "python" }
& $python -B (Join-Path $PSScriptRoot "opos_gpu_link.py") --headless --always-allow @args
if ($LASTEXITCODE -is [int]) { exit $LASTEXITCODE }
exit 1

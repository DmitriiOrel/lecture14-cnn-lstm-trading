param(
    [string]$ProjectDir = "C:\projects\lecture14-cnn-lstm-trading-repo",
    [string]$PythonExe = "C:\projects\lecture14-cnn-lstm-trading-repo\.venv\Scripts\python.exe",
    [string]$AccountId = "",
    [string]$Token = $env:TINVEST_TOKEN,
    [string]$ForecastJson = "C:\projects\lecture14-cnn-lstm-trading-repo\reports\simple_lstm_etln_h3\latest_forecast_signal_etln_h3.json",
    [switch]$RunRealOrder,
    [switch]$NoScheduleGate,
    [ValidateSet("", "BUY", "SELL")]
    [string]$ForceAction = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Force UTF-8 in Windows console so Russian text from Python is readable
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = "utf-8"
cmd /c chcp 65001 > $null

$tradeScript = Join-Path $ProjectDir "trade_signal_executor_vtbr.py"
$logDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $PythonExe)) {
    throw "Python not found: $PythonExe"
}

if (-not (Test-Path $tradeScript)) {
    throw "Trade script not found: $tradeScript"
}

if (-not (Test-Path $ForecastJson)) {
    throw "Forecast JSON not found: $ForecastJson. Run notebook first and save latest forecast JSON."
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    throw "Token is empty. Pass -Token or set TINVEST_TOKEN."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "etln_trade_signal_$timestamp.log"

$args = @(
    $tradeScript,
    "--token", $Token,
    "--forecast-json", $ForecastJson
)

if (-not [string]::IsNullOrWhiteSpace($AccountId)) {
    $args += @("--account-id", $AccountId)
} else {
    Write-Host "AccountId not provided -> Python script will use the first available account for this token."
}

if ($RunRealOrder) {
    $args += "--run-real-order"
}

if ($NoScheduleGate) {
    $args += "--no-enforce-horizon-schedule"
}

if (-not [string]::IsNullOrWhiteSpace($ForceAction)) {
    $args += @("--force-action", $ForceAction)
}

Write-Host "Python       :" $PythonExe
Write-Host "Trade script :" $tradeScript
Write-Host "Forecast JSON:" $ForecastJson
Write-Host "RunRealOrder :" $RunRealOrder.IsPresent
Write-Host "NoScheduleGate:" $NoScheduleGate.IsPresent
Write-Host "ForceAction  :" $(if ($ForceAction) { $ForceAction } else { "<none>" })
Write-Host "Log file     :" $logPath

& $PythonExe @args 2>&1 | Tee-Object -FilePath $logPath
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    throw "trade_signal_executor_vtbr.py finished with exit code $exitCode"
}

Write-Host "Done. ExitCode=0"

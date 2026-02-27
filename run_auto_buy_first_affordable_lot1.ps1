param(
    [string]$ProjectDir = "C:\projects\lecture14-cnn-lstm-trading-repo",
    [string]$PythonExe = "C:\projects\lecture14-cnn-lstm-trading-repo\.venv\Scripts\python.exe",
    [string]$AccountId = "",
    [string]$Token = $env:TINVEST_TOKEN,
    [double]$MaxPrice = 50,
    [double]$FallbackMaxPrice = 100,
    [int]$BuyLots = 1,
    [string]$Tickers = "",
    [switch]$RunRealOrder
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = "utf-8"
cmd /c chcp 65001 > $null

$scriptPath = Join-Path $ProjectDir "auto_buy_first_affordable_lot1.py"
$logDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
if (-not (Test-Path $scriptPath)) { throw "Script not found: $scriptPath" }
if ([string]::IsNullOrWhiteSpace($Token)) { throw "Token is empty. Pass -Token or set TINVEST_TOKEN." }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "auto_buy_lot1_$timestamp.log"

$args = @(
    $scriptPath,
    "--token", $Token,
    "--max-price", "$MaxPrice",
    "--fallback-max-price", "$FallbackMaxPrice",
    "--buy-lots", "$BuyLots"
)

if (-not [string]::IsNullOrWhiteSpace($AccountId)) {
    $args += @("--account-id", $AccountId)
} else {
    Write-Host "AccountId not provided -> Python script will use the first available account for this token."
}

if (-not [string]::IsNullOrWhiteSpace($Tickers)) {
    $args += @("--tickers", $Tickers)
}

if ($RunRealOrder) {
    $args += "--run-real-order"
}

Write-Host "Python       :" $PythonExe
Write-Host "Script       :" $scriptPath
Write-Host "RunRealOrder :" $RunRealOrder.IsPresent
Write-Host "MaxPrice     :" $MaxPrice
Write-Host "FallbackMax  :" $FallbackMaxPrice
Write-Host "BuyLots      :" $BuyLots
Write-Host "Tickers      :" $(if ($Tickers) { $Tickers } else { "<auto from MOEX>" })
Write-Host "Log file     :" $logPath

& $PythonExe @args 2>&1 | Tee-Object -FilePath $logPath
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    throw "auto_buy_first_affordable_lot1.py finished with exit code $exitCode"
}

Write-Host "Done. ExitCode=0"

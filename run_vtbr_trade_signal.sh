#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXE="${PROJECT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON_EXE" ]]; then
  PYTHON_EXE="${PYTHON_EXE_OVERRIDE:-python3}"
fi

TRADE_SCRIPT="${PROJECT_DIR}/trade_signal_executor_vtbr.py"
FORECAST_JSON="${PROJECT_DIR}/reports/simple_lstm_etln_h3/latest_forecast_signal_etln_h3.json"
ACCOUNT_ID=""
TOKEN="${TINVEST_TOKEN:-}"
RUN_REAL_ORDER=0
NO_SCHEDULE_GATE=0
FORCE_ACTION=""

usage() {
  cat <<'EOF'
Usage: ./run_vtbr_trade_signal.sh [options]

Options:
  --token TOKEN
  --account-id ID
  --forecast-json PATH
  --python PATH
  --run-real-order
  --no-schedule-gate
  --force-action BUY|SELL
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2 ;;
    --account-id) ACCOUNT_ID="$2"; shift 2 ;;
    --forecast-json) FORECAST_JSON="$2"; shift 2 ;;
    --python) PYTHON_EXE="$2"; shift 2 ;;
    --run-real-order) RUN_REAL_ORDER=1; shift ;;
    --no-schedule-gate) NO_SCHEDULE_GATE=1; shift ;;
    --force-action)
      FORCE_ACTION="${2^^}"
      if [[ "$FORCE_ACTION" != "BUY" && "$FORCE_ACTION" != "SELL" ]]; then
        echo "Invalid --force-action: $FORCE_ACTION (expected BUY or SELL)" >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$TOKEN" ]]; then
  echo "Token is empty. Pass --token or export TINVEST_TOKEN." >&2
  exit 2
fi

if [[ ! -f "$TRADE_SCRIPT" ]]; then
  echo "Trade script not found: $TRADE_SCRIPT" >&2
  exit 2
fi

if [[ ! -f "$FORECAST_JSON" ]]; then
  echo "Forecast JSON not found: $FORECAST_JSON" >&2
  echo "Run the notebook first and export latest forecast JSON." >&2
  exit 2
fi

mkdir -p "${PROJECT_DIR}/logs"
LOG_PATH="${PROJECT_DIR}/logs/etln_trade_signal_$(date +%Y%m%d_%H%M%S).log"

ARGS=(
  "$TRADE_SCRIPT"
  "--token" "$TOKEN"
  "--forecast-json" "$FORECAST_JSON"
)

if [[ -n "$ACCOUNT_ID" ]]; then
  ARGS+=("--account-id" "$ACCOUNT_ID")
else
  echo "AccountId not provided -> Python script will use the first available account for this token."
fi

if [[ $RUN_REAL_ORDER -eq 1 ]]; then
  ARGS+=("--run-real-order")
fi

if [[ $NO_SCHEDULE_GATE -eq 1 ]]; then
  ARGS+=("--no-enforce-horizon-schedule")
fi

if [[ -n "$FORCE_ACTION" ]]; then
  ARGS+=("--force-action" "$FORCE_ACTION")
fi

echo "Python       : $PYTHON_EXE"
echo "Trade script : $TRADE_SCRIPT"
echo "Forecast JSON: $FORECAST_JSON"
echo "RunRealOrder : $RUN_REAL_ORDER"
echo "NoScheduleGate: $NO_SCHEDULE_GATE"
echo "ForceAction  : ${FORCE_ACTION:-<none>}"
echo "Log file     : $LOG_PATH"

"$PYTHON_EXE" "${ARGS[@]}" 2>&1 | tee "$LOG_PATH"
STATUS=${PIPESTATUS[0]}

if [[ $STATUS -ne 0 ]]; then
  echo "trade_signal_executor_vtbr.py finished with exit code $STATUS" >&2
  exit $STATUS
fi

echo "Done. ExitCode=0"

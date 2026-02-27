#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXE="${PROJECT_DIR}/venv/bin/python"
if [[ ! -x "$PYTHON_EXE" ]]; then
  PYTHON_EXE="${PYTHON_EXE_OVERRIDE:-python3}"
fi

SCRIPT_PATH="${PROJECT_DIR}/auto_buy_first_affordable_lot1.py"
ACCOUNT_ID=""
TOKEN="${TINVEST_TOKEN:-}"
MAX_PRICE="50"
FALLBACK_MAX_PRICE="100"
BUY_LOTS="1"
TICKERS=""
RUN_REAL_ORDER=0

usage() {
  cat <<'EOF'
Usage: ./run_auto_buy_first_affordable_lot1.sh [options]

Options:
  --token TOKEN
  --account-id ID
  --python PATH
  --max-price N
  --fallback-max-price N
  --buy-lots N
  --tickers T1,T2,T3
  --run-real-order
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2 ;;
    --account-id) ACCOUNT_ID="$2"; shift 2 ;;
    --python) PYTHON_EXE="$2"; shift 2 ;;
    --max-price) MAX_PRICE="$2"; shift 2 ;;
    --fallback-max-price) FALLBACK_MAX_PRICE="$2"; shift 2 ;;
    --buy-lots) BUY_LOTS="$2"; shift 2 ;;
    --tickers) TICKERS="$2"; shift 2 ;;
    --run-real-order) RUN_REAL_ORDER=1; shift ;;
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

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Script not found: $SCRIPT_PATH" >&2
  exit 2
fi

mkdir -p "${PROJECT_DIR}/logs"
LOG_PATH="${PROJECT_DIR}/logs/auto_buy_lot1_$(date +%Y%m%d_%H%M%S).log"

ARGS=(
  "$SCRIPT_PATH"
  "--token" "$TOKEN"
  "--max-price" "$MAX_PRICE"
  "--fallback-max-price" "$FALLBACK_MAX_PRICE"
  "--buy-lots" "$BUY_LOTS"
)

if [[ -n "$ACCOUNT_ID" ]]; then
  ARGS+=("--account-id" "$ACCOUNT_ID")
else
  echo "AccountId not provided -> Python script will use the first available account for this token."
fi

if [[ -n "$TICKERS" ]]; then
  ARGS+=("--tickers" "$TICKERS")
fi

if [[ $RUN_REAL_ORDER -eq 1 ]]; then
  ARGS+=("--run-real-order")
fi

echo "Python       : $PYTHON_EXE"
echo "Script       : $SCRIPT_PATH"
echo "RunRealOrder : $RUN_REAL_ORDER"
echo "MaxPrice     : $MAX_PRICE"
echo "FallbackMax  : $FALLBACK_MAX_PRICE"
echo "BuyLots      : $BUY_LOTS"
echo "Tickers      : ${TICKERS:-<auto from MOEX>}"
echo "Log file     : $LOG_PATH"

"$PYTHON_EXE" "${ARGS[@]}" 2>&1 | tee "$LOG_PATH"
STATUS=${PIPESTATUS[0]}

if [[ $STATUS -ne 0 ]]; then
  echo "auto_buy_first_affordable_lot1.py finished with exit code $STATUS" >&2
  exit $STATUS
fi

echo "Done. ExitCode=0"

import argparse
import os
import subprocess
import sys
from pathlib import Path


def configure_console_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Cross-platform launcher for trade_signal_executor_vtbr.py. "
            "Finds latest forecast JSON in Downloads/reports and runs strategy CLI."
        )
    )
    p.add_argument("--forecast-json", default="", help="Path to forecast JSON (optional)")
    p.add_argument("--token", default="", help="T-Invest token (optional, else env TINVEST_TOKEN)")
    p.add_argument("--account-id", default="", help="Real account id (optional)")
    p.add_argument("--run-real-order", action="store_true", help="Allow real order sending")
    p.add_argument("--force-action", choices=["BUY", "SELL"], default="", help="Force BUY/SELL for integration test")
    p.add_argument("--buy-lots", type=int, default=None, help="Lots to buy on BUY signal/force buy")
    p.add_argument("--no-schedule-gate", action="store_true", help="Disable horizon schedule gate")
    p.add_argument("--search-downloads-only", action="store_true", help="Search JSON only in Downloads")
    p.add_argument("--python-exe", default=sys.executable, help="Python executable to use")
    p.add_argument("--show-command", action="store_true", help="Print exact underlying command")
    return p.parse_args()


def candidate_dirs(repo_root: Path, downloads_only: bool) -> list[Path]:
    home = Path.home()
    dirs = []
    if not downloads_only:
        dirs.append(repo_root / "reports")
    for name in ("Downloads", "downloads", "Загрузки"):
        d = home / name
        if d.exists():
            dirs.append(d)
    # Keep order, remove duplicates
    out = []
    seen = set()
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen:
            out.append(d)
            seen.add(key)
    return out


def find_latest_forecast_json(repo_root: Path, downloads_only: bool) -> Path | None:
    found: list[Path] = []
    for base in candidate_dirs(repo_root, downloads_only):
        if not base.exists():
            continue
        try:
            found.extend(base.rglob("latest_forecast_signal_*.json"))
        except Exception:
            continue
    if not found:
        return None
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0]


def main() -> int:
    configure_console_utf8()
    args = parse_args()

    repo_root = Path(__file__).resolve().parent
    executor = repo_root / "trade_signal_executor_vtbr.py"
    if not executor.exists():
        print(f"Executor script not found: {executor}", file=sys.stderr)
        return 2

    if args.token:
        os.environ["TINVEST_TOKEN"] = args.token.strip()

    forecast_json: Path
    if args.forecast_json:
        forecast_json = Path(args.forecast_json).expanduser()
        if not forecast_json.is_absolute():
            forecast_json = (Path.cwd() / forecast_json).resolve()
        if not forecast_json.exists():
            print(f"Forecast JSON not found: {forecast_json}", file=sys.stderr)
            return 2
    else:
        auto = find_latest_forecast_json(repo_root, downloads_only=args.search_downloads_only)
        if auto is None:
            print(
                "No forecast JSON found. Put latest_forecast_signal_*.json in Downloads or repo/reports,\n"
                "or pass --forecast-json <path>.",
                file=sys.stderr,
            )
            return 2
        forecast_json = auto

    cmd = [
        str(Path(args.python_exe)),
        str(executor),
        "--forecast-json",
        str(forecast_json),
    ]
    if args.account_id:
        cmd.extend(["--account-id", args.account_id])
    if args.run_real_order:
        cmd.append("--run-real-order")
    if args.force_action:
        cmd.extend(["--force-action", args.force_action])
    if args.buy_lots is not None:
        cmd.extend(["--buy-lots", str(args.buy_lots)])
    if args.no_schedule_gate:
        cmd.append("--no-enforce-horizon-schedule")

    print("Python       :", Path(args.python_exe))
    print("Trade script :", executor)
    print("Forecast JSON:", forecast_json)
    print("RunRealOrder :", bool(args.run_real_order))
    print("ForceAction  :", args.force_action or "(none)")
    if args.account_id:
        print("AccountId    :", args.account_id)
    else:
        print("AccountId    : (not set, executor will use first available account)")
    if args.show_command:
        print("Command      :", " ".join(cmd))

    completed = subprocess.run(cmd, env=os.environ.copy())
    return int(completed.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())

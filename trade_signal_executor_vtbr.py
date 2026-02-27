import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

from tinkoff.invest import Client, OrderDirection, OrderType
from tinkoff.invest.exceptions import RequestError


DEFAULT_FIGI = "BBG00RM6M4T8"  # ETLN / Эталон Груп (MOEX)
DEFAULT_APP_NAME = "LSTM-ETLN-H3-CLI"
DEFAULT_OUTPUT_DIR = Path("reports/simple_lstm_etln_h3")


def configure_console_utf8() -> None:
    # Helps on Windows terminals to avoid garbled Cyrillic output.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def q_to_float(q) -> float:
    return float(q.units + q.nano / 1e9)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Исполнение торговой логики (BUY/HOLD/SELL) по консенсусу GB + LSTM "
            "на реальном счете T-Invest. По умолчанию dry-run."
        )
    )
    p.add_argument("--token", default=None, help="T-Invest token (или env TINVEST_TOKEN)")
    p.add_argument("--app-name", default=DEFAULT_APP_NAME)
    p.add_argument("--account-id", default="", help="ID реального счета (лучше указать явно)")
    p.add_argument("--figi", default=DEFAULT_FIGI)

    p.add_argument("--forecast-horizon", type=int, default=3)
    p.add_argument("--forecast-json", default="", help="Путь к JSON с прогнозом из ноутбука")
    p.add_argument("--current-price", type=float, default=None)
    p.add_argument("--gb-price", type=float, default=None, help="Прогноз GB на горизонт")
    p.add_argument("--lstm-price", type=float, default=None, help="Прогноз LSTM на горизонт")
    p.add_argument("--signal-date", default=None, help="Дата последней цены YYYY-MM-DD")
    p.add_argument("--forecast-date", default=None, help="Дата прогнозной точки YYYY-MM-DD (опционально)")

    p.add_argument("--buy-lots", type=int, default=1)
    p.add_argument(
        "--force-action",
        choices=["BUY", "SELL"],
        default="",
        help="Принудительное действие для теста интеграции (обходит консенсус и расписание)",
    )
    p.add_argument("--sell-all-on-down", action="store_true", default=True)
    p.add_argument(
        "--sell-one-lot-on-down",
        action="store_true",
        help="При сигнале вниз продавать только 1 лот (или buy-lots), а не всю позицию",
    )

    p.add_argument("--enforce-horizon-schedule", action="store_true", default=True)
    p.add_argument("--no-enforce-horizon-schedule", action="store_true")
    p.add_argument("--save-strategy-state", action="store_true", default=True)
    p.add_argument("--no-save-strategy-state", action="store_true")
    p.add_argument("--update-state-in-dry-run", action="store_true", default=False)
    p.add_argument("--state-path", default="")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    p.add_argument("--run-real-order", action="store_true", default=False)
    return p.parse_args()


def load_forecast_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_inputs(args: argparse.Namespace) -> dict:
    data: dict = {}

    if args.forecast_json:
        payload_path = Path(args.forecast_json)
        if not payload_path.exists():
            raise FileNotFoundError(f"forecast JSON not found: {payload_path}")
        data.update(load_forecast_payload(payload_path))

    # CLI overrides JSON if provided
    if args.current_price is not None:
        data["current_price"] = args.current_price
    if args.gb_price is not None:
        data["gb_horizon_price"] = args.gb_price
    if args.lstm_price is not None:
        data["lstm_horizon_price"] = args.lstm_price
    if args.signal_date is not None:
        data["signal_date"] = args.signal_date
    if args.forecast_date is not None:
        data["forecast_target_date"] = args.forecast_date
    if args.figi:
        data.setdefault("figi", args.figi)
    if args.forecast_horizon:
        data.setdefault("forecast_horizon", args.forecast_horizon)

    required = ["current_price", "gb_horizon_price", "lstm_horizon_price", "signal_date"]
    missing = [k for k in required if k not in data or data[k] in ("", None)]
    if missing:
        raise ValueError(
            "Не хватает входных значений. Укажите их через --forecast-json или параметры CLI. "
            f"Missing: {missing}"
        )

    return data


def main() -> int:
    configure_console_utf8()
    args = parse_args()

    token = args.token or os.environ.get("TINVEST_TOKEN")
    if not token:
        raise ValueError("Не указан token: передайте --token или задайте TINVEST_TOKEN")

    inputs = merge_inputs(args)

    figi = inputs.get("figi", args.figi)
    forecast_horizon = int(inputs.get("forecast_horizon", args.forecast_horizon))

    current_price = float(inputs["current_price"])
    gb_horizon_price = float(inputs["gb_horizon_price"])
    lstm_horizon_price = float(inputs["lstm_horizon_price"])

    force_action = (args.force_action or "").upper()
    force_mode_active = force_action in {"BUY", "SELL"}

    signal_date = pd.Timestamp(inputs["signal_date"]).normalize()
    if inputs.get("forecast_target_date"):
        forecast_target_date = pd.Timestamp(inputs["forecast_target_date"]).normalize()
    else:
        forecast_target_date = (signal_date + pd.offsets.BDay(forecast_horizon)).normalize()
    next_check_date_planned = (signal_date + pd.offsets.BDay(forecast_horizon)).normalize()

    consensus_up = (gb_horizon_price > current_price) and (lstm_horizon_price > current_price)
    consensus_down = (gb_horizon_price < current_price) and (lstm_horizon_price < current_price)

    sell_all_on_down = not args.sell_one_lot_on_down
    enforce_horizon_schedule = not args.no_enforce_horizon_schedule
    save_strategy_state = not args.no_save_strategy_state

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_path) if args.state_path else output_dir / f"strategy_state_etln_h{forecast_horizon}.json"

    strategy_state = {}
    if state_path.exists():
        try:
            strategy_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            print("Не удалось прочитать state-файл, продолжаем без него:", e)
            strategy_state = {}

    state_next_check_date = None
    if strategy_state.get("next_check_date"):
        state_next_check_date = pd.Timestamp(strategy_state["next_check_date"]).normalize()

    print("Дата последней цены :", signal_date.date())
    print("Дата прогноза       :", forecast_target_date.date())
    print("Текущая цена        :", round(current_price, 4), "RUB")
    print(f"GB  ({forecast_horizon}d)       :", round(gb_horizon_price, 4), "RUB")
    print(f"LSTM({forecast_horizon}d)       :", round(lstm_horizon_price, 4), "RUB")
    print("consensus_up        :", consensus_up)
    print("consensus_down      :", consensus_down)
    if state_next_check_date is not None:
        print("Следующая дата проверки из state:", state_next_check_date.date())
    else:
        print("State-файл отсутствует или next_check_date не задан -> считаем это первой проверкой")

    wait_for_next_check = (
        enforce_horizon_schedule
        and state_next_check_date is not None
        and signal_date < state_next_check_date
    )
    if force_mode_active:
        print(f"FORCE ACTION MODE: {force_action} (обходим консенсус и расписание)")
        wait_for_next_check = False

    with Client(token, app_name=args.app_name) as api:
        accounts = api.users.get_accounts().accounts
        if not accounts:
            raise RuntimeError("Не найдено доступных счетов для токена.")

        if args.account_id:
            account_ids = [a.id for a in accounts]
            if args.account_id not in account_ids:
                raise ValueError(f"account-id не найден. Доступные: {account_ids}")
            account_id = args.account_id
        else:
            account_id = accounts[0].id
            print("account-id не задан, используем первый доступный счет:", account_id)

        portfolio = api.operations.get_portfolio(account_id=account_id)
        current_lots = 0
        for pos in portfolio.positions:
            if pos.figi == figi:
                current_lots = int(round(q_to_float(pos.quantity_lots)))
                break

        print("Текущая позиция (лотов):", current_lots)

        order_sent = False
        order_id = None
        order_qty = 0
        direction = None

        if force_action == "BUY":
            action = "FORCE_BUY"
            order_qty = int(args.buy_lots)
            direction = OrderDirection.ORDER_DIRECTION_BUY
        elif force_action == "SELL":
            if current_lots > 0:
                action = "FORCE_SELL"
                order_qty = int(current_lots if sell_all_on_down else min(current_lots, args.buy_lots))
                direction = OrderDirection.ORDER_DIRECTION_SELL
            else:
                action = "FORCE_SELL_SKIPPED_NO_POSITION"
                print("FORCE SELL skipped: нет длинной позиции для закрытия.")
        elif wait_for_next_check:
            action = "WAIT_UNTIL_NEXT_CHECK"
            print("До следующей проверки еще рано -> торговое решение не пересматриваем.")
        elif current_lots < 0:
            action = "SKIP_SHORT_POSITION"
            print("Обнаружена short-позиция. Стратегия long-only, ордер не отправляем.")
        elif consensus_up and current_lots == 0:
            action = "BUY"
            order_qty = int(args.buy_lots)
            direction = OrderDirection.ORDER_DIRECTION_BUY
        elif consensus_up and current_lots > 0:
            action = "HOLD_LONG"
        elif consensus_down and current_lots > 0:
            action = "SELL"
            order_qty = int(current_lots if sell_all_on_down else min(current_lots, args.buy_lots))
            direction = OrderDirection.ORDER_DIRECTION_SELL
        else:
            action = "HOLD_NO_ACTION"

        print("Решение стратегии:", action)

        if wait_for_next_check and not force_mode_active:
            pass
        elif not args.run_real_order:
            print("run-real-order не включен -> ордер НЕ отправлен (dry-run).")
        elif action in ("BUY", "SELL", "FORCE_BUY", "FORCE_SELL") and order_qty > 0:
            try:
                status = api.market_data.get_trading_status(figi=figi)
                if not status.market_order_available_flag:
                    print("Ордер не отправлен: market order сейчас недоступен.")
                else:
                    order = api.orders.post_order(
                        order_id=str(uuid4()),
                        figi=figi,
                        quantity=order_qty,
                        direction=direction,
                        order_type=OrderType.ORDER_TYPE_MARKET,
                        account_id=account_id,
                    )
                    order_sent = True
                    order_id = order.order_id
                    print("Ордер отправлен на РЕАЛЬНЫЙ счет!")
                    print("order_id:", order.order_id)
                    print("lots    :", order_qty)
                    print("side    :", "BUY" if direction == OrderDirection.ORDER_DIRECTION_BUY else "SELL")
            except RequestError as e:
                print(f"Ордер не отправлен из-за ошибки API: {e}")
        else:
            print("Торгового действия нет (hold / нет консенсуса / нет позиции для продажи).")

    allow_state_update_now = args.run_real_order or args.update_state_in_dry_run
    skip_state_update_in_force_mode = force_mode_active

    if save_strategy_state and not wait_for_next_check and allow_state_update_now and not skip_state_update_in_force_mode:
        new_state = {
            "figi": figi,
            "signal_date": str(signal_date.date()),
            "forecast_target_date": str(forecast_target_date.date()),
            "next_check_date": str(next_check_date_planned.date()),
            "current_price": current_price,
            "gb_horizon_price": gb_horizon_price,
            "lstm_horizon_price": lstm_horizon_price,
            "consensus_up": bool(consensus_up),
            "consensus_down": bool(consensus_down),
            "action": action,
            "order_sent": bool(order_sent),
            "order_id": order_id,
            "run_real_order": bool(args.run_real_order),
        }
        state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("State стратегии сохранен в:", state_path.resolve())
    elif force_mode_active:
        print("State не обновлен: force-action режим (тестовая сделка не сдвигает расписание стратегии).")
    elif save_strategy_state and not wait_for_next_check and not allow_state_update_now:
        print("State НЕ обновлен (dry-run и update-state-in-dry-run=False).")
    elif wait_for_next_check:
        print("State НЕ обновлен, т.к. еще не наступила следующая дата проверки.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

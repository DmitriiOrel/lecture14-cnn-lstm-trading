import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd

from tinkoff.invest import CandleInterval, Client, OrderDirection, OrderType
from tinkoff.invest.exceptions import RequestError
from tinkoff.invest.utils import now


DEFAULT_FIGI = "BBG00RM6M4T8"  # ETLN / Эталон Груп (MOEX)
DEFAULT_APP_NAME = "SMA30-SIGMA-CLI"
DEFAULT_OUTPUT_DIR = Path("reports/simple_lstm_etln_h3")


def configure_console_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def q_to_float(q) -> float:
    return float(q.units + q.nano / 1e9)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Исполнение контртрендовой стратегии SMA(30) ± σ на реальном счете T-Invest. "
            "Вход: выход цены за канал 2σ; выход: возврат в канал 2σ; стоп-лосс: канал 3σ."
        )
    )
    p.add_argument("--token", default=None, help="T-Invest token (или env TINVEST_TOKEN)")
    p.add_argument("--app-name", default=DEFAULT_APP_NAME)
    p.add_argument("--account-id", default="", help="ID реального счета")
    p.add_argument("--figi", default=DEFAULT_FIGI)

    p.add_argument("--forecast-json", default="", help="Путь к JSON из ноутбука")
    p.add_argument("--current-price", type=float, default=None)
    p.add_argument("--sma30", type=float, default=None)
    p.add_argument("--std30", type=float, default=None)
    p.add_argument("--signal-date", default=None, help="Дата сигнала YYYY-MM-DD")
    p.add_argument("--upper-2sigma", type=float, default=None)
    p.add_argument("--lower-2sigma", type=float, default=None)
    p.add_argument("--upper-3sigma", type=float, default=None)
    p.add_argument("--lower-3sigma", type=float, default=None)

    p.add_argument("--buy-lots", type=int, default=1)
    p.add_argument("--force-action", choices=["BUY", "SELL"], default="")

    p.add_argument("--enforce-horizon-schedule", action="store_true", default=False)
    p.add_argument("--no-enforce-horizon-schedule", action="store_true")
    p.add_argument("--save-strategy-state", action="store_true", default=True)
    p.add_argument("--no-save-strategy-state", action="store_true")
    p.add_argument("--update-state-in-dry-run", action="store_true", default=False)
    p.add_argument("--state-path", default="")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    p.add_argument("--run-real-order", action="store_true", default=False)
    return p.parse_args()


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_inputs(args: argparse.Namespace) -> dict:
    data: dict = {}

    if args.forecast_json:
        data.update(load_payload(Path(args.forecast_json)))

    if args.current_price is not None:
        data["current_price"] = args.current_price
    if args.sma30 is not None:
        data["sma30"] = args.sma30
    if args.std30 is not None:
        data["std30"] = args.std30
    if args.signal_date is not None:
        data["signal_date"] = args.signal_date
    if args.upper_2sigma is not None:
        data["upper_2sigma"] = args.upper_2sigma
    if args.lower_2sigma is not None:
        data["lower_2sigma"] = args.lower_2sigma
    if args.upper_3sigma is not None:
        data["upper_3sigma"] = args.upper_3sigma
    if args.lower_3sigma is not None:
        data["lower_3sigma"] = args.lower_3sigma

    data.setdefault("figi", args.figi)
    data.setdefault("signal_date", str(pd.Timestamp.utcnow().normalize().date()))

    return data


def fetch_price_stats(api: Client, figi: str, days_back: int = 120) -> tuple[float, float, float]:
    close_values: list[float] = []
    for candle in api.get_all_candles(
        figi=figi,
        from_=now() - timedelta(days=days_back),
        to=now(),
        interval=CandleInterval.CANDLE_INTERVAL_DAY,
    ):
        close_values.append(q_to_float(candle.close))

    if len(close_values) < 30:
        raise ValueError("Недостаточно дневных свечей для расчета SMA30 и STD30.")

    close = pd.Series(close_values, dtype="float64")
    current_price = float(close.iloc[-1])
    sma30 = float(close.rolling(30).mean().iloc[-1])
    std30 = float(close.rolling(30).std(ddof=0).iloc[-1])
    return current_price, sma30, std30


def main() -> int:
    configure_console_utf8()
    args = parse_args()

    token = args.token or os.environ.get("TINVEST_TOKEN")
    if not token:
        raise ValueError("Не указан token: передайте --token или задайте TINVEST_TOKEN")

    inputs = merge_inputs(args)
    figi = inputs.get("figi", args.figi)
    signal_date = pd.Timestamp(inputs["signal_date"]).normalize()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_path) if args.state_path else output_dir / "strategy_state_sma30_sigma.json"

    save_strategy_state = not args.no_save_strategy_state

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

        market_price, market_sma30, market_std30 = fetch_price_stats(api=api, figi=figi)

        current_price = float(inputs.get("current_price", market_price))
        sma30 = float(inputs.get("sma30", market_sma30))
        std30 = float(inputs.get("std30", market_std30))

        upper_2sigma = float(inputs.get("upper_2sigma", sma30 + 2 * std30))
        lower_2sigma = float(inputs.get("lower_2sigma", sma30 - 2 * std30))
        upper_3sigma = float(inputs.get("upper_3sigma", sma30 + 3 * std30))
        lower_3sigma = float(inputs.get("lower_3sigma", sma30 - 3 * std30))

        in_channel_2sigma = (lower_2sigma <= current_price) and (current_price <= upper_2sigma)
        above_upper_2sigma = current_price > upper_2sigma
        below_lower_2sigma = current_price < lower_2sigma
        above_upper_3sigma = current_price > upper_3sigma
        below_lower_3sigma = current_price < lower_3sigma

        print("Дата сигнала      :", signal_date.date())
        print("Текущая цена      :", round(current_price, 4), "RUB")
        print("SMA30             :", round(sma30, 4))
        print("STD30             :", round(std30, 4))
        print("Канал 2σ          :", round(lower_2sigma, 4), "...", round(upper_2sigma, 4))
        print("Канал 3σ          :", round(lower_3sigma, 4), "...", round(upper_3sigma, 4))
        print("Текущая позиция (лотов):", current_lots)

        force_action = (args.force_action or "").upper()

        order_sent = False
        order_id = None
        order_qty = 0
        direction = None

        if force_action == "BUY":
            action = "FORCE_BUY"
            order_qty = int(args.buy_lots)
            direction = OrderDirection.ORDER_DIRECTION_BUY

        elif force_action == "SELL":
            action = "FORCE_SELL"
            order_qty = int(args.buy_lots)
            direction = OrderDirection.ORDER_DIRECTION_SELL

        elif current_lots == 0 and above_upper_2sigma:
            action = "SELL_OPEN_SHORT"
            order_qty = int(args.buy_lots)
            direction = OrderDirection.ORDER_DIRECTION_SELL

        elif current_lots == 0 and below_lower_2sigma:
            action = "BUY_OPEN_LONG"
            order_qty = int(args.buy_lots)
            direction = OrderDirection.ORDER_DIRECTION_BUY

        elif current_lots > 0 and below_lower_3sigma:
            action = "STOP_LOSS_LONG"
            order_qty = int(current_lots)
            direction = OrderDirection.ORDER_DIRECTION_SELL

        elif current_lots < 0 and above_upper_3sigma:
            action = "STOP_LOSS_SHORT"
            order_qty = int(abs(current_lots))
            direction = OrderDirection.ORDER_DIRECTION_BUY

        elif current_lots > 0 and in_channel_2sigma:
            action = "EXIT_LONG_TO_FLAT"
            order_qty = int(current_lots)
            direction = OrderDirection.ORDER_DIRECTION_SELL

        elif current_lots < 0 and in_channel_2sigma:
            action = "EXIT_SHORT_TO_FLAT"
            order_qty = int(abs(current_lots))
            direction = OrderDirection.ORDER_DIRECTION_BUY

        else:
            action = "HOLD_NO_ACTION"

        print("Решение стратегии:", action)

        if not args.run_real_order:
            print("run-real-order не включен -> ордер НЕ отправлен (тестовый режим).")

        elif order_qty > 0 and direction is not None:
            status = api.market_data.get_trading_status(figi=figi)
            if not status.market_order_available_flag:
                print("Ордер не отправлен: market order сейчас недоступен.")
            else:
                try:
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
                    print("Ордер отправлен на РЕАЛЬНЫЙ счет.")
                    print("order_id:", order_id)
                    print("lots    :", order_qty)
                    print("side    :", "BUY" if direction == OrderDirection.ORDER_DIRECTION_BUY else "SELL")
                except RequestError as e:
                    print(f"Ордер не отправлен из-за ошибки API: {e}")

        else:
            print("Торгового действия нет (HOLD / нет триггера).")

    if save_strategy_state:
        new_state = {
            "figi": figi,
            "signal_date": str(signal_date.date()),
            "current_price": current_price,
            "sma30": sma30,
            "std30": std30,
            "upper_2sigma": upper_2sigma,
            "lower_2sigma": lower_2sigma,
            "upper_3sigma": upper_3sigma,
            "lower_3sigma": lower_3sigma,
            "action": action,
            "order_sent": bool(order_sent),
            "order_id": order_id,
            "run_real_order": bool(args.run_real_order),
        }
        state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("State стратегии сохранен в:", state_path.resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

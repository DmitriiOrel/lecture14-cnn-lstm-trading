import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from uuid import uuid4

from tinkoff.invest import Client, OrderDirection, OrderType
from tinkoff.invest.exceptions import RequestError
from tinkoff.invest.schemas import InstrumentIdType


def configure_console_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def q_to_float(q) -> float:
    return float(q.units + q.nano / 1e9)


def money_to_float(m) -> float:
    return float(m.units + m.nano / 1e9)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Автоподбор и покупка первой доступной акции MOEX (TQBR) с лотом=1 и ценой ниже лимита. "
            "Сначала dry-run, для реальной отправки используйте --run-real-order."
        )
    )
    p.add_argument("--token", default=None, help="T-Invest token (или env TINVEST_TOKEN)")
    p.add_argument("--app-name", default="AUTO-BUY-LOT1-MOEX")
    p.add_argument("--account-id", default="", help="ID счета (если не указан, берется первый)")
    p.add_argument("--board", default="TQBR", help="MOEX board, по умолчанию TQBR")
    p.add_argument("--max-price", type=float, default=50.0, help="Макс цена акции для первого прохода")
    p.add_argument(
        "--fallback-max-price",
        type=float,
        default=100.0,
        help="Если по первому лимиту ничего не купили, пробуем до этой цены (0 = отключить)",
    )
    p.add_argument("--buy-lots", type=int, default=1, help="Сколько лотов купить")
    p.add_argument("--commission-buffer-rub", type=float, default=10.0, help="Запас на комиссию")
    p.add_argument(
        "--tickers",
        default="",
        help="Список тикеров через запятую. Если не указан, кандидаты берутся автоматически с MOEX ISS.",
    )
    p.add_argument("--run-real-order", action="store_true", default=False)
    return p.parse_args()


def fetch_moex_candidates(board: str, max_price: float) -> list[dict]:
    params = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "securities.columns": "SECID,SHORTNAME,LOTSIZE",
        "marketdata.columns": "SECID,LAST,MARKETPRICE2,LCURRENTPRICE,NUMTRADES,VALTODAY",
        "securities.limit": "500",
        "marketdata.limit": "500",
    }
    url = (
        f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/{board}/securities.json?"
        + urllib.parse.urlencode(params)
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)

    sec_cols = data["securities"]["columns"]
    md_cols = data["marketdata"]["columns"]
    secs = {row[0]: dict(zip(sec_cols, row)) for row in data["securities"]["data"]}

    result: list[dict] = []
    for row in data["marketdata"]["data"]:
        md = dict(zip(md_cols, row))
        secid = md["SECID"]
        sec = secs.get(secid)
        if not sec:
            continue
        if sec.get("LOTSIZE") != 1:
            continue
        px = md.get("LAST") or md.get("MARKETPRICE2") or md.get("LCURRENTPRICE")
        if px is None:
            continue
        try:
            px = float(px)
        except Exception:
            continue
        if px <= 0 or px > max_price:
            continue
        result.append(
            {
                "ticker": secid,
                "name": sec.get("SHORTNAME") or secid,
                "moex_price": px,
                "numtrades": int(md.get("NUMTRADES") or 0),
                "valtoday": float(md.get("VALTODAY") or 0),
            }
        )

    # Приоритет ликвидным бумагам, потом более низкой цене.
    result.sort(key=lambda x: (-x["valtoday"], -x["numtrades"], x["moex_price"], x["ticker"]))
    return result


def get_free_rub(api: Client, account_id: str) -> float:
    positions = api.operations.get_positions(account_id=account_id)
    for m in positions.money:
        if str(m.currency).lower() == "rub":
            return money_to_float(m)
    return 0.0


def resolve_share(api: Client, ticker: str, board: str):
    return api.instruments.share_by(
        id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_TICKER,
        class_code=board,
        id=ticker,
    ).instrument


def try_buy_candidate(
    api: Client,
    account_id: str,
    ticker: str,
    board: str,
    rub_free: float,
    buy_lots: int,
    commission_buffer_rub: float,
    run_real_order: bool,
) -> tuple[bool, str]:
    try:
        instrument = resolve_share(api, ticker=ticker, board=board)
    except Exception as e:
        return False, f"{ticker}: не удалось найти инструмент в T-Invest ({e})"

    lot = int(instrument.lot)
    if lot != 1:
        return False, f"{ticker}: пропуск, lot={lot} (нужен lot=1)"

    last_resp = api.market_data.get_last_prices(figi=[instrument.figi])
    if not last_resp.last_prices:
        return False, f"{ticker}: нет last price"
    price = q_to_float(last_resp.last_prices[0].price)
    est_cost = price * buy_lots * lot

    if rub_free < est_cost + commission_buffer_rub:
        need = est_cost + commission_buffer_rub
        return False, f"{ticker}: не хватает RUB (нужно ~{need:.2f}, доступно {rub_free:.2f})"

    status = api.market_data.get_trading_status(figi=instrument.figi)
    if not status.market_order_available_flag:
        return False, f"{ticker}: market order сейчас недоступен"

    if not run_real_order:
        msg = (
            f"DRY-RUN -> купили бы {ticker} ({instrument.name}), figi={instrument.figi}, "
            f"lots={buy_lots}, lot={lot}, price~{price:.4f}, cost~{est_cost:.2f} RUB"
        )
        return True, msg

    try:
        order = api.orders.post_order(
            order_id=str(uuid4()),
            figi=instrument.figi,
            quantity=int(buy_lots),
            direction=OrderDirection.ORDER_DIRECTION_BUY,
            order_type=OrderType.ORDER_TYPE_MARKET,
            account_id=account_id,
        )
        msg = (
            f"УСПЕХ: BUY {ticker} ({instrument.name}) отправлен. "
            f"order_id={order.order_id}, lots={buy_lots}, price~{price:.4f}, cost~{est_cost:.2f} RUB"
        )
        return True, msg
    except RequestError as e:
        # Продолжаем к следующему кандидату вместо падения.
        return False, f"{ticker}: ошибка API при отправке ордера ({e})"


def main() -> int:
    configure_console_utf8()
    args = parse_args()

    token = args.token or os.environ.get("TINVEST_TOKEN")
    if not token:
        print("Не указан token (передайте --token или задайте TINVEST_TOKEN)")
        return 2

    max_prices = [args.max_price]
    if args.fallback_max_price and args.fallback_max_price > args.max_price:
        max_prices.append(args.fallback_max_price)

    with Client(token, app_name=args.app_name) as api:
        accounts = api.users.get_accounts().accounts
        if not accounts:
            print("Не найдено доступных счетов для токена")
            return 2

        if args.account_id:
            account_ids = [a.id for a in accounts]
            if args.account_id not in account_ids:
                print(f"account-id не найден. Доступные: {account_ids}")
                return 2
            account_id = args.account_id
        else:
            account_id = accounts[0].id
            print(f"account-id не задан -> используем первый счет: {account_id}")

        rub_free = get_free_rub(api, account_id)
        print(f"Свободно RUB: {rub_free:.2f}")
        print(f"Режим: {'REAL ORDER' if args.run_real_order else 'DRY-RUN'}")

        for current_max_price in max_prices:
            if args.tickers.strip():
                candidates = [{"ticker": t.strip().upper()} for t in args.tickers.split(",") if t.strip()]
                print(f"\nКандидаты из --tickers ({len(candidates)}), лимит цены={current_max_price:g}")
            else:
                candidates = fetch_moex_candidates(board=args.board, max_price=current_max_price)
                print(f"\nКандидаты с MOEX ISS (lot=1, price<={current_max_price:g}): {len(candidates)}")
                if candidates:
                    preview = ", ".join(x["ticker"] for x in candidates[:10])
                    print("Первые кандидаты:", preview)

            for c in candidates:
                ticker = c["ticker"]
                ok, msg = try_buy_candidate(
                    api=api,
                    account_id=account_id,
                    ticker=ticker,
                    board=args.board,
                    rub_free=rub_free,
                    buy_lots=args.buy_lots,
                    commission_buffer_rub=args.commission_buffer_rub,
                    run_real_order=args.run_real_order,
                )
                print(msg)
                if ok:
                    return 0

        print("Не удалось подобрать/купить инструмент в заданных лимитах.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

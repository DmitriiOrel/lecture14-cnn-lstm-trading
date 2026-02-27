# Лекция 14: ETLN + LSTM/CNN/CNN-LSTM + push ордеров T-Invest

Репозиторий содержит:
- `lecture14_cnn_lstm.ipynb` — учебный ноутбук без GB: LSTM для цены, CNN для классификации паттерна, CNN-LSTM для цены.
- `trade_signal_executor_vtbr.py` — логика торгового сигнала и отправки ордера (перенесена 1-в-1 из исходного репозитория).
- `auto_buy_first_affordable_lot1.py` — автопокупка первой доступной бумаги MOEX (перенесена 1-в-1).
- `run_trade_signal.py`, `run_vtbr_trade_signal.ps1`, `run_vtbr_trade_signal.sh` — запуск торгового скрипта.
- `run_auto_buy_first_affordable_lot1.ps1`, `run_auto_buy_first_affordable_lot1.sh` — запуск автопокупки.

## Установка

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
```

## Что внутри ноутбука

1. LSTM-регрессор:
- прогноз цены ETLN через `FORECAST_HORIZON` торговых дней;
- метрики: `MAE`, `RMSE`.

2. CNN-классификатор:
- задача: направление цены вверх/вниз через `FORECAST_HORIZON`;
- метрики: `accuracy`, `ROC-AUC`.

3. CNN-LSTM-регрессор:
- прогноз цены на том же горизонте;
- сравнение с базовой LSTM по `MAE`, `RMSE`.

## Безопасность

- Не храните токен в коде.
- Используйте переменную окружения `TINVEST_TOKEN`.
- Для теста ордеров используйте dry-run режим в CLI-скриптах.

# Торговая логика `SMA(30) ± σ` + торговые скрипты T-Invest

Репозиторий содержит:
- `lecture14.ipynb` — учебный ноутбук (в стиле лекции 13) для прогноза цены ETLN (`Gradient Boosting` vs `LSTM`, горизонт = 3 торговых дня).
- `trade_signal_executor_vtbr.py` — CLI-исполнитель торговой логики по стратегии `SMA(30) ± σ`.
- `run_trade_signal.py` — универсальный кроссплатформенный Python-раннер (автопоиск `latest_forecast_signal_*.json` в `Загрузки` / `reports`).
- `run_vtbr_trade_signal.ps1` — обертка для Windows PowerShell.
- `run_vtbr_trade_signal.sh` — обертка для macOS / Linux.
- `auto_buy_first_affordable_lot1.py` — утилита автопокупки первой доступной акции MOEX с `lot=1`.
- `run_auto_buy_first_affordable_lot1.ps1` — обертка для Windows PowerShell.
- `run_auto_buy_first_affordable_lot1.sh` — обертка для macOS / Linux.

## Торговая логика `SMA(30) ± σ`

- Вход в шорт: цена выше `SMA30 + 2σ`.
- Вход в лонг: цена ниже `SMA30 - 2σ`.
- Выход из позиции: возврат цены внутрь канала `SMA30 ± 2σ`.
- Стоп-лосс: выход цены за границу `SMA30 ± 3σ` против текущей позиции.

## 1) Клонирование репозитория

```bash
git clone https://github.com/DmitriiOrel/lecture14-cnn-lstm-trading.git
cd lecture14-cnn-lstm-trading
```

## 2) Google Colab (обучение и прогноз)

1. Откройте или загрузите `lecture14.ipynb` в Google Colab.
2. Запустите первую install-ячейку.
3. После первой установки сделайте `Runtime -> Restart runtime`.
4. Запустите ноутбук сверху вниз.
5. Введите T-Invest токен через `getpass()`.

Ноутбук сохраняет JSON с последним прогнозом в:

- `reports/simple_lstm_etln_h3/latest_forecast_signal_etln_h3.json`

## 3) Локальная установка (Windows / macOS / Linux)

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
chmod +x run_vtbr_trade_signal.sh run_auto_buy_first_affordable_lot1.sh
```

## 4) Проверка, что JSON действительно сохранен

### Windows PowerShell

```powershell
Get-ChildItem $HOME\Downloads\latest_forecast_signal_*.json
```

### macOS / Linux

```bash
ls -1 ~/Downloads/latest_forecast_signal_*.json
```

## 5) Универсальный запуск торговой логики (рекомендуется)

### Шаг 1. Задайте токен

Windows PowerShell:

```powershell
$env:TINVEST_TOKEN = "t.nRVqFeoEg__tNSbea-8HwFh-3m8KGcyKvJlLiYnpt4MpMRzwo6ik1BKL1hYC9dS7EzAOSDqLPz0i8h5ctqBJlg"
```

macOS / Linux:

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
```

### Шаг 2. Тестовый запуск без отправки ордера

```bash
python run_trade_signal.py
```

### Шаг 3. Реальный запуск

```bash
python run_trade_signal.py --run-real-order
```

### Шаг 4. Принудительный тест BUY/SELL

```bash
python run_trade_signal.py --run-real-order --force-action BUY
python run_trade_signal.py --run-real-order --force-action SELL
```

### Если JSON лежит в нестандартной папке

```bash
python run_trade_signal.py --forecast-json "C:/Users/your_user/Downloads/latest_forecast_signal_etln_h3.json"
```

## 6) Запуск через платформенные обертки (опционально)

### Windows PowerShell

```powershell
$env:TINVEST_TOKEN = "t.nRVqFeoEg__tNSbea-8HwFh-3m8KGcyKvJlLiYnpt4MpMRzwo6ik1BKL1hYC9dS7EzAOSDqLPz0i8h5ctqBJlg"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1 -RunRealOrder
```

### macOS / Linux

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
./run_vtbr_trade_signal.sh
./run_vtbr_trade_signal.sh --run-real-order
```

## 7) Утилита: купить первую доступную акцию с `lot=1`

### Windows PowerShell

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_auto_buy_first_affordable_lot1.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_auto_buy_first_affordable_lot1.ps1 -RunRealOrder
```

### macOS / Linux

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
./run_auto_buy_first_affordable_lot1.sh
./run_auto_buy_first_affordable_lot1.sh --run-real-order
```

## 8) Безопасность

- Не храните T-Invest токены в ноутбуке и репозитории.
- Используйте переменную окружения `TINVEST_TOKEN`.
- Для студентов по умолчанию используйте тестовый запуск без отправки ордера.
- Реальную торговлю запускайте из локального терминала.

## 9) Что исключено из git

В `.gitignore` исключены:
- `venv/`
- `.venv/`
- `logs/`
- `reports/`

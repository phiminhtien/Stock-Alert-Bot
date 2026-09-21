"""Cấu hình bot giao dịch chứng khoán.

Đọc thông tin từ biến môi trường (.env) và định nghĩa các tham số kỹ thuật.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Watchlist ─────────────────────────────────────────────
raw_codes = os.getenv("STOCK_CODES", "FPT,SSI,VCB,VHM,HPG")
WATCHLIST = [code.strip().upper() for code in raw_codes.split(",") if code.strip()]


# ── Thời gian ─────────────────────────────────────────────
TIMEZONE = "Asia/Ho_Chi_Minh"
NOTIFY_INTERVAL_MINUTES = int(os.getenv("NOTIFY_INTERVAL_MINUTES", 15))

# ── Chỉ báo kỹ thuật ─────────────────────────────────────
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
ATR_STOP_LOSS_FACTOR = 1.5
MIN_RR_RATIO = 2.0
EMA_SHORT = 20
EMA_LONG = 50
RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 10  # Chiều dài dải Bollinger = 10 theo yêu cầu
BB_STD = 2      # Mult = 2 theo yêu cầu
VOLUME_MA_PERIOD = 20
VOLUME_SPIKE_RATIO = 1.5
HISTORICAL_DAYS = 365
FIB_LOOKBACK_DAYS = 120
TRENDLINE_LOOKBACK = 30
CONSECUTIVE_BARS_ALERT = 3  # Ngưỡng cảnh báo số nhịp tăng/giảm liên tiếp


# Kế hoạch triển khai: Bot Notify Chứng khoán Việt Nam qua Telegram

## 1. Mục tiêu

Xây dựng một bot Python chạy nền, tự động:
- Quét dữ liệu chứng khoán Việt Nam (EOD + polling trong phiên)
- Tính toán chỉ báo kỹ thuật, sinh tín hiệu vào lệnh / cắt lỗ / chốt lời
- Lọc ra danh sách cổ phiếu tiềm năng và cổ phiếu downtrend
- Gửi báo cáo phân tích chi tiết từng mã qua Telegram (một chiều)

**Nguyên tắc thiết kế: tối giản.** Không dùng database, message queue, dashboard. Một script Python chạy scheduler, chấp nhận trùng lặp tín hiệu giữa các lần quét.

## 2. Nguồn dữ liệu

- **vnstock 4.x** (Python lib, free) — nguồn chính: lấy giá lịch sử, real-time qua API VCI
- `data_fetcher.py` thiết kế class `DataFetcher` dễ swap source sau này

## 3. Cấu trúc thư mục

```
vn-stock-bot/
├── main.py              # entry point, AsyncIOScheduler
├── config.py            # watchlist, Telegram token, ngưỡng chỉ báo
├── data_fetcher.py      # lấy dữ liệu từ vnstock.api.quote
├── indicators.py        # tính MA/EMA/RSI/MACD/ATR/BB (thuần pandas)
├── signals.py           # logic entry/stop-loss/take-profit/potential/downtrend
├── telegram_notify.py   # gửi Telegram + format báo cáo chi tiết
├── .env.example         # template cấu hình Telegram
├── .gitignore
└── requirements.txt
```

## 4. Stack kỹ thuật

```
vnstock>=4.0
pandas>=2.0
apscheduler>=3.10
python-telegram-bot>=20
python-dotenv>=1.0
```

Không dùng: pandas-ta (incompatible với Python 3.14), SQL/NoSQL database, Redis, RabbitMQ.

## 5. Chi tiết từng module

### 5.1 `config.py`
- `WATCHLIST`: danh sách mã theo dõi
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — đọc từ `.env`
- `NOTIFY_INTERVAL_MINUTES`: tần suất báo cáo giữa phiên (mặc định 15)
- Các ngưỡng: RSI oversold/overbought, ATR stop-loss factor, R:R ratio

### 5.2 `data_fetcher.py`
- `DataFetcher` dùng `vnstock.api.quote.Quote` (source=VCI)
- `fetch_historical(symbol)` → OHLCV DataFrame
- `fetch_multiple_historical()` → dict `{symbol: df}`
- Cache đơn giản trong memory

### 5.3 `indicators.py`
Tính trên DataFrame OHLCV bằng pandas thuần (không pandas-ta):
- EMA20, EMA50, SMA50, SMA200
- RSI(14) — EWM-based
- MACD (12, 26, 9)
- ATR(14)
- Bollinger Bands (20, 2 std)
- Volume MA(20)

### 5.4 `signals.py`
- **Entry**: EMA20 cắt lên EMA50 + volume spike; RSI hồi từ oversold
- **Stop-loss**: price − ATR × factor
- **Take-profit**: trail theo EMA20 nếu giá đã chạy 5%+
- **Potential**: giá > SMA50 & SMA200 + volume spike
- **Downtrend**: giá < SMA50 & SMA200 + MACD âm 5 phiên + volume spike

### 5.5 `telegram_notify.py`
- Gửi message async qua `python-telegram-bot`
- `format_stock_analysis()`: báo cáo chi tiết từng mã gồm:
  - Giá, khung giá, khối lượng
  - Điểm vào lệnh (0-10) + điểm chốt lời (0-10)
  - RSI, MACD, xu hướng (SMA200), Golden/Death cross
  - Hỗ trợ/kháng cự (BB)
  - Chiến lược: SL, TP1/TP2 (ATR), Fibonacci
  - Khuyến nghị (MUA/THEO DÕI/KHÔNG NÊN MUA)
- `format_session_report()`: top 5 mã biến động + tín hiệu mới

### 5.6 `main.py`
Dùng `AsyncIOScheduler` (timezone `Asia/Ho_Chi_Minh`):

| Job | Lịch | Việc làm |
|---|---|---|
| `scan_pre_market` | cron 8:30 | Quét toàn bộ watchlist, gửi báo cáo tiềm năng + downtrend |
| `scan_session` | cron 9:00–14:45, mỗi 15 phút | Quét, tính chỉ báo, gửi phân tích top 5 + tín hiệu |
| `scan_pre_close` | cron 14:30 | Cảnh báo biến động >3% trước ATC |
| `scan_post_market` | cron 15:15 | Tổng kết phiên: top biến động + xu hướng + volume |

Không lưu trạng thái giữa các lần chạy — mỗi lần quét độc lập.

## 6. Deploy

- `py vn-stock-bot/main.py`
- Cần `.env` với `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID`
- VPS nhẹ (Oracle Cloud free) đủ tải

## 7. Lưu ý

- Chỉ báo kỹ thuật có độ trễ và nhiễu cao, đặc biệt mã thanh khoản thấp
- Bot hỗ trợ ra quyết định, không tự động đặt lệnh
- Rate limit vnstock API và Telegram (~30 msg/s)

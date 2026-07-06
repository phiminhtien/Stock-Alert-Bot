# VN Stock Bot - Bot Telegram Thông báo Chứng khoán Việt Nam

Bot Python tự động quét dữ liệu chứng khoán Việt Nam, tính toán chỉ báo kỹ thuật, và gửi báo cáo phân tích chi tiết qua Telegram. Có thể chạy local hoặc trên GitHub Actions free tier.

## Cài đặt

```bash
# Clone repo
git clone <repo-url>
cd bot_alert_stock

# Tạo môi trường ảo (tùy chọn)
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash

# Cài dependencies
pip install -r vn-stock-bot/requirements.txt

# Cấu hình Telegram + watchlist
cp vn-stock-bot/.env.example vn-stock-bot/.env
```

Chỉnh sửa `.env`:
```ini
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
STOCK_CODES=FPT,VCB,VHM,VNM,HDB
```

### Tạo Bot Telegram
1. Chat với [@BotFather](https://t.me/BotFather) → `/newbot` → đặt tên → nhận token
2. Chat với bot vừa tạo → gửi 1 tin nhắn bất kỳ
3. Lấy `chat_id`: vào `https://api.telegram.org/bot<TOKEN>/getUpdates` → lấy số `chat.id`

## Chạy

### Local
```bash
py vn-stock-bot/main.py
```

### GitHub Actions (recommended, không cần VPS)
1. Push code lên GitHub
2. Vào **Settings → Secrets and variables → Actions** → thêm:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `STOCK_CODES` (VD: `FPT,VCB,VHM`)
3. Workflow `scan-daily.yml` tự chạy 8:30 AM VN (t2–t6), hoặc vào tab Actions → Run workflow

## Lịch gửi

| Giờ VN | Job | Nội dung |
|---|---|---|
| 08:30 | `pre_market` | Báo cáo đầu ngày: cổ phiếu tiềm năng + downtrend |
| 09:00–14:45 | `session` | Mỗi 15 phút: phân tích chi tiết top 5 mã biến động + tín hiệu mới |
| 14:30 | `pre_close` | Cảnh báo biến động >3% trước ATC |
| 15:15 | `post_market` | Tổng kết phiên: top biến động + xu hướng + volume |

## Mẫu báo cáo

```
📊 PHÂN TÍCH MÃ VHM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💹 Giá: 151.60đ  🟢 +0.80%
📈 Khung: 148.20 - 155.40
📊 KL: 4.051.400

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 ĐIỂM VÀO LỆNH: 10.0/10 ✅
  • RSI(14): 56.58 - trung tính
  • MACD Histogram dương - Đà tăng
  • Giá > SMA200 (114.93) - Uptrend
  • Giá > SMA20 (147.12)
  • Golden Cross: SMA50 > SMA200

💰 ĐIỂM CHỐT LỜI: 4.5/10 ⚪
  • Giá trên BB Mid
  • RSI trung tính

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📍 HỖ TRỢ/KHÁNG CỰ
  • Hỗ trợ gần: 127.51đ
  • Kháng cự gần: 160.54đ

📌 CHIẾN LƯỢC GIAO DỊCH
  • Cắt lỗ: 142.73đ
  • Target 1 (2xATR): 163.43đ
  • Target 2 (3xATR): 169.34đ
  • Fib 0.382: 148.85đ
  • Fib 0.618: 147.15đ
  • Fib 1.0 (SMA200): 115.20đ

🟡 KHUYẾN NGHỊ: THEO DÕI
```

## Cấu hình

Sửa biến môi trường trong `.env` hoặc GitHub Secrets:

| Biến | Mô tả | Ví dụ |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token bot Telegram | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | Chat ID nhận tin | `-100123456789` |
| `STOCK_CODES` | Danh sách mã theo dõi (phân cách bằng dấu phẩy) | `FPT,VCB,VHM` |

Chỉnh ngưỡng kỹ thuật trong `vn-stock-bot/config.py`:

```python
NOTIFY_INTERVAL_MINUTES = 15    # tần suất báo cáo giữa phiên
RSI_OVERSOLD = 30               # ngưỡng quá bán
RSI_OVERBOUGHT = 70             # ngưỡng quá mua
ATR_STOP_LOSS_FACTOR = 1.5      # hệ số ATR cho stop-loss
MIN_RR_RATIO = 2.0              # tỷ lệ risk:reward tối thiểu
```

## Module

| File | Mô tả |
|---|---|
| `config.py` | Cấu hình: Telegram, watchlist, ngưỡng kỹ thuật |
| `data_fetcher.py` | Lấy dữ liệu OHLCV từ vnstock API (VCI source) |
| `indicators.py` | Tính chỉ báo: EMA, SMA, RSI, MACD, ATR, BB (thuần pandas) |
| `signals.py` | Logic phát hiện entry, take-profit, potential, downtrend |
| `telegram_notify.py` | Gửi Telegram + format báo cáo phân tích chi tiết |
| `main.py` | AsyncIOScheduler: 4 job theo cron |
| `.github/workflows/scan-daily.yml` | GitHub Actions: chạy bot hàng ngày 8:30 AM VN |

## Yêu cầu

- Python >= 3.10
- Kết nối internet (gọi vnstock API)
- Telegram Bot Token + Chat ID
- (Optional) GitHub account nếu dùng GitHub Actions

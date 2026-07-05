# VN Stock Bot - Bot Telegram Thông báo Chứng khoán Việt Nam

Bot Python tự động quét dữ liệu chứng khoán Việt Nam, tính toán chỉ báo kỹ thuật, và gửi báo cáo phân tích chi tiết qua Telegram.

## Cài đặt

```bash
# Clone repo
git clone <repo-url>
cd bot_alert_stock

# Cài dependencies
pip install -r vn-stock-bot/requirements.txt

# Cấu hình Telegram
cp vn-stock-bot/.env.example vn-stock-bot/.env
```

Chỉnh sửa `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Tạo Bot Telegram
1. Messaging @BotFather trên Telegram → `/newbot`
2. Lấy token, paste vào `.env`
3. Gửi tin nhắn cho bot, rồi truy cập `https://api.telegram.org/bot<TOKEN>/getUpdates` để lấy `chat_id`

## Chạy

```bash
py vn-stock-bot/main.py
```

## Cấu trúc báo cáo

### Phân tích từng mã

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

🟡 KHUYẾN NGHỊ: THEO DÕI
```

### Lịch gửi

| Thời gian | Nội dung |
|---|---|
| 08:30 | Báo cáo đầu ngày: cổ phiếu tiềm năng + downtrend |
| 09:00–14:45 | Mỗi 15 phút: phân tích top 5 mã + tín hiệu mới |
| 14:30 | Cảnh báo biến động >3% trước ATC |
| 15:15 | Tổng kết phiên: top biến động + xu hướng |

## Cấu hình

Sửa `vn-stock-bot/config.py`:

```python
# Danh sách mã theo dõi
WATCHLIST = ["FPT", "VCB", "VHM", ...]

# Tần suất báo cáo giữa phiên (phút)
NOTIFY_INTERVAL_MINUTES = 15

# Các ngưỡng kỹ thuật
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
ATR_STOP_LOSS_FACTOR = 1.5
MIN_RR_RATIO = 2.0
```

## Module

| File | Mô tả |
|---|---|
| `config.py` | Cấu hình: watchlist, token, ngưỡng |
| `data_fetcher.py` | Lấy dữ liệu từ vnstock API (VCI) |
| `indicators.py` | Tính chỉ báo: MA, RSI, MACD, ATR, BB |
| `signals.py` | Logic sinh tín hiệu entry/stop/take |
| `telegram_notify.py` | Gửi Telegram + format báo cáo |
| `main.py` | APScheduler chạy 4 job theo lịch |

## Yêu cầu

- Python >= 3.10
- Kết nối internet (gọi vnstock API)
- Telegram Bot Token + Chat ID

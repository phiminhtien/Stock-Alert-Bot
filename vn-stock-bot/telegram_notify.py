import logging
import pandas as pd
from telegram import Bot
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_bot: Bot | None = None

def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot

async def send_message(text: str, chat_id: str | None = None) -> bool:
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        logger.warning("TELEGRAM_CHAT_ID not configured")
        return False
    try:
        await _get_bot().send_message(
            chat_id=cid,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        return True
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        return False

def escape_markdown(text: str) -> str:
    special = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text

def _rsi_label(rsi: float) -> str:
    if pd.isna(rsi):
        return "N/A"
    if rsi <= 30:
        return "oversold"
    if rsi >= 70:
        return "overbought"
    if rsi < 40:
        return "yếu"
    if rsi > 60:
        return "mạnh"
    return "trung tính"

def _trend_label(row) -> str:
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    close = row.get("close")
    if pd.isna(sma50) or pd.isna(sma200):
        return ""
    if close > sma50 and close > sma200:
        return "xu hướng lên"
    if close < sma50 and close < sma200:
        return "xu hướng xuống"
    return "sideways"

def _volume_label(row) -> str:
    vol = row.get("volume", 0)
    vol_ma = row.get("volume_ma", 0)
    if pd.isna(vol_ma) or vol_ma == 0:
        return ""
    ratio = vol / vol_ma
    if ratio >= 1.5:
        return f"đột biến x{ratio:.1f}"
    if ratio >= 1.2:
        return f"cao x{ratio:.1f}"
    return ""

def _macd_label(row) -> str:
    hist = row.get("macd_hist")
    signal = row.get("macd_signal")
    macd = row.get("macd")
    if pd.isna(hist) or pd.isna(macd) or pd.isna(signal):
        return ""
    if hist > 0:
        return "dương"
    return "âm"

def _bb_label(row) -> str:
    close = row.get("close")
    upper = row.get("bb_upper")
    lower = row.get("bb_lower")
    mid = row.get("bb_middle")
    if pd.isna(close) or pd.isna(upper) or pd.isna(lower):
        return ""
    if close >= upper:
        return "sát trên BB"
    if close <= lower:
        return "sát dưới BB"
    return ""

def format_pre_market_report(potential: list, downtrend: list) -> str:
    lines = ["*[TRƯỚC PHIÊN]* Báo cáo đầu ngày"]
    lines.append("")
    if potential:
        lines.append(f"*📈 Cổ phiếu tiềm năng ({len(potential)}):*")
        for s in potential:
            rsi = s.get("rsi", "N/A")
            reason = s.get("reason", "")
            lines.append(f"  • {s['symbol']} — giá {s.get('price','?')} | RSI {rsi} | {reason}")
    if downtrend:
        lines.append("")
        lines.append(f"*📉 Cổ phiếu downtrend ({len(downtrend)}):*")
        for s in downtrend:
            rsi = s.get("rsi", "N/A")
            reason = s.get("reason", "")
            lines.append(f"  • {s['symbol']} — giá {s.get('price','?')} | RSI {rsi} | {reason}")
    if not potential and not downtrend:
        lines.append("Không có tín hiệu đặc biệt.")
    lines.append("")
    lines.append("— Bot hỗ trợ đầu tư —")
    return "\n".join(lines)

def format_post_market_report(summary: list) -> str:
    lines = ["*[SAU PHIÊN]* Tổng kết phiên giao dịch"]
    lines.append("")
    for item in summary:
        change = item.get("change", 0)
        emoji = "🟢" if change > 0 else "🔴"
        vol_str = f"VOL {item.get('vol_ratio','')}" if item.get("vol_ratio") else ""
        trend_str = f" | {item['trend']}" if item.get("trend") else ""
        lines.append(f"  {emoji} {item['symbol']}: {change:+.2f}%{trend_str} {vol_str}")
    lines.append("")
    lines.append("— Bot hỗ trợ đầu tư —")
    return "\n".join(lines)

def _fmt(v) -> str:
    if pd.isna(v):
        return "N/A"
    return f"{v:.2f}"

def format_stock_analysis(symbol: str, df: pd.DataFrame) -> str:
    cur = df.iloc[-1]
    pre = df.iloc[-2]

    change_pct = ((cur["close"] - pre["close"]) / pre["close"]) * 100
    day_low = min(cur["low"], pre["low"])
    day_high = max(cur["high"], pre["high"])
    close = cur["close"]

    rsi = cur.get("rsi")
    macd_hist = cur.get("macd_hist")
    atr = cur.get("atr")
    sma20 = cur.get("ema_short")
    sma50 = cur.get("sma_50")
    sma200 = cur.get("sma_200")
    bb_mid = cur.get("bb_middle")
    bb_lower = cur.get("bb_lower")

    has_data = not all(pd.isna(x) for x in [rsi, atr, sma50])

    rsi_lbl = _rsi_label(rsi)
    rsi_str = f"RSI(14): {rsi:.2f} - {rsi_lbl}" if not pd.isna(rsi) else "RSI(14): N/A"

    macd_str = f"MACD Histogram dương - Đà tăng" if not pd.isna(macd_hist) and macd_hist > 0 else f"MACD Histogram âm - Đà giảm" if not pd.isna(macd_hist) else "MACD: N/A"

    trend_str = ""
    if not pd.isna(sma200) and not pd.isna(close):
        if close > sma200:
            trend_str = f"Giá > SMA200 ({_fmt(sma200)}) - Uptrend"
        else:
            trend_str = f"Giá < SMA200 ({_fmt(sma200)}) - Downtrend"
    else:
        trend_str = "Xu hướng: N/A"

    sma20_str = ""
    if not pd.isna(sma20) and not pd.isna(close):
        sma20_str = f"Giá {'>' if close > sma20 else '<'} SMA20 ({_fmt(sma20)})"

    cross_str = ""
    if not pd.isna(sma50) and not pd.isna(sma200):
        if sma50 > sma200:
            cross_str = "Golden Cross: SMA50 > SMA200"
        else:
            cross_str = "Death Cross: SMA50 < SMA200"

    entry_score = 5.0
    entry_parts = []
    if not pd.isna(rsi):
        if 30 <= rsi <= 60:
            entry_score += 1.5
            entry_parts.append("RSI trong vùng an toàn")
        elif rsi < 30:
            entry_score += 2.0
            entry_parts.append("RSI oversold - hồi phục")
        else:
            entry_score -= 1.0
            entry_parts.append("RSI quá mua - rủi ro")
    if not pd.isna(macd_hist) and macd_hist > 0:
        entry_score += 1.5
        entry_parts.append("MACD dương")
    else:
        entry_score -= 0.5
    if not pd.isna(close) and not pd.isna(sma200) and close > sma200:
        entry_score += 1.5
        entry_parts.append("Uptrend SMA200")
    else:
        entry_score -= 0.5
    if not pd.isna(close) and not pd.isna(sma20) and close > sma20:
        entry_score += 1.0
        entry_parts.append("Giá trên SMA20")
    else:
        entry_score -= 0.5
    if not pd.isna(sma50) and not pd.isna(sma200) and sma50 > sma200:
        entry_score += 1.0
        entry_parts.append("Golden Cross")
    entry_score = max(0, min(10, entry_score))

    tp_score = 5.0
    bb_mid_str = ""
    if not pd.isna(close) and not pd.isna(bb_mid):
        if close < bb_mid:
            tp_score += 2.0
            bb_mid_str = "Giá dưới BB Mid - Tiềm năng"
        elif close > bb_mid:
            tp_score -= 0.5
            bb_mid_str = "Giá trên BB Mid"
        if not pd.isna(bb_lower) and close <= bb_lower * 1.02:
            tp_score += 1.0
    if not pd.isna(rsi) and rsi > 60:
        tp_score -= 1.0
    tp_score = max(0, min(10, tp_score))

    entry_icon = "✅" if entry_score >= 6 else "⏳" if entry_score >= 4 else "❌"
    tp_icon = "✅" if tp_score >= 6 else "⚪" if tp_score >= 4 else "🔴"

    atr_val = atr if not pd.isna(atr) else 0
    sl = close - atr_val * 1.5 if close > 0 else 0
    tp1 = close + atr_val * 2
    tp2 = close + atr_val * 3

    fib_382 = close - (day_high - day_low) * 0.382 if day_high > day_low else 0
    fib_618 = close - (day_high - day_low) * 0.618 if day_high > day_low else 0
    fib_100 = day_low

    support = bb_lower if not pd.isna(bb_lower) else day_low
    resistance = cur.get("bb_upper", day_high)

    rec = "CHƯA NÊN MUA"
    rec_icon = "🔴"
    if entry_score >= 6 and tp_score >= 5:
        rec = "CÓ THỂ MUA"
        rec_icon = "🟢"
    elif entry_score >= 5:
        rec = "THEO DÕI"
        rec_icon = "🟡"

    vol_str = f"{cur['volume']:,.0f}".replace(",", ".")

    lines = [
        f"📊 *PHÂN TÍCH MÃ {symbol}*",
        "━" * 35,
        "",
        f"💹 *Giá:* {_fmt(close)}đ  {'🔴' if change_pct < 0 else '🟢'} {change_pct:+.2f}%",
        f"📈 Khung: {_fmt(day_low)} - {_fmt(day_high)}",
        f"📊 KL: {vol_str}",
        "",
        "━" * 35,
        "",
        f"🎯 *ĐIỂM VÀO LỆNH:* {entry_score:.1f}/10 {entry_icon}",
    ]

    if has_data:
        lines.append(f"  • {rsi_str}")
        lines.append(f"  • {macd_str}")
        lines.append(f"  • {trend_str}")
        if sma20_str:
            lines.append(f"  • {sma20_str}")
        if cross_str:
            lines.append(f"  • {cross_str}")

    lines.append("")
    lines.append(f"💰 *ĐIỂM CHỐT LỜI:* {tp_score:.1f}/10 {tp_icon}")
    if bb_mid_str:
        lines.append(f"  • {bb_mid_str}")
    if not pd.isna(rsi):
        lines.append(f"  • RSI {'vùng quá mua' if rsi > 60 else 'vùng an toàn' if rsi < 40 else 'trung tính'}")

    lines.append("")
    lines.append("━" * 35)
    lines.append("")

    if not pd.isna(support) and not pd.isna(resistance):
        lines.append(f"📍 *HỖ TRỢ/KHÁNG CỰ*")
        lines.append(f"  • Hỗ trợ gần: {_fmt(support)}đ")
        lines.append(f"  • Kháng cự gần: {_fmt(resistance)}đ")
        lines.append("")

    lines.append(f"📌 *CHIẾN LƯỢC GIAO DỊCH*")
    if close > 0:
        lines.append(f"  • Cắt lỗ: {_fmt(sl)}đ")
        lines.append(f"  • Target 1 (2xATR): {_fmt(tp1)}đ")
        lines.append(f"  • Target 2 (3xATR): {_fmt(tp2)}đ")
    if day_high > day_low:
        lines.append(f"  • Fib 0.382: {_fmt(fib_382)}đ")
        lines.append(f"  • Fib 0.618: {_fmt(fib_618)}đ")
        lines.append(f"  • Fib 1.0:   {_fmt(fib_100)}đ")
    if not pd.isna(rsi):
        lines.append(f"  • RSI: {_fmt(rsi)}")
    if not pd.isna(atr):
        lines.append(f"  • ATR: {_fmt(atr)}")

    lines.append("")
    lines.append(f"{rec_icon} *KHUYẾN NGHỊ:* {rec}")
    lines.append("=" * 35)
    return "\n".join(lines)


def format_session_report(data: dict, signals: list) -> str:
    now = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%H:%M %d/%m")
    lines = [f"*🔔 GIỮA PHIÊN — Cập nhật {now}*"]
    lines.append("")

    sorted_items = []
    for symbol, df in data.items():
        if df.empty or len(df) < 2:
            continue
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        change_pct = ((curr["close"] - prev["close"]) / prev["close"]) * 100
        sorted_items.append((symbol, df, change_pct))

    sorted_items.sort(key=lambda x: abs(x[2]), reverse=True)

    for symbol, df, change_pct in sorted_items[:5]:
        analysis = format_stock_analysis(symbol, df)
        lines.append(analysis)
        lines.append("")

    if signals:
        lines.append("⚠️ *TÍN HIỆU MỚI:*")
        for s in signals:
            t = s.get("type", "?")
            icon = {"entry": "🟢", "stop_loss": "🔴", "take_profit": "💰", "potential": "📈", "downtrend": "📉"}.get(t, "•")
            lines.append(f"  {icon} *{s.get('symbol','?')}* — {t}: {s.get('price','?')}")
            if s.get("reason"):
                lines.append(f"    └ {s.get('reason')}")

    lines.append("")
    lines.append("— Bot hỗ trợ đầu tư —")
    return "\n".join(lines)

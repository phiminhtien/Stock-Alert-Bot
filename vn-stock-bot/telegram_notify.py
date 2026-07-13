"""Gửi thông báo Telegram và định dạng báo cáo phân tích.

Sử dụng python-telegram-bot (async) để gửi tin nhắn qua Bot API.
"""

import logging
import pandas as pd
from telegram import Bot
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def _get_bot() -> Bot:
    """Lấy hoặc tạo singleton Bot instance."""
    global _bot
    if _bot is None:
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def send_message(text: str, chat_id: str | None = None) -> bool:
    """Gửi tin nhắn Markdown qua Telegram.

    Args:
        text: Nội dung tin nhắn (hỗ trợ Markdown).
        chat_id: ID chat nhận tin. Mặc định dùng TELEGRAM_CHAT_ID.

    Returns:
        True nếu gửi thành công, False nếu lỗi.
    """
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
    """Escape các ký tự đặc biệt trong Markdown.

    Args:
        text: Chuỗi cần escape.

    Returns:
        Chuỗi đã escape.
    """
    special = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def _rsi_label(rsi: float) -> str:
    """Trả về nhãn mô tả trạng thái RSI."""
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
    """Trả về nhãn xu hướng dựa trên SMA50/SMA200."""
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
    """Trả về nhãn volume so với trung bình 20 phiên."""
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
    """Trả về trạng thái MACD histogram (dương/âm)."""
    hist = row.get("macd_hist")
    signal = row.get("macd_signal")
    macd = row.get("macd")
    if pd.isna(hist) or pd.isna(macd) or pd.isna(signal):
        return ""
    if hist > 0:
        return "dương"
    return "âm"


def _bb_label(row) -> str:
    """Trả về vị trí giá so với Bollinger Bands."""
    close = row.get("close")
    upper = row.get("bb_upper")
    lower = row.get("bb_lower")
    if pd.isna(close) or pd.isna(upper) or pd.isna(lower):
        return ""
    if close >= upper:
        return "sát trên BB"
    if close <= lower:
        return "sát dưới BB"
    return ""


def _fmt(v) -> str:
    """Format số thành chuỗi 2 chữ số thập phân. Trả 'N/A' nếu NaN."""
    if pd.isna(v):
        return "N/A"
    return f"{v:.2f}"


def format_pre_market_report(potential: list, downtrend: list) -> str:
    """Định dạng báo cáo trước phiên (8:30 AM).

    Args:
        potential: Danh sách tín hiệu tiềm năng.
        downtrend: Danh sách tín hiệu downtrend.

    Returns:
        Chuỗi Markdown báo cáo.
    """
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
    """Định dạng báo cáo sau phiên (15:15 PM).

    Args:
        summary: List dict chứa symbol, change (%), vol_ratio, trend.

    Returns:
        Chuỗi Markdown báo cáo tổng kết.
    """
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


def format_stock_analysis(symbol: str, df: pd.DataFrame) -> str:
    """Phân tích chi tiết một mã chứng khoán.

    Hiển thị: giá, khung giá, KL, điểm vào lệnh, điểm chốt lời,
    hỗ trợ/kháng cự, chiến lược giao dịch, khuyến nghị.

    Args:
        symbol: Mã chứng khoán.
        df: DataFrame đã tính chỉ báo (ít nhất 2 dòng).

    Returns:
        Chuỗi Markdown báo cáo phân tích.
    """
    cur = df.iloc[-1]
    pre = df.iloc[-2]

    change_pct = ((cur["close"] - pre["close"]) / pre["close"]) * 100
    day_low = cur["low"]
    day_high = cur["high"]
    close = cur["close"]

    rsi = cur.get("rsi")
    macd_hist = cur.get("macd_hist")
    atr = cur.get("atr")
    sma20 = cur.get("ema_short")
    ema50 = cur.get("ema_long")
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
        sma20_str = f"Giá {'>' if close > sma20 else '<'} EMA20 ({_fmt(sma20)})"

    cross_str = ""
    if not pd.isna(sma50) and not pd.isna(sma200):
        if sma50 > sma200:
            cross_str = "Golden Cross: SMA50 > SMA200"
        else:
            cross_str = "Death Cross: SMA50 < SMA200"

    # ============== ENTRY SCORE (0-10) ==============
    entry_score = 0.0

    has_trend = not pd.isna(close) and not pd.isna(sma200)
    has_indicators = not pd.isna(rsi) and not pd.isna(macd_hist)

    if has_trend and has_indicators:
        # 1. Trend dài hạn (quan trọng nhất)
        if close > sma200:
            entry_score += 3.0
        else:
            entry_score -= 2.0

        # 2. Pullback discount: trong uptrend, giá < EMA20 = entry đẹp
        if close > sma200:
            if not pd.isna(sma20) and close < sma20:
                entry_score += 2.0
            elif not pd.isna(sma20):
                entry_score += 0.5

        # 3. Cross SMA50/SMA200
        if not pd.isna(sma50) and not pd.isna(sma200):
            if sma50 > sma200:
                entry_score += 1.0
            else:
                entry_score -= 1.0

        # 4. MACD momentum
        if not pd.isna(macd_hist):
            if macd_hist > 0:
                entry_score += 1.0
            else:
                entry_score -= 0.5

        # 5. RSI sweet spot
        if not pd.isna(rsi):
            if 40 <= rsi <= 55:
                entry_score += 1.0
            elif rsi > 70 or rsi < 20:
                entry_score -= 1.0

    entry_score = max(0, min(10, entry_score))
    entry_str = f"{entry_score:.1f}/10"
    entry_icon = "✅" if entry_score >= 6 else "⏳" if entry_score >= 4 else "❌"

    # ============== RISK SCORE (0-10) ==============
    risk_score = 5.0
    rr1 = 0.0
    sl_pct = 0.0

    atr_val = atr if not pd.isna(atr) else 0
    if atr_val > 0 and close > 0:
        sl_pct = (atr_val * 1.5 / close) * 100
        risk_amt = atr_val * 1.5
        tp1_profit = atr_val * 2
        tp2_profit = atr_val * 3
        rr1 = tp1_profit / risk_amt if risk_amt > 0 else 0
        rr2 = tp2_profit / risk_amt if risk_amt > 0 else 0

        # SL distance
        if sl_pct <= 2.0:
            risk_score += 2.0
        elif sl_pct <= 3.5:
            risk_score += 1.5
        elif sl_pct <= 5.0:
            risk_score += 0.5
        else:
            risk_score -= 1.0

        # R:R ratio
        if rr1 >= 2.0:
            risk_score += 2.0
        elif rr1 >= 1.5:
            risk_score += 1.0
        else:
            risk_score -= 1.0

        # Volatility
        atr_pct = (atr_val / close) * 100
        if 1.0 <= atr_pct <= 4.0:
            risk_score += 1.0
        elif atr_pct > 7.0:
            risk_score -= 1.0

        # BB position
        if not pd.isna(close) and not pd.isna(bb_mid):
            if close < bb_mid:
                risk_score += 0.5
            if not pd.isna(bb_lower) and close <= bb_lower * 1.03:
                risk_score += 0.5

    risk_score = max(0, min(10, risk_score))
    risk_icon = "✅" if risk_score >= 6 else "⚪" if risk_score >= 4 else "🔴"

    # ============== KHOẢNG CHỐT LỜI ==============
    sl = close - atr_val * 1.5 if close > 0 else 0
    tp1 = close + atr_val * 2
    tp2 = close + atr_val * 3

    # ============== FIBONACCI ==============
    if not pd.isna(sma200):
        if close > sma200:
            fib_382 = close - (close - sma200) * 0.382
            fib_618 = close - (close - sma200) * 0.618
            fib_100 = sma200
        else:
            fib_382 = close + (sma200 - close) * 0.382
            fib_618 = close + (sma200 - close) * 0.618
            fib_100 = sma200
    else:
        fib_382 = fib_618 = fib_100 = 0

    # ============== SUPPORT/RESISTANCE ==============
    support = bb_lower if not pd.isna(bb_lower) else day_low
    resistance = cur.get("bb_upper", day_high)

    # ============== RECOMMENDATION ==============
    rec = "CHƯA NÊN MUA"
    rec_icon = "🔴"
    if entry_score >= 7 and risk_score >= 6:
        rec = "CÓ THỂ MUA"
        rec_icon = "🟢"
    elif entry_score >= 6 and risk_score >= 5:
        rec = "CÓ THỂ MUA"
        rec_icon = "🟢"
    elif entry_score >= 5:
        rec = "THEO DÕI"
        rec_icon = "🟡"
    elif entry_score >= 4:
        rec = "THEO DÕI"
        rec_icon = "🟡"

    # ============== FORMAT CHUỖI PHẦN TỬ PHỤ ==============
    _bb_mid_str = ""
    if not pd.isna(close) and not pd.isna(bb_mid):
        if close < bb_mid:
            _bb_mid_str = "Giá dưới BB Mid"
            if not pd.isna(bb_lower) and close <= bb_lower * 1.03:
                _bb_mid_str += " - Sát BB Lower"
        else:
            _bb_mid_str = "Giá trên BB Mid"

    vol_str = f"{cur['volume']:,.0f}".replace(",", ".")

    lines = [
        f"🔔 *{symbol}: {_fmt(close)}đ* ({change_pct:+.2f}%) — {pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').strftime('%H:%M %d/%m')}",
        "━" * 35,
        "",
        f"💹 *Giá:* {_fmt(close)}đ  {'🔴' if change_pct < 0 else '🟢'} {change_pct:+.2f}%",
        f"📈 Khung: {_fmt(day_low)} - {_fmt(day_high)}",
        f"📊 KL: {vol_str}",
        "",
        "━" * 35,
        "",
        f"🎯 *ĐIỂM VÀO LỆNH:* {entry_str} {entry_icon}",
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
    lines.append(f"💰 *ĐIỂM RỦI RO:* {risk_score:.1f}/10 {risk_icon}")
    if atr_val > 0 and close > 0:
        lines.append(f"  • Khoảng chốt lời: {_fmt(tp1)}đ - {_fmt(tp2)}đ")
        lines.append(f"  • R:R = {rr1:.1f} | SL: {sl_pct:.1f}%")
    if _bb_mid_str:
        lines.append(f"  • {_bb_mid_str}")
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
        lines.append(f"  • Cắt lỗ: {_fmt(sl)}đ ({sl_pct:.1f}%)")
        lines.append(f"  • Target 1 (2xATR): {_fmt(tp1)}đ (RR {rr1:.1f})")
        lines.append(f"  • Target 2 (3xATR): {_fmt(tp2)}đ")
    if not pd.isna(sma200) and sma200 > 0:
        lines.append(f"  • Fib 0.382: {_fmt(fib_382)}đ")
        lines.append(f"  • Fib 0.618: {_fmt(fib_618)}đ")
        lines.append(f"  • Fib 1.0 (SMA200): {_fmt(fib_100)}đ")
    if not pd.isna(rsi):
        lines.append(f"  • RSI: {_fmt(rsi)}")
    if not pd.isna(atr):
        atr_pct = (atr_val / close) * 100 if close > 0 else 0
        lines.append(f"  • ATR: {_fmt(atr)} ({atr_pct:.1f}%)")

    lines.append("")
    lines.append(f"{rec_icon} *KHUYẾN NGHỊ:* {rec}")
    lines.append("")

    # === THỜI GIAN NẮM GIỮ ===
    timeframes = _timeframe_recommendation(cur)
    lines.append("⏳ *THỜI GIAN NẮM GIỮ*")
    for name, verdict, reason in timeframes:
        lines.append(f"  {verdict}")
        if reason:
            lines.append(f"    └ {reason}")

    lines.append("=" * 35)
    return "\n".join(lines)


def _timeframe_recommendation(cur: pd.Series) -> list:
    """Đánh giá khuyến nghị theo 3 khung thời gian: T+, ngắn hạn, dài hạn.

    Returns:
        List [tplus_rec, short_rec, long_rec] với tuple (label, icon, reason).
    """
    close = cur.get("close")
    rsi = cur.get("rsi")
    macd_hist = cur.get("macd_hist")
    ema20 = cur.get("ema_short")
    ema50 = cur.get("ema_long")
    sma50 = cur.get("sma_50")
    sma200 = cur.get("sma_200")
    bb_mid = cur.get("bb_middle")
    bb_lower = cur.get("bb_lower")

    # ---- T+ (1-3 ngày): momentum ngắn hạn ----
    tplus_score = 0
    tplus_reasons = []

    if not pd.isna(close) and not pd.isna(ema20):
        if close > ema20:
            tplus_score += 1
            tplus_reasons.append("Giá trên EMA20")
        else:
            tplus_score -= 1
    if not pd.isna(macd_hist) and macd_hist > 0:
        tplus_score += 1
        tplus_reasons.append("MACD dương")
    if not pd.isna(rsi):
        if 30 <= rsi <= 65:
            tplus_score += 1
            tplus_reasons.append("RSI hợp lý")
        elif rsi > 75:
            tplus_score -= 1
            tplus_reasons.append("RSI quá mua")
    if not pd.isna(close) and not pd.isna(bb_lower):
        if close <= bb_lower * 1.03:
            tplus_score += 1
            tplus_reasons.append("Sát BB Lower")

    if tplus_score >= 2:
        tplus = ("🟢 CÓ THỂ PLAY", " ".join(tplus_reasons[:2]))
    elif tplus_score >= 1:
        tplus = ("🟡 ĐỢI XÁC NHẬN", " ".join(tplus_reasons[:2]))
    else:
        tplus = ("🔴 KHÔNG PLAY", " ".join(tplus_reasons[:2]) if tplus_reasons else "Momentum yếu")

    # ---- Ngắn hạn (1-2 tuần): trend trung hạn ----
    short_score = 0
    short_reasons = []

    if not pd.isna(close) and not pd.isna(ema50):
        if close > ema50:
            short_score += 1
            short_reasons.append("Giá trên EMA50")
        else:
            short_score -= 1
    if not pd.isna(sma50) and not pd.isna(sma200):
        if sma50 > sma200:
            short_score += 1
            short_reasons.append("Golden Cross")
        else:
            short_score -= 1
            short_reasons.append("Death Cross")
    if not pd.isna(close) and not pd.isna(bb_mid):
        if close < bb_mid:
            short_score += 1
            short_reasons.append("Dưới BB Mid")
        else:
            short_reasons.append("Trên BB Mid")
    if not pd.isna(rsi) and 40 <= rsi <= 65:
        short_score += 1
        short_reasons.append("RSI ổn định")

    if short_score >= 3:
        short = ("🟢 NÊN MUA", " ".join(short_reasons[:2]))
    elif short_score >= 1:
        short = ("🟡 THEO DÕI", " ".join(short_reasons[:2]))
    else:
        short = ("🔴 KHÔNG NÊN", " ".join(short_reasons[:2]) if short_reasons else "Xu hướng yếu")

    # ---- Dài hạn (1-3 tháng): trend dài hạn ----
    long_score = 0
    long_reasons = []

    if not pd.isna(close) and not pd.isna(sma200):
        if close > sma200:
            long_score += 2
            long_reasons.append("Uptrend SMA200")
        else:
            long_score -= 2
            long_reasons.append("Downtrend SMA200")
    if not pd.isna(sma50) and not pd.isna(sma200):
        if sma50 > sma200:
            long_score += 1
            long_reasons.append("SMA50 > SMA200")
        else:
            long_score -= 1
    if not pd.isna(rsi) and not pd.isna(sma200):
        if 45 <= rsi <= 70 and not pd.isna(close) and close > sma200:
            long_score += 1
            long_reasons.append("RSI mạnh trong uptrend")
        elif rsi < 35 and not pd.isna(close) and close > sma200:
            long_score += 1
            long_reasons.append("RSI thấp + uptrend = pullback")

    if long_score >= 3:
        long = ("🟢 NÊN GIỮ/MUA", " ".join(long_reasons[:2]))
    elif long_score >= 1:
        long = ("🟡 GIỮ XEM", " ".join(long_reasons[:2]))
    else:
        long = ("🔴 KHÔNG MUA DÀI", " ".join(long_reasons[:2]) if long_reasons else "Xu hướng dài hạn yếu")

    return [("T+ (1-3 ngày)", tplus[0], tplus[1]),
            ("Ngắn hạn (1-2 tuần)", short[0], short[1]),
            ("Dài hạn (1-3 tháng)", long[0], long[1])]


def format_session_report(data: dict, signals: list) -> str:
    """Định dạng báo cáo giữa phiên.

    Gộp phân tích top 5 mã biến động mạnh nhất + danh sách tín hiệu mới.

    Args:
        data: Dict {symbol: DataFrame} với chỉ báo.
        signals: List tín hiệu mới phát hiện.

    Returns:
        Chuỗi Markdown báo cáo.
    """
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

    for symbol, df, _ in sorted_items[:5]:
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

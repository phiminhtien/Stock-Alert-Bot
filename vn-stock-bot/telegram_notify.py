"""Gửi thông báo Telegram và định dạng báo cáo phân tích kỹ thuật chuyên sâu.

Sử dụng python-telegram-bot (async) để gửi tin nhắn qua Bot API.
Tích hợp:
- MACD (12, 26, 9): Histogram, Golden/Death Cross, động lượng.
- Bollinger Bands (10, 2): Squeeze, %B, tiếp xúc dải trên/dưới.
- Fibonacci: Retracement 0.382, 0.500, 0.618, 1.000.
- Đường Trendline & Xu hướng: Hỗ trợ/Kháng cự động, khoảng cách tới giá.
- Số nhịp tăng/giảm liên tiếp & Tỷ lệ nến tăng/giảm 20 phiên.
"""

import logging
import pandas as pd
from telegram import Bot
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from signals import _compute_entry_score

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
    """Escape các ký tự đặc biệt trong Markdown."""
    special = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def _fmt(v) -> str:
    """Format số thành chuỗi 2 chữ số thập phân. Trả 'N/A' nếu NaN."""
    if pd.isna(v):
        return "N/A"
    return f"{float(v):.2f}"


def _rsi_label(rsi: float) -> str:
    """Trả về nhãn mô tả trạng thái RSI."""
    if pd.isna(rsi):
        return "N/A"
    if rsi <= 30:
        return "quá bán"
    if rsi >= 70:
        return "quá mua"
    if rsi < 40:
        return "yếu"
    if rsi > 60:
        return "mạnh"
    return "trung tính"


def _macd_label(row) -> str:
    """Trả về trạng thái MACD (12, 26, 9) và giao cắt."""
    hist = row.get("macd_hist")
    signal = row.get("macd_signal")
    macd = row.get("macd")
    if pd.isna(hist) or pd.isna(macd) or pd.isna(signal):
        return "N/A"
    parts = []
    if row.get("macd_bullish_cross", False):
        parts.append("Golden Cross (cắt lên) 🔥")
    elif row.get("macd_bearish_cross", False):
        parts.append("Death Cross (cắt xuống) ⚠️")
    if hist > 0:
        parts.append(f"Hist dương (+{hist:.2f})")
    else:
        parts.append(f"Hist âm ({hist:.2f})")
    return " | ".join(parts)


def _bb_label(row) -> str:
    """Trả về vị trí giá so với Bollinger Bands (10, 2)."""
    pct_b = row.get("bb_percent_b")
    squeeze = row.get("bb_squeeze", False)
    parts = []
    if squeeze:
        parts.append("Nén hẹp (Squeeze) ⚡")
    if not pd.isna(pct_b):
        if pct_b >= 1.0:
            parts.append("Vượt biên trên (Quá mua)")
        elif pct_b >= 0.8:
            parts.append("Sát biên trên")
        elif pct_b <= 0.0:
            parts.append("Thủng biên dưới (Quá bán)")
        elif pct_b <= 0.2:
            parts.append("Sát biên dưới (Hỗ trợ)")
        else:
            parts.append(f"%B={pct_b:.2f}")
    return " - ".join(parts) if parts else "Bình thường"


def _consecutive_label(row) -> str:
    """Trả về chuỗi số phiên tăng hoặc giảm liên tiếp."""
    u = row.get("consec_up", 0)
    d = row.get("consec_down", 0)
    if u > 0:
        return f"{int(u)} phiên tăng liên tiếp 🔥"
    elif d > 0:
        return f"{int(d)} phiên giảm liên tiếp ❄️"
    return "Đi ngang"


def _trendline_label(row) -> str:
    """Trả về chuỗi hỗ trợ / kháng cự từ đường Trendline."""
    close = row.get("close")
    supp = row.get("trendline_support")
    res = row.get("trendline_resistance")
    parts = []
    if not pd.isna(supp) and not pd.isna(close) and supp > 0:
        dist_supp = ((close - supp) / supp) * 100
        parts.append(f"Hỗ trợ: {_fmt(supp)}đ ({dist_supp:+.1f}%)")
    if not pd.isna(res) and not pd.isna(close) and close > 0:
        dist_res = ((res - close) / close) * 100
        parts.append(f"Kháng cự: {_fmt(res)}đ (+{dist_res:.1f}%)")
    return " | ".join(parts) if parts else "N/A"


def format_pre_market_report(potential: list, downtrend: list) -> str:
    """Định dạng báo cáo trước phiên (8:30 AM)."""
    lines = ["*[TRƯỚC PHIÊN]* Báo cáo tổng hợp đầu ngày"]
    lines.append("")
    if potential:
        lines.append(f"*📈 Cổ phiếu tiềm năng tích lũy ({len(potential)}):*")
        for s in potential:
            rsi = s.get("rsi", "N/A")
            reason = s.get("reason", "")
            lines.append(f"  • *{s['symbol']}* — giá {s.get('price','?')}đ | RSI {rsi} | {reason}")
    if downtrend:
        lines.append("")
        lines.append(f"*📉 Cổ phiếu downtrend / rủi ro ({len(downtrend)}):*")
        for s in downtrend:
            rsi = s.get("rsi", "N/A")
            reason = s.get("reason", "")
            lines.append(f"  • *{s['symbol']}* — giá {s.get('price','?')}đ | RSI {rsi} | {reason}")
    if not potential and not downtrend:
        lines.append("Không có tín hiệu kỹ thuật đặc biệt.")
    lines.append("")
    lines.append("— Bot hỗ trợ đầu tư —")
    return "\n".join(lines)


def format_post_market_report(summary: list) -> str:
    """Định dạng báo cáo sau phiên (15:15 PM)."""
    lines = ["*[SAU PHIÊN]* Tổng kết phiên giao dịch"]
    lines.append("")
    for item in summary:
        change = item.get("change", 0)
        emoji = "🟢" if change > 0 else "🔴"
        vol_str = f"VOL {item.get('vol_ratio','')}" if item.get("vol_ratio") else ""
        trend_str = f" | {item['trend']}" if item.get("trend") else ""
        lines.append(f"  {emoji} *{item['symbol']}*: {change:+.2f}%{trend_str} {vol_str}")
    lines.append("")
    lines.append("— Bot hỗ trợ đầu tư —")
    return "\n".join(lines)


def format_signal_alert(sig: dict) -> str:
    """Định dạng tin nhắn cảnh báo tín hiệu giao dịch riêng lẻ trong phiên."""
    stype = sig.get("type", "alert")
    symbol = sig.get("symbol", "?")
    price = sig.get("price", 0)
    reason = sig.get("reason", "")
    strategy = sig.get("strategy", "")
    sl = sig.get("stop_loss")
    tp = sig.get("take_profit")

    if stype == "entry":
        lines = [f"🟢 *[TÍN HIỆU MUA] {symbol}* — Giá: {_fmt(price)}đ"]
        if strategy:
            lines.append(f"  🎯 *Chiến lược:* {strategy}")
        if sl and tp:
            lines.append(f"  🛡️ *Cắt lỗ:* {_fmt(sl)}đ | 🎯 *Mục tiêu:* {_fmt(tp)}đ")
        if reason:
            lines.append(f"  💡 *Căn cứ:* {reason}")
        return "\n".join(lines)
    elif stype == "take_profit":
        lines = [f"💰 *[CẢNH BÁO CHỐT LỜI] {symbol}* — Giá: {_fmt(price)}đ"]
        if reason:
            lines.append(f"  ⚠️ *Căn cứ:* {reason}")
        return "\n".join(lines)
    elif stype == "potential":
        rsi = sig.get("rsi", "N/A")
        lines = [f"📈 *[TIỀM NĂNG TÍCH LŨY] {symbol}* — Giá: {_fmt(price)}đ | RSI: {rsi}"]
        if reason:
            lines.append(f"  💡 *Căn cứ:* {reason}")
        return "\n".join(lines)
    elif stype == "downtrend":
        rsi = sig.get("rsi", "N/A")
        lines = [f"📉 *[CẢNH BÁO RỦI RO / DOWNTREND] {symbol}* — Giá: {_fmt(price)}đ | RSI: {rsi}"]
        if reason:
            lines.append(f"  ⚠️ *Căn cứ:* {reason}")
        return "\n".join(lines)
    else:
        lines = [f"🔔 *[{stype.upper()}] {symbol}* — {_fmt(price)}đ"]
        if reason:
            lines.append(f"  └ {reason}")
        return "\n".join(lines)


def format_stock_analysis(symbol: str, df: pd.DataFrame) -> str:
    """Phân tích chi tiết một mã chứng khoán theo bộ chỉ báo kỹ thuật nâng cao.

    Hiển thị:
    - Giá, biên độ, khối lượng, nhịp nến tăng/giảm liên tiếp.
    - Điểm vào lệnh & Điểm rủi ro (0-10).
    - MACD (12, 26, 9) và Bollinger Bands (10, 2).
    - Đường Trendline hỗ trợ / kháng cự và các mốc Fibonacci Retracement.
    - Chiến lược giao dịch & Khuyến nghị khung thời gian (T+, Ngắn hạn, Dài hạn).

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
    macd = cur.get("macd")
    signal = cur.get("macd_signal")
    macd_hist = cur.get("macd_hist")
    atr = cur.get("atr")
    sma50 = cur.get("sma_50")
    sma200 = cur.get("sma_200")
    bb_upper = cur.get("bb_upper")
    bb_mid = cur.get("bb_middle")
    bb_lower = cur.get("bb_lower")
    pct_b = cur.get("bb_percent_b")
    t_supp = cur.get("trendline_support")
    t_res = cur.get("trendline_resistance")

    # Format RSI & MACD
    rsi_lbl = _rsi_label(rsi)
    rsi_str = f"RSI(14): {rsi:.2f} ({rsi_lbl})" if not pd.isna(rsi) else "RSI(14): N/A"
    macd_str = f"MACD(12,26,9): {_fmt(macd)} | Sig: {_fmt(signal)} ({_macd_label(cur)})"

    # Format BB(10, 2)
    bb_str = f"BB(10,2): {_fmt(bb_lower)} - {_fmt(bb_mid)} - {_fmt(bb_upper)}đ ({_bb_label(cur)})"

    # Format Trend & Trendline
    trend_str = ""
    if not pd.isna(sma200) and not pd.isna(close):
        if close > sma200:
            trend_str = f"Uptrend (Giá > SMA200: {_fmt(sma200)}đ)"
        else:
            trend_str = f"Downtrend (Giá < SMA200: {_fmt(sma200)}đ)"
    else:
        trend_str = "Xu hướng: N/A"

    cross_str = ""
    if not pd.isna(sma50) and not pd.isna(sma200):
        if sma50 > sma200:
            cross_str = "Golden Cross: SMA50 > SMA200"
        else:
            cross_str = "Death Cross: SMA50 < SMA200"

    tline_str = f"Trendline: {_trendline_label(cur)}"

    # Format Consecutive bars
    bars_str = _consecutive_label(cur)
    up20 = cur.get("up_days_20")
    down20 = cur.get("down_days_20")
    if not pd.isna(up20) and not pd.isna(down20):
        bars_str += f" (20 phiên: {int(up20)} tăng / {int(down20)} giảm)"

    # ENTRY SCORE (0-10)
    entry_score = _compute_entry_score(cur)
    entry_str = f"{entry_score:.1f}/10"
    entry_icon = "✅" if entry_score >= 6.0 else "⏳" if entry_score >= 4.0 else "❌"

    # RISK SCORE (0-10)
    atr_val = atr if not pd.isna(atr) else (close * 0.03)
    sl = close - atr_val * 1.5 if close > 0 else 0
    sl_pct = (atr_val * 1.5 / close) * 100 if close > 0 else 0
    tp1 = close + atr_val * 2
    tp2 = close + atr_val * 3
    rr1 = 2.0 / 1.5  # ~1.33

    risk_score = 5.0
    if sl_pct <= 2.5:
        risk_score += 2.0
    elif sl_pct <= 4.0:
        risk_score += 1.0
    else:
        risk_score -= 1.0

    if not pd.isna(pct_b):
        if 0.1 <= pct_b <= 0.55:
            risk_score += 1.5
        elif pct_b > 0.85:
            risk_score -= 1.5

    if not pd.isna(rsi) and rsi < 65:
        risk_score += 1.0
    elif not pd.isna(rsi) and rsi > 70:
        risk_score -= 1.5

    risk_score = max(0.0, min(10.0, risk_score))
    risk_icon = "✅" if risk_score >= 6.0 else "⚪" if risk_score >= 4.0 else "🔴"

    # Fibonacci (Lookback 120D)
    swing_h = cur.get("swing_high_120")
    swing_l = cur.get("swing_low_120")
    if pd.isna(swing_h) or swing_h == 0:
        swing_h = day_high
    if pd.isna(swing_l) or swing_l == 0:
        swing_l = day_low

    fib_382 = cur.get("fib_382", swing_h)
    fib_500 = cur.get("fib_500", (swing_h + swing_l) / 2)
    fib_618 = cur.get("fib_618", swing_l)

    # Support / Resistance
    supp_candidates = [x for x in [bb_lower, t_supp, fib_618, swing_l] if not pd.isna(x) and x <= close]
    res_candidates = [x for x in [bb_upper, t_res, fib_382, swing_h] if not pd.isna(x) and x >= close]
    support = max(supp_candidates) if supp_candidates else (bb_lower if not pd.isna(bb_lower) else day_low)
    resistance = min(res_candidates) if res_candidates else (bb_upper if not pd.isna(bb_upper) else day_high)

    # Recommendation
    if entry_score >= 6.5 and risk_score >= 5.5:
        rec = "CÓ THỂ MUA"
        rec_icon = "🟢"
    elif entry_score >= 5.0:
        rec = "THEO DÕI TÍCH LŨY"
        rec_icon = "🟡"
    else:
        rec = "CHƯA NÊN MUA"
        rec_icon = "🔴"

    vol_str = f"{cur['volume']:,.0f}".replace(",", ".")
    time_str = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%H:%M %d/%m")

    lines = [
        f"🔔 *{symbol}: {_fmt(close)}đ* ({change_pct:+.2f}%) — {time_str}",
        "━" * 32,
        "",
        f"💹 *Giá:* {_fmt(close)}đ  {'🔴' if change_pct < 0 else '🟢'} {change_pct:+.2f}%",
        f"📈 Biên độ: {_fmt(day_low)} - {_fmt(day_high)}",
        f"📊 Khối lượng: {vol_str}",
        f"⏳ Nhịp nến: {bars_str}",
        "",
        "━" * 32,
        "",
        f"🎯 *ĐIỂM VÀO LỆNH:* {entry_str} {entry_icon}",
        f"  • {macd_str}",
        f"  • {bb_str}",
        f"  • {tline_str}",
        f"  • {trend_str}",
        f"  • {rsi_str}",
    ]
    if cross_str:
        lines.append(f"  • {cross_str}")

    lines.extend([
        "",
        f"💰 *ĐIỂM RỦI RO:* {risk_score:.1f}/10 {risk_icon}",
        f"  • Cắt lỗ đề xuất: {_fmt(sl)}đ ({sl_pct:.1f}%)",
        f"  • Target 1 (2xATR): {_fmt(tp1)}đ (RR {rr1:.1f})",
        f"  • Target 2 (3xATR): {_fmt(tp2)}đ",
        "",
        "━" * 32,
        "",
        "📍 *HỖ TRỢ / KHÁNG CỰ & FIBONACCI*",
        f"  • Hỗ trợ gần: {_fmt(support)}đ",
        f"  • Kháng cự gần: {_fmt(resistance)}đ",
        f"  • Fib 0.382: {_fmt(fib_382)}đ | Fib 0.500: {_fmt(fib_500)}đ",
        f"  • Fib 0.618 (Vùng vàng): {_fmt(fib_618)}đ",
        f"  • Đáy/Đỉnh 120D: {_fmt(swing_l)}đ - {_fmt(swing_h)}đ",
        "",
        f"{rec_icon} *KHUYẾN NGHỊ:* {rec}",
        "",
        "⏳ *THỜI GIAN NẮM GIỮ*",
    ])

    for name, verdict, reason in _timeframe_recommendation(cur):
        lines.append(f"  {verdict} ({name})")
        if reason:
            lines.append(f"    └ {reason}")

    lines.append("=" * 32)
    return "\n".join(lines)


def _timeframe_recommendation(cur: pd.Series) -> list:
    """Đánh giá khuyến nghị theo 3 khung thời gian: T+, ngắn hạn, dài hạn."""
    close = cur.get("close")
    rsi = cur.get("rsi")
    macd_hist = cur.get("macd_hist")
    macd = cur.get("macd")
    signal = cur.get("macd_signal")
    cross_up = cur.get("macd_bullish_cross", False)
    sma50 = cur.get("sma_50")
    sma200 = cur.get("sma_200")
    bb_mid = cur.get("bb_middle")
    bb_lower = cur.get("bb_lower")
    pct_b = cur.get("bb_percent_b")
    consec_up = cur.get("consec_up", 0)
    consec_down = cur.get("consec_down", 0)
    t_supp = cur.get("trendline_support")
    fib_618 = cur.get("fib_618")

    # ---- 1. T+ (1-3 ngày): Động lượng ngắn hạn MACD & BB(10,2) ----
    tplus_score = 0
    tplus_reasons = []

    if cross_up or (not pd.isna(macd) and not pd.isna(signal) and macd > signal):
        tplus_score += 1.5
        tplus_reasons.append("MACD đà tăng")
    elif not pd.isna(macd_hist) and macd_hist > 0:
        tplus_score += 1.0
        tplus_reasons.append("Histogram dương")

    if not pd.isna(pct_b):
        if 0.1 <= pct_b <= 0.6:
            tplus_score += 1.0
            tplus_reasons.append("Vị thế BB(10,2) đẹp")
        elif pct_b < 0.1 or (not pd.isna(bb_lower) and close <= bb_lower * 1.02):
            tplus_score += 1.0
            tplus_reasons.append("Chạm đáy BB(10,2)")
        elif pct_b >= 0.9:
            tplus_score -= 1.0
            tplus_reasons.append("Sát đỉnh BB(10,2)")

    if 1 <= consec_up <= 2:
        tplus_score += 0.5
        tplus_reasons.append("Đầu nhịp tăng")
    elif consec_down >= 3:
        tplus_score += 0.5
        tplus_reasons.append("Sau chuỗi giảm")
    elif consec_up >= 4:
        tplus_score -= 1.0
        tplus_reasons.append("Tăng nhiều phiên (tránh FOMO)")

    if not pd.isna(rsi):
        if 35 <= rsi <= 65:
            tplus_score += 0.5
        elif rsi > 70:
            tplus_score -= 1.0
            tplus_reasons.append("RSI quá mua")

    if tplus_score >= 2.5:
        tplus = ("🟢 CÓ THỂ PLAY", " | ".join(tplus_reasons[:2]))
    elif tplus_score >= 1.0:
        tplus = ("🟡 ĐỢI XÁC NHẬN", " | ".join(tplus_reasons[:2]))
    else:
        tplus = ("🔴 KHÔNG NÊN PLAY", " | ".join(tplus_reasons[:2]) if tplus_reasons else "Động lượng suy yếu")

    # ---- 2. Ngắn hạn (1-2 tuần): Trendline & BB Mid SMA10 & Fibonacci ----
    short_score = 0
    short_reasons = []

    if not pd.isna(close) and not pd.isna(bb_mid):
        if close >= bb_mid:
            short_score += 1.5
            short_reasons.append("Trên BB Mid (SMA10)")
        else:
            short_score -= 1.0
            short_reasons.append("Dưới BB Mid")

    if not pd.isna(t_supp) and not pd.isna(close):
        if close >= t_supp * 0.99:
            short_score += 1.0
            short_reasons.append("Giữ Trendline hỗ trợ")
        else:
            short_score -= 1.0
            short_reasons.append("Gãy Trendline hỗ trợ")

    if not pd.isna(fib_618) and not pd.isna(close):
        if close >= fib_618 * 0.99:
            short_score += 1.0
            short_reasons.append("Trên vùng Fib 0.618")

    if not pd.isna(macd) and not pd.isna(signal) and macd > signal:
        short_score += 0.5

    if short_score >= 2.5:
        short = ("🟢 NÊN MUA/NẮM GIỮ", " | ".join(short_reasons[:2]))
    elif short_score >= 1.0:
        short = ("🟡 THEO DÕI", " | ".join(short_reasons[:2]))
    else:
        short = ("🔴 KHÔNG NÊN", " | ".join(short_reasons[:2]) if short_reasons else "Xu hướng ngắn hạn yếu")

    # ---- 3. Dài hạn (1-3 tháng): Uptrend SMA200 & SMA50 ----
    long_score = 0
    long_reasons = []

    if not pd.isna(close) and not pd.isna(sma200):
        if close > sma200:
            long_score += 2.0
            long_reasons.append("Uptrend SMA200")
        else:
            long_score -= 2.0
            long_reasons.append("Downtrend SMA200")

    if not pd.isna(sma50) and not pd.isna(sma200):
        if sma50 > sma200:
            long_score += 1.0
            long_reasons.append("Golden Cross (SMA50 > SMA200)")
        else:
            long_score -= 1.0
            long_reasons.append("Death Cross (SMA50 < SMA200)")

    if long_score >= 2.0:
        long = ("🟢 NÊN TÍCH LŨY/GIỮ", " | ".join(long_reasons[:2]))
    elif long_score >= 0.0:
        long = ("🟡 QUAN SÁT THÊM", " | ".join(long_reasons[:2]))
    else:
        long = ("🔴 KHÔNG NÊN MUA DÀI", " | ".join(long_reasons[:2]) if long_reasons else "Xu hướng dài hạn tiêu cực")

    return [("T+ (1-3 ngày)", tplus[0], tplus[1]),
            ("Ngắn hạn (1-2 tuần)", short[0], short[1]),
            ("Dài hạn (1-3 tháng)", long[0], long[1])]


def format_session_report(data: dict, signals: list) -> str:
    """Định dạng báo cáo giữa phiên."""
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
            lines.append(format_signal_alert(s))
            lines.append("")

    lines.append("— Bot hỗ trợ đầu tư —")
    return "\n".join(lines)

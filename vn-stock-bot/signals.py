"""Logic sinh tín hiệu giao dịch và cảnh báo giá dựa trên phân tích kỹ thuật đa chỉ báo.

Trọng tâm:
- MACD (12, 26, 9): Tín hiệu giao cắt Bullish/Bearish Cross, phân kỳ, động lực Histogram.
- Bollinger Bands (10, 2): Đảo chiều từ dải dưới (Lower), bám dải (Upper), co thắt dải (Squeeze) và bung nén.
- Đường Trendline & Xu hướng: Hỗ trợ/kháng cự động qua các đỉnh/đáy pivot, kiểm tra Uptrend/Downtrend.
- Fibonacci Retracement (0.382, 0.5, 0.618, 1.0): Xác định vùng thoái lui vàng và mục tiêu giá.
- Số nhịp tăng / Số nhịp giảm: Đếm số phiên tăng/giảm liên tiếp để tránh FOMO đỉnh và nhận diện nhịp hồi tạo đáy.
"""

import logging
import pandas as pd
from typing import List, Dict
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    ATR_STOP_LOSS_FACTOR, MIN_RR_RATIO,
    VOLUME_SPIKE_RATIO, EMA_SHORT, EMA_LONG,
    CONSECUTIVE_BARS_ALERT,
)

logger = logging.getLogger(__name__)


def _volume_spike(row: pd.Series, ratio: float = VOLUME_SPIKE_RATIO) -> bool:
    """Kiểm tra khối lượng có đột biến so với trung bình 20 phiên."""
    vol_ma = row.get("volume_ma")
    vol = row.get("volume", 0)
    return not pd.isna(vol_ma) and vol_ma > 0 and vol >= vol_ma * ratio


def _is_uptrend(row: pd.Series) -> bool:
    """Kiểm tra xu hướng tăng: Giá đóng cửa > SMA50 hoặc SMA200."""
    close = row.get("close")
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    if pd.isna(close):
        return False
    if not pd.isna(sma200) and close > sma200:
        return True
    if not pd.isna(sma50) and close > sma50:
        return True
    return False


def _is_downtrend(row: pd.Series) -> bool:
    """Kiểm tra xu hướng giảm: Giá đóng cửa < SMA50 và SMA200."""
    close = row.get("close")
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    if pd.isna(close) or pd.isna(sma50) or pd.isna(sma200):
        return False
    return close < sma50 and close < sma200


def detect_entry(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện các tín hiệu mua (entry alert).

    Các chiến lược cảnh báo:
    1. MACD Bullish Cross + Bollinger (10, 2) Rebound:
       - MACD vừa cắt lên Signal line (hoặc chuyển sang Histogram dương).
       - Giá ở nửa dưới dải BB(10,2) (%B <= 0.6) hoặc bật nảy từ dải dưới.
    2. Bollinger Band (10, 2) Squeeze Breakout:
       - Dải BB nén hẹp (Squeeze) trước đó, phiên nay nổ Volume bứt phá qua dải trên.
       - MACD Histogram dương và mở rộng.
    3. Bắt đáy rút chân sau chuỗi giảm (Oversold Bounce):
       - Giảm liên tiếp >= 3 phiên (consec_down >= 3).
       - Chạm/thủng BB Lower (10, 2) rồi rút chân nến xanh.
       - Gặp hỗ trợ Fibonacci (0.5 - 0.618) hoặc Trendline hỗ trợ.
       - MACD Histogram bắt đầu co hẹp đà giảm.
    4. Breakout đường Trendline kháng cự giảm:
       - Giá vượt qua đường Trendline kháng cự.
       - Giá nằm trên BB Middle (SMA10) và MACD > Signal.

    Returns:
        Mỗi tín hiệu gồm: symbol, type="entry", price, stop_loss, take_profit, strategy, reason.
    """
    signals = []
    if len(df) < 5:
        return signals

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    atr = curr.get("atr", 0) if not pd.isna(curr.get("atr")) else curr["close"] * 0.03
    close = curr["close"]

    # 1. Chiến lược MACD Bullish Cross + Bollinger (10, 2) Rebound
    macd_crossed_up = (
        curr.get("macd_bullish_cross", False)
        or (
            not pd.isna(prev.get("macd")) and not pd.isna(prev.get("macd_signal"))
            and prev["macd"] <= prev["macd_signal"]
            and curr.get("macd", 0) > curr.get("macd_signal", 0)
        )
    )
    pct_b = curr.get("bb_percent_b", 0.5)
    bb_lower = curr.get("bb_lower", close * 0.95)
    bb_mid = curr.get("bb_middle", close)
    bb_upper = curr.get("bb_upper", close * 1.05)

    if macd_crossed_up and (pct_b <= 0.65 or curr["low"] <= bb_lower * 1.01):
        sl = min(curr["low"], bb_lower) - atr * 0.5
        tp = bb_upper if bb_upper > close else close + (close - sl) * MIN_RR_RATIO
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(close, 2),
            "stop_loss": round(sl, 2),
            "take_profit": round(tp, 2),
            "strategy": "MACD Cross + Bollinger Rebound",
            "reason": f"MACD (12,26,9) cắt lên Signal + Giá vùng dưới BB(10,2) (%B={pct_b:.2f})",
        })

    # 2. Chiến lược Bollinger Band (10, 2) Squeeze Breakout
    prev_squeeze = prev.get("bb_squeeze", False) or prev.get("bb_bandwidth", 1.0) <= 0.08
    if prev_squeeze and close >= bb_upper * 0.99 and _volume_spike(curr, ratio=1.3):
        hist = curr.get("macd_hist", 0)
        if not pd.isna(hist) and hist > 0:
            sl = bb_mid - atr * 0.5
            risk = max(close - sl, atr)
            tp = close + risk * MIN_RR_RATIO
            signals.append({
                "symbol": symbol,
                "type": "entry",
                "price": round(close, 2),
                "stop_loss": round(sl, 2),
                "take_profit": round(tp, 2),
                "strategy": "BB(10,2) Squeeze Breakout",
                "reason": "BB(10,2) nén hẹp bung nở dải trên + MACD Histogram dương + Volume bùng nổ",
            })

    # 3. Chiến lược Bắt đáy rút chân sau chuỗi giảm (Oversold Bounce)
    consec_down = prev.get("consec_down", 0)
    touched_lower = prev["low"] <= prev.get("bb_lower", 0) or curr["low"] <= bb_lower * 1.01
    bullish_candle = close > curr["open"] or close > prev["close"]
    macd_hist_improving = (
        not pd.isna(curr.get("macd_hist"))
        and not pd.isna(prev.get("macd_hist"))
        and curr["macd_hist"] > prev["macd_hist"]
    )

    if consec_down >= CONSECUTIVE_BARS_ALERT and touched_lower and bullish_candle and macd_hist_improving:
        sl = min(curr["low"], prev["low"]) - atr * 0.3
        tp = bb_mid if bb_mid > close else close + atr * 2
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(close, 2),
            "stop_loss": round(sl, 2),
            "take_profit": round(tp, 2),
            "strategy": "Bắt đáy rút chân BB(10,2)",
            "reason": f"Rút chân dải dưới BB(10,2) sau {consec_down} phiên giảm liên tiếp + MACD chững đà rơi",
        })

    # 4. Chiến lược Breakout đường Trendline kháng cự giảm
    t_res = curr.get("trendline_resistance")
    prev_t_res = prev.get("trendline_resistance")
    if (
        not pd.isna(t_res) and not pd.isna(prev_t_res)
        and prev["close"] <= prev_t_res * 1.005
        and close > t_res
        and close > bb_mid
        and curr.get("macd", 0) > curr.get("macd_signal", 0)
    ):
        sl = bb_mid - atr * 0.5
        risk = max(close - sl, atr)
        tp = close + risk * MIN_RR_RATIO
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(close, 2),
            "stop_loss": round(sl, 2),
            "take_profit": round(tp, 2),
            "strategy": "Breakout Trendline Kháng Cự",
            "reason": f"Bứt phá vượt đường Trendline kháng cự ({t_res:.2f}đ) + Giá trên BB Mid (SMA10)",
        })

    return signals


def detect_take_profit(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện các tín hiệu chốt lời / bán (take-profit / sell alert).

    Các trường hợp:
    1. MACD Bearish Cross: MACD cắt xuống Signal line ở vùng cao.
    2. Đảo chiều tại đỉnh Bollinger (10, 2):
       - Giá vượt ra ngoài dải trên bb_upper rồi đóng nến tạo râu đảo chiều.
       - Hoặc chạm dải trên sau khi đã tăng liên tiếp >= 3-4 phiên.
    3. Chạm kháng cự Fibonacci mạnh (Fib 0.618 hoặc Swing High 120D).
    4. Gãy đường Trendline hỗ trợ hoặc gãy BB Middle (SMA10) sau một nhịp tăng dài.

    Returns:
        Mỗi tín hiệu gồm: symbol, type="take_profit", price, reason.
    """
    signals = []
    if len(df) < 5:
        return signals

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    close = curr["close"]
    bb_upper = curr.get("bb_upper")
    bb_mid = curr.get("bb_middle")
    consec_up = curr.get("consec_up", 0)

    # 1. MACD Bearish Cross (Cắt xuống)
    macd_crossed_down = (
        curr.get("macd_bearish_cross", False)
        or (
            not pd.isna(prev.get("macd")) and not pd.isna(prev.get("macd_signal"))
            and prev["macd"] >= prev["macd_signal"]
            and curr.get("macd", 0) < curr.get("macd_signal", 0)
        )
    )
    if macd_crossed_down:
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(close, 2),
            "reason": "MACD (12,26,9) cắt xuống Signal - Động lượng tăng đảo chiều",
        })

    # 2. Đảo chiều tại đỉnh Bollinger Bands (10, 2) sau chuỗi tăng
    if not pd.isna(bb_upper):
        hit_upper = curr["high"] >= bb_upper * 0.995 or prev["high"] >= prev.get("bb_upper", 0)
        reversal_candle = close < curr["open"] or close < curr["high"] * 0.985
        if hit_upper and reversal_candle and (consec_up >= 2 or prev.get("consec_up", 0) >= 3):
            signals.append({
                "symbol": symbol,
                "type": "take_profit",
                "price": round(close, 2),
                "reason": f"Chạm đỉnh BB(10,2) xuất hiện nến quay đầu sau {prev.get('consec_up', consec_up)} phiên tăng liên tiếp",
            })

    # 3. Chạm kháng cự Fibonacci 0.618 hoặc Swing High 120D
    fib_618 = curr.get("fib_618")
    swing_high = curr.get("swing_high_120")
    rsi = curr.get("rsi", 50)
    if not pd.isna(fib_618) and abs(close - fib_618) / fib_618 <= 0.01 and rsi >= 65:
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(close, 2),
            "reason": f"Tiệm cận kháng cự Fibonacci 0.618 ({fib_618:.2f}đ) kèm RSI cao ({rsi:.1f})",
        })
    elif not pd.isna(swing_high) and abs(close - swing_high) / swing_high <= 0.01 and rsi >= 65:
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(close, 2),
            "reason": f"Tiệm cận đỉnh cũ 120 phiên ({swing_high:.2f}đ) - Canh hạ tỷ trọng",
        })

    # 4. Gãy đường Trendline hỗ trợ hoặc gãy BB Middle (SMA10)
    t_supp = curr.get("trendline_support")
    if (
        not pd.isna(t_supp)
        and prev["close"] >= prev.get("trendline_support", 0)
        and close < t_supp * 0.995
    ):
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(close, 2),
            "reason": f"Gãy đường Trendline hỗ trợ ({t_supp:.2f}đ) - Cảnh báo kết thúc nhịp tăng",
        })
    elif (
        not pd.isna(bb_mid)
        and prev["close"] >= prev.get("bb_middle", 0)
        and close < bb_mid * 0.99
        and len(df) >= 5
        and close > df.iloc[-5]["close"] * 1.04
    ):
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(close, 2),
            "reason": "Gãy đệm hỗ trợ BB Mid (SMA10) sau nhịp tăng ngắn hạn",
        })

    return signals


def detect_potential(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện cổ phiếu tiềm năng tích lũy sắp bùng nổ.

    Tiêu chí (thỏa mãn >= 2 tiêu chí):
    - Bollinger Bands (10, 2) co thắt (Squeeze).
    - Nằm trên Trendline hỗ trợ và trong xu hướng Uptrend (Giá > SMA50/SMA200).
    - Vùng hỗ trợ Fibonacci an toàn (Fib 0.382 / 0.500).
    - MACD Histogram co hẹp về mức 0 chuẩn bị Golden Cross.

    Returns:
        Mỗi tín hiệu gồm: symbol, type="potential", price, rsi, reason.
    """
    signals = []
    if df.empty or len(df) < 5:
        return signals

    curr = df.iloc[-1]
    reasons = []
    score = 0

    # 1. BB Squeeze
    if curr.get("bb_squeeze", False) or curr.get("bb_bandwidth", 1.0) <= 0.08:
        score += 1
        reasons.append("BB(10,2) nén chặt (Squeeze)")

    # 2. Xu hướng Uptrend & Nằm trên Trendline hỗ trợ
    t_supp = curr.get("trendline_support")
    close = curr["close"]
    if _is_uptrend(curr):
        if not pd.isna(t_supp) and close >= t_supp * 0.99:
            score += 1
            reasons.append("Uptrend giữ vững Trendline hỗ trợ")
        else:
            score += 1
            reasons.append("Uptrend trên MA")

    # 3. MACD chuẩn bị cắt lên
    macd = curr.get("macd")
    signal = curr.get("macd_signal")
    hist = curr.get("macd_hist")
    if not pd.isna(macd) and not pd.isna(signal):
        if abs(macd - signal) <= abs(close) * 0.005:
            score += 1
            reasons.append("MACD hội tụ chuẩn bị Golden Cross")
        elif hist > 0 and curr.get("macd_bullish_cross", False):
            score += 1
            reasons.append("MACD vừa xuất hiện Golden Cross")

    # 4. Fibonacci hỗ trợ
    fib_382 = curr.get("fib_382")
    fib_500 = curr.get("fib_500")
    if not pd.isna(fib_500) and close >= fib_500 * 0.99:
        score += 1
        reasons.append("Giữ vững vùng hỗ trợ Fibonacci")

    rsi = curr.get("rsi", 50)
    if score >= 2:
        signals.append({
            "symbol": symbol,
            "type": "potential",
            "price": round(close, 2),
            "rsi": round(rsi, 1) if not pd.isna(rsi) else "N/A",
            "reason": " + ".join(reasons),
        })
    return signals


def detect_downtrend(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện cổ phiếu đang trong downtrend hoặc rủi ro cao.

    Tiêu chí (thỏa mãn >= 1 tiêu chí nguy hiểm):
    - Giá < SMA50 và SMA200 (Downtrend hoàn toàn).
    - Giá bám dải dưới BB Lower (10, 2) đi xuống (%B <= 0.1).
    - Gãy đường Trendline hỗ trợ.
    - MACD Histogram âm liên tiếp 5 phiên hoặc MACD suy giảm mạnh.
    - Số nhịp giảm liên tiếp >= 3 phiên kèm Volume bán tăng.

    Returns:
        Mỗi tín hiệu gồm: symbol, type="downtrend", price, rsi, reason.
    """
    signals = []
    if df.empty or len(df) < 5:
        return signals

    curr = df.iloc[-1]
    close = curr["close"]
    reasons = []

    if _is_downtrend(curr):
        reasons.append("Giá < MA50 & MA200")

    pct_b = curr.get("bb_percent_b")
    if not pd.isna(pct_b) and pct_b <= 0.1:
        reasons.append("Bám dải dưới BB(10,2) suy thoái")

    t_supp = curr.get("trendline_support")
    if not pd.isna(t_supp) and close < t_supp * 0.985:
        reasons.append("Gãy đường Trendline hỗ trợ")

    if "macd_hist" in df.columns and len(df) >= 5:
        recent = df.tail(5)
        if (recent["macd_hist"] < 0).all():
            reasons.append("MACD Histogram âm 5 phiên liên tiếp")

    consec_down = curr.get("consec_down", 0)
    if consec_down >= CONSECUTIVE_BARS_ALERT and _volume_spike(curr, ratio=1.1):
        reasons.append(f"{consec_down} nhịp giảm liên tiếp + áp lực bán tăng")

    rsi = curr.get("rsi", 50)
    if reasons:
        signals.append({
            "symbol": symbol,
            "type": "downtrend",
            "price": round(close, 2),
            "rsi": round(rsi, 1) if not pd.isna(rsi) else "N/A",
            "reason": " + ".join(reasons[:3]),
        })
    return signals


def scan_all(data: dict) -> List[Dict]:
    """Quét toàn bộ watchlist và tập hợp tất cả tín hiệu.

    Args:
        data: Dict {symbol: DataFrame} chứa dữ liệu đã tính chỉ báo.

    Returns:
        List tín hiệu (entry, take_profit, potential, downtrend) từ tất cả mã.
    """
    all_signals = []
    for symbol, df in data.items():
        all_signals.extend(detect_entry(df, symbol))
        all_signals.extend(detect_take_profit(df, symbol))
        all_signals.extend(detect_potential(df, symbol))
        all_signals.extend(detect_downtrend(df, symbol))
    return all_signals


def _compute_entry_score(row: pd.Series) -> float:
    """Tính điểm vào lệnh dựa trên 5 trụ cột phân tích kỹ thuật (thang điểm 0 - 10).

    1. Động lực MACD (12, 26, 9): Max 2.5đ
       - MACD > Signal: +1.0đ (Bullish cross mới: +0.5đ)
       - MACD Histogram dương: +0.5đ
       - MACD > 0: +0.5đ
    2. Vị thế Bollinger Bands (10, 2): Max 2.5đ
       - Vị trí %B an toàn (0.1 - 0.55): +1.0đ
       - Bật nảy từ BB Lower hoặc vượt BB Mid (SMA10): +1.0đ
       - Dải BB co thắt chuẩn bị bung nở (Squeeze): +0.5đ
    3. Đường Trendline & Xu hướng (Trend): Max 2.0đ
       - Nằm trên Trendline hỗ trợ: +1.0đ
       - Xu hướng chính Uptrend (Close > SMA200 hoặc SMA50): +1.0đ
    4. Hỗ trợ Fibonacci & Nhịp nến: Max 1.5đ
       - Vùng hỗ trợ Fibonacci (0.382 - 0.618): +1.0đ
       - Nhịp nến: Nhịp tăng mới bắt đầu (1-2 phiên) hoặc nến rút chân sau giảm: +0.5đ
       - (Nếu đã tăng >= 4 phiên liên tiếp: -0.5đ vì rủi ro mua đuổi)
    5. Khối lượng xác nhận (Volume): Max 1.5đ
       - Volume >= 1.2x MA20: +1.0đ
       - Volume >= 1.5x MA20: +0.5đ
    """
    if row is None or row.empty:
        return 0.0

    score = 0.0
    close = row.get("close")
    if pd.isna(close) or close <= 0:
        return 0.0

    # 1. Trụ cột MACD (12, 26, 9) - Max 2.5đ
    macd = row.get("macd")
    signal = row.get("macd_signal")
    hist = row.get("macd_hist")
    cross = row.get("macd_bullish_cross", False)

    if not pd.isna(macd) and not pd.isna(signal):
        if macd > signal:
            score += 1.0
        if cross:
            score += 0.5
        if macd > 0:
            score += 0.5
    if not pd.isna(hist) and hist > 0:
        score += 0.5

    # 2. Trụ cột Bollinger Bands (10, 2) - Max 2.5đ
    pct_b = row.get("bb_percent_b")
    bb_mid = row.get("bb_middle")
    bb_lower = row.get("bb_lower")
    squeeze = row.get("bb_squeeze", False)

    if not pd.isna(pct_b):
        if 0.1 <= pct_b <= 0.55:
            score += 1.0
        elif pct_b < 0.1:
            score += 0.5  # Vùng quá bán BB

    if not pd.isna(bb_mid) and close >= bb_mid * 0.995:
        score += 0.5
    if not pd.isna(bb_lower) and close <= bb_lower * 1.03:
        score += 0.5  # Chạm hỗ trợ dải dưới
    if squeeze:
        score += 0.5

    # 3. Trụ cột Trendline & Xu hướng - Max 2.0đ
    t_supp = row.get("trendline_support")
    if not pd.isna(t_supp) and close >= t_supp * 0.99:
        score += 1.0

    sma200 = row.get("sma_200")
    sma50 = row.get("sma_50")
    if not pd.isna(sma200) and close > sma200:
        score += 0.7
    elif not pd.isna(sma50) and close > sma50:
        score += 0.5
    if not pd.isna(sma50) and not pd.isna(sma200) and sma50 > sma200:
        score += 0.3  # Golden Cross

    # 4. Trụ cột Fibonacci & Nhịp nến - Max 1.5đ
    fib_382 = row.get("fib_382")
    fib_618 = row.get("fib_618")
    if not pd.isna(fib_382) and not pd.isna(fib_618):
        # Nằm trong vùng thoái lui vàng 0.382 đến 0.618
        if fib_618 * 0.98 <= close <= fib_382 * 1.02:
            score += 1.0

    consec_up = row.get("consec_up", 0)
    consec_down = row.get("consec_down", 0)
    if 1 <= consec_up <= 2:
        score += 0.5  # Đầu nhịp tăng
    elif consec_down >= 3:
        score += 0.5  # Vùng kỳ vọng rút chân
    elif consec_up >= 4:
        score -= 0.5  # Rủi ro quá mua, FOMO

    # 5. Trụ cột Khối lượng (Volume) - Max 1.5đ
    vol = row.get("volume", 0)
    vol_ma = row.get("volume_ma", 0)
    if not pd.isna(vol_ma) and vol_ma > 0 and vol > 0:
        ratio = vol / vol_ma
        if ratio >= 1.5:
            score += 1.5
        elif ratio >= 1.2:
            score += 1.0

    return round(max(0.0, min(10.0, score)), 1)


def detect_entry_opportunity(data: dict, min_score: float = 6.0) -> List[Dict]:
    """Lọc các cổ phiếu có điểm vào lệnh >= min_score.

    Args:
        data: Dict {symbol: DataFrame} chứa dữ liệu đã tính chỉ báo.
        min_score: Điểm tối thiểu để được chọn (mặc định 6.0).

    Returns:
        List dict: symbol, entry_score, price, strategy, reason.
    """
    results = []
    for symbol, df in data.items():
        if df.empty:
            continue
        curr = df.iloc[-1]
        es = _compute_entry_score(curr)
        if es >= min_score:
            reasons = []

            # MACD status
            if curr.get("macd_bullish_cross", False):
                reasons.append("MACD vừa Golden Cross")
            elif not pd.isna(curr.get("macd_hist")) and curr["macd_hist"] > 0:
                reasons.append("MACD Histogram dương")

            # Bollinger Bands status
            pct_b = curr.get("bb_percent_b")
            if curr.get("bb_squeeze", False):
                reasons.append("BB(10,2) nén hẹp (Squeeze)")
            elif not pd.isna(pct_b) and pct_b <= 0.3:
                reasons.append(f"Vùng đáy BB(10,2) (%B={pct_b:.2f})")
            elif not pd.isna(curr.get("bb_middle")) and curr["close"] >= curr["bb_middle"]:
                reasons.append("Giữ trên BB Mid (SMA10)")

            # Trendline & Trend
            t_supp = curr.get("trendline_support")
            if not pd.isna(t_supp) and curr["close"] >= t_supp * 0.995:
                reasons.append("Nằm trên Trendline hỗ trợ")
            sma200 = curr.get("sma_200")
            if not pd.isna(sma200) and curr["close"] > sma200:
                reasons.append("Uptrend SMA200")

            # Nhịp nến
            consec_up = curr.get("consec_up", 0)
            consec_down = curr.get("consec_down", 0)
            if 1 <= consec_up <= 2:
                reasons.append(f"Nhịp tăng mới ({consec_up} phiên)")
            elif consec_down >= 3:
                reasons.append(f"Kỳ vọng rút chân ({consec_down} phiên giảm)")

            # Volume
            vol = curr.get("volume", 0)
            vol_ma = curr.get("volume_ma", 0)
            if not pd.isna(vol_ma) and vol_ma > 0 and vol >= vol_ma * 1.2:
                reasons.append(f"Volume cao (x{vol/vol_ma:.1f})")

            results.append({
                "symbol": symbol,
                "type": "entry_opportunity",
                "price": round(curr["close"], 2),
                "entry_score": es,
                "reason": " + ".join(reasons) if reasons else "Hội tụ chỉ báo kỹ thuật tích cực",
            })
    results.sort(key=lambda x: x["entry_score"], reverse=True)
    return results

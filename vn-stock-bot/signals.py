"""Logic sinh tín hiệu giao dịch từ DataFrame đã tính chỉ báo.

Đầu vào: DataFrame với các cột từ indicators.py.
Đầu ra: list dict tín hiệu (entry, stop_loss, take_profit, potential, downtrend).
"""

import logging
import pandas as pd
from typing import List, Dict
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    ATR_STOP_LOSS_FACTOR, MIN_RR_RATIO,
    VOLUME_SPIKE_RATIO, EMA_SHORT, EMA_LONG,
)

logger = logging.getLogger(__name__)


def _ema_cross_up(row: pd.Series) -> bool:
    """Kiểm tra EMA short cắt lên EMA long."""
    return (
        not pd.isna(row.get("ema_short"))
        and not pd.isna(row.get("ema_long"))
        and row["ema_short"] > row["ema_long"]
    )


def _volume_spike(row: pd.Series) -> bool:
    """Kiểm tra khối lượng có đột biến so với trung bình 20 phiên."""
    vol_ma = row.get("volume_ma")
    return not pd.isna(vol_ma) and vol_ma > 0 and row["volume"] > vol_ma * VOLUME_SPIKE_RATIO


def _is_uptrend(row: pd.Series) -> bool:
    """Kiểm tra uptrend: giá đóng > SMA50 và SMA200."""
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    return not pd.isna(sma50) and not pd.isna(sma200) and row["close"] > sma50 and row["close"] > sma200


def _is_downtrend(row: pd.Series) -> bool:
    """Kiểm tra downtrend: giá đóng < SMA50 và SMA200."""
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    return not pd.isna(sma50) and not pd.isna(sma200) and row["close"] < sma50 and row["close"] < sma200


def _macd_bearish(df: pd.DataFrame) -> bool:
    """Kiểm tra MACD histogram âm liên tiếp 5 phiên."""
    if "macd_hist" not in df.columns:
        return False
    recent = df.tail(5)
    return (recent["macd_hist"] < 0).all()


def detect_entry(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện tín hiệu mua (entry).

    Hai điều kiện:
    1. EMA20 cắt lên EMA50 kèm volume > 1.5x volume MA20.
    2. RSI hồi phục từ vùng oversold (< 30) kèm volume tăng.

    Returns:
        Mỗi tín hiệu gồm: symbol, type="entry", price, stop_loss, take_profit, reason.
    """
    signals = []
    if len(df) < 3:
        return signals

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_ema_cross = (
        not pd.isna(prev.get("ema_short"))
        and not pd.isna(prev.get("ema_long"))
        and prev["ema_short"] <= prev["ema_long"]
    )
    curr_ema_cross = _ema_cross_up(curr)

    if prev_ema_cross and curr_ema_cross and _volume_spike(curr):
        atr = curr.get("atr", 0)
        stop_loss = curr["close"] - atr * ATR_STOP_LOSS_FACTOR
        risk = curr["close"] - stop_loss
        take_profit = curr["close"] + risk * MIN_RR_RATIO
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(curr["close"], 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "reason": "EMA20 cắt lên EMA50 + volume tăng",
        })

    if (
        prev.get("rsi", 100) < RSI_OVERSOLD
        and curr.get("rsi", 100) >= RSI_OVERSOLD
        and _volume_spike(curr)
    ):
        atr = curr.get("atr", 0)
        stop_loss = curr["close"] - atr * ATR_STOP_LOSS_FACTOR
        risk = curr["close"] - stop_loss
        take_profit = curr["close"] + risk * MIN_RR_RATIO
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(curr["close"], 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "reason": "RSI hồi từ oversold + volume tăng",
        })

    return signals


def detect_take_profit(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện tín hiệu chốt lời.

    Trail theo EMA20 nếu giá đã tăng hơn 5% so với 2 phiên trước.

    Returns:
        Mỗi tín hiệu gồm: symbol, type="take_profit", price, reason.
    """
    signals = []
    if len(df) < 2:
        return signals

    curr = df.iloc[-1]
    if _ema_cross_up(curr) and len(df) >= 3 and curr["close"] > df.iloc[-3]["close"] * 1.05:
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(curr["close"], 2),
            "reason": "Giá đã chạy có lời, trail theo EMA20",
        })
    return signals


def detect_potential(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện cổ phiếu tiềm năng.

    Điều kiện (cần >= 2/3):
    - Giá > SMA50 và SMA200 (uptrend)
    - RSI < 40
    - Volume đột biến

    Returns:
        Mỗi tín hiệu gồm: symbol, type="potential", price, rsi, reason.
    """
    signals = []
    if df.empty:
        return signals

    curr = df.iloc[-1]
    score = 0
    reasons = []

    if _is_uptrend(curr):
        score += 1
        reasons.append("Giá > MA50 & MA200")

    rsi = curr.get("rsi", 50)
    if not pd.isna(rsi) and rsi < 40:
        score += 1
        reasons.append(f"RSI thấp ({rsi:.1f})")

    if _volume_spike(curr):
        score += 1
        reasons.append("Volume đột biến")

    if score >= 2:
        signals.append({
            "symbol": symbol,
            "type": "potential",
            "price": round(curr["close"], 2),
            "rsi": round(rsi, 1) if not pd.isna(rsi) else "N/A",
            "reason": " + ".join(reasons),
        })
    return signals


def detect_downtrend(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Phát hiện cổ phiếu downtrend.

    Điều kiện (cần >= 1):
    - Giá < SMA50 và SMA200
    - MACD histogram âm 5 phiên liên tiếp
    - RSI < 40 + volume bán tăng

    Returns:
        Mỗi tín hiệu gồm: symbol, type="downtrend", price, rsi, reason.
    """
    signals = []
    if df.empty:
        return signals

    curr = df.iloc[-1]
    reasons = []

    if _is_downtrend(curr):
        reasons.append("Giá < MA50 & MA200")

    if _macd_bearish(df):
        reasons.append("MACD âm 5 phiên liên tiếp")

    rsi = curr.get("rsi", 50)
    if not pd.isna(rsi) and rsi < 40 and _volume_spike(curr):
        reasons.append(f"RSI < 40 ({rsi:.1f}) + volume bán tăng")

    if reasons:
        signals.append({
            "symbol": symbol,
            "type": "downtrend",
            "price": round(curr["close"], 2),
            "rsi": round(rsi, 1) if not pd.isna(rsi) else "N/A",
            "reason": " + ".join(reasons),
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


def _compute_entry_score(row) -> float:
    """Tính điểm vào lệnh từ chỉ báo (0-10).

    Weight: trend > pullback > cross > momentum > RSI.
    """
    score = 0.0
    close = row.get("close")
    rsi = row.get("rsi")
    macd_hist = row.get("macd_hist")
    ema20 = row.get("ema_short")
    ema50 = row.get("ema_long")
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")

    has_trend = not pd.isna(close) and not pd.isna(sma200)
    has_indicators = not pd.isna(rsi) and not pd.isna(macd_hist)

    if has_trend and has_indicators:
        # 1. Trend: ±3
        if close > sma200:
            score += 3.0
        else:
            score -= 2.0

        # 2. Pullback discount trong uptrend
        if close > sma200:
            if not pd.isna(ema20) and close < ema20:
                score += 2.0
            elif not pd.isna(ema20):
                score += 0.5

        # 3. Cross: ±1
        if not pd.isna(sma50) and not pd.isna(sma200):
            if sma50 > sma200:
                score += 1.0
            else:
                score -= 1.0

        # 4. MACD momentum: +1/-0.5
        if not pd.isna(macd_hist):
            if macd_hist > 0:
                score += 1.0
            else:
                score -= 0.5

        # 5. RSI sweet spot: +1/-1
        if not pd.isna(rsi):
            if 40 <= rsi <= 55:
                score += 1.0
            elif rsi > 70 or rsi < 20:
                score -= 1.0

    return max(0, min(10, score))


def detect_entry_opportunity(data: dict, min_score: float = 6.0) -> List[Dict]:
    """Lọc các cổ phiếu có điểm vào lệnh >= min_score.

    Args:
        data: Dict {symbol: DataFrame} chứa dữ liệu đã tính chỉ báo.
        min_score: Điểm tối thiểu để được chọn (mặc định 6.0).

    Returns:
        List dict: symbol, entry_score, price, reason.
    """
    results = []
    for symbol, df in data.items():
        if df.empty:
            continue
        curr = df.iloc[-1]
        es = _compute_entry_score(curr)
        if es >= min_score:
            reasons = []
            rsi = curr.get("rsi")
            if not pd.isna(rsi):
                if rsi < 30:
                    reasons.append(f"RSI oversold ({rsi:.1f})")
                elif rsi < 40:
                    reasons.append(f"RSI thấp ({rsi:.1f})")
            sma200 = curr.get("sma_200")
            if not pd.isna(sma200) and not pd.isna(curr.get("close")) and curr["close"] > sma200:
                reasons.append("Uptrend SMA200")
            sma50 = curr.get("sma_50")
            if not pd.isna(sma50) and not pd.isna(sma200) and sma50 > sma200:
                reasons.append("Golden Cross")
            if not pd.isna(curr.get("macd_hist")) and curr["macd_hist"] > 0:
                reasons.append("MACD dương")
            results.append({
                "symbol": symbol,
                "type": "entry_opportunity",
                "price": round(curr["close"], 2),
                "entry_score": round(es, 1),
                "reason": " + ".join(reasons) if reasons else "Nhiều yếu tố tích cực",
            })
    results.sort(key=lambda x: x["entry_score"], reverse=True)
    return results

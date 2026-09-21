"""Tính toán các chỉ báo kỹ thuật từ dữ liệu giá OHLCV.

Sử dụng pandas thuần, không phụ thuộc pandas-ta.
"""

import logging
import numpy as np
import pandas as pd

from config import (
    EMA_SHORT, EMA_LONG, RSI_PERIOD, ATR_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, VOLUME_MA_PERIOD, FIB_LOOKBACK_DAYS,
    TRENDLINE_LOOKBACK
)

logger = logging.getLogger(__name__)

MIN_ROWS = 50


def _ema(series: pd.Series, length: int) -> pd.Series:
    """Tính Exponential Moving Average (EMA).

    Args:
        series: Chuỗi giá (thường là cột close).
        length: Số phiên tính EMA.

    Returns:
        Chuỗi EMA.
    """
    return series.ewm(span=length, adjust=False).mean()


def _sma(series: pd.Series, length: int) -> pd.Series:
    """Tính Simple Moving Average (SMA).

    Args:
        series: Chuỗi giá.
        length: Số phiên tính SMA.

    Returns:
        Chuỗi SMA.
    """
    return series.rolling(window=length).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Tính Relative Strength Index (RSI) theo chuẩn Wilder's Smoothing.

    Args:
        close: Chuỗi giá đóng cửa.
        length: Số phiên tính RSI (mặc định 14).

    Returns:
        Chuỗi RSI (giá trị 0-100).
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=length - 1, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(com=length - 1, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Tính Average True Range (ATR).

    Args:
        high: Chuỗi giá cao nhất.
        low: Chuỗi giá thấp nhất.
        close: Chuỗi giá đóng cửa.
        length: Số phiên tính ATR (mặc định 14).

    Returns:
        Chuỗi ATR.
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Tính MACD, Signal line, và Histogram.

    Args:
        close: Chuỗi giá đóng cửa.
        fast: EMA nhanh (mặc định 12).
        slow: EMA chậm (mặc định 26).
        signal: EMA tín hiệu (mặc định 9).

    Returns:
        Tuple (macd_line, signal_line, histogram) — mỗi phần là Series.
    """
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger_bands(close: pd.Series, length: int = 10, std_dev: int = 2):
    """Tính Bollinger Bands (upper, middle, lower, bandwidth, percent_b).

    Dùng ddof=0 (population std) theo chuẩn John Bollinger.
    Mặc định: length = 10, std_dev = 2.

    Args:
        close: Chuỗi giá đóng cửa.
        length: Số phiên tính SMA cho middle band (mặc định 10).
        std_dev: Số độ lệch chuẩn cho bands (mặc định 2).

    Returns:
        Tuple (upper, mid, lower, bandwidth, percent_b) — mỗi phần là Series.
    """
    mid = _sma(close, length)
    std = close.rolling(window=length).std(ddof=0)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    bandwidth = (upper - lower) / mid.replace(0, 1e-10)
    diff = (upper - lower).replace(0, 1e-10)
    percent_b = (close - lower) / diff
    return upper, mid, lower, bandwidth, percent_b


def _consecutive_bars(close: pd.Series):
    """Tính số phiên tăng liên tiếp và số phiên giảm liên tiếp.

    Args:
        close: Chuỗi giá đóng cửa.

    Returns:
        Tuple (consec_up, consec_down) — mỗi phần là Series.
    """
    diff = close.diff()
    consec_up = []
    consec_down = []
    u = 0
    d = 0
    for val in diff:
        if pd.isna(val) or val == 0:
            u = 0
            d = 0
        elif val > 0:
            u += 1
            d = 0
        else:
            d += 1
            u = 0
        consec_up.append(u)
        consec_down.append(d)
    return pd.Series(consec_up, index=close.index), pd.Series(consec_down, index=close.index)


def _trendlines(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 30):
    """Tính toán đường Trendline hỗ trợ (nối 2 đáy gần nhất) và kháng cự (nối 2 đỉnh gần nhất).

    Args:
        high: Chuỗi giá cao nhất.
        low: Chuỗi giá thấp nhất.
        close: Chuỗi giá đóng cửa.
        lookback: Cửa sổ quan sát tìm đỉnh/đáy pivot (mặc định 30).

    Returns:
        Tuple (trendline_support, trendline_resistance) — mỗi phần là Series.
    """
    n = len(close)
    supp_series = [np.nan] * n
    res_series = [np.nan] * n

    low_arr = low.values
    high_arr = high.values

    for i in range(lookback, n):
        w_start = max(0, i - lookback)
        w_low = low_arr[w_start:i+1]
        w_high = high_arr[w_start:i+1]
        w_len = len(w_low)

        # Tìm pivot lows (đáy cục bộ: thấp hơn 2 nến trước và 2 nến sau trong cửa sổ)
        min_pivots = []
        for k in range(2, w_len - 2):
            if w_low[k] <= min(w_low[k-2:k+3]):
                min_pivots.append(k)

        if len(min_pivots) >= 2:
            x1, x2 = min_pivots[-2], min_pivots[-1]
            y1, y2 = w_low[x1], w_low[x2]
            slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
            curr_supp = y2 + slope * (w_len - 1 - x2)
            supp_series[i] = curr_supp
        else:
            supp_series[i] = float(np.min(w_low))

        # Tìm pivot highs (đỉnh cục bộ: cao hơn 2 nến trước và 2 nến sau trong cửa sổ)
        max_pivots = []
        for k in range(2, w_len - 2):
            if w_high[k] >= max(w_high[k-2:k+3]):
                max_pivots.append(k)

        if len(max_pivots) >= 2:
            x1, x2 = max_pivots[-2], max_pivots[-1]
            y1, y2 = w_high[x1], w_high[x2]
            slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
            curr_res = y2 + slope * (w_len - 1 - x2)
            res_series[i] = curr_res
        else:
            res_series[i] = float(np.max(w_high))

    return pd.Series(supp_series, index=close.index), pd.Series(res_series, index=close.index)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Tính toàn bộ chỉ báo kỹ thuật cho DataFrame OHLCV.

    Thêm các cột:
    - EMA / SMA: ema_short (20), ema_long (50), sma_50, sma_200
    - RSI (14), ATR (14)
    - MACD (12, 26, 9): macd, macd_signal, macd_hist, macd_bullish_cross, macd_bearish_cross
    - Bollinger Bands (10, 2): bb_upper, bb_middle, bb_lower, bb_bandwidth, bb_percent_b, bb_squeeze
    - Volume: volume_ma (20)
    - Số nhịp tăng/giảm: consec_up, consec_down, up_days_20, down_days_20
    - Trendlines: trendline_support, trendline_resistance
    - Fibonacci: swing_high_120, swing_low_120, fib_236, fib_382, fib_500, fib_618, fib_786, fib_100

    Args:
        df: DataFrame chứa OHLCV + cột "time".

    Returns:
        DataFrame mới với các cột chỉ báo đã tính.
        Trả về nguyên bản nếu dữ liệu không đủ (dưới 50 dòng).
    """
    if df.empty or len(df) < MIN_ROWS:
        logger.warning("Not enough data to compute indicators (need >= %d rows)", MIN_ROWS)
        return df

    df = df.copy()

    # EMA & SMA
    df["ema_short"] = _ema(df["close"], EMA_SHORT)
    df["ema_long"] = _ema(df["close"], EMA_LONG)
    df["sma_50"] = _sma(df["close"], 50)
    df["sma_200"] = _sma(df["close"], 200)

    # RSI
    df["rsi"] = _rsi(df["close"], RSI_PERIOD)

    # MACD (12, 26, 9)
    macd_line, signal_line, histogram = _macd(
        df["close"], MACD_FAST, MACD_SLOW, MACD_SIGNAL
    )
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram
    prev_macd = df["macd"].shift(1)
    prev_signal = df["macd_signal"].shift(1)
    df["macd_bullish_cross"] = (df["macd"] > df["macd_signal"]) & (prev_macd <= prev_signal)
    df["macd_bearish_cross"] = (df["macd"] < df["macd_signal"]) & (prev_macd >= prev_signal)

    # ATR
    df["atr"] = _atr(df["high"], df["low"], df["close"], ATR_PERIOD)

    # Bollinger Bands (chiều dài = 10, Mult = 2)
    bb_upper, bb_mid, bb_lower, bb_bw, bb_pct_b = _bollinger_bands(
        df["close"], length=BB_PERIOD, std_dev=BB_STD
    )
    df["bb_upper"] = bb_upper
    df["bb_middle"] = bb_mid
    df["bb_lower"] = bb_lower
    df["bb_bandwidth"] = bb_bw
    df["bb_percent_b"] = bb_pct_b

    # Squeeze: Bandwidth nằm trong vùng co hẹp thấp nhất 20% của 50 phiên
    bw_q20 = df["bb_bandwidth"].rolling(window=50, min_periods=20).quantile(0.20)
    df["bb_squeeze"] = df["bb_bandwidth"] <= bw_q20

    # Volume MA
    df["volume_ma"] = _sma(df["volume"], VOLUME_MA_PERIOD)

    # Số nhịp tăng / Số nhịp giảm
    consec_up, consec_down = _consecutive_bars(df["close"])
    df["consec_up"] = consec_up
    df["consec_down"] = consec_down
    df["up_days_20"] = (df["close"].diff() > 0).rolling(window=20, min_periods=5).sum()
    df["down_days_20"] = (df["close"].diff() < 0).rolling(window=20, min_periods=5).sum()

    # Trendlines
    t_supp, t_res = _trendlines(df["high"], df["low"], df["close"], lookback=TRENDLINE_LOOKBACK)
    df["trendline_support"] = t_supp
    df["trendline_resistance"] = t_res

    # Swing High & Swing Low cho Fibonacci
    window_len = min(FIB_LOOKBACK_DAYS, len(df))
    df["swing_high_120"] = df["high"].rolling(window=window_len, min_periods=20).max()
    df["swing_low_120"] = df["low"].rolling(window=window_len, min_periods=20).min()

    fib_diff = df["swing_high_120"] - df["swing_low_120"]
    df["fib_236"] = df["swing_high_120"] - fib_diff * 0.236
    df["fib_382"] = df["swing_high_120"] - fib_diff * 0.382
    df["fib_500"] = df["swing_high_120"] - fib_diff * 0.500
    df["fib_618"] = df["swing_high_120"] - fib_diff * 0.618
    df["fib_786"] = df["swing_high_120"] - fib_diff * 0.786
    df["fib_100"] = df["swing_low_120"]

    return df



def compute_indicators_batch(data: dict) -> dict:
    """Tính chỉ báo cho nhiều mã cùng lúc.

    Args:
        data: Dict {symbol: DataFrame} chứa dữ liệu OHLCV.

    Returns:
        Dict {symbol: DataFrame} với các cột chỉ báo đã thêm.
    """
    result = {}
    for symbol, df in data.items():
        result[symbol] = compute_indicators(df)
    return result

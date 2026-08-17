"""Lấy dữ liệu giá chứng khoán từ vnstock API với hỗ trợ multi-source fallback và cache."""

import logging
import time
from typing import List, Optional
import pandas as pd
from datetime import datetime, timedelta
from config import WATCHLIST, HISTORICAL_DAYS

logger = logging.getLogger(__name__)

# Runtime patch cho vnstock.core.utils.env.get_hosting_service để ngăn UnboundLocalError khi chạy trên môi trường Windows / Local
try:
    import vnstock.core.utils.env as _vnstock_env
    _orig_get_hosting_service = getattr(_vnstock_env, "get_hosting_service", None)
    if _orig_get_hosting_service:
        def _safe_get_hosting_service():
            try:
                res = _orig_get_hosting_service()
                return res if res is not None else "Local or Unknown"
            except UnboundLocalError:
                return "Local or Unknown"
        _vnstock_env.get_hosting_service = _safe_get_hosting_service
except Exception:
    pass


class DataFetcher:
    """Lớp trung gian lấy dữ liệu giá từ vnstock, hỗ trợ cache trong memory và tự động fallback nguồn dữ liệu."""

    def __init__(self, source: str = "VCI"):
        """Khởi tạo DataFetcher.

        Args:
            source: Nguồn dữ liệu vnstock chính (mặc định "VCI").
        """
        self._source = source
        self._cache = {}
        # Danh sách các nguồn dự phòng theo thứ tự ưu tiên
        self._fallback_sources = [source.lower()]

    def _get_quote(self, symbol: str, source: Optional[str] = None):
        """Tạo đối tượng Quote cho một mã chứng khoán.

        Hỗ trợ tương thích với các phiên bản vnstock (3.x và 4.x).

        Args:
            symbol: Mã chứng khoán (VD: "FPT", "VCB").
            source: Nguồn dữ liệu tùy chọn. Nếu None, dùng self._source.

        Returns:
            Đối tượng Quote từ vnstock.
        """
        src = (source or self._source).lower()
        QuoteClass = None

        try:
            from vnstock import Quote
            QuoteClass = Quote
        except ImportError:
            pass

        if QuoteClass is None:
            try:
                from vnstock.api.quote import Quote
                QuoteClass = Quote
            except ImportError:
                pass

        if QuoteClass is None:
            try:
                from vnstock import Vnstock
                return Vnstock().quote(symbol=symbol, source=src)
            except Exception as e:
                raise ImportError(f"Không thể import thư viện vnstock: {e}")

        try:
            return QuoteClass(symbol=symbol, source=src)
        except TypeError:
            try:
                return QuoteClass(source=src, symbol=symbol)
            except TypeError:
                return QuoteClass(symbol)

    def fetch_historical(
        self, symbol: str, start: Optional[str] = None, end: Optional[str] = None, bypass_cache: bool = False
    ) -> pd.DataFrame:
        """Lấy dữ liệu giá lịch sử (OHLCV) cho một mã với Smart Cache và Fallback Multi-Source.

        Args:
            symbol: Mã chứng khoán.
            start: Ngày bắt đầu (YYYY-MM-DD), mặc định cách đây HISTORICAL_DAYS ngày.
            end: Ngày kết thúc (YYYY-MM-DD), mặc định hôm nay.
            bypass_cache: Nếu True, bỏ qua cache và lấy trực tiếp từ API.

        Returns:
            DataFrame chứa các cột: time, open, high, low, close, volume.
        """
        if end is None:
            end = pd.Timestamp.now().strftime("%Y-%m-%d")
        if start is None:
            start = (pd.Timestamp.now() - pd.Timedelta(days=HISTORICAL_DAYS)).strftime("%Y-%m-%d")

        cache_key = f"hist_{symbol}_{start}_{end}"
        now_ts = time.time()

        # TTL cache: 600 giây (10 phút)
        if not bypass_cache and cache_key in self._cache:
            cached_time, cached_df = self._cache[cache_key]
            if now_ts - cached_time < 600:
                return cached_df.copy()

        # Thử lấy dữ liệu qua danh sách các nguồn (Primary + Fallbacks)
        last_error = None
        for src in self._fallback_sources:
            try:
                q = self._get_quote(symbol, source=src)
                df = q.history(start=start, end=end)

                if df is None or df.empty:
                    continue

                col_map = {c.lower(): c for c in df.columns}
                if not {"open", "high", "low", "close", "volume"}.issubset(col_map):
                    continue

                df = df.rename(columns=col_map)
                df = df.sort_values("time").reset_index(drop=True)

                self._cache[cache_key] = (now_ts, df)
                return df
            except BaseException as e:
                last_error = e
                logger.debug("Fetch historical failed for %s using source %s: %s", symbol, src, e)
                time.sleep(0.5)

        logger.warning("Failed to fetch historical data for %s (all sources tried): %s", symbol, last_error)
        return pd.DataFrame()

    def fetch_multiple_historical(
        self, symbols: Optional[List[str]] = None, start: Optional[str] = None, bypass_cache: bool = False
    ) -> dict:
        """Lấy dữ liệu lịch sử cho nhiều mã cùng lúc.

        Args:
            symbols: Danh sách mã cần lấy. Mặc định dùng WATCHLIST từ config.
            start: Ngày bắt đầu.
            bypass_cache: Nếu True, lấy trực tiếp không dùng cache.

        Returns:
            Dict {symbol: DataFrame} chứa dữ liệu của các mã lấy thành công.
        """
        if symbols is None:
            import config
            symbols = config.WATCHLIST
        result = {}
        for symbol in symbols:
            df = self.fetch_historical(symbol, start=start, bypass_cache=bypass_cache)
            if not df.empty:
                result[symbol] = df
        return result

    def fetch_realtime_price(self, symbol: str) -> Optional[float]:
        """Lấy giá real-time (intraday) hiện tại của một mã.

        Args:
            symbol: Mã chứng khoán.

        Returns:
            Giá hiện tại (float), hoặc None nếu không lấy được.
        """
        for src in self._fallback_sources:
            try:
                q = self._get_quote(symbol, source=src)
                df = q.intraday(symbol=symbol, page_size=1)
                if df is not None and not df.empty and "price" in df.columns:
                    return float(df.iloc[-1]["price"])
            except BaseException as e:
                logger.debug("Failed to fetch realtime price for %s using source %s: %s", symbol, src, e)
        logger.warning("Failed to fetch realtime price for %s (all sources tried)", symbol)
        return None

    def update_with_realtime(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Cập nhật hoặc bổ sung giá/khối lượng realtime vào nến mới nhất của DataFrame."""
        if df.empty:
            return df

        for src in self._fallback_sources:
            try:
                q = self._get_quote(symbol, source=src)
                intraday_df = q.intraday(symbol=symbol, page_size=50)
                if intraday_df is None or intraday_df.empty:
                    continue

                last_price = float(intraday_df.iloc[-1]["price"])
                today_str = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%Y-%m-%d")

                total_vol = intraday_df["volume"].sum() if "volume" in intraday_df.columns else df.iloc[-1]["volume"]
                high_price = intraday_df["price"].max() if "price" in intraday_df.columns else last_price
                low_price = intraday_df["price"].min() if "price" in intraday_df.columns else last_price
                open_price = intraday_df.iloc[0]["price"] if "price" in intraday_df.columns else last_price

                df_copy = df.copy()
                last_df_time = str(df_copy.iloc[-1]["time"])[:10]

                if last_df_time == today_str:
                    # Update existing today's bar
                    df_copy.loc[df_copy.index[-1], "close"] = last_price
                    df_copy.loc[df_copy.index[-1], "high"] = max(df_copy.iloc[-1]["high"], high_price)
                    df_copy.loc[df_copy.index[-1], "low"] = min(df_copy.iloc[-1]["low"], low_price)
                    df_copy.loc[df_copy.index[-1], "volume"] = max(df_copy.iloc[-1]["volume"], total_vol)
                else:
                    # Append new bar for today
                    new_row = {
                        "time": today_str,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": last_price,
                        "volume": total_vol,
                    }
                    df_copy = pd.concat([df_copy, pd.DataFrame([new_row])], ignore_index=True)

                return df_copy
            except BaseException as e:
                logger.debug("Could not update realtime for %s using source %s: %s", symbol, src, e)

        return df

    def clear_cache(self):
        """Xóa toàn bộ cache dữ liệu trong memory."""
        self._cache.clear()

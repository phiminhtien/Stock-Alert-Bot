"""Lấy dữ liệu giá chứng khoán từ vnstock API (VCI source)."""

import logging
import time
from typing import List, Optional
import pandas as pd

from datetime import datetime, timedelta
from config import WATCHLIST, HISTORICAL_DAYS

logger = logging.getLogger(__name__)


class DataFetcher:
    """Lớp trung gian lấy dữ liệu giá từ vnstock, hỗ trợ cache trong memory."""

    def __init__(self, source: str = "VCI"):
        """Khởi tạo DataFetcher.

        Args:
            source: Nguồn dữ liệu vnstock (mặc định "VCI").
        """
        self._source = source
        self._cache = {}

    def _get_quote(self, symbol: str):
        """Tạo đối tượng Quote cho một mã chứng khoán.

        Hỗ trợ fallback import tương thích với mọi phiên bản vnstock (3.x và 4.x).

        Args:
            symbol: Mã chứng khoán (VD: "FPT", "VCB").

        Returns:
            Đối tượng Quote từ vnstock.
        """
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
                return Vnstock().quote(symbol=symbol, source=self._source)
            except Exception as e:
                raise ImportError(f"Không thể import thư viện vnstock: {e}")

        try:
            return QuoteClass(symbol=symbol, source=self._source)
        except TypeError:
            return QuoteClass(self._source, symbol)


    def fetch_historical(
        self, symbol: str, start: Optional[str] = None, end: Optional[str] = None, bypass_cache: bool = False
    ) -> pd.DataFrame:
        """Lấy dữ liệu giá lịch sử (OHLCV) cho một mã.

        Sử dụng Smart Cache với TTL (Time-To-Live) là 10 phút (600 giây).
        Dữ liệu lịch sử các ngày đã qua hoàn toàn cố định, còn dữ liệu trong phiên sẽ được
        update_with_realtime() cập nhật liên tục live mỗi khi quét.

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

        try:
            q = self._get_quote(symbol)
            df = q.history(start=start, end=end)

            if df is None or df.empty:
                logger.warning("No data for %s", symbol)
                return pd.DataFrame()

            col_map = {c.lower(): c for c in df.columns}
            if not {"open", "high", "low", "close", "volume"}.issubset(col_map):
                logger.warning("Missing OHLCV columns for %s, got: %s", symbol, list(col_map))
                return pd.DataFrame()

            df = df.rename(columns=col_map)
            df = df.sort_values("time").reset_index(drop=True)

            self._cache[cache_key] = (now_ts, df)
            return df
        except BaseException as e:
            if "Rate Limit" in str(e) or "limit" in str(e).lower():
                logger.warning("Rate limit reached while fetching %s. Retrying in 3 seconds...", symbol)
                time.sleep(3.0)
                try:
                    q = self._get_quote(symbol)
                    df = q.history(start=start, end=end)
                    if df is not None and not df.empty:
                        col_map = {c.lower(): c for c in df.columns}
                        if {"open", "high", "low", "close", "volume"}.issubset(col_map):
                            df = df.rename(columns=col_map)
                            df = df.sort_values("time").reset_index(drop=True)
                            self._cache[cache_key] = (now_ts, df)
                            return df
                except BaseException as inner_e:
                    logger.warning("Retry failed for %s: %s", symbol, inner_e)
            else:
                logger.warning("Failed to fetch historical data for %s: %s", symbol, e)
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
            symbols = WATCHLIST
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
        try:
            q = self._get_quote(symbol)
            df = q.intraday(symbol=symbol, page_size=1)
            if df is not None and not df.empty:
                return float(df.iloc[-1]["price"])
        except BaseException as e:
            logger.warning("Failed to fetch realtime price for %s: %s", symbol, e)
        return None

    def update_with_realtime(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Cập nhật hoặc bổ sung giá/khối lượng realtime vào nến mới nhất của DataFrame.

        Nếu phiên hôm nay chưa có trong df (df chỉ có đến hôm qua), tạo thêm 1 nến mới cho hôm nay.
        Nếu phiên hôm nay đã có (ví dụ EOD vừa cập nhật), cập nhật giá close/high/low/volume mới nhất.
        """
        if df.empty:
            return df

        try:
            q = self._get_quote(symbol)
            intraday_df = q.intraday(symbol=symbol, page_size=50)
            if intraday_df is None or intraday_df.empty:
                return df

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
            logger.debug("Could not update realtime for %s: %s", symbol, e)
            return df


    def clear_cache(self):
        """Xóa toàn bộ cache dữ liệu trong memory."""
        self._cache.clear()


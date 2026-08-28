"""Synthetic market fixtures for unit and integration testing of market normalization."""

from __future__ import annotations

from decimal import Decimal

from simulator.application.services.market_normalizer import RawKlineRecord


def make_kline_ms(
    symbol: str,
    day_offset: int,
    open_price: str | Decimal,
    high_price: str | Decimal,
    low_price: str | Decimal,
    close_price: str | Decimal,
    volume: str | Decimal = "100.0",
    quote_volume: str | Decimal = "4000000.0",
    count: int = 1000,
    taker_v: str | Decimal = "50.0",
    taker_qv: str | Decimal = "2000000.0",
    base_year: int = 2024,
) -> RawKlineRecord:
    """Create a RawKlineRecord in millisecond format for a 2024 date.

    Base start is 2024-01-01T00:00:00.000Z (timestamp 1704067200000 ms).
    """
    base_ms = 1_704_067_200_000 + (day_offset * 86_400_000)
    close_ms = base_ms + 86_400_000 - 1
    return RawKlineRecord(
        symbol=symbol,
        open_time=base_ms,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        close_time=close_ms,
        quote_volume=quote_volume,
        count=count,
        taker_buy_volume=taker_v,
        taker_buy_quote_volume=taker_qv,
    )


def make_kline_us(
    symbol: str,
    day_offset: int,
    open_price: str | Decimal,
    high_price: str | Decimal,
    low_price: str | Decimal,
    close_price: str | Decimal,
    volume: str | Decimal = "100.0",
    quote_volume: str | Decimal = "4000000.0",
    count: int = 1000,
    taker_v: str | Decimal = "50.0",
    taker_qv: str | Decimal = "2000000.0",
) -> RawKlineRecord:
    """Create a RawKlineRecord in microsecond format for a 2025 date.

    Base start is 2025-01-01T00:00:00.000000Z (timestamp 1735689600000000 us).
    """
    base_us = 1_735_689_600_000_000 + (day_offset * 86_400_000_000)
    close_us = base_us + 86_400_000_000 - 1
    return RawKlineRecord(
        symbol=symbol,
        open_time=base_us,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        close_time=close_us,
        quote_volume=quote_volume,
        count=count,
        taker_buy_volume=taker_v,
        taker_buy_quote_volume=taker_qv,
    )


def create_stable_series(symbol: str = "BTCUSDT", length: int = 5) -> list[RawKlineRecord]:
    """Generate a stable flat synthetic price series."""
    return [
        make_kline_ms(
            symbol=symbol,
            day_offset=i,
            open_price="40000.00",
            high_price="40500.00",
            low_price="39500.00",
            close_price="40000.00",
            volume="100.00",
            quote_volume="4000000.00",
            count=1500,
        )
        for i in range(length)
    ]


def create_trend_series(symbol: str = "BTCUSDT", length: int = 5) -> list[RawKlineRecord]:
    """Generate a steady upward trending price series."""
    records = []
    for i in range(length):
        base_p = 40000 + (i * 1000)
        records.append(
            make_kline_ms(
                symbol=symbol,
                day_offset=i,
                open_price=f"{base_p}.00",
                high_price=f"{base_p + 800}.00",
                low_price=f"{base_p - 200}.00",
                close_price=f"{base_p + 600}.00",
                volume=f"{100 + i * 10}.00",
                quote_volume=f"{(100 + i * 10) * base_p}.00",
                count=2000 + i * 100,
            )
        )
    return records


def create_reversal_series(symbol: str = "BTCUSDT") -> list[RawKlineRecord]:
    """Generate an upward trend followed by a sharp downward reversal."""
    # 5 days: 40k -> 42k -> 44k -> 41k -> 38k
    prices = [
        ("40000.00", "41500.00", "39800.00", "41200.00"),
        ("41200.00", "43000.00", "41000.00", "42800.00"),
        ("42800.00", "44500.00", "42500.00", "44200.00"),  # Peak
        ("44200.00", "44400.00", "40500.00", "41000.00"),  # Reversal
        ("41000.00", "41500.00", "37500.00", "38000.00"),  # Downtrend
    ]
    return [
        make_kline_ms(
            symbol=symbol,
            day_offset=i,
            open_price=p[0],
            high_price=p[1],
            low_price=p[2],
            close_price=p[3],
            volume="250.00",
            quote_volume="10000000.00",
            count=3000,
        )
        for i, p in enumerate(prices)
    ]


def create_volatile_series(symbol: str = "SOLUSDT") -> list[RawKlineRecord]:
    """Generate high volatility series with wide intraday swings."""
    prices = [
        ("100.00", "125.00", "95.00", "120.00"),
        ("120.00", "130.00", "90.00", "95.00"),
        ("95.00", "140.00", "88.00", "135.00"),
        ("135.00", "145.00", "100.00", "105.00"),
        ("105.00", "130.00", "98.00", "128.00"),
    ]
    return [
        make_kline_ms(
            symbol=symbol,
            day_offset=i,
            open_price=p[0],
            high_price=p[1],
            low_price=p[2],
            close_price=p[3],
            volume="5000.00",
            quote_volume="550000.00",
            count=10000,
        )
        for i, p in enumerate(prices)
    ]


def create_missing_day_series(symbol: str = "ETHUSDT") -> list[RawKlineRecord]:
    """Generate a series with day 1 (offset 1) intentionally missing."""
    # Days 0, 2, 3 (day 1 missing)
    offsets = [0, 2, 3]
    return [
        make_kline_ms(
            symbol=symbol,
            day_offset=off,
            open_price=f"{2500 + off * 50}.00",
            high_price=f"{2600 + off * 50}.00",
            low_price=f"{2450 + off * 50}.00",
            close_price=f"{2550 + off * 50}.00",
            volume="500.00",
            quote_volume="1300000.00",
            count=2500,
        )
        for off in offsets
    ]


def create_structural_break_series(symbol: str = "BTCUSDT") -> list[RawKlineRecord]:
    """Generate a series featuring a structural break (-40% drop with volume surge)."""
    # 4 days: 50k, 51k, sudden break to 30k, then 29k
    return [
        make_kline_ms(
            symbol=symbol,
            day_offset=0,
            open_price="50000.00",
            high_price="50800.00",
            low_price="49500.00",
            close_price="50400.00",
            volume="100.00",
            quote_volume="5040000.00",
            count=1500,
        ),
        make_kline_ms(
            symbol=symbol,
            day_offset=1,
            open_price="50400.00",
            high_price="51500.00",
            low_price="50100.00",
            close_price="51200.00",
            volume="120.00",
            quote_volume="6144000.00",
            count=1800,
        ),
        make_kline_ms(
            symbol=symbol,
            day_offset=2,
            open_price="51200.00",
            high_price="51300.00",
            low_price="29000.00",
            close_price="30500.00",
            volume="1500.00",  # Massive volume surge
            quote_volume="45750000.00",
            count=25000,
        ),
        make_kline_ms(
            symbol=symbol,
            day_offset=3,
            open_price="30500.00",
            high_price="31200.00",
            low_price="28800.00",
            close_price="29800.00",
            volume="800.00",
            quote_volume="23840000.00",
            count=12000,
        ),
    ]

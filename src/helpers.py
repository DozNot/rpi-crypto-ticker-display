"""
Utility functions for formatting, connectivity checks, data updates, and adaptive text rendering.
All shared data access is protected by locks where needed.
"""
import time
import socket
import pygame
from typing import Tuple

from src.constants import (
    GREEN, RED, ORANGE, BLUE, GRAY, WHITE,
    CANDLE_SECONDS, MARQUEE_REFRESH_INTERVAL,
    PRICE_DECIMALS, KRAKEN_PAIRS, COINGECKO_IDS,
    MINER_ACTIVE_THRESHOLD, DATA_TIMEOUT,
    MARQUEE_SPEED, WIFI_CHECK_INTERVAL,
    MARQUEE_SYMBOLS
)
from src.data import (
    data, data_lock, last_known_marquee_prices,
    wifi_ok, last_wifi_check,
    binance_ws_status, kraken_ws_status
)

import logging
logger = logging.getLogger(__name__)

def is_wifi_connected() -> bool:
    # Quick non-blocking internet check via DNS resolution.
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2.5)
        return True
    except OSError:
        return False

def get_ws_color() -> Tuple[int, int, int]:
    # Determine global connection status color:
    #  - RED:    no WiFi
    #  - GREEN:  both WS connected
    #  - ORANGE: at least one WS connected
    # Updates WiFi status periodically.
    global wifi_ok, last_wifi_check
    now = time.time()

    if now - last_wifi_check > WIFI_CHECK_INTERVAL:
        wifi_ok = is_wifi_connected()
        last_wifi_check = now

    # Debug log (only when checked)
    logger.debug(
        f"WS indicator → wifi_ok={wifi_ok} | binance='{binance_ws_status}' | kraken='{kraken_ws_status}'"
    )

    if not wifi_ok:
        return RED

    # Loose matching for various connection states
    binance_ok = binance_ws_status.lower() in [
        "websocket connected", "binance ws connected", "connected",
        "live", "open", "connecting…", "subscription sent"
    ]
    kraken_ok = kraken_ws_status.lower() in [
        "websocket connected", "kraken subscription sent", "connected",
        "live", "open", "connecting…", "subscription sent"
    ]

    if binance_ok and kraken_ok:
        return GREEN
    if binance_ok or kraken_ok:
        return ORANGE
    return RED

def format_hashrate(th: float) -> str:
    # Format hashrate in TH/s with 2 decimals.
    return f"{th:.2f} TH/s"

def format_difficulty(diff: float) -> str:
    # Human-readable difficulty with appropriate unit (K/M/G/T).
    if diff >= 1e12: return f"{diff / 1e12:.2f} T"
    if diff >= 1e9:  return f"{diff / 1e9:.2f} G"
    if diff >= 1e6:  return f"{diff / 1e6:.2f} M"
    if diff >= 1e3:  return f"{diff / 1e3:.2f} K"
    return f"{diff:.0f}"

def format_network_hashrate(hr_eh: float) -> str:
    # Format network hashrate starting from EH/s with dynamic scaling.
    if hr_eh <= 0:
        return "0.00 EH/s"

    prefixes = ["TH/s", "PH/s", "EH/s", "ZH/s", "YH/s"]
    idx = 2  # start at EH/s
    hr = hr_eh

    while hr >= 1000 and idx < len(prefixes) - 1:
        hr /= 1000
        idx += 1
    while hr < 1 and idx > 0:
        hr *= 1000
        idx -= 1

    return f"{hr:.2f} {prefixes[idx]}"

def prices_changed_for_marquee() -> bool:
    # Check if any marquee symbol price changed since last rebuild.
    with data_lock:
        for sym in MARQUEE_SYMBOLS:
            key = sym.lower()
            current = data[key].last_marquee_price
            previous = last_known_marquee_prices.get(key)
            if current != previous:
                return True
    return False

def update_ticker_data(key: str, price: float, change: float, update_marquee: bool = True):
    # Thread-safe update of ticker data + candle building logic.
    # Creates new candle when interval elapsed.
    now = time.time()
    with data_lock:
        ticker = data[key]
        ticker.price = price
        ticker.change_24h = change
        ticker.status = "Live"
        ticker.last_update = now
        if update_marquee:
            ticker.last_marquee_price = price

        candle = ticker.current_candle
        if candle is None or now - candle["start"] >= CANDLE_SECONDS:
            if candle:
                ticker.candles.append(candle)
            ticker.current_candle = {
                "start": int(now),
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }
        else:
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price

def render_adaptive_text(text: str, max_width: int, color: Tuple[int, int, int],
                         start_size: int = 14, min_size: int = 8,
                         font_name: str = "dejavusans", bold: bool = False) -> pygame.Surface:
    # Render text by reducing font size until it fits max_width.
    # Returns smallest acceptable surface (fallback to min_size).
    size = start_size
    while size >= min_size:
        font = pygame.font.SysFont(font_name, size, bold=bold)
        surf = font.render(text, True, color)
        if surf.get_width() <= max_width:
            return surf
        size -= 1

    # Fallback to minimum size
    font = pygame.font.SysFont(font_name, min_size, bold=bold)
    return font.render(text, True, color)

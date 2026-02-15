#!/usr/bin/env python3
"""
RPi Crypto Ticker Display
Real-time cryptocurrency ticker, local Bitcoin miners monitor, and Bitcoin network stats dashboard.

Key Features:
- Global connection status indicator
- Low CPU usage: software rendering, static background, configurable 25 FPS cap
- Real-time prices with 24h change via Binance/Kraken WebSockets, CoinGecko polling fallback
- Auto-rotating main symbols with configurable 1-min candlestick charts and local hashrate overlay
- Bitcoin network stats from mempool.space: fees, block height, mining pool, network hashrate/difficulty
- Scrolling marquee with configurable altcoin prices and 24h change
- Aggregated local miner stats: total hashrate, best share difficulty, connected/active counts with color-coded health
- Auto-hide miner section if none configured
- Configurable via JSON, automatic reconnections, thread-safe data, WiFi checks

Developed and tested with:
  - Raspberry Pi 3B+, 4, 5
  - Waveshare 3.5" TFT touchscreen (480x320, XPT2046 controller)
  - HDMI monitors (auto-scaled with preserved aspect ratio)
"""
import os

os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_FBDEV"] = "/dev/fb0"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import logging
from logging.handlers import RotatingFileHandler
import threading
import atexit
import socket
import time

import signal
import sys

def signal_handler(sig, frame):
    pygame.quit()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

from src.constants import *
from src.data import data, data_lock, miner_stats, TickerData
from src.helpers import *
from src.websockets import (
    run_kraken_websocket, run_binance_websocket, run_coingecko_polling,
    fetch_initial_binance, fetch_initial_kraken, fetch_initial_coingecko
)
from src.miners import run_miners_polling
from src.mempool import run_mempool_polling
from src.rendering import init_pygame, run_render_loop

# LOGGING SETUP
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

log_handler = RotatingFileHandler(
    log_file,
    maxBytes=2*1024*1024,
    backupCount=5
)

logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s | %(levelname)-5s | %(threadName)s | %(message)s',
    handlers=[log_handler, logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

# WAITING FOR NETWORK AT STARTUP
def wait_for_internet(timeout=90):
    logger.info("Waiting for internet connection at startup...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            logger.info("Internet connection established")
            return True
        except OSError:
            time.sleep(2)
    logger.error("Timeout: no internet connection after %d seconds", timeout)
    return False

wait_for_internet()

logger.info(f"Config loaded: {len(MINERS_IPS)} miners configured")

miner_stats["total_miners"] = len(MINERS_IPS)

# INITIALIZE DATA STRUCTURES
for symbol in MAIN_SYMBOLS + MARQUEE_SYMBOLS:
    key = symbol.lower()
    source = "binance"
    if key in KRAKEN_PAIRS:
        source = "kraken"
    elif key in COINGECKO_IDS:
        source = "coingecko"
    data[key] = TickerData(source=source)

# INITIAL DATA FETCH
binance_symbols = [
    s for s in set(MAIN_SYMBOLS + MARQUEE_SYMBOLS)
    if data[s.lower()].source == "binance"
]

for sym in binance_symbols:
    fetch_initial_binance(sym)

fetch_initial_kraken()
fetch_initial_coingecko()

# START BACKGROUND THREADS
threading.Thread(target=run_kraken_websocket, daemon=True, name="KrakenWS").start()
threading.Thread(target=run_binance_websocket, daemon=True, name="BinanceWS").start()
threading.Thread(target=run_coingecko_polling, daemon=True, name="CoinGecko").start()
threading.Thread(target=run_mempool_polling, daemon=True, name="Mempool").start()

threading.Thread(
    target=run_miners_polling,
    args=(MINERS_IPS,),
    daemon=True,
    name="Miners"
).start()

# MAIN
if __name__ == "__main__":
    logger.info("Starting RPi Crypto Ticker Display...")
    init_pygame(BTC_LOGO_PATH)
    run_render_loop()

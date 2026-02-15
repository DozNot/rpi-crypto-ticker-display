"""
Thread-safe global data structures for prices, miners, mempool and connection status.
All mutable shared data should be accessed with the appropriate lock.
"""
import time
from collections import deque
from typing import Dict, Any, Optional

import threading

from src.constants import MARQUEE_REFRESH_INTERVAL, MAX_CANDLES

class TickerData:
    # Per-symbol market data container
    def __init__(self, source: str = "binance"):
        self.price: Optional[float] = None
        self.change_24h: float = 0.0
        self.status: str = "Connecting…"
        self.last_update: Optional[float] = None
        self.candles: deque = deque(maxlen=MAX_CANDLES)
        self.current_candle: Optional[Dict[str, Any]] = None
        self.source: str = source
        self.last_marquee_price: Optional[float] = None

# Main shared data
data: Dict[str, TickerData] = {}
data_lock = threading.Lock()

miner_stats: Dict[str, Any] = {
    "total_hashrate_th": 0.0,
    "best_difficulty": 0.0,
    "connected_count": 0,
    "active_count": 0,
}
miners_lock = threading.Lock()

hash_history = deque(maxlen=MAX_CANDLES)

mempool_data = {
    "fees_sats_vb": None,
    "block_height": None,
    "mining_pool": None,
    "network_hashrate_eh": None,
    "network_difficulty": None
}
fees_lock = threading.Lock()

# Marquee optimization helpers
last_known_marquee_prices: Dict[str, Optional[float]] = {}

# Connection status indicators
binance_ws_status = "Connecting…"
kraken_ws_status = "Connecting…"

wifi_ok = False
last_wifi_check = 0.0

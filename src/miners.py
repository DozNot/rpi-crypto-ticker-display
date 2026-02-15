"""
Background polling thread for local Bitcoin miners (BitAxe, NerdQaxe, etc.).
Aggregates total hashrate, best difficulty, and health stats (connected/active).
Polls every 15 seconds in parallel using ThreadPoolExecutor.
If no miners configured, thread exits immediately.
"""
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.constants import MINER_ACTIVE_THRESHOLD
from src.data import miner_stats, miners_lock, hash_history

logger = logging.getLogger(__name__)

def fetch_miner_stats(ip: str) -> tuple[float, float, bool]:
    # Query miner API for current hashrate (TH/s), best share difficulty, and connection status.
    # Returns (hashrate_th, best_diff, connected: bool)
    try:
        resp = requests.get(
            f"http://{ip}/api/system/info",
            timeout=4,
            headers={"User-Agent": "rpi-crypto-ticker-display/1.0"}
        )
        resp.raise_for_status()
        data = resp.json()

        # API returns hashRate in GH/s → convert to TH/s
        hr_th = data.get("hashRate", 0.0) / 1000.0
        diff = data.get("bestDiff", 0.0)

        return hr_th, diff, True
    except Exception:
        # Silent failure → treat as disconnected / 0 stats
        return 0.0, 0.0, False

def run_miners_polling(miners_ips: list[str]):
    # Main polling loop.
    # Exits early if miners_ips is empty.
    # Uses thread pool for concurrent fetches (max 16 workers → safe for RPi).
    # Updates shared miner_stats and hash_history thread-safely.
    if not miners_ips:
        logger.info("No miners configured - miner polling thread exiting")
        return

    total_miners = len(miners_ips)
    logger.info(f"Starting miner polling for {total_miners} IPs")

    with ThreadPoolExecutor(max_workers=16) as executor:
        while True:
            # Submit all fetches concurrently
            futures = {executor.submit(fetch_miner_stats, ip): ip for ip in miners_ips}

            total_hr = 0.0
            best_diff = 0.0
            conn_count = 0
            act_count = 0

            for future in as_completed(futures):
                hr, diff, connected = future.result()
                total_hr += hr
                best_diff = max(best_diff, diff)
                if connected:
                    conn_count += 1
                if hr > MINER_ACTIVE_THRESHOLD:
                    act_count += 1

            # Thread-safe update of global stats
            with miners_lock:
                miner_stats.update({
                    "total_hashrate_th": total_hr,
                    "best_difficulty": best_diff,
                    "connected_count": conn_count,
                    "active_count": act_count,
                })
                hash_history.append(total_hr)

            time.sleep(15)

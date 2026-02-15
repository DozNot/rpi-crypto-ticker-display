"""
Background polling thread for Bitcoin network statistics from mempool.space API.
Fetches fees, block height, latest pool, network hashrate and difficulty.
Updates shared mempool_data dict thread-safely every ~25 seconds.
"""
import time
import logging
import requests

from src.data import mempool_data, fees_lock
from src.helpers import format_network_hashrate, format_difficulty

logger = logging.getLogger(__name__)

def run_mempool_polling():
    # Infinite polling loop with error handling and graceful fallback to None values.
    # Uses a polite User-Agent and 15s timeout per request to respect the API.
    headers = {"User-Agent": "rpi-crypto-ticker-display/1.0"}

    while True:
        try:
            # Recommended fee
            fees_resp = requests.get(
                "https://mempool.space/api/v1/fees/precise",
                timeout=15, headers=headers
            ).json()
            fees = float(fees_resp.get("halfHourFee", None))

            # Current block height
            height_resp = requests.get(
                "https://mempool.space/api/blocks/tip/height",
                timeout=15, headers=headers
            )
            height_str = height_resp.text.strip()
            height = int(height_str) if height_str.isdigit() else None

            pool = None
            net_diff = None

            if height:
                # Get block hash for latest height
                hash_resp = requests.get(
                    f"https://mempool.space/api/block-height/{height}",
                    timeout=15, headers=headers
                )
                block_hash = hash_resp.text.strip()

                if block_hash:
                    # Fetch full block info → mining pool & difficulty
                    block_resp = requests.get(
                        f"https://mempool.space/api/v1/block/{block_hash}",
                        timeout=15, headers=headers
                    ).json()
                    pool = block_resp.get("extras", {}).get("pool", {}).get("name", "Unknown")
                    net_diff = block_resp.get("difficulty")

            # Average hashrate (converted from GH/s to EH/s)
            hr_resp = requests.get(
                "https://mempool.space/api/v1/mining/hashrate/3m",
                timeout=15, headers=headers
            ).json()
            net_hr = hr_resp.get("currentHashrate", 0) / 1e18  # GH/s → EH/s

            # Thread-safe update
            with fees_lock:
                mempool_data.update({
                    "fees_sats_vb": fees,
                    "block_height": height,
                    "mining_pool": pool,
                    "network_hashrate_eh": net_hr,
                    "network_difficulty": net_diff
                })

        except Exception as e:
            logger.error(f"Mempool fetch error: {e}")
            with fees_lock:
                mempool_data.update({
                    "fees_sats_vb": None,
                    "block_height": None,
                    "mining_pool": None,
                    "network_hashrate_eh": None,
                    "network_difficulty": None
                })

        time.sleep(25)

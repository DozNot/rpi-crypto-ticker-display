"""
WebSocket clients (Binance, Kraken) + polling fallback (CoinGecko) for real-time prices.
Handles initial REST bootstrap + live updates with thread-safe data writes.
Automatic reconnection with exponential backoff.
"""
import json
import time
import random
import logging
import requests
import websocket

from src.constants import MAIN_SYMBOLS, MARQUEE_SYMBOLS, KRAKEN_PAIRS, COINGECKO_IDS
from src.data import data, data_lock, binance_ws_status, kraken_ws_status
from src.helpers import update_ticker_data

logger = logging.getLogger(__name__)

# Initial data bootstrap (REST)
def fetch_initial_binance(symbol: str):
    # Fetch 24hr ticker + recent 1m klines (for main symbols) from Binance.
    key = symbol.lower()
    if data[key].source != "binance":
        return

    try:
        # 24hr ticker
        resp_t = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": symbol.upper()},
            timeout=10
        )
        resp_t.raise_for_status()
        t_data = resp_t.json()
        price = float(t_data["lastPrice"])
        change_pct = float(t_data["priceChangePercent"])
        update_ticker_data(key, price, change_pct, update_marquee=True)

        # 1m klines bootstrap (only for main symbols)
        if symbol in MAIN_SYMBOLS:
            resp_k = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol.upper(), "interval": "1m", "limit": 60},
                timeout=10
            )
            resp_k.raise_for_status()
            klines = resp_k.json()

            with data_lock:
                ticker = data[key]
                ticker.candles.clear()
                for kline in klines[:-1]:
                    o_time, o, h, l, c, *_ = kline
                    ticker.candles.append({
                        "start": o_time / 1000.0,
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c)
                    })
                last_k = klines[-1]
                ticker.current_candle = {
                    "start": last_k[0] / 1000.0,
                    "open": float(last_k[1]),
                    "high": float(last_k[2]),
                    "low": float(last_k[3]),
                    "close": float(last_k[4])
                }

        logger.info(f"Initial Binance data loaded for {symbol}")

    except Exception as e:
        logger.error(f"Initial Binance fetch failed for {symbol}: {e}")

def fetch_initial_kraken():
    # Fetch current ticker for all Kraken pairs via REST.
    try:
        pairs = ",".join(p.replace("/", "") for p in KRAKEN_PAIRS.values())
        resp = requests.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": pairs},
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()["result"]

        for api_pair, ticker_data in result.items():
            pair_clean = next((v.replace("/", "") for v in KRAKEN_PAIRS.values() if v.replace("/", "") in api_pair), None)
            key = next((k for k, v in KRAKEN_PAIRS.items() if v.replace("/", "") == pair_clean), None)
            if not key or "c" not in ticker_data:
                continue

            price = float(ticker_data["c"][0])
            change_pct = 0.0  # Kraken ticker doesn't provide direct 24h change here
            update_ticker_data(key, price, change_pct, update_marquee=True)

        logger.info("Initial Kraken data loaded")

    except Exception as e:
        logger.error(f"Initial Kraken fetch failed: {e}")

def fetch_initial_coingecko():
    # Fetch current price + 24h change from CoinGecko for configured coins.
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(COINGECKO_IDS.values()),
        "vs_currencies": "usd",
        "include_24hr_change": "true"
    }
    headers = {"User-Agent": "rpi-crypto-ticker-display/1.0"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        result = resp.json()

        for coin_id, ticker_data in result.items():
            price = ticker_data.get("usd")
            change = ticker_data.get("usd_24h_change", 0.0)
            if price is not None:
                key = next(k for k, v in COINGECKO_IDS.items() if v == coin_id)
                update_ticker_data(key, price, change, update_marquee=True)

        logger.info("Initial CoinGecko data loaded")

    except Exception as e:
        logger.error(f"Initial CoinGecko fetch failed: {e}")

# Kraken WebSocket handlers
def kraken_on_message(ws, message):
    # Parse ticker updates from Kraken WS.
    try:
        msg = json.loads(message)
        if isinstance(msg, dict) and "event" in msg:
            return
        if not isinstance(msg, list) or len(msg) < 4 or msg[2] != "ticker":
            return

        _, ticker_data, _, pair = msg
        pair_clean = pair.replace("/", "")
        key = next((k for k, v in KRAKEN_PAIRS.items() if v.replace("/", "") == pair_clean), None)

        if not key or "c" not in ticker_data or "o" not in ticker_data:
            return

        price = float(ticker_data["c"][0])
        open_24h = float(ticker_data["o"][1])
        change_pct = ((price - open_24h) / open_24h * 100) if open_24h > 0 else 0.0
        update_ticker_data(key, price, change_pct)

    except Exception as e:
        logger.error("Kraken message parse error", exc_info=True)

def kraken_on_error(ws, error):
    global kraken_ws_status
    kraken_ws_status = "Error"
    err_str = str(error).lower()
    if "restarting, please reconnect" in err_str:
        logger.info("Kraken WS: server requested reconnect (maintenance/restart)")
    else:
        logger.error(f"Kraken WS error: {error}", exc_info=True)

def kraken_on_close(ws, code=None, reason=None):
    global kraken_ws_status
    kraken_ws_status = "Reconnecting…"
    reason_str = str(reason) if reason is not None else "no reason"
    if "restarting, please reconnect" in reason_str.lower():
        logger.info("Kraken WS closed cleanly (server restart/maintenance)")
    else:
        logger.warning(f"Kraken WS closed - code={code}, reason={reason_str}")

def kraken_on_open(ws):
    global kraken_ws_status
    kraken_ws_status = "Live"
    subscribe_msg = {
        "event": "subscribe",
        "pair": list(KRAKEN_PAIRS.values()),
        "subscription": {"name": "ticker"}
    }
    ws.send(json.dumps(subscribe_msg))
    logger.info("Kraken subscription sent")

def run_kraken_websocket():
    # Kraken WS client with exponential backoff reconnection.
    backoff = 1.0
    while True:
        ws = websocket.WebSocketApp(
            "wss://ws.kraken.com",
            on_message=kraken_on_message,
            on_error=kraken_on_error,
            on_close=kraken_on_close,
            on_open=kraken_on_open
        )
        ws.run_forever(ping_interval=25, ping_timeout=10)
        logger.info(f"Kraken WS disconnected → backoff {backoff:.1f}s")
        time.sleep(backoff)
        backoff = min(backoff * 1.8, 120)

# Binance WebSocket handlers
def binance_on_message(ws, message):
    # Parse ticker updates from Binance WS.
    try:
        data_json = json.loads(message)
        symbol = data_json.get("s", "").lower()
        if symbol not in data or data[symbol].source != "binance":
            return
        price = float(data_json["c"])
        change_pct = float(data_json["P"])
        update_ticker_data(symbol, price, change_pct)
    except Exception as e:
        logger.error("Binance message parse error", exc_info=True)

def binance_on_error(ws, error):
    global binance_ws_status
    binance_ws_status = "Error"
    err_str = str(error).lower()
    if any(word in err_str for word in ["reconnect", "maintenance", "restart"]):
        logger.info("Binance WS: server requested reconnect/maintenance")
    else:
        logger.error(f"Binance WS error: {error}", exc_info=True)

def binance_on_close(ws, code=None, reason=None):
    global binance_ws_status
    binance_ws_status = "Reconnecting…"
    reason_str = str(reason) if reason is not None else "no reason"
    if any(word in reason_str.lower() for word in ["reconnect", "maintenance", "restart"]):
        logger.info("Binance WS closed cleanly (server maintenance)")
    else:
        logger.warning(f"Binance WS closed - code={code}, reason={reason_str}")

def binance_on_open(ws):
    global binance_ws_status
    binance_ws_status = "Live"
    logger.info("Binance WS connected")

def run_binance_websocket():
    # Binance WS client – subscribes dynamically to configured symbols.
    backoff = 1.0
    while True:
        binance_symbols = [
            s.lower() for s in (MAIN_SYMBOLS + MARQUEE_SYMBOLS)
            if data.get(s.lower(), {}).source == "binance"
        ]
        if not binance_symbols:
            time.sleep(10)
            continue

        streams = "/".join(f"{s}@ticker" for s in binance_symbols)
        url = f"wss://stream.binance.com:9443/ws/{streams}"

        ws = websocket.WebSocketApp(
            url,
            on_message=binance_on_message,
            on_error=binance_on_error,
            on_close=binance_on_close,
            on_open=binance_on_open
        )
        ws.run_forever(ping_interval=30, ping_timeout=10)
        logger.info(f"Binance WS disconnected → backoff {backoff:.1f}s")
        time.sleep(backoff)
        backoff = min(backoff * 1.8, 120)

# CoinGecko polling fallback
def run_coingecko_polling():
    # Periodic polling for CoinGecko coins (rate-limit aware with backoff).
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(COINGECKO_IDS.values()),
        "vs_currencies": "usd",
        "include_24hr_change": "true"
    }
    headers = {"User-Agent": "rpi-crypto-ticker-display/1.0"}
    backoff = 1.0

    while True:
        time.sleep(backoff)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()

            for coin_id, ticker_data in result.items():
                price = ticker_data.get("usd")
                change = ticker_data.get("usd_24h_change", 0.0)
                if price is not None:
                    key = next(k for k, v in COINGECKO_IDS.items() if v == coin_id)
                    update_ticker_data(key, price, change)

            backoff = 300  # Normal interval: 5 min

        except requests.HTTPError as e:
            if e.response and e.response.status_code == 429:
                jitter = random.uniform(0, 30)
                logger.warning(f"CoinGecko rate limit → backoff ~{180 + jitter:.0f}s")
                backoff = 180 + jitter
            else:
                logger.error(f"CoinGecko HTTP error: {e}")
                backoff = 60
        except Exception as e:
            logger.error(f"CoinGecko error: {e}")
            backoff = 60

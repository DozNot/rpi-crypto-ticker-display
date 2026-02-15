"""
Centralized constants and configuration loader.
Loads user settings from config.json with safe defaults if missing or invalid.
All display, timing, color, and layout constants are defined here.
"""
import json
import os

# Determine config file path relative to project root
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

# Load configuration or fall back to empty dict
try:
    with open(config_path, "r") as f:
        config_data = json.load(f)
except Exception as e:
    config_data = {}
    print(f"Failed to load config.json: {e}. Using default values.")

# Configurable runtime parameters
FPS = config_data.get("fps", 25)
DIM_ALPHA = config_data.get("dim_alpha", 50)
CANDLE_SECONDS = config_data.get("candle_seconds", 60)
MAX_CANDLES = config_data.get("max_candles", 14)
MARQUEE_HEIGHT = config_data.get("marquee_height", 24)
MARQUEE_SPEED = config_data.get("marquee_speed", 1.0)
MARQUEE_REFRESH_INTERVAL = config_data.get("marquee_refresh_interval", 8.0)

# Symbols and data sources
MAIN_SYMBOLS = config_data.get("main_symbols", ["BTCUSDT"])
MARQUEE_SYMBOLS = config_data.get("marquee_symbols", [
    "ETHUSDT", "BNBUSDT", "XMRUSDT", "SOLUSDT", "LTCUSDT",
    "XRPUSDT", "ADAUSDT", "TRXUSDT", "MEUSDT", "HBARUSDT", "ESXUSD",
    "XECUSDT", "RUNECOIN"
])

PRICE_DECIMALS = config_data.get("price_decimals", {
    "xecusdt": 8, "xecusdc": 8,
    "esxusd": 6,
    "runecoin": 8,
})

KRAKEN_PAIRS = config_data.get("kraken_pairs", {"xmrusdt": "XMR/USDT", "esxusd": "ESX/USD"})
COINGECKO_IDS = config_data.get("coingecko_ids", {"runecoin": "runecoin"})

# Miner and data behavior
MINER_ACTIVE_THRESHOLD = config_data.get("miner_active_threshold", 0.25)
DATA_TIMEOUT = config_data.get("data_timeout", 300)
HASHRATE_CURVE_THICKNESS = config_data.get("hashrate_curve_thickness", 2)
WIFI_CHECK_INTERVAL = config_data.get("wifi_check_interval", 12.0)

MINERS_IPS = config_data.get("miners_ips", [])
BTC_LOGO_PATH = config_data.get("btc_logo_path", "logos/btc.png")

# Fixed display geometry and colors (native 3.5" TFT resolution)
SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320

BLACK      = (6,   6,   10)
GRID_COLOR = (40,  40,  55)
WHITE      = (240, 240, 255)
GREEN      = (0,   230, 140)
RED        = (255, 90,  90)
GRAY       = (130, 130, 160)
ORANGE     = (255, 180, 0)
BLUE       = (100, 180, 255)

CHART_X = 16
CHART_Y = 180
CHART_W = 448
CHART_H = 96

MARQUEE_Y = SCREEN_HEIGHT - MARQUEE_HEIGHT

MEMPOOL_MIN_LEFT_X  = 20
MEMPOOL_RIGHT_EDGE  = SCREEN_WIDTH - 20
MEMPOOL_MAX_WIDTH   = MEMPOOL_RIGHT_EDGE - MEMPOOL_MIN_LEFT_X

# Fonts (initialized later in rendering.py)
FONT_BIG       = None
FONT_MID       = None
FONT_SMALL     = None
FONT_HASHRATE  = None
FONT_MARQUEE   = None

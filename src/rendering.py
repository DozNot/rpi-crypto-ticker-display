"""
Core rendering module using Pygame.
Handles display init (TFT/HDMI auto-scaling), background, marquee, charts,
candles, miner stats, mempool info, connection indicator, and smooth updates.
Optimized for low CPU: static BG, capped FPS, minimal redraws.
"""
import os
import time
import logging
import atexit
import pygame

from src.constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, DIM_ALPHA,
    BLACK, GRID_COLOR, WHITE, GREEN, RED, GRAY, ORANGE, BLUE,
    CHART_X, CHART_Y, CHART_W, CHART_H,
    MARQUEE_HEIGHT, MARQUEE_Y, MARQUEE_SPEED,
    MAIN_SYMBOLS, DATA_TIMEOUT, HASHRATE_CURVE_THICKNESS,
    MEMPOOL_MIN_LEFT_X, MEMPOOL_MAX_WIDTH,
    MARQUEE_REFRESH_INTERVAL, MARQUEE_SYMBOLS, PRICE_DECIMALS
)
from src.data import (
    data, data_lock, miner_stats, miners_lock, hash_history,
    mempool_data, fees_lock,
    last_known_marquee_prices,
    binance_ws_status, kraken_ws_status
)
from src.helpers import (
    get_ws_color, format_hashrate, format_difficulty, format_network_hashrate,
    prices_changed_for_marquee, render_adaptive_text
)

logger = logging.getLogger(__name__)

# Global display objects (initialized in init_pygame)
screen = None
render_surface = None
BG_SURFACE = None
DIM_LAYER = None
logos_dict = None
clock = None
FONT_BIG = None
FONT_MID = None
FONT_SMALL = None
FONT_HASHRATE = None
FONT_MARQUEE = None

# Scaling / offset for HDMI displays (preserves aspect ratio)
display_width = SCREEN_WIDTH
display_height = SCREEN_HEIGHT
render_width = SCREEN_WIDTH
render_height = SCREEN_HEIGHT
scale_factor = 1.0
offset_x = 0
offset_y = 0

def init_pygame(btc_logo_path: str):
    # Initialize Pygame, detect display, set up surfaces, fonts, and logos.
    global screen, render_surface, BG_SURFACE, DIM_LAYER, logos_dict, clock
    global FONT_BIG, FONT_MID, FONT_SMALL, FONT_HASHRATE, FONT_MARQUEE
    global display_width, display_height, render_width, render_height
    global scale_factor, offset_x, offset_y

    pygame.init()
    info = pygame.display.Info()
    real_width, real_height = info.current_w, info.current_h
    logger.info(f"Detected display: {real_width} × {real_height}")

    # Calculate scaling to fit 480×320 natively while preserving aspect
    scale_w = real_width / render_width
    scale_h = real_height / render_height
    scale_factor = min(scale_w, scale_h)
    display_width = int(render_width * scale_factor)
    display_height = int(render_height * scale_factor)
    offset_x = (real_width - display_width) // 2
    offset_y = (real_height - display_height) // 2

    try:
        screen = pygame.display.set_mode(
            (real_width, real_height),
            pygame.FULLSCREEN | pygame.NOFRAME
        )
    except Exception as e:
        logger.critical(f"Display init failed: {e}")
        raise SystemExit(1)

    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()

    render_surface = pygame.Surface((render_width, render_height))
    BG_SURFACE = pygame.Surface((render_width, render_height))
    BG_SURFACE.fill(BLACK)

    # Draw grid lines on static background
    for i in range(1, 4):
        y = CHART_Y + i * (CHART_H / 4)
        pygame.draw.line(BG_SURFACE, GRID_COLOR,
                         (CHART_X + 4, y), (CHART_X + CHART_W - 4, y), 1)

    DIM_LAYER = pygame.Surface((render_width, render_height))
    DIM_LAYER.fill((0, 0, 0))
    DIM_LAYER.set_alpha(DIM_ALPHA)

    # Load logos for main symbols
    project_root = os.path.dirname(os.path.dirname(__file__))
    logos_dict = {}
    for symbol in MAIN_SYMBOLS:
        logo_name = symbol.replace("USDT", "").lower() + ".png"
        full_path = os.path.join(project_root, "logos", logo_name)
        try:
            logo = pygame.image.load(full_path).convert_alpha()
            logo = pygame.transform.smoothscale(logo, (24, 24))
            logos_dict[symbol.lower()] = logo
        except Exception:
            logger.warning(f"Logo load failed: {logo_name}")
            fallback = pygame.Surface((24, 24), pygame.SRCALPHA)
            logos_dict[symbol.lower()] = fallback

    # Font loading with DejaVu fallback to system default
    font_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        FONT_BIG = pygame.font.Font(font_bold, 52)
        FONT_MID = pygame.font.Font(font_regular, 22)
        FONT_SMALL = pygame.font.Font(font_regular, 20)
        FONT_HASHRATE = pygame.font.Font(font_regular, 17)
        FONT_MARQUEE = pygame.font.Font(font_regular, 21)
    except FileNotFoundError:
        logger.warning("DejaVu fonts missing → using system fallback")
        FONT_BIG = pygame.font.Font(None, 52)
        FONT_MID = pygame.font.Font(None, 22)
        FONT_SMALL = pygame.font.Font(None, 20)
        FONT_HASHRATE = pygame.font.Font(None, 17)
        FONT_MARQUEE = pygame.font.Font(None, 21)

def cleanup():
    # Pygame shutdown on exit
    if pygame.get_init():
        pygame.quit()

def create_marquee_surfaces(font_marquee):
    # Build list of marquee text surfaces + total width (doubled for seamless loop).
    parts = []
    separator = font_marquee.render(" • ", True, (140, 140, 140))
    name_template = lambda t: font_marquee.render(t, True, WHITE)
    price_template = lambda t, c: font_marquee.render(t, True, c)
    na_template = lambda t: font_marquee.render(t, True, GRAY)

    with data_lock:
        for symbol in MARQUEE_SYMBOLS:
            key = symbol.lower()
            name = symbol.upper().replace("USDT", "").replace("USD", "")
            if symbol == "RUNECOIN":
                name = "RUNECOIN"
            ticker = data[key]

            if ticker.price is not None:
                decimals = PRICE_DECIMALS.get(key, 4 if ticker.price < 10 else 2)
                price_str = f"{ticker.price:,.{decimals}f}"
                color = GREEN if ticker.change_24h >= 0 else RED
                parts.extend([
                    (name_template(f"{name} "), name_template(f"{name} ").get_width()),
                    (price_template(f"${price_str}", color), price_template(f"${price_str}", color).get_width())
                ])
            else:
                na_surf = na_template(f"{name} ---")
                parts.append((na_surf, na_surf.get_width()))

            parts.append((separator, separator.get_width()))

    doubled = parts + parts
    total_width = sum(w for _, w in doubled)
    return doubled, total_width

def run_render_loop():
    # Main render loop: 25 FPS cap, event handling, dynamic updates, blitting.
    global last_known_marquee_prices

    atexit.register(cleanup)

    local_surfaces = []
    local_total_width = 0
    last_marquee_rebuild = 0
    current_symbol_idx = 0
    last_symbol_switch = time.time()
    symbol_switch_interval = 0 if len(MAIN_SYMBOLS) <= 1 else 21.0
    marquee_x = float(render_width)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit(0)

        now = time.time()

        # Rotate main symbol if multiple configured
        if now - last_symbol_switch >= symbol_switch_interval:
            current_symbol_idx = (current_symbol_idx + 1) % len(MAIN_SYMBOLS)
            last_symbol_switch = now

        current_symbol = MAIN_SYMBOLS[current_symbol_idx].lower()
        with data_lock:
            ticker = data.get(current_symbol)

        # Rebuild marquee only when needed (interval or price change)
        if now - last_marquee_rebuild >= MARQUEE_REFRESH_INTERVAL or prices_changed_for_marquee():
            local_surfaces, local_total_width = create_marquee_surfaces(FONT_MARQUEE)
            with data_lock:
                last_known_marquee_prices = {k.lower(): data[k.lower()].last_marquee_price for k in MARQUEE_SYMBOLS}
            last_marquee_rebuild = now

        marquee_x -= MARQUEE_SPEED
        if local_total_width > 0 and marquee_x <= -(local_total_width / 2):
            marquee_x += local_total_width / 2

        render_surface.blit(BG_SURFACE, (0, 0))

        # Logo + symbol name (top-left)
        logo = logos_dict.get(current_symbol)
        if logo is not None:
            render_surface.blit(logo, (9, 9))
            ticker_name = current_symbol.replace("usdt", "").upper()
            if current_symbol == "runecoin":
                ticker_name = "RUNECOIN"
            name_surf = FONT_SMALL.render(ticker_name, True, WHITE)
            name_x = 9 + 24 + 6
            name_y = 9 + 12 - (name_surf.get_height() // 2)
            render_surface.blit(name_surf, (name_x, name_y))

        # Miner stats or clock (top-right)
        with miners_lock:
            total_hr = miner_stats.get("total_hashrate_th", 0)
            best_diff = miner_stats.get("best_difficulty", 0)
            conn_count = miner_stats.get("connected_count", 0)
            active_count = miner_stats.get("active_count", 0)
        total_miners = miner_stats.get("total_miners", 0)

        if total_miners > 0:
            hr_str = format_hashrate(total_hr)
            diff_str = format_difficulty(best_diff)

            if conn_count == total_miners and active_count == total_miners:
                miner_color = BLUE
            elif conn_count > 0:
                miner_color = ORANGE
            else:
                miner_color = RED

            miner_surf = FONT_HASHRATE.render(f"{hr_str} - {diff_str}", True, miner_color)
            miner_x = render_width - 25 - miner_surf.get_width()
            render_surface.blit(miner_surf, (miner_x, 9))

            # Hashrate curve overlay (semi-transparent)
            hr_values = list(hash_history)
            if len(hr_values) > 1:
                min_hr = min(hr_values)
                max_hr = max(hr_values)
                hr_range = max(max_hr - min_hr, 0.001)

                def hr_to_y(h: float) -> int:
                    norm = (h - min_hr) / hr_range
                    return CHART_Y + CHART_H - int(norm * CHART_H)

                line_surf = pygame.Surface((CHART_W, CHART_H), pygame.SRCALPHA)
                points = []
                for i, hr in enumerate(hr_values):
                    x = int((i / (len(hr_values) - 1)) * (CHART_W - 1))
                    y = hr_to_y(hr) - CHART_Y
                    points.append((x, y))

                if points:
                    pygame.draw.lines(line_surf, miner_color, False, points, HASHRATE_CURVE_THICKNESS)
                line_surf.set_alpha(128)
                render_surface.blit(line_surf, (CHART_X, CHART_Y))
        else:
            # Show current time instead
            time_str = time.strftime('%H:%M', time.localtime(now))
            time_surf = FONT_HASHRATE.render(time_str, True, WHITE)
            time_x = render_width - 25 - time_surf.get_width()
            render_surface.blit(time_surf, (time_x, 9))

        # Connection status dot (top-right)
        ws_color = get_ws_color()
        indicator_y = 9 + FONT_HASHRATE.get_height() // 2 + 1
        pygame.draw.circle(render_surface, ws_color, (render_width - 16, indicator_y), 4)

        # Mempool/network info (BTC only, centered)
        if current_symbol == "btcusdt":
            with fees_lock:
                fees = mempool_data.get("fees_sats_vb")
                height = mempool_data.get("block_height")
                pool = mempool_data.get("mining_pool")
                net_hr = mempool_data.get("network_hashrate_eh")
                net_diff = mempool_data.get("network_difficulty")

            if fees is not None and height is not None:
                parts = [f"{fees:.1f} sat/vB", str(height)]
                if pool:
                    parts.append(pool)
                if net_hr is not None:
                    parts.append(format_network_hashrate(net_hr))
                if net_diff is not None:
                    parts.append(format_difficulty(net_diff))
                top_text = " | ".join(parts)
                top_color = WHITE
            else:
                top_text = "Loading network data…"
                top_color = GRAY
        else:
            top_text = ""
            top_color = WHITE

        top_surf = render_adaptive_text(top_text, MEMPOOL_MAX_WIDTH, top_color,
                                        start_size=16, min_size=8, bold=False)
        top_y = 48
        top_x = (render_width - top_surf.get_width()) // 2
        render_surface.blit(top_surf, (top_x, top_y))

        # Price, change, candlesticks (center)
        if (ticker and ticker.price is not None and ticker.last_update is not None
                and now - ticker.last_update < DATA_TIMEOUT):
            price_str = f"${ticker.price:,.2f}"
            price_surf = FONT_BIG.render(price_str, True, WHITE)
            price_y = 75 if current_symbol == "btcusdt" else 55
            render_surface.blit(price_surf, ((render_width - price_surf.get_width()) // 2, price_y))

            change_color = GREEN if ticker.change_24h >= 0 else RED
            arrow = "↑" if ticker.change_24h >= 0 else "↓"
            change_text = f"{arrow} {ticker.change_24h:+.2f}%"
            change_surf = FONT_MID.render(change_text, True, change_color)
            change_y = 142 if current_symbol == "btcusdt" else 122
            render_surface.blit(change_surf, ((render_width - change_surf.get_width()) // 2, change_y))

            # Candlestick chart
            candles = list(ticker.candles)
            if ticker.current_candle:
                candles.append(ticker.current_candle)

            if len(candles) > 1:
                all_highs = [c["high"] for c in candles]
                all_lows = [c["low"] for c in candles]
                min_price = min(all_lows)
                max_price = max(all_highs)
                price_range = max(max_price - min_price, 0.001)
                candle_width = CHART_W / len(candles)

                def price_to_y(p: float) -> int:
                    norm = (p - min_price) / price_range
                    return CHART_Y + CHART_H - int(norm * CHART_H)

                for i, candle in enumerate(candles):
                    x_center = CHART_X + i * candle_width + candle_width / 2
                    color_candle = GREEN if candle["close"] >= candle["open"] else RED

                    # Wick
                    pygame.draw.line(
                        render_surface, WHITE,
                        (x_center, price_to_y(candle["high"])),
                        (x_center, price_to_y(candle["low"])),
                        1
                    )

                    # Body
                    open_y = price_to_y(candle["open"])
                    close_y = price_to_y(candle["close"])
                    top_y_c = min(open_y, close_y)
                    height = max(3, abs(close_y - open_y))
                    pygame.draw.rect(
                        render_surface, color_candle,
                        (x_center - candle_width * 0.28, top_y_c,
                         candle_width * 0.56, height),
                        border_radius=0
                    )
        else:
            status_text = ticker.status if ticker else "No data"
            status_surf = FONT_MID.render(status_text, True, GRAY)
            render_surface.blit(status_surf, ((render_width - status_surf.get_width()) // 2, 140))

        # Final overlays
        render_surface.blit(DIM_LAYER, (0, 0))
        pygame.draw.rect(render_surface, (18, 18, 28), (0, MARQUEE_Y, render_width, MARQUEE_HEIGHT))

        # Scrolling marquee
        current_pos = int(marquee_x)
        for surf, width in local_surfaces:
            if current_pos + width < 0:
                current_pos += width
                continue
            if current_pos > render_width:
                break
            render_surface.blit(surf, (current_pos, MARQUEE_Y))
            current_pos += width

        # Output to screen (with scaling if needed)
        screen.fill(BLACK)
        if scale_factor != 1.0:
            scaled = pygame.transform.smoothscale(render_surface, (display_width, display_height))
            screen.blit(scaled, (offset_x, offset_y))
        else:
            screen.blit(render_surface, (0, 0))

        pygame.display.flip()
        clock.tick(FPS)
        pygame.event.pump()

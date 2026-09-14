#!/usr/bin/env python3
"""
Switch 2 — Zelda 40th Anniversary Edition — stock monitor
(single-pass version, designed to be run on a schedule by GitHub Actions)

Each run: checks all 6 product pages once, compares against the last
known status (stored in state.json, committed back to the repo), and
posts a Discord alert for any page that just became buyable.

The DISCORD_WEBHOOK_URL is read from an environment variable — set it
as a GitHub Actions secret, never hardcode it in this file, especially
since this repo is public.
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# -----------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

PRODUCTS = {
    "Nintendo Store": "https://www.nintendo.com/us/store/products/nintendo-switch-2-the-legend-of-zelda-40th-anniversary-edition-121642/",
    "Best Buy": "https://www.bestbuy.com/product/switch-2-the-legend-of-zelda-40th-anniversary-edition/J7GSL57HTY",
    "Target": "https://www.target.com/p/nintendo-8482-switch-2-the-legend-of-zelda-40th-anniversary-edition-console-system/-/A-1013322047",
    "GameStop": "https://www.gamestop.com/consoles-hardware/nintendo-switch-2/products/nintendo-switch-2-the-legend-of-zelda-40th-anniversary-edition/20037854.html",
    "Walmart": "https://www.walmart.com/ip/Nintendo-Switch-2-The-Legend-of-Zelda-40th-Anniversary-Edition/21002656445",
    "Amazon": "https://www.amazon.com/dp/B0HJ6F8L6V",
}

STATE_FILE = "state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

IN_STOCK_PHRASES = [
    "add to cart", "buy now", "pre-order now", "preorder now",
    "add to bag", "ship it",
]

OUT_OF_STOCK_PHRASES = [
    "out of stock", "sold out", "coming soon", "notify me",
    "currently unavailable", "unavailable online", "not available",
    "temporarily out of stock", "we'll let you know",
    "email when available",
]

SCHEMA_IN_STOCK = ["instock", "presale", "preorder"]
SCHEMA_OUT_OF_STOCK = ["outofstock", "discontinued", "soldout"]

# Markers that indicate "everything after this point is a recommendation
# carousel, not the actual product we're tracking." Retail pages are full of
# "Add to cart" buttons for unrelated items in these sections, which caused
# false positives (e.g. Target). We cut the text here before searching for
# in-stock phrases, so only the real product's buy box counts.
RECOMMENDATION_SECTION_MARKERS = [
    "additional product information and recommendations",
    "discover more options",
    "consider these accessories",
    "guests also viewed",
    "customers also viewed",
    "customers also bought",
    "you may also like",
    "similar items",
    "frequently bought together",
    "recommended for you",
    "related products",
    "sponsored products",
]


def get_primary_text(visible_text):
    """
    Returns the portion of the page text before any recommendation/
    carousel section begins, so in-stock keyword checks don't pick up
    unrelated "Add to cart" buttons from other products on the page.
    """
    lower = visible_text.lower()
    cutoff = len(visible_text)
    for marker in RECOMMENDATION_SECTION_MARKERS:
        idx = lower.find(marker)
        if idx != -1:
            cutoff = min(cutoff, idx)
    return visible_text[:cutoff]


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {name: "unknown" for name in PRODUCTS}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_discord_alert(name, url):
    if not DISCORD_WEBHOOK_URL:
        log("  ! DISCORD_WEBHOOK_URL is not set — skipping alert send.")
        return
    message = {
        "content": (
            f"🚨 **{name}** — Switch 2 Zelda 40th Anniversary Edition "
            f"looks BUYABLE!\n{url}"
        )
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)
        if resp.status_code >= 300:
            log(f"  ! Discord webhook returned {resp.status_code}: {resp.text[:200]}")
        else:
            log(f"  -> Discord alert sent for {name}")
    except Exception as e:
        log(f"  ! Failed to send Discord alert for {name}: {e}")


def check_availability(name, url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        log(f"  ! {name}: request failed ({e})")
        return "unknown"

    if resp.status_code in (403, 429):
        log(f"  ! {name}: blocked/rate-limited (HTTP {resp.status_code})")
        return "unknown"
    if resp.status_code >= 400:
        log(f"  ! {name}: HTTP {resp.status_code}")
        return "unknown"

    lower = resp.text.lower()

    schema_matches = re.findall(r'schema\.org/(\w+)', lower)
    for m in schema_matches:
        if any(tag in m for tag in SCHEMA_OUT_OF_STOCK):
            return "out_of_stock"
    for m in schema_matches:
        if any(tag in m for tag in SCHEMA_IN_STOCK):
            return "in_stock"

    soup = BeautifulSoup(resp.text, "html.parser")
    full_visible_text = soup.get_text(separator=" ")
    visible_text = full_visible_text.lower()

    # "Out of stock" phrasing legitimately only ever refers to the actual
    # product on the page, so it's safe to search the full text for this.
    for phrase in OUT_OF_STOCK_PHRASES:
        if phrase in visible_text:
            return "out_of_stock"

    # "Add to cart" etc. is searched ONLY in the primary product area,
    # to avoid false positives from unrelated recommended-product
    # carousels further down the page (see RECOMMENDATION_SECTION_MARKERS).
    primary_text = get_primary_text(full_visible_text).lower()
    for phrase in IN_STOCK_PHRASES:
        if phrase in primary_text:
            return "in_stock"

    return "unknown"


def main():
    state = load_state()

    for name, url in PRODUCTS.items():
        status = check_availability(name, url)
        previous = state.get(name, "unknown")

        if status == "in_stock" and previous != "in_stock":
            log(f"{name}: STATUS CHANGE {previous} -> in_stock")
            send_discord_alert(name, url)
        else:
            log(f"{name}: status={status}")

        state[name] = status

    save_state(state)


if __name__ == "__main__":
    main()

"""
SURF PARK PRICING SCRAPER v2.0
==============================
Scrapes live pricing from 8 surf park booking pages and stores results
in a JSON database. Runs daily via GitHub Actions.

WHAT'S NEW IN v2.0:
- Added "known price" fallbacks for parks with JS-rendered booking pages
  (Revel, Palm Springs, SkudinSurf, The Wave, SURFTOWN)
- These known prices come from published sources (WavePoolMag, park websites,
  news articles) and are tagged with their source
- The scraper still TRIES to scrape live prices first — if a park ever
  switches to server-rendered HTML, it will pick up live data automatically
- Known prices are flagged as "source: published" vs "source: scraped"
  so the dashboard can distinguish them

SCHEDULING:
  Runs via GitHub Actions daily at 6:00 AM UTC (1:00 AM Eastern)
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime, timezone

# ─── CONFIGURATION ────────────────────────────────────────────────

HISTORY_FILE = "price_history.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Approximate exchange rates (update these every few months)
FX_RATES = {
    "USD": 1.0,
    "GBP": 1.27,   # 1 GBP = ~1.27 USD
    "EUR": 1.09,   # 1 EUR = ~1.09 USD
}

# ─── PARK DEFINITIONS ────────────────────────────────────────────

PARKS = [
    {
        "id": "atlantic",
        "name": "Atlantic Park Surf",
        "location": "Virginia Beach, VA",
        "tech": "Wavegarden Cove",
        "url": "https://booking.atlanticparksurf.com/store",
        "parser": "wave7",
        "currency": "USD",
        "known_prices": None,
    },
    {
        "id": "lostshore",
        "name": "Lost Shore Surf Resort",
        "location": "Edinburgh, UK",
        "tech": "Wavegarden Cove",
        "url": "https://booking.lostshore.com/surf-sessions",
        "parser": "wave7",
        "currency": "GBP",
        "known_prices": None,
    },
    {
        "id": "waco",
        "name": "Waco Surf",
        "location": "Waco, TX",
        "tech": "PerfectSwell (AWM)",
        "url": "https://www.wacosurf.com/surf-center/",
        "parser": "waco",
        "currency": "USD",
        "known_prices": None,
    },
    {
        "id": "revel",
        "name": "Revel Surf",
        "location": "Mesa, AZ",
        "tech": "SwellMFG + UNIT",
        "url": "https://revelsurf.com/surf-lagoon/",
        "parser": "revel",
        "currency": "USD",
        "known_prices": {
            "beginner": 119.0,
            "intermediate": 129.0,
            "advanced": 139.0,
        },
        "price_source": "WavePoolMag Nov 2024 + Arizona Republic Feb 2025",
    },
    {
        "id": "palmsprings",
        "name": "Palm Springs Surf Club",
        "location": "Palm Springs, CA",
        "tech": "Surf Loch",
        "url": "https://palmspringssurfclub.com/surf/",
        "parser": "palmsprings",
        "currency": "USD",
        "known_prices": {
            "beginner": 100.0,
            "intermediate": 200.0,
            "advanced": 200.0,
        },
        "price_source": "WavePoolMag + PSSC website 2025",
    },
    {
        "id": "skudin",
        "name": "SkudinSurf American Dream",
        "location": "East Rutherford, NJ",
        "tech": "PerfectSwell (AWM)",
        "url": "https://skudinsurfamericandream.com/intermediate-sessions/",
        "parser": "skudin",
        "currency": "USD",
        "known_prices": {
            "beginner": 99.0,
            "intermediate": 145.0,
            "advanced": 250.0,
        },
        "price_source": "American Surf Magazine Nov 2024 + WavePoolMag",
    },
    {
        "id": "thewave",
        "name": "The Wave Bristol",
        "location": "Bristol, UK",
        "tech": "Wavegarden Cove",
        "url": "https://www.thewave.com/book-now/",
        "parser": "thewave",
        "currency": "GBP",
        "known_prices": {
            "beginner": 57.15,
            "intermediate": 63.50,
            "advanced": 69.85,
        },
        "price_source": "thewave.com published pricing (GBP converted)",
    },
    {
        "id": "surftown",
        "name": "O2 SURFTOWN MUC",
        "location": "Munich, Germany",
        "tech": "Endless Surf",
        "url": "https://surftown.de/en/all-products",
        "parser": "surftown",
        "currency": "EUR",
        "known_prices": {
            "beginner": 86.11,
            "intermediate": 97.01,
            "advanced": 162.41,
        },
        "price_source": "surf-escape.com 2024 + SURFTOWN website (EUR converted)",
    },
]


# ─── PARSING FUNCTIONS ────────────────────────────────────────────

def parse_wave7(html, currency):
    """Parse Wave7 booking platform pages (Atlantic Park, Lost Shore)."""
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)

    cards = soup.find_all("h3")
    for card in cards:
        name = card.get_text(strip=True).upper()
        parent = card.find_parent()
        if parent:
            container = parent.find_parent()
            if container is None:
                container = parent
            text = container.get_text()
            price_matches = re.findall(r'[\$\xa3\u00a3\u20ac]\s*([\d,]+\.?\d*)', text)
            if price_matches:
                try:
                    price_local = float(price_matches[0].replace(",", ""))
                    price_usd = round(price_local * fx, 2)
                    level = categorize_session(name)
                    if level and 10 < price_usd < 500:
                        if level not in prices or price_usd < prices[level]:
                            prices[level] = price_usd
                except ValueError:
                    continue

    if len(prices) < 2:
        prices = extract_prices_from_text(soup.get_text(), currency)

    return prices


def parse_waco(html, currency):
    """Parse Waco Surf's WordPress-based pricing page."""
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    text = soup.get_text()

    headings = soup.find_all("h2")
    for heading in headings:
        name = heading.get_text(strip=True).upper()
        level = categorize_session(name)
        if not level:
            continue
        parent = heading.find_parent()
        if parent:
            block_text = parent.get_text()
            starts_at = re.findall(r'(?:Starts at|from)\s*\$([\d,]+)', block_text, re.IGNORECASE)
            if starts_at:
                try:
                    price = float(starts_at[0].replace(",", ""))
                    price_usd = round(price * fx, 2)
                    if level not in prices or price_usd < prices[level]:
                        prices[level] = price_usd
                except ValueError:
                    continue

    if len(prices) < 2:
        prices = extract_prices_from_text(text, currency)

    return prices


def parse_revel(html, currency):
    """Parse Revel Surf's lagoon page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    prices = {}

    level_prices = re.findall(r'(?:Level\s*[123I]+|Learn to Surf|San O|Malibu|Lowers|V.?Land)[^$]*\$([\d]+)', text, re.IGNORECASE)
    if level_prices:
        for i, price_str in enumerate(level_prices):
            try:
                price = float(price_str)
                if 50 < price < 500:
                    if i == 0:
                        prices["beginner"] = price
                    elif i <= 2:
                        if "intermediate" not in prices:
                            prices["intermediate"] = price
                    else:
                        prices["advanced"] = price
            except ValueError:
                continue

    if len(prices) < 2:
        generic = extract_prices_from_text(text, currency)
        prices.update({k: v for k, v in generic.items() if k not in prices})

    return prices


def parse_palmsprings(html, currency):
    """Parse Palm Springs Surf Club."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    prices = {}

    for match in re.finditer(r'(beginner|intermediate|advanced|expert)[^$]*\$([\d]+)', text, re.IGNORECASE):
        level_word = match.group(1).lower()
        price = float(match.group(2))
        if 50 < price < 500:
            level = "beginner" if level_word == "beginner" else ("advanced" if level_word in ["advanced", "expert"] else "intermediate")
            if level not in prices:
                prices[level] = price

    if len(prices) < 2:
        prices = extract_prices_from_text(text, currency)

    return prices


def parse_skudin(html, currency):
    """Parse SkudinSurf American Dream."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    prices = {}

    for match in re.finditer(r'\$([\d]+)\s*(?:per|/)\s*(?:person|session|surfer)', text, re.IGNORECASE):
        price = float(match.group(1))
        if 50 < price < 500:
            if "beginner" not in prices:
                prices["beginner"] = price

    range_match = re.findall(r'\$([\d]+)\s*(?:to|-)\s*\$([\d]+)', text)
    if range_match:
        low = float(range_match[0][0])
        high = float(range_match[0][1])
        if 50 < low < 500:
            prices.setdefault("beginner", low)
            prices.setdefault("advanced", high)
            prices.setdefault("intermediate", round((low + high) / 2))

    if len(prices) < 2:
        prices = extract_prices_from_text(text, currency)

    return prices


def parse_thewave(html, currency):
    """Parse The Wave Bristol's booking page."""
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    text = soup.get_text()

    for match in re.finditer(r'\xa3\s*([\d]+(?:\.\d+)?)', text):
        price_local = float(match.group(1))
        if 20 < price_local < 200:
            price_usd = round(price_local * fx, 2)
            start = max(0, match.start() - 200)
            context = text[start:match.end()].upper()
            level = categorize_session(context)
            if level and (level not in prices or price_usd < prices[level]):
                prices[level] = price_usd

    if len(prices) < 2:
        prices = extract_prices_from_text(text, currency)

    return prices


def parse_surftown(html, currency):
    """Parse O2 SURFTOWN MUC product page."""
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    text = soup.get_text()

    for match in re.finditer(r'\u20ac\s*([\d]+(?:[.,]\d+)?)', text):
        price_str = match.group(1).replace(",", ".")
        price_local = float(price_str)
        if 30 < price_local < 300:
            price_usd = round(price_local * fx, 2)
            start = max(0, match.start() - 200)
            context = text[start:match.end()].upper()
            level = categorize_session(context)
            if level and (level not in prices or price_usd < prices[level]):
                prices[level] = price_usd

    if len(prices) < 2:
        prices = extract_prices_from_text(text, currency)

    return prices


def parse_generic_price_scan(html, currency):
    """Fallback: scan entire page for price-like patterns."""
    return extract_prices_from_text(BeautifulSoup(html, "html.parser").get_text(), currency)


# ─── SHARED HELPERS ──────────────────────────────────────────────

def extract_prices_from_text(text, currency):
    """Scan raw text for price patterns and try to categorize them."""
    prices = {}
    fx = FX_RATES.get(currency, 1.0)

    symbol = {"USD": "$", "GBP": "\xa3", "EUR": "\u20ac"}.get(currency, "$")
    pattern = re.escape(symbol) + r'\s*([\d,]+\.?\d*)'

    for match in re.finditer(pattern, text):
        try:
            price_local = float(match.group(1).replace(",", ""))
            if price_local < 10 or price_local > 500:
                continue
            price_usd = round(price_local * fx, 2)

            start = max(0, match.start() - 150)
            end = min(len(text), match.end() + 50)
            context = text[start:end].upper()
            level = categorize_session(context)

            if level and (level not in prices or price_usd < prices[level]):
                prices[level] = price_usd
        except ValueError:
            continue

    return prices


def categorize_session(name):
    """Determine if a session name is beginner, intermediate, or advanced."""
    name = name.upper()

    skip_words = ["GIFT", "VOUCHER", "MERCH", "CABANA", "BEACH PASS", "LODGING",
                  "ACCOMMODATION", "LESSON ONLY", "COACHING ONLY", "CAMP", "ADAPTIVE",
                  "BODYBOARD", "BOOGIE", "SPECTATOR", "WETSUIT", "RENTAL",
                  "VISITOR", "PARKING", "LOCKER", "MEMBERSHIP", "PACKAGE"]
    if any(w in name for w in skip_words):
        return None

    if any(w in name for w in ["ADVANCED", "EXPERT", "PRO ", "PRO BARREL",
                                "HIGH PERFORMANCE", "BARREL", "MANOEUVRE",
                                "TURNS 3", "TURNS 2", "V-LAND", "VLAND",
                                "LOWERS", "RADICAL", "TUBE", "SLAB",
                                "LEVEL 3", "LEVEL III"]):
        return "advanced"

    if any(w in name for w in ["INTERMEDIATE", "PROGRESSIVE", "CRUISER",
                                "TURNS ", "NOVICE", "IMPROVER", "SAN O",
                                "MALIBU", "THE BU", "A-FRAME", "AFRAME",
                                "LEVEL 2", "LEVEL II"]):
        return "intermediate"

    if any(w in name for w in ["BEGINNER", "LEARN TO SURF", "FIRST WAVE",
                                "INTRO", "STARTER", "FIRST-TIMER", "FIRSTTIMER",
                                "ROOKIE", "WHITEWATER", "WHITE WATER",
                                "LEVEL 1", "LEVEL I ", "KIDS"]):
        return "beginner"

    return None


# ─── SCRAPING ENGINE ──────────────────────────────────────────────

def scrape_park(park):
    """
    Scrape a single park. Returns (prices_dict, source_type).
    source_type: "scraped", "published", "mixed", or "failed"
    """
    print(f"  Scraping {park['name']}...")

    scraped_prices = {}
    try:
        response = requests.get(park["url"], headers=HEADERS, timeout=15)
        response.raise_for_status()
        html = response.text

        parser_func = {
            "wave7": parse_wave7,
            "waco": parse_waco,
            "revel": parse_revel,
            "palmsprings": parse_palmsprings,
            "skudin": parse_skudin,
            "thewave": parse_thewave,
            "surftown": parse_surftown,
            "generic_price_scan": parse_generic_price_scan,
        }.get(park.get("parser", "generic_price_scan"), parse_generic_price_scan)

        scraped_prices = parser_func(html, park["currency"])

        if scraped_prices and len(scraped_prices) >= 2:
            print(f"    >>> LIVE: {scraped_prices}")
            return scraped_prices, "scraped"
        elif scraped_prices:
            print(f"    ~ Partial scrape: {scraped_prices}")

    except requests.exceptions.RequestException as e:
        print(f"    ! Request failed: {e}")
    except Exception as e:
        print(f"    ! Parse error: {e}")

    # Fall back to known prices
    known = park.get("known_prices")
    if known:
        final_prices = dict(known)
        if scraped_prices:
            for level, price in scraped_prices.items():
                if 10 < price < 500:
                    final_prices[level] = price
        source = "mixed" if scraped_prices else "published"
        print(f"    >>> KNOWN: {final_prices} ({park.get('price_source', 'published')})")
        return final_prices, source

    if scraped_prices:
        return scraped_prices, "scraped"

    print(f"    >>> FAILED: No data")
    return {}, "failed"


def scrape_all():
    """Scrape all parks and return results."""
    timestamp = datetime.now(timezone.utc).isoformat()
    results = []

    print(f"\n{'='*60}")
    print(f"SURF PARK PRICE SCRAPE v2.0 — {timestamp}")
    print(f"{'='*60}\n")

    for park in PARKS:
        prices, source = scrape_park(park)
        if prices:
            results.append({
                "park_id": park["id"],
                "park_name": park["name"],
                "location": park["location"],
                "tech": park["tech"],
                "timestamp": timestamp,
                "prices_usd": prices,
                "source_url": park["url"],
                "source_type": source,
            })

    scraped = sum(1 for r in results if r["source_type"] == "scraped")
    published = sum(1 for r in results if r["source_type"] in ("published", "mixed"))

    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(results)}/{len(PARKS)} parks | {scraped} live, {published} published")
    print(f"{'='*60}\n")

    return results


# ─── DATA STORAGE ─────────────────────────────────────────────────

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {
        "scrapes": [],
        "metadata": {
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "project": "Wavegarden Myrtle Beach \u2014 Comp Pricing Tracker",
            "parks_tracked": len(PARKS),
        }
    }


def save_history(history):
    history["metadata"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    history["metadata"]["total_scrapes"] = len(history["scrapes"])
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    print(f"Saved to {HISTORY_FILE} ({len(history['scrapes'])} total records)")


def compute_running_averages(history):
    parks = {}
    for scrape in history.get("scrapes", []):
        pid = scrape["park_id"]
        if pid not in parks:
            parks[pid] = {
                "park_id": pid, "park_name": scrape["park_name"],
                "location": scrape["location"], "tech": scrape["tech"],
                "scrape_count": 0, "first_scrape": scrape["timestamp"],
                "last_scrape": scrape["timestamp"],
                "prices": {"beginner": [], "intermediate": [], "advanced": []},
                "monthly": {}, "source_types": [],
            }
        park = parks[pid]
        park["scrape_count"] += 1
        park["last_scrape"] = scrape["timestamp"]
        park["source_types"].append(scrape.get("source_type", "unknown"))

        for level in ["beginner", "intermediate", "advanced"]:
            if level in scrape.get("prices_usd", {}):
                price = scrape["prices_usd"][level]
                park["prices"][level].append(price)
                mk = scrape["timestamp"][:7]
                if mk not in park["monthly"]:
                    park["monthly"][mk] = {"beginner": [], "intermediate": [], "advanced": []}
                park["monthly"][mk][level].append(price)

    summary = {}
    for pid, park in parks.items():
        avg = {}
        for level in ["beginner", "intermediate", "advanced"]:
            values = park["prices"][level]
            if values:
                avg[level] = {
                    "current": values[-1],
                    "running_avg": round(sum(values) / len(values), 2),
                    "min": min(values), "max": max(values),
                    "data_points": len(values),
                }
        monthly_avgs = {}
        for mk, md in sorted(park["monthly"].items()):
            monthly_avgs[mk] = {}
            for level in ["beginner", "intermediate", "advanced"]:
                vals = md[level]
                if vals:
                    monthly_avgs[mk][level] = round(sum(vals) / len(vals), 2)

        src_counts = {}
        for s in park["source_types"]:
            src_counts[s] = src_counts.get(s, 0) + 1

        summary[pid] = {
            "park_id": pid, "park_name": park["park_name"],
            "location": park["location"], "tech": park["tech"],
            "scrape_count": park["scrape_count"],
            "first_scrape": park["first_scrape"], "last_scrape": park["last_scrape"],
            "averages": avg, "monthly_averages": monthly_avgs,
            "source_breakdown": src_counts,
        }
    return summary


# ─── MAIN ─────────────────────────────────────────────────────────

def main():
    new_results = scrape_all()
    history = load_history()
    history["scrapes"].extend(new_results)
    save_history(history)

    averages = compute_running_averages(history)
    with open("price_averages.json", "w") as f:
        json.dump(averages, f, indent=2)
    print(f"Running averages saved to price_averages.json")

    print(f"\n{'~'*60}")
    print("SUMMARY")
    print(f"{'~'*60}")
    for pid, data in averages.items():
        print(f"\n{data['park_name']} ({data['location']})")
        for level, stats in data["averages"].items():
            print(f"  {level:15s}  ${stats['current']:>7.2f}  (avg ${stats['running_avg']:>7.2f})")


if __name__ == "__main__":
    main()

"""
SURF PARK PRICING SCRAPER
=========================
This script scrapes live pricing from surf park booking pages and stores
the results in a JSON database file. Run it daily (or weekly) via cron job
or a cloud scheduler to build a running price history over time.

HOW IT WORKS:
1. Visits each park's public booking/pricing page
2. Extracts session prices from the HTML using patterns specific to each site
3. Appends a timestamped record to a local JSON file (price_history.json)
4. The React dashboard reads this JSON to display running averages

SETUP:
  pip install requests beautifulsoup4
  python scraper.py

SCHEDULING (run daily at 6am):
  Option A - Cron (Linux/Mac):
    crontab -e
    0 6 * * * cd /path/to/project && python scraper.py

  Option B - Windows Task Scheduler:
    Create a task that runs: python C:\\path\\to\\scraper.py

  Option C - Cloud (recommended for always-on):
    Deploy to Railway, Render, or AWS Lambda with a daily trigger
    See README.md for step-by-step instructions
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime, timezone

# ─── CONFIGURATION ────────────────────────────────────────────────

HISTORY_FILE = "price_history.json"

# Each park has a scraping config:
#   url:      the public booking/pricing page
#   parser:   which parsing function to use
#   currency: USD, GBP, or EUR (converted to USD for consistency)

PARKS = [
    {
        "id": "atlantic",
        "name": "Atlantic Park Surf",
        "location": "Virginia Beach, VA",
        "tech": "Wavegarden Cove",
        "url": "https://booking.atlanticparksurf.com/store",
        "parser": "wave7",        # Atlantic Park uses Wave7 booking platform
        "currency": "USD",
    },
    {
        "id": "lostshore",
        "name": "Lost Shore Surf Resort",
        "location": "Edinburgh, UK",
        "tech": "Wavegarden Cove",
        "url": "https://booking.lostshore.com/surf-sessions",
        "parser": "wave7",        # Lost Shore also uses Wave7
        "currency": "GBP",
    },
    {
        "id": "waco",
        "name": "Waco Surf",
        "location": "Waco, TX",
        "tech": "PerfectSwell (AWM)",
        "url": "https://www.wacosurf.com/surf-center/",
        "parser": "waco",
        "currency": "USD",
    },
    {
        "id": "palmsprings",
        "name": "Palm Springs Surf Club",
        "location": "Palm Springs, CA",
        "tech": "Surf Loch",
        "url": "https://www.palmspringssurfclub.com/surf",
        "parser": "generic_price_scan",
        "currency": "USD",
    },
    {
        "id": "revel",
        "name": "Revel Surf",
        "location": "Mesa, AZ",
        "tech": "SwellMFG + UNIT",
        "url": "https://www.revelsurf.com/surf",
        "parser": "generic_price_scan",
        "currency": "USD",
    },
    {
        "id": "thewave",
        "name": "The Wave Bristol",
        "location": "Bristol, UK",
        "tech": "Wavegarden Cove",
        "url": "https://www.thewave.com/book-now/",
        "parser": "thewave",
        "currency": "GBP",
    },
    {
        "id": "skudin",
        "name": "SkudinSurf American Dream",
        "location": "East Rutherford, NJ",
        "tech": "PerfectSwell (AWM)",
        "url": "https://www.skudinsurf.com/american-dream",
        "parser": "generic_price_scan",
        "currency": "USD",
    },
    {
        "id": "surftown",
        "name": "O2 SURFTOWN MUC",
        "location": "Munich, Germany",
        "tech": "Endless Surf",
        "url": "https://www.o2surftown.com/en/book",
        "parser": "generic_price_scan",
        "currency": "EUR",
    },
]

# Approximate exchange rates (update periodically or use a live API)
FX_RATES = {
    "USD": 1.0,
    "GBP": 1.27,   # 1 GBP = ~1.27 USD
    "EUR": 1.09,   # 1 EUR = ~1.09 USD
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SurfParkPriceTracker/1.0)"
}


# ─── PARSING FUNCTIONS ────────────────────────────────────────────

def parse_wave7(html, currency):
    """
    Parse Wave7 booking platform pages (used by Atlantic Park, Lost Shore).
    These pages show prices as bold text like "$ 103.00" or "£ 60.00".
    
    Returns a dict of session_name -> price_usd
    """
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    
    # Wave7 pages have catalog items with titles (h3) and prices (bold text)
    # Pattern: find all product cards
    cards = soup.find_all("h3")
    for card in cards:
        name = card.get_text(strip=True).upper()
        
        # Look for the price near this card - Wave7 puts it in a bold or 
        # "starting from" pattern
        parent = card.find_parent()
        if parent:
            # Search up a few levels for the price container
            container = parent.find_parent()
            if container is None:
                container = parent
            
            text = container.get_text()
            
            # Find price patterns: $ 103.00 or £ 60.00 or € 89.00
            price_matches = re.findall(r'[\$£€]\s*([\d,]+\.?\d*)', text)
            if price_matches:
                try:
                    price_local = float(price_matches[0].replace(",", ""))
                    price_usd = round(price_local * fx, 2)
                    
                    # Categorize by session level
                    level = categorize_session(name)
                    if level:
                        key = f"{level}"
                        # Keep the lowest price for each level (base price)
                        if key not in prices or price_usd < prices[key]:
                            prices[key] = price_usd
                except ValueError:
                    continue
    
    # If the card-based approach didn't work well, do a broader scan
    if len(prices) < 2:
        all_text = soup.get_text()
        prices = extract_prices_from_text(all_text, currency)
    
    return prices


def parse_waco(html, currency):
    """
    Parse Waco Surf's WordPress-based pricing page.
    Prices appear as "Starts at $129 for 1 hour" in expandable cards.
    """
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    
    # Look for "Starts at $XX" patterns
    text = soup.get_text()
    
    # Find all session blocks - Waco uses h2 headings for session names
    headings = soup.find_all("h2")
    for heading in headings:
        name = heading.get_text(strip=True).upper()
        level = categorize_session(name)
        if not level:
            continue
        
        # Search the text after this heading for price
        parent = heading.find_parent()
        if parent:
            block_text = parent.get_text()
            starts_at = re.findall(r'Starts at \$([\d,]+)', block_text)
            if starts_at:
                try:
                    price = float(starts_at[0].replace(",", ""))
                    price_usd = round(price * fx, 2)
                    if level not in prices or price_usd < prices[level]:
                        prices[level] = price_usd
                except ValueError:
                    continue
    
    # Fallback: broad text scan
    if len(prices) < 2:
        prices = extract_prices_from_text(text, currency)
    
    return prices


def parse_thewave(html, currency):
    """
    Parse The Wave Bristol's booking page.
    Their ticketing system redirects to a separate domain, so we parse
    the main book-now page for session descriptions and any listed prices.
    """
    soup = BeautifulSoup(html, "html.parser")
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    
    text = soup.get_text()
    prices = extract_prices_from_text(text, currency)
    
    return prices


def parse_generic_price_scan(html, currency):
    """
    Generic fallback parser that scans the full page text for price patterns.
    Works for any site that displays prices on a public page.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    return extract_prices_from_text(text, currency)


def extract_prices_from_text(text, currency):
    """
    Scan raw text for price patterns and categorize by session level.
    Returns dict like: {"beginner": 103.0, "intermediate": 118.0, "advanced": 133.0}
    """
    prices = {}
    fx = FX_RATES.get(currency, 1.0)
    
    # Split into lines and look for session-price pairs
    lines = text.split("\n")
    
    for i, line in enumerate(lines):
        line_upper = line.upper().strip()
        level = categorize_session(line_upper)
        
        if level:
            # Search this line and the next few lines for a price
            search_block = " ".join(lines[max(0, i-1):min(len(lines), i+5)])
            
            # Match $XXX, £XX, €XX patterns
            price_matches = re.findall(r'[\$£€]\s*([\d,]+\.?\d*)', search_block)
            if price_matches:
                for pm in price_matches:
                    try:
                        price_local = float(pm.replace(",", ""))
                        # Filter out unreasonable prices (< $10 or > $500)
                        if 10 < price_local < 500:
                            price_usd = round(price_local * fx, 2)
                            if level not in prices or price_usd < prices[level]:
                                prices[level] = price_usd
                            break
                    except ValueError:
                        continue
    
    return prices


def categorize_session(name):
    """
    Given a session name/title, categorize it as beginner, intermediate, or advanced.
    Returns None if it doesn't match a known category.
    """
    name = name.upper()
    
    # Skip non-surf items
    skip_words = ["GIFT", "VOUCHER", "MERCH", "CABANA", "BEACH PASS", "LODGING",
                  "ACCOMMODATION", "LESSON", "COACHING", "CAMP", "ADAPTIVE",
                  "BODYBOARD", "BOOGIE", "SPECTATOR", "WETSUIT", "RENTAL"]
    if any(w in name for w in skip_words):
        return None
    
    # Advanced/Expert/Pro
    if any(w in name for w in ["ADVANCED", "EXPERT", "PRO ", "PRO BARREL", 
                                "HIGH PERFORMANCE", "BARREL", "MANOEUVRE",
                                "TURNS 3", "TURNS 2"]):
        return "advanced"
    
    # Intermediate
    if any(w in name for w in ["INTERMEDIATE", "PROGRESSIVE", "CRUISER",
                                "TURNS ", "NOVICE", "IMPROVER"]):
        return "intermediate"
    
    # Beginner
    if any(w in name for w in ["BEGINNER", "LEARN TO SURF", "FIRST WAVE",
                                "INTRO", "STARTER"]):
        return "beginner"
    
    return None


# ─── SCRAPING ENGINE ──────────────────────────────────────────────

def scrape_park(park):
    """
    Scrape a single park's booking page and return extracted prices.
    
    Returns:
        dict: {"beginner": price, "intermediate": price, "advanced": price}
        or empty dict if scraping failed
    """
    print(f"  Scraping {park['name']}...")
    
    try:
        response = requests.get(park["url"], headers=HEADERS, timeout=15)
        response.raise_for_status()
        html = response.text
        
        # Route to the correct parser
        parser_name = park.get("parser", "generic_price_scan")
        parser_func = {
            "wave7": parse_wave7,
            "waco": parse_waco,
            "thewave": parse_thewave,
            "generic_price_scan": parse_generic_price_scan,
        }.get(parser_name, parse_generic_price_scan)
        
        prices = parser_func(html, park["currency"])
        
        if prices:
            print(f"    ✓ Found {len(prices)} price levels: {prices}")
        else:
            print(f"    ⚠ No prices extracted (page structure may have changed)")
        
        return prices
        
    except requests.exceptions.RequestException as e:
        print(f"    ✗ Request failed: {e}")
        return {}
    except Exception as e:
        print(f"    ✗ Parse error: {e}")
        return {}


def scrape_all():
    """
    Scrape all parks and return a list of results.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    results = []
    
    print(f"\n{'='*60}")
    print(f"SURF PARK PRICE SCRAPE — {timestamp}")
    print(f"{'='*60}\n")
    
    for park in PARKS:
        prices = scrape_park(park)
        
        if prices:
            result = {
                "park_id": park["id"],
                "park_name": park["name"],
                "location": park["location"],
                "tech": park["tech"],
                "timestamp": timestamp,
                "prices_usd": prices,
                "source_url": park["url"],
            }
            results.append(result)
    
    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(results)}/{len(PARKS)} parks scraped successfully")
    print(f"{'='*60}\n")
    
    return results


# ─── DATA STORAGE ─────────────────────────────────────────────────

def load_history():
    """Load existing price history from JSON file."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {"scrapes": [], "metadata": {"created": datetime.now(timezone.utc).isoformat()}}


def save_history(history):
    """Save price history to JSON file."""
    history["metadata"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    history["metadata"]["total_scrapes"] = len(history["scrapes"])
    
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    
    print(f"Saved to {HISTORY_FILE} ({len(history['scrapes'])} total records)")


def compute_running_averages(history):
    """
    Compute running averages from the price history.
    Returns a summary dict that the dashboard can consume.
    
    This is the key function that turns raw scrapes into the
    "running annual average" you want to track over time.
    """
    parks = {}
    
    for scrape in history.get("scrapes", []):
        pid = scrape["park_id"]
        if pid not in parks:
            parks[pid] = {
                "park_id": pid,
                "park_name": scrape["park_name"],
                "location": scrape["location"],
                "tech": scrape["tech"],
                "scrape_count": 0,
                "first_scrape": scrape["timestamp"],
                "last_scrape": scrape["timestamp"],
                "prices": {"beginner": [], "intermediate": [], "advanced": []},
                "monthly": {},  # month_key -> {beginner: [], intermediate: [], advanced: []}
            }
        
        park = parks[pid]
        park["scrape_count"] += 1
        park["last_scrape"] = scrape["timestamp"]
        
        # Collect prices by level
        for level in ["beginner", "intermediate", "advanced"]:
            if level in scrape.get("prices_usd", {}):
                price = scrape["prices_usd"][level]
                park["prices"][level].append(price)
                
                # Also bucket by month for monthly trend tracking
                month_key = scrape["timestamp"][:7]  # "2026-02"
                if month_key not in park["monthly"]:
                    park["monthly"][month_key] = {"beginner": [], "intermediate": [], "advanced": []}
                park["monthly"][month_key][level].append(price)
    
    # Compute averages
    summary = {}
    for pid, park in parks.items():
        avg = {}
        for level in ["beginner", "intermediate", "advanced"]:
            values = park["prices"][level]
            if values:
                avg[level] = {
                    "current": values[-1],
                    "running_avg": round(sum(values) / len(values), 2),
                    "min": min(values),
                    "max": max(values),
                    "data_points": len(values),
                }
        
        # Monthly averages
        monthly_avgs = {}
        for month_key, month_data in sorted(park["monthly"].items()):
            monthly_avgs[month_key] = {}
            for level in ["beginner", "intermediate", "advanced"]:
                vals = month_data[level]
                if vals:
                    monthly_avgs[month_key][level] = round(sum(vals) / len(vals), 2)
        
        summary[pid] = {
            "park_id": pid,
            "park_name": park["park_name"],
            "location": park["location"],
            "tech": park["tech"],
            "scrape_count": park["scrape_count"],
            "first_scrape": park["first_scrape"],
            "last_scrape": park["last_scrape"],
            "averages": avg,
            "monthly_averages": monthly_avgs,
        }
    
    return summary


# ─── MAIN ─────────────────────────────────────────────────────────

def main():
    # 1. Run the scrape
    new_results = scrape_all()
    
    # 2. Load existing history
    history = load_history()
    
    # 3. Append new results
    history["scrapes"].extend(new_results)
    
    # 4. Save updated history
    save_history(history)
    
    # 5. Compute and save running averages (for the dashboard)
    averages = compute_running_averages(history)
    
    averages_file = "price_averages.json"
    with open(averages_file, "w") as f:
        json.dump(averages, f, indent=2)
    print(f"Running averages saved to {averages_file}")
    
    # 6. Print summary
    print(f"\n{'─'*60}")
    print("RUNNING AVERAGES SUMMARY")
    print(f"{'─'*60}")
    for pid, data in averages.items():
        print(f"\n{data['park_name']} ({data['location']})")
        print(f"  Scrapes: {data['scrape_count']} | First: {data['first_scrape'][:10]} | Last: {data['last_scrape'][:10]}")
        for level, stats in data["averages"].items():
            print(f"  {level:15s}  Current: ${stats['current']:>7.2f}  Avg: ${stats['running_avg']:>7.2f}  Range: ${stats['min']:.0f}–${stats['max']:.0f}  ({stats['data_points']} pts)")


if __name__ == "__main__":
    main()

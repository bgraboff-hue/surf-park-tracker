# Surf Park Pricing Comp Tracker
### Wavegarden Myrtle Beach — Automated Price Scraping via GitHub

This tool automatically scrapes public session pricing from 8 comparable surf parks every day and stores a running history so you can track market pricing trends over time.

**Everything runs on GitHub's servers — you never need to open a command prompt or install anything on your computer.**

---

## Parks Being Tracked

| Park | Location | Technology | Booking Page Scraped |
|------|----------|-----------|---------------------|
| Atlantic Park Surf | Virginia Beach, VA | Wavegarden Cove | booking.atlanticparksurf.com |
| Lost Shore Surf Resort | Edinburgh, UK | Wavegarden Cove | booking.lostshore.com |
| Waco Surf | Waco, TX | PerfectSwell (AWM) | wacosurf.com |
| Palm Springs Surf Club | Palm Springs, CA | Surf Loch | palmspringssurfclub.com |
| Revel Surf | Mesa, AZ | SwellMFG + UNIT | revelsurf.com |
| The Wave Bristol | Bristol, UK | Wavegarden Cove | thewave.com |
| SkudinSurf American Dream | NJ | PerfectSwell (AWM) | skudinsurf.com |
| O₂ SURFTOWN MUC | Munich, Germany | Endless Surf | o2surftown.com |

---

## How To Set This Up (All in Your Browser)

### Step 1: Create a GitHub account (if you don't have one)

1. Go to **github.com**
2. Click **Sign Up** and create a free account

### Step 2: Create a new repository

1. Once logged in, click the **+** button in the top right corner
2. Click **New repository**
3. Name it: `surf-park-tracker`
4. Set it to **Private** (so only you can see it)
5. Check the box for **"Add a README file"**
6. Click **Create repository**

### Step 3: Upload the files

1. In your new repository, click the **"Add file"** button → **"Upload files"**
2. Drag and drop these files from your computer:
   - `scraper.py`
   - `price_history.json`
3. Click **"Commit changes"** at the bottom

### Step 4: Create the workflow folder and file

This is the file that tells GitHub to run the scraper automatically. The folder structure needs to be exact:

1. In your repository, click **"Add file"** → **"Create new file"**
2. In the filename box at the top, type exactly: `.github/workflows/scrape.yml`
   - (When you type the `/` it will automatically create the folders)
3. Copy the ENTIRE contents of the `scrape.yml` file I provided and paste it in
4. Click **"Commit changes"** at the bottom

### Step 5: Enable GitHub Actions

1. Go to the **"Actions"** tab at the top of your repository
2. If you see a message about enabling workflows, click **"I understand my workflows, go ahead and enable them"**
3. You should see your workflow listed: **"Scrape Surf Park Prices"**

### Step 6: Run it for the first time

1. In the **Actions** tab, click on **"Scrape Surf Park Prices"** on the left
2. Click the **"Run workflow"** dropdown button on the right
3. Click the green **"Run workflow"** button
4. Wait 1-2 minutes, then refresh the page
5. You should see a green checkmark ✓ — that means it worked!

### Step 7: Check your data

1. Go back to the main page of your repository (click the repo name at top)
2. Click on `price_history.json`
3. You should see scraped price data in there!

---

## What Happens Automatically From Now On

- **Every day at 6:00 AM UTC (1:00 AM Eastern)**, GitHub runs the scraper
- It visits all 8 parks' booking pages and pulls the latest prices
- It saves the new data to `price_history.json` and `price_averages.json`
- The files update automatically in your repo — you don't need to do anything

---

## How To Check Your Data

**Option A: On GitHub**
- Just click on `price_history.json` or `price_averages.json` in your repo to see the latest data

**Option B: Download it**
- Click on the file, then click the download button to get it on your computer
- Open it in any text editor, or paste it into Claude and ask for analysis

**Option C: View scrape logs**
- Go to the **Actions** tab to see every time the scraper has run
- Click on any run to see the detailed output (which parks succeeded, what prices were found)

---

## How Data Builds Over Time

| Timeframe | Data Points | What You Can See |
|-----------|-------------|-----------------|
| Day 1 | ~8 prices | Current snapshot across all parks |
| Week 1 | ~56 prices | Whether prices are stable or moving |
| Month 1 | ~240 prices | Monthly average forming |
| Month 3 | ~720 prices | Seasonal direction visible |
| Month 6 | ~1,440 prices | Clear seasonal pattern |
| Year 1 | ~2,900 prices | Full annual cycle — the gold standard |

---

## Troubleshooting

**The Action shows a red X (failed):**
- Click on the failed run to see the error log
- Most likely a park changed their website — the other parks will still work fine
- You can share the error log with Claude to get help fixing it

**"No prices extracted" for a park:**
- That park may have changed their page layout
- The scraper will keep working for the other parks

**Want to run it more than once a day?**
- Go to Actions tab → click "Run workflow" anytime you want a manual scrape

**Want to change the schedule?**
- Edit the `.github/workflows/scrape.yml` file
- Change the cron line. Examples:
  - `'0 6 * * *'` = every day at 6am UTC
  - `'0 6 * * 1'` = every Monday at 6am UTC
  - `'0 */12 * * *'` = every 12 hours

---

## Files In This Repo

| File | What It Does |
|------|-------------|
| `scraper.py` | The scraping script — visits booking pages and extracts prices |
| `price_history.json` | Every price ever scraped (grows over time — this is your database) |
| `price_averages.json` | Running averages computed from the history (created after first scrape) |
| `.github/workflows/scrape.yml` | Tells GitHub when and how to run the scraper |
| `README.md` | This file |

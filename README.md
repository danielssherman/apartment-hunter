# 🏠 SF Apartment Hunter

A TOS-compliant bot that aggregates 3BR apartment listings from **RentCast**, **Zillow**, and **Redfin**, scores them for quality and desirability, and generates a daily dashboard with direct links to each listing.

## How It Works

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│ RentCast │  │  Zillow   │  │  Redfin  │
│   API    │  │ (RapidAPI)│  │(RapidAPI)│
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │              │
     └─────────────┼──────────────┘
                   ▼
          ┌────────────────┐
          │  Normalize &   │
          │  Deduplicate   │
          └───────┬────────┘
                  ▼
          ┌────────────────┐
          │ Quality Scorer │  ← weighted: price, size, amenities,
          │   (0–100)      │    location, recency, laundry, etc.
          └───────┬────────┘
                  ▼
          ┌────────────────┐
          │   Dashboard    │  ← self-contained HTML with filters
          │   Generator    │    and search
          └────────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Try the demo (no API keys needed)

```bash
python main.py --demo --open
```

This generates a dashboard with realistic sample data so you can see the UI.

### 3. Set up API keys for real data

You need **at least one** of these:

| Source | API | Free Tier | Sign Up |
|--------|-----|-----------|---------|
| RentCast | Direct API | 50 req/month | [rentcast.io/api](https://www.rentcast.io/api) |
| Zillow | RapidAPI | Varies by plan | [rapidapi.com/apimaker/api/zillow-com1](https://rapidapi.com/apimaker/api/zillow-com1) |
| Redfin | RapidAPI | Varies by plan | [rapidapi.com/apimaker/api/redfin-com](https://rapidapi.com/apimaker/api/redfin-com) |

```bash
export RENTCAST_API_KEY="your-rentcast-key"
export RAPIDAPI_KEY="your-rapidapi-key"     # Used for both Zillow and Redfin
```

### 4. Run with real data

```bash
python main.py --open
```

### 5. Set up daily morning runs

```bash
bash setup_cron.sh
```

This installs a cron job that runs at **7:00 AM daily** and regenerates the dashboard.

## Customization

Edit `config.py` to adjust:

**Search criteria:**
- `city` / `state` — target location
- `bedrooms` — number of bedrooms
- `min_price` / `max_price` — rent range

**Scoring weights** (what matters most to you):
- `price_value` — cheaper relative to area average
- `size_sqft` — larger apartments
- `amenities` — more amenities
- `location_walkscore` — proximity to desirable neighborhoods
- `recency` — newly listed
- `pet_friendly`, `parking`, `laundry` — specific features

**Example: prioritize new, cheap, spacious apartments:**
```python
@dataclass
class ScoringWeights:
    price_value: float = 0.30       # ↑ heavily weight price
    size_sqft: float = 0.25         # ↑ heavily weight size
    recency: float = 0.25           # ↑ heavily weight newness
    amenities: float = 0.05
    location_walkscore: float = 0.05
    photos_count: float = 0.02
    pet_friendly: float = 0.02
    parking: float = 0.03
    laundry: float = 0.03
```

## Dashboard Features

- **Filter by source** — RentCast, Zillow, Redfin
- **Filter by quality** — New listings, Top Rated, Best Value
- **Search** — by address or neighborhood
- **Score badge** — green (70+), orange (50-69), red (<50)
- **Tags** — 🆕 New, Great Value, Spacious, In-Unit Laundry, Parking
- **Direct links** — click through to original listing on each platform

## TOS Compliance

This tool uses **only official APIs and authorized data partners**:

- **RentCast**: Licensed rental data API with direct partnership agreements
- **Zillow**: Accessed via the authorized RapidAPI marketplace endpoint
- **Redfin**: Accessed via the authorized RapidAPI marketplace endpoint

No web scraping, no HTML parsing, no automated browser sessions. All data access follows each platform's Terms of Service.

## Project Structure

```
apartment-hunter/
├── main.py                 # Entry point & orchestrator
├── config.py               # All configuration in one place
├── fetchers.py             # API fetchers for each source
├── scorer.py               # Quality scoring algorithm
├── dashboard_generator.py  # HTML dashboard builder
├── setup_cron.sh           # Cron job installer
├── requirements.txt        # Python dependencies
└── output/
    ├── dashboard.html      # ← Open this in your browser
    └── listings.json       # Raw data export
```

## Tips

- Run `--demo` first to verify everything works before adding API keys
- The dashboard is a single HTML file — bookmark it or set it as a browser homepage
- JSON output at `output/listings.json` can be used for your own analysis
- Add your shell API key exports to `~/.bashrc` or `~/.zshrc` so cron picks them up

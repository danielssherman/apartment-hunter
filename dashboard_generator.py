"""
Generates a self-contained HTML dashboard from scored listings.
The dashboard is a single file with all CSS/JS inline.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import requests

from config import AppConfig
from fetchers import Listing

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _build_zillow_url(address: str, city: str, state: str, zip_code: str) -> str:
    addr = f"{address}, {city}, {state} {zip_code}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", addr).strip("-")
    return f"https://www.zillow.com/homes/for_rent/{slug}_rb/"


def _build_google_rental_url(address: str, city: str, state: str) -> str:
    q = f'"{address}" "{city}" {state} for rent'
    return f"https://www.google.com/search?q={quote(q)}"


def _check_page_rental_status(url: str) -> Optional[bool]:
    """GET a URL and check page content for rental vs sale signals.

    Returns True (rental), False (sale), or None (could not determine).
    """
    try:
        resp = requests.get(
            url, headers=_BROWSER_HEADERS, timeout=5, allow_redirects=True
        )
        if resp.status_code != 200:
            return None
        text = resp.text[:120_000].lower()
        rental = text.count("for rent") + text.count('"forrent"') + text.count('"for_rent"')
        sale = text.count("for sale") + text.count('"forsale"') + text.count('"for_sale"')
        if rental > sale:
            return True
        if sale > rental:
            return False
        return None
    except Exception:
        return None


def _can_reach_site(url: str) -> bool:
    """Quick check: does a HEAD request to this URL get a non-blocked response?"""
    try:
        resp = requests.head(
            url, headers=_BROWSER_HEADERS, timeout=4, allow_redirects=True
        )
        return resp.status_code == 200
    except Exception:
        return False


def _enrich_listing_urls(listings_json: list[dict]) -> None:
    """Add search_url, url_verified, and search_label to each listing.

    Strategy:
    1. Try Zillow (canary test first — skip all if blocked).
    2. For each listing, attempt GET-based rental verification on Zillow.
    3. If Zillow is blocked, fall back to Google rental search URL.
    """
    # Separate already-verified listings
    need_url = [l for l in listings_json if not l.get("url")]
    for l in listings_json:
        if l.get("url"):
            l["search_url"] = l["url"]
            l["url_verified"] = True
            src = l["source"]
            l["search_label"] = "via " + src[0].upper() + src[1:]

    if not need_url:
        return

    # Canary: test one Zillow URL to see if we're blocked
    sample = need_url[0]
    canary_url = _build_zillow_url(
        sample["address"], sample["city"], sample["state"], sample["zip"],
    )
    zillow_reachable = _can_reach_site(canary_url)

    if zillow_reachable:
        logger.info("Zillow reachable — verifying %d listing URLs...", len(need_url))

        def verify_via_zillow(listing: dict) -> None:
            url = _build_zillow_url(
                listing["address"], listing["city"],
                listing["state"], listing["zip"],
            )
            result = _check_page_rental_status(url)
            if result is True:
                listing["search_url"] = url
                listing["url_verified"] = True
                listing["search_label"] = "Zillow (verified rental)"
            elif result is False:
                listing["search_url"] = _build_google_rental_url(
                    listing["address"], listing["city"], listing["state"],
                )
                listing["url_verified"] = False
                listing["search_label"] = "Search Rentals"
            else:
                listing["search_url"] = url
                listing["url_verified"] = None
                listing["search_label"] = "Search Zillow"

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(verify_via_zillow, need_url))
    else:
        logger.info(
            "Zillow blocked (anti-bot) — using Google rental search as fallback"
        )
        for listing in need_url:
            listing["search_url"] = _build_google_rental_url(
                listing["address"], listing["city"], listing["state"],
            )
            listing["url_verified"] = None
            listing["search_label"] = "Search Rentals"

    verified = sum(1 for l in listings_json if l.get("url_verified") is True)
    sale = sum(1 for l in listings_json if l.get("url_verified") is False)
    unknown = sum(1 for l in listings_json if l.get("url_verified") is None)
    logger.info(
        "URL results: %d verified, %d sale-redirect, %d search-fallback",
        verified, sale, unknown,
    )


def generate_dashboard(
    scored_listings: list[tuple[Listing, float, list[str]]],
    config: AppConfig,
) -> str:
    """Generate HTML dashboard and write to output directory."""

    os.makedirs(config.output_dir, exist_ok=True)

    # Serialize listings to JSON for the dashboard
    listings_json = []
    for listing, score, tags in scored_listings[: config.max_dashboard_listings]:
        listings_json.append({
            "id": listing.id,
            "source": listing.source,
            "title": listing.title,
            "address": listing.address,
            "city": listing.city,
            "state": listing.state,
            "zip": listing.zip_code,
            "price": listing.price,
            "bedrooms": listing.bedrooms,
            "bathrooms": listing.bathrooms,
            "sqft": listing.sqft,
            "url": listing.url,
            "image": listing.image_url,
            "lat": listing.latitude,
            "lng": listing.longitude,
            "listed_date": listing.listed_date,
            "days_on_market": listing.days_on_market,
            "property_type": listing.property_type,
            "pet_friendly": listing.pet_friendly,
            "parking": listing.parking,
            "laundry": listing.laundry,
            "photos_count": listing.photos_count,
            "score": score,
            "tags": tags,
            "amenities": listing.amenities[:10],  # cap for display
        })

    # Verify and enrich listing URLs
    _enrich_listing_urls(listings_json)

    # Also save raw JSON
    json_path = os.path.join(config.output_dir, config.data_filename)
    with open(json_path, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "criteria": {
                "city": config.search.city,
                "state": config.search.state,
                "bedrooms": config.search.bedrooms,
                "max_price": config.search.max_price,
            },
            "total_listings": len(scored_listings),
            "listings": listings_json,
        }, f, indent=2)

    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    data_blob = json.dumps(listings_json)

    html = _build_html(data_blob, now, config)

    html_path = os.path.join(config.output_dir, config.dashboard_filename)
    with open(html_path, "w") as f:
        f.write(html)

    return html_path


def _build_html(data_json: str, generated_at: str, config: AppConfig) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SF Apartment Hunter — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,500;0,9..40,700;1,9..40,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {{
    --bg:        #0c0c0f;
    --surface:   #16161a;
    --surface2:  #1e1e24;
    --border:    #2a2a32;
    --text:      #e8e6e3;
    --text2:     #9a9a9f;
    --accent:    #ff6b35;
    --accent2:   #ffa726;
    --green:     #4caf50;
    --blue:      #42a5f5;
    --purple:    #ab47bc;
    --red:       #ef5350;
    --tag-new:   #1b5e20;
    --tag-value: #0d47a1;
    --tag-space: #4a148c;
    --radius:    12px;
  }}

  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{
    font-family: 'DM Sans', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.5;
  }}

  /* ── Header ─────────────────────────────── */
  .header {{
    padding: 2.5rem 2rem 2rem;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #12121a 0%, var(--bg) 100%);
  }}
  .header-inner {{
    max-width: 1400px;
    margin: 0 auto;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 1rem;
  }}
  .header h1 {{
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }}
  .header h1 span.icon {{ font-size: 1.5rem; }}
  .header .meta {{
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: var(--text2);
    text-align: right;
  }}

  /* ── Controls ───────────────────────────── */
  .controls {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 1.25rem 2rem;
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
    align-items: center;
  }}
  .controls button {{
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    padding: 0.45rem 1rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text2);
    cursor: pointer;
    transition: all 0.2s;
  }}
  .controls button:hover {{ border-color: var(--accent); color: var(--text); }}
  .controls button.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }}
  .controls .search-box {{
    flex: 1;
    min-width: 200px;
    max-width: 320px;
    margin-left: auto;
  }}
  .controls input {{
    width: 100%;
    font-family: 'DM Sans', sans-serif;
    font-size: 0.85rem;
    padding: 0.5rem 1rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text);
    outline: none;
    transition: border-color 0.2s;
  }}
  .controls input:focus {{ border-color: var(--accent); }}
  .controls input::placeholder {{ color: var(--text2); }}

  /* ── Stats Bar ──────────────────────────── */
  .stats {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 0 2rem 1rem;
    display: flex;
    gap: 1.5rem;
    flex-wrap: wrap;
  }}
  .stat {{
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    color: var(--text2);
  }}
  .stat strong {{ color: var(--text); font-size: 1.1rem; display: block; }}

  /* ── Grid ────────────────────────────────── */
  .grid {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 0 2rem 3rem;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 1rem;
  }}

  /* ── Card ────────────────────────────────── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    transition: transform 0.2s, border-color 0.25s;
    display: flex;
    flex-direction: column;
  }}
  .card:hover {{
    transform: translateY(-3px);
    border-color: var(--accent);
  }}

  .card-img {{
    width: 100%;
    height: 180px;
    object-fit: cover;
    background: var(--surface2);
  }}
  .card-img-placeholder {{
    width: 100%;
    height: 180px;
    background: var(--surface2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2.5rem;
    color: var(--text2);
    opacity: 0.3;
  }}

  .card-body {{
    padding: 1.1rem 1.25rem;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }}

  .card-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 0.5rem;
  }}
  .card-title {{
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.3;
  }}
  .card-score {{
    flex-shrink: 0;
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
    font-weight: 700;
    padding: 0.2rem 0.55rem;
    border-radius: 8px;
    background: var(--surface2);
  }}
  .card-score.high {{ background: #1b5e20; color: #a5d6a7; }}
  .card-score.mid  {{ background: #e65100; color: #ffcc80; }}
  .card-score.low  {{ background: #b71c1c; color: #ef9a9a; }}

  .card-address {{
    font-size: 0.8rem;
    color: var(--text2);
    line-height: 1.3;
  }}

  .card-details {{
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: var(--text2);
  }}
  .card-details .price {{
    color: var(--accent2);
    font-weight: 700;
    font-size: 1.1rem;
  }}

  .card-tags {{
    display: flex;
    gap: 0.35rem;
    flex-wrap: wrap;
  }}
  .tag {{
    font-size: 0.68rem;
    font-family: 'DM Mono', monospace;
    padding: 0.2rem 0.5rem;
    border-radius: 6px;
    background: var(--surface2);
    color: var(--text2);
    white-space: nowrap;
  }}
  .tag.new   {{ background: var(--tag-new);   color: #a5d6a7; }}
  .tag.value {{ background: var(--tag-value); color: #90caf9; }}
  .tag.space {{ background: var(--tag-space); color: #ce93d8; }}

  .card-source {{
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  .card-source.rentcast {{ color: var(--green); }}
  .card-source.zillow   {{ color: var(--blue); }}
  .card-source.redfin   {{ color: var(--red); }}

  .card-link-wrapper {{
    text-decoration: none;
    color: inherit;
    display: block;
  }}

  .card-neighborhood {{
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: var(--accent);
    letter-spacing: 0.03em;
  }}

  .card-map {{
    width: 100%;
    height: 180px;
    background: var(--surface2);
  }}
  .card-map .leaflet-container {{
    background: var(--surface2);
  }}

  .card-via {{
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: var(--text2);
  }}
  .card-via.verified {{ color: var(--green); }}
  .card-via.sale-warning {{ color: var(--accent2); }}

  /* ── Action Buttons ─────────────────────── */
  .card-actions {{
    display: flex;
    gap: 0.3rem;
  }}
  .card-action-btn {{
    background: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text2);
    cursor: pointer;
    font-size: 0.82rem;
    padding: 0.15rem 0.45rem;
    line-height: 1;
    transition: all 0.15s;
  }}
  .card-action-btn:hover {{ border-color: var(--text2); color: var(--text); }}
  .card-action-btn.active-liked {{ background: var(--green); border-color: var(--green); color: #fff; }}
  .card-action-btn.active-disliked {{ background: var(--red); border-color: var(--red); color: #fff; }}
  .card-action-btn.active-inactive {{ background: var(--accent2); border-color: var(--accent2); color: #000; }}

  /* ── Card States ────────────────────────── */
  .card.state-liked {{ border-left: 3px solid var(--green); }}
  .card.state-disliked {{ opacity: 0.5; }}
  .card.state-inactive {{ opacity: 0.5; }}
  .card.state-inactive .card-title {{ text-decoration: line-through; }}

  .neighborhood-select {{
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    padding: 0.45rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text2);
    cursor: pointer;
    outline: none;
    transition: border-color 0.2s;
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%239a9a9f' d='M3 5l3 3 3-3'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 0.6rem center;
    padding-right: 1.8rem;
  }}
  .neighborhood-select:focus {{ border-color: var(--accent); }}
  .neighborhood-select:hover {{ border-color: var(--accent); color: var(--text); }}

  .empty-state {{
    grid-column: 1 / -1;
    text-align: center;
    padding: 4rem 2rem;
    color: var(--text2);
  }}
  .empty-state h2 {{ font-size: 1.5rem; color: var(--text); margin-bottom: 0.5rem; }}

  @media (max-width: 768px) {{
    .header {{ padding: 1.5rem 1rem; }}
    .controls, .stats, .grid {{ padding-left: 1rem; padding-right: 1rem; }}
    .grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <h1><span class="icon">🏠</span> SF Apartment Hunter</h1>
    <div class="meta">
      <div>{config.search.bedrooms}BR · {config.search.city} · ≤${config.search.max_price or '∞'}/mo</div>
      <div>Updated {generated_at}</div>
    </div>
  </div>
</div>

<div class="controls" id="controls">
  <button class="active" data-filter="all">All</button>
  <button data-filter="new">🆕 New Listings</button>
  <button data-filter="top">⭐ Top Rated</button>
  <button data-filter="value">💰 Best Value</button>
  <button data-filter="liked">♥ Liked</button>
  <button data-filter="rentcast">RentCast</button>
  <button data-filter="zillow">Zillow</button>
  <button data-filter="redfin">Redfin</button>
  <select id="neighborhoodFilter" class="neighborhood-select">
    <option value="">All Neighborhoods</option>
  </select>
  <div class="search-box">
    <input type="text" id="searchInput" placeholder="Search address or neighborhood...">
  </div>
</div>

<div class="stats" id="stats"></div>
<div class="grid" id="grid"></div>

<script>
const DATA = {data_json};

// ── Neighborhoods ─────────────────────────
const NEIGHBORHOODS = [
  ["Hayes Valley",37.7752,-122.4372],["Mission District",37.7599,-122.4148],
  ["Castro",37.7609,-122.4350],["Noe Valley",37.7502,-122.4337],
  ["SoMa",37.7785,-122.3950],["Pacific Heights",37.7925,-122.4382],
  ["Marina",37.8015,-122.4368],["Russian Hill",37.7982,-122.4183],
  ["Nob Hill",37.7930,-122.4161],["North Beach",37.8061,-122.4103],
  ["Financial District",37.7946,-122.3999],["Tenderloin",37.7847,-122.4141],
  ["Chinatown",37.7941,-122.4078],["Lower Haight",37.7717,-122.4310],
  ["Inner Sunset",37.7602,-122.4634],["Outer Sunset",37.7555,-122.4950],
  ["Inner Richmond",37.7797,-122.4630],["Outer Richmond",37.7766,-122.4950],
  ["Cole Valley",37.7657,-122.4500],["Haight-Ashbury",37.7692,-122.4481],
  ["Western Addition",37.7808,-122.4310],["Japantown",37.7853,-122.4298],
  ["Polk Gulch",37.7895,-122.4197],["Potrero Hill",37.7601,-122.3926],
  ["Dogpatch",37.7574,-122.3871],["Bernal Heights",37.7442,-122.4158],
  ["Glen Park",37.7341,-122.4333],["Mission Bay",37.7706,-122.3932],
  ["Bayview",37.7296,-122.3884],["Excelsior",37.7251,-122.4300],
  ["Visitacion Valley",37.7135,-122.4108],["Twin Peaks",37.7544,-122.4477],
  ["Diamond Heights",37.7436,-122.4414],["Duboce Triangle",37.7694,-122.4300],
  ["Laurel Heights",37.7863,-122.4515],["Presidio Heights",37.7886,-122.4500],
  ["Cow Hollow",37.7985,-122.4380],["Telegraph Hill",37.8025,-122.4060],
];

// Assign neighborhood to each listing
DATA.forEach(l => {{
  if (l.lat && l.lng) {{
    let minDist = Infinity, nearest = '';
    NEIGHBORHOODS.forEach(([name, lat, lng]) => {{
      const d = (l.lat - lat) ** 2 + (l.lng - lng) ** 2;
      if (d < minDist) {{ minDist = d; nearest = name; }}
    }});
    l.neighborhood = nearest;
  }} else {{
    l.neighborhood = '';
  }}
}});

// Populate neighborhood dropdown
const nhDropdown = document.getElementById('neighborhoodFilter');
const nhSet = [...new Set(DATA.map(l => l.neighborhood).filter(Boolean))].sort();
nhSet.forEach(n => {{
  const opt = document.createElement('option');
  opt.value = n;
  opt.textContent = n;
  nhDropdown.appendChild(opt);
}});

// ── State ──────────────────────────────────
let activeFilter = 'all';
let searchQuery = '';
let selectedNeighborhood = '';

// ── Listing Actions (localStorage) ────────
const ACTIONS_KEY = 'apt-hunter-actions';
function loadActions() {{ return JSON.parse(localStorage.getItem(ACTIONS_KEY) || '{{}}'); }}
function saveActions(a) {{ localStorage.setItem(ACTIONS_KEY, JSON.stringify(a)); }}
function listingKey(l) {{ return l.address + ', ' + l.city + ', ' + l.state + ', ' + l.zip; }}
let listingActions = loadActions();

// ── Map Management ────────────────────────
let mapInstances = {{}};
let mapObserver = null;

function renderMaps() {{
  if (mapObserver) mapObserver.disconnect();
  Object.values(mapInstances).forEach(m => m.remove());
  mapInstances = {{}};

  const mapDivs = document.querySelectorAll('.card-map[data-lat]');
  if (!mapDivs.length) return;

  mapObserver = new IntersectionObserver((entries) => {{
    entries.forEach(entry => {{
      if (!entry.isIntersecting) return;
      const div = entry.target;
      const id = div.id;
      if (mapInstances[id]) return;

      const lat = parseFloat(div.dataset.lat);
      const lng = parseFloat(div.dataset.lng);

      const map = L.map(id, {{
        zoomControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        keyboard: false,
        touchZoom: false,
        attributionControl: false,
      }}).setView([lat, lng], 15);

      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        maxZoom: 19,
      }}).addTo(map);

      L.circleMarker([lat, lng], {{
        radius: 8,
        fillColor: '#ff6b35',
        color: '#fff',
        weight: 2,
        fillOpacity: 0.9,
      }}).addTo(map);

      mapInstances[id] = map;
      mapObserver.unobserve(div);
    }});
  }}, {{ rootMargin: '200px' }});

  mapDivs.forEach(div => mapObserver.observe(div));
}}

// ── Render ─────────────────────────────────
function render() {{
  const filtered = DATA.filter(l => {{
    if (searchQuery) {{
      const q = searchQuery.toLowerCase();
      const matchesText = l.address.toLowerCase().includes(q) ||
          l.title.toLowerCase().includes(q) ||
          l.neighborhood.toLowerCase().includes(q);
      const matchesAction = q === 'liked' && listingActions[listingKey(l)] === 'liked';
      if (!matchesText && !matchesAction) return false;
    }}
    if (selectedNeighborhood && l.neighborhood !== selectedNeighborhood)
      return false;
    switch (activeFilter) {{
      case 'new':      return l.tags.some(t => t.includes('New'));
      case 'top':      return l.score >= 70;
      case 'value':    return l.tags.includes('Great Value');
      case 'liked':    return listingActions[listingKey(l)] === 'liked';
      case 'rentcast': return l.source === 'rentcast';
      case 'zillow':   return l.source === 'zillow';
      case 'redfin':   return l.source === 'redfin';
      default:         return true;
    }}
  }});

  // Sort: liked first, neutral middle, disliked/inactive last
  const actionOrder = (l) => {{
    const a = listingActions[listingKey(l)];
    if (a === 'liked') return 0;
    if (a === 'disliked' || a === 'inactive') return 2;
    return 1;
  }};
  filtered.sort((a, b) => actionOrder(a) - actionOrder(b));

  // Stats
  const stats = document.getElementById('stats');
  const prices = filtered.filter(l => l.price).map(l => l.price);
  const avgPrice = prices.length ? Math.round(prices.reduce((a,b) => a+b, 0) / prices.length) : 0;
  const newCount = filtered.filter(l => l.tags.some(t => t.includes('New'))).length;
  const likedCount = DATA.filter(l => listingActions[listingKey(l)] === 'liked').length;
  stats.innerHTML = `
    <div class="stat"><strong>${{filtered.length}}</strong>listings</div>
    <div class="stat"><strong>${{newCount}}</strong>new this week</div>
    <div class="stat"><strong>${{avgPrice ? '$' + avgPrice.toLocaleString() : '—'}}</strong>avg rent</div>
    <div class="stat"><strong>${{likedCount}}</strong>liked</div>
    <div class="stat"><strong>${{DATA.length}}</strong>total tracked</div>
  `;

  // Grid
  const grid = document.getElementById('grid');
  if (filtered.length === 0) {{
    grid.innerHTML = `<div class="empty-state">
      <h2>No listings match</h2>
      <p>Try adjusting your filters or search query.</p>
    </div>`;
    return;
  }}

  grid.innerHTML = filtered.map((l, i) => {{
    const scoreClass = l.score >= 70 ? 'high' : l.score >= 50 ? 'mid' : 'low';
    const priceStr = l.price ? '$' + l.price.toLocaleString() + '/mo' : 'Price TBD';
    const details = [
      l.bedrooms ? l.bedrooms + 'bd' : '',
      l.bathrooms ? l.bathrooms + 'ba' : '',
      l.sqft ? l.sqft.toLocaleString() + ' sqft' : '',
    ].filter(Boolean).join(' · ');

    // Link URL + label (pre-computed at build time)
    const linkUrl = l.search_url || '';
    const linkLabel = l.search_label || '';
    const viaCls = l.url_verified === true ? 'verified'
                 : l.url_verified === false ? 'sale-warning' : '';

    // Map or image
    const mapId = 'map-' + i;
    const mediaHtml = (l.lat && l.lng)
      ? `<div class="card-map" id="${{mapId}}" data-lat="${{l.lat}}" data-lng="${{l.lng}}"></div>`
      : (l.image
        ? `<img class="card-img" src="${{l.image}}" alt="${{l.title}}" loading="lazy" onerror="this.outerHTML='<div class=card-img-placeholder>🏢</div>'">`
        : `<div class="card-img-placeholder">🏢</div>`);

    const tagsHtml = l.tags.map(t => {{
      let cls = '';
      if (t.includes('New')) cls = 'new';
      else if (t.includes('Value')) cls = 'value';
      else if (t.includes('Spacious')) cls = 'space';
      return `<span class="tag ${{cls}}">${{t}}</span>`;
    }}).join('');

    const domStr = l.days_on_market !== null ? l.days_on_market + 'd ago' : '';

    // Action state
    const key = listingKey(l);
    const action = listingActions[key] || '';
    const stateClass = action ? 'state-' + action : '';
    const escKey = key.replace(/'/g, '&#39;');

    return `
      <a class="card-link-wrapper" href="${{linkUrl}}" target="_blank" rel="noopener">
      <div class="card ${{stateClass}}">
        ${{mediaHtml}}
        <div class="card-body">
          <div class="card-top">
            <div class="card-title">${{l.title}}</div>
            <div class="card-score ${{scoreClass}}">${{l.score}}</div>
          </div>
          <div class="card-address">${{l.address}}</div>
          ${{l.neighborhood ? `<div class="card-neighborhood">${{l.neighborhood}}</div>` : ''}}
          <div class="card-details">
            <span class="price">${{priceStr}}</span>
            <span>${{details}}</span>
            ${{domStr ? `<span>${{domStr}}</span>` : ''}}
          </div>
          ${{tagsHtml ? `<div class="card-tags">${{tagsHtml}}</div>` : ''}}
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:0.4rem;">
            <span class="card-source ${{l.source}}">${{l.source}}</span>
            <div class="card-actions">
              <button class="card-action-btn ${{action === 'liked' ? 'active-liked' : ''}}" data-address="${{escKey}}" data-action="liked" title="Like">&#9829;</button>
              <button class="card-action-btn ${{action === 'disliked' ? 'active-disliked' : ''}}" data-address="${{escKey}}" data-action="disliked" title="Dislike">&#10007;</button>
              <button class="card-action-btn ${{action === 'inactive' ? 'active-inactive' : ''}}" data-address="${{escKey}}" data-action="inactive" title="Not for rent">&#8856;</button>
            </div>
            <span class="card-via ${{viaCls}}">${{linkLabel}}</span>
          </div>
        </div>
      </div>
      </a>
    `;
  }}).join('');

  renderMaps();
}}

// ── Events ─────────────────────────────────
document.getElementById('controls').addEventListener('click', e => {{
  if (e.target.tagName !== 'BUTTON') return;
  document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
  activeFilter = e.target.dataset.filter;
  render();
}});

document.getElementById('searchInput').addEventListener('input', e => {{
  searchQuery = e.target.value;
  render();
}});

document.getElementById('neighborhoodFilter').addEventListener('change', e => {{
  selectedNeighborhood = e.target.value;
  render();
}});

// ── Action Button Delegation ──────────
document.getElementById('grid').addEventListener('click', e => {{
  const btn = e.target.closest('.card-action-btn');
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  const addr = btn.dataset.address.replace(/&#39;/g, "'");
  const action = btn.dataset.action;
  if (listingActions[addr] === action) {{
    delete listingActions[addr];
  }} else {{
    listingActions[addr] = action;
  }}
  saveActions(listingActions);
  render();
}});

// ── Init ───────────────────────────────────
render();
</script>
</body>
</html>"""

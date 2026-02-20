"""
Generates a self-contained HTML dashboard from scored listings.
The dashboard is a single file with all CSS/JS inline.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from config import AppConfig
from fetchers import Listing


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

  .card-link {{
    display: inline-block;
    margin-top: auto;
    padding-top: 0.5rem;
  }}
  .card-link a {{
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: var(--accent);
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.2s;
  }}
  .card-link a:hover {{ border-bottom-color: var(--accent); }}

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
  <button data-filter="rentcast">RentCast</button>
  <button data-filter="zillow">Zillow</button>
  <button data-filter="redfin">Redfin</button>
  <div class="search-box">
    <input type="text" id="searchInput" placeholder="Search address or neighborhood...">
  </div>
</div>

<div class="stats" id="stats"></div>
<div class="grid" id="grid"></div>

<script>
const DATA = {data_json};

// ── State ──────────────────────────────────
let activeFilter = 'all';
let searchQuery = '';

// ── Render ─────────────────────────────────
function render() {{
  const filtered = DATA.filter(l => {{
    if (searchQuery) {{
      const q = searchQuery.toLowerCase();
      if (!l.address.toLowerCase().includes(q) && !l.title.toLowerCase().includes(q))
        return false;
    }}
    switch (activeFilter) {{
      case 'new':      return l.tags.some(t => t.includes('New'));
      case 'top':      return l.score >= 70;
      case 'value':    return l.tags.includes('Great Value');
      case 'rentcast': return l.source === 'rentcast';
      case 'zillow':   return l.source === 'zillow';
      case 'redfin':   return l.source === 'redfin';
      default:         return true;
    }}
  }});

  // Stats
  const stats = document.getElementById('stats');
  const prices = filtered.filter(l => l.price).map(l => l.price);
  const avgPrice = prices.length ? Math.round(prices.reduce((a,b) => a+b, 0) / prices.length) : 0;
  const newCount = filtered.filter(l => l.tags.some(t => t.includes('New'))).length;
  stats.innerHTML = `
    <div class="stat"><strong>${{filtered.length}}</strong>listings</div>
    <div class="stat"><strong>${{newCount}}</strong>new this week</div>
    <div class="stat"><strong>${{avgPrice ? '$' + avgPrice.toLocaleString() : '—'}}</strong>avg rent</div>
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

  grid.innerHTML = filtered.map(l => {{
    const scoreClass = l.score >= 70 ? 'high' : l.score >= 50 ? 'mid' : 'low';
    const priceStr = l.price ? '$' + l.price.toLocaleString() + '/mo' : 'Price TBD';
    const details = [
      l.bedrooms ? l.bedrooms + 'bd' : '',
      l.bathrooms ? l.bathrooms + 'ba' : '',
      l.sqft ? l.sqft.toLocaleString() + ' sqft' : '',
    ].filter(Boolean).join(' · ');

    const imgHtml = l.image
      ? `<img class="card-img" src="${{l.image}}" alt="${{l.title}}" loading="lazy" onerror="this.outerHTML='<div class=card-img-placeholder>🏢</div>'">`
      : `<div class="card-img-placeholder">🏢</div>`;

    const tagsHtml = l.tags.map(t => {{
      let cls = '';
      if (t.includes('New')) cls = 'new';
      else if (t.includes('Value')) cls = 'value';
      else if (t.includes('Spacious')) cls = 'space';
      return `<span class="tag ${{cls}}">${{t}}</span>`;
    }}).join('');

    const domStr = l.days_on_market !== null ? l.days_on_market + 'd ago' : '';

    return `
      <div class="card">
        ${{imgHtml}}
        <div class="card-body">
          <div class="card-top">
            <div class="card-title">${{l.title}}</div>
            <div class="card-score ${{scoreClass}}">${{l.score}}</div>
          </div>
          <div class="card-address">${{l.address}}</div>
          <div class="card-details">
            <span class="price">${{priceStr}}</span>
            <span>${{details}}</span>
            ${{domStr ? `<span>${{domStr}}</span>` : ''}}
          </div>
          ${{tagsHtml ? `<div class="card-tags">${{tagsHtml}}</div>` : ''}}
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:0.4rem;">
            <span class="card-source ${{l.source}}">${{l.source}}</span>
            ${{l.url ? `<span class="card-link"><a href="${{l.url}}" target="_blank" rel="noopener">View Listing →</a></span>` : ''}}
          </div>
        </div>
      </div>
    `;
  }}).join('');
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

// ── Init ───────────────────────────────────
render();
</script>
</body>
</html>"""

#!/usr/bin/env python3
"""
SF Apartment Hunter — Main Entry Point

Fetches listings from multiple APIs, scores them, and generates
a dashboard. Run daily via cron for morning updates.

Usage:
    python main.py                  # Normal run
    python main.py --demo           # Generate with sample data (no API keys needed)
    python main.py --open           # Open dashboard in browser after generating

Environment Variables:
    RENTCAST_API_KEY    — RentCast API key
    RAPIDAPI_KEY        — RapidAPI key (for Zillow + Redfin)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from config import AppConfig
from fetchers import Listing, fetch_all
from scorer import score_listings
from dashboard_generator import generate_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def generate_demo_data() -> list[Listing]:
    """Generate realistic sample data for testing the dashboard without API keys."""
    import random

    neighborhoods = [
        ("Hayes Valley",     37.7752, -122.4372, 4200, 5800),
        ("Mission District", 37.7599, -122.4148, 3800, 5500),
        ("Nob Hill",         37.7920, -122.4130, 4500, 6500),
        ("Pacific Heights",  37.7925, -122.4382, 5000, 7500),
        ("SoMa",             37.7785, -122.3950, 3900, 5600),
        ("Inner Sunset",     37.7640, -122.4680, 3600, 5200),
        ("Noe Valley",       37.7510, -122.4330, 4300, 6200),
        ("Castro",           37.7609, -122.4350, 3700, 5400),
        ("Marina",           37.8020, -122.4370, 4800, 7000),
        ("Richmond",         37.7800, -122.4600, 3400, 4900),
        ("Potrero Hill",     37.7600, -122.4000, 3600, 5300),
        ("Dogpatch",         37.7580, -122.3870, 3800, 5500),
        ("North Beach",      37.8060, -122.4100, 4000, 5800),
        ("Russian Hill",     37.8000, -122.4200, 4500, 6800),
        ("Glen Park",        37.7340, -122.4340, 3500, 5000),
    ]

    sources = ["rentcast", "zillow", "redfin"]
    amenities_pool = [
        "Dishwasher", "Hardwood Floors", "Central AC", "Gym",
        "Rooftop Deck", "Concierge", "Bike Storage", "Pool",
        "EV Charging", "Package Room", "Dog Run", "Co-Working Space",
    ]

    listings = []
    for i, (name, lat, lng, low, high) in enumerate(neighborhoods):
        for j in range(random.randint(2, 4)):
            price = random.randint(low, high)
            source = random.choice(sources)
            sqft = random.randint(900, 1800)
            baths = random.choice([1, 1.5, 2, 2.5])
            days_ago = random.randint(0, 45)
            num_amenities = random.randint(2, 8)
            selected_amenities = random.sample(amenities_pool, min(num_amenities, len(amenities_pool)))
            pet = random.random() > 0.4
            park = random.random() > 0.5
            laundry = random.choice(["in-unit", "on-site", "none", ""])

            street_num = random.randint(100, 3999)
            streets = ["Valencia St", "Fillmore St", "Divisadero St", "Market St",
                       "Guerrero St", "Hyde St", "Polk St", "Irving St",
                       "24th St", "Haight St", "Church St", "Folsom St"]
            street = random.choice(streets)

            from datetime import timedelta
            listed = datetime.now(timezone.utc) - timedelta(days=days_ago)

            # Construct realistic URLs
            if source == "zillow":
                url = f"https://www.zillow.com/homedetails/{street_num}-{street.replace(' ', '-')}-San-Francisco-CA/1234{i}{j}_zpid/"
            elif source == "redfin":
                url = f"https://www.redfin.com/CA/San-Francisco/{street_num}-{street.replace(' ', '-')}-94{random.randint(100,134)}/home/1234{i}{j}"
            else:
                url = f"https://www.rentcast.io/apartments/san-francisco-ca/{street_num}-{street.lower().replace(' ', '-')}"

            listings.append(Listing(
                id=f"{source[:2]}_{i}_{j}",
                source=source,
                title=f"{street_num} {street}",
                address=f"{street_num} {street}, San Francisco, CA 94{random.randint(100,134)}",
                city="San Francisco",
                state="CA",
                zip_code=f"94{random.randint(100,134)}",
                price=price,
                bedrooms=3,
                bathrooms=baths,
                sqft=sqft,
                url=url,
                image_url="",
                latitude=lat + random.uniform(-0.008, 0.008),
                longitude=lng + random.uniform(-0.008, 0.008),
                listed_date=listed.isoformat(),
                property_type=random.choice(["apartment", "condo", "townhouse"]),
                amenities=selected_amenities,
                pet_friendly=pet,
                parking=park,
                laundry=laundry,
                photos_count=random.randint(3, 25),
            ))

    return listings


def main():
    parser = argparse.ArgumentParser(description="SF Apartment Hunter")
    parser.add_argument("--demo", action="store_true", help="Use sample data (no API keys needed)")
    parser.add_argument("--open", action="store_true", help="Open dashboard in browser after generating")
    args = parser.parse_args()

    config = AppConfig()
    os.makedirs(config.output_dir, exist_ok=True)

    if args.demo:
        logger.info("Running in DEMO mode with sample data...")
        listings = generate_demo_data()
    else:
        # Check for API keys
        has_keys = config.keys.rentcast or config.keys.rapidapi
        if not has_keys:
            logger.error(
                "No API keys configured!\n"
                "Set environment variables:\n"
                "  export RENTCAST_API_KEY='your-key'\n"
                "  export RAPIDAPI_KEY='your-key'\n"
                "\nOr run with --demo to test with sample data."
            )
            sys.exit(1)

        logger.info(f"Searching: {config.search.bedrooms}BR in {config.search.city}, {config.search.state}")
        logger.info(f"Price range: ${config.search.min_price or 0} - ${config.search.max_price or '∞'}")

        listings = fetch_all(config.keys, config.search)

        if not listings:
            logger.warning("No listings found from any source. Try --demo to test the dashboard.")
            sys.exit(0)

    # Score & rank
    logger.info(f"Scoring {len(listings)} listings...")
    scored = score_listings(listings, config.scoring, config.new_listing_days)

    top_score = scored[0][1] if scored else 0
    new_count = sum(1 for _, _, tags in scored if any("New" in t for t in tags))
    logger.info(f"Top score: {top_score} | New listings: {new_count}")

    # Generate dashboard
    html_path = generate_dashboard(scored, config)
    logger.info(f"Dashboard saved to: {html_path}")
    logger.info(f"JSON data saved to: {os.path.join(config.output_dir, config.data_filename)}")

    if args.open:
        webbrowser.open(f"file://{os.path.abspath(html_path)}")

    print(f"\n✅ Dashboard ready: {html_path}")
    return html_path


if __name__ == "__main__":
    main()

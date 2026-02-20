"""
Quality scoring algorithm for apartment listings.

Each listing gets a 0-100 score based on configurable weights.
Higher scores = more desirable.
"""

import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

from config import ScoringWeights
from fetchers import Listing

logger = logging.getLogger(__name__)


def score_listings(
    listings: list[Listing],
    weights: ScoringWeights,
    new_listing_days: int = 3,
) -> list[tuple[Listing, float, list[str]]]:
    """
    Score each listing on a 0-100 scale.

    Returns list of (listing, score, tags) sorted by score descending.
    Tags are human-readable labels like "New", "Great Value", "Spacious".
    """
    if not listings:
        return []

    # Compute reference statistics for relative scoring
    prices = [l.price for l in listings if l.price and l.price > 0]
    sqfts = [l.sqft for l in listings if l.sqft and l.sqft > 0]
    photo_counts = [l.photos_count for l in listings if l.photos_count > 0]

    avg_price = statistics.mean(prices) if prices else 4000
    avg_sqft = statistics.mean(sqfts) if sqfts else 1200
    max_photos = max(photo_counts) if photo_counts else 10

    results = []
    for listing in listings:
        score, tags = _score_one(listing, weights, avg_price, avg_sqft, max_photos, new_listing_days)
        results.append((listing, round(score, 1), tags))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _score_one(
    listing: Listing,
    w: ScoringWeights,
    avg_price: float,
    avg_sqft: float,
    max_photos: int,
    new_listing_days: int,
) -> tuple[float, list[str]]:
    """Score a single listing. Returns (score, tags)."""
    scores: dict[str, float] = {}
    tags: list[str] = []

    # ── Price Value (lower is better relative to average) ───────────────
    if listing.price and listing.price > 0:
        # Score 100 if price is 40%+ below average, 0 if 40%+ above
        ratio = listing.price / avg_price
        scores["price_value"] = max(0, min(100, (1.4 - ratio) / 0.8 * 100))
        if ratio < 0.85:
            tags.append("Great Value")
    else:
        scores["price_value"] = 50  # neutral if unknown

    # ── Square Footage (larger is better) ───────────────────────────────
    if listing.sqft and listing.sqft > 0:
        ratio = listing.sqft / avg_sqft
        scores["size_sqft"] = max(0, min(100, (ratio - 0.6) / 0.8 * 100))
        if ratio > 1.2:
            tags.append("Spacious")
    else:
        scores["size_sqft"] = 50

    # ── Amenities ───────────────────────────────────────────────────────
    amenity_count = len(listing.amenities)
    scores["amenities"] = min(100, amenity_count * 10)  # 10 amenities = 100
    if amenity_count >= 8:
        tags.append("Loaded with Amenities")

    # ── Location / Walk Score (placeholder - enhance with API) ──────────
    # For now, use a heuristic: SF downtown core gets higher scores
    scores["location_walkscore"] = _location_heuristic(listing)

    # ── Photos ──────────────────────────────────────────────────────────
    if max_photos > 0:
        scores["photos_count"] = min(100, (listing.photos_count / max_photos) * 100)
    else:
        scores["photos_count"] = 50

    # ── Recency ─────────────────────────────────────────────────────────
    dom = listing.days_on_market
    if dom is not None:
        if dom <= new_listing_days:
            scores["recency"] = 100
            tags.append("🆕 New")
        elif dom <= 7:
            scores["recency"] = 80
        elif dom <= 14:
            scores["recency"] = 60
        elif dom <= 30:
            scores["recency"] = 40
        else:
            scores["recency"] = 20
    else:
        scores["recency"] = 50

    # ── Pet Friendly ────────────────────────────────────────────────────
    scores["pet_friendly"] = 100 if listing.pet_friendly else 30

    # ── Parking ─────────────────────────────────────────────────────────
    scores["parking"] = 100 if listing.parking else 30
    if listing.parking:
        tags.append("Parking")

    # ── Laundry ─────────────────────────────────────────────────────────
    if listing.laundry == "in-unit":
        scores["laundry"] = 100
        tags.append("In-Unit Laundry")
    elif listing.laundry == "on-site":
        scores["laundry"] = 60
    else:
        scores["laundry"] = 30

    # ── Weighted Total ──────────────────────────────────────────────────
    weight_map = {
        "price_value": w.price_value,
        "size_sqft": w.size_sqft,
        "amenities": w.amenities,
        "location_walkscore": w.location_walkscore,
        "photos_count": w.photos_count,
        "recency": w.recency,
        "pet_friendly": w.pet_friendly,
        "parking": w.parking,
        "laundry": w.laundry,
    }

    total_weight = sum(weight_map.values())
    if total_weight == 0:
        return 50.0, tags

    weighted_sum = sum(scores.get(k, 50) * v for k, v in weight_map.items())
    final_score = weighted_sum / total_weight

    return final_score, tags


def _location_heuristic(listing: Listing) -> float:
    """
    Simple location scoring based on proximity to desirable SF neighborhoods.
    In production, replace with Walk Score API or Google Places data.
    """
    if not listing.latitude or not listing.longitude:
        return 50.0

    # Desirable SF neighborhood centers (lat, lng, name)
    hotspots = [
        (37.7749, -122.4194, "Downtown/FiDi"),
        (37.7599, -122.4148, "Mission"),
        (37.7694, -122.4862, "Inner Sunset"),
        (37.7849, -122.4094, "Nob Hill"),
        (37.7879, -122.4074, "North Beach"),
        (37.7751, -122.4193, "SoMa"),
        (37.7647, -122.4230, "Castro"),
        (37.7752, -122.4372, "Hayes Valley"),
        (37.7850, -122.4383, "Pacific Heights"),
        (37.7609, -122.4350, "Noe Valley"),
    ]

    # Find distance to nearest hotspot
    min_dist = float("inf")
    for lat, lng, _ in hotspots:
        dist = ((listing.latitude - lat) ** 2 + (listing.longitude - lng) ** 2) ** 0.5
        min_dist = min(min_dist, dist)

    # Convert distance to score (closer = higher)
    # ~0.01 degree ≈ 1km in SF
    if min_dist < 0.005:
        return 95
    elif min_dist < 0.01:
        return 85
    elif min_dist < 0.02:
        return 70
    elif min_dist < 0.04:
        return 55
    else:
        return 35

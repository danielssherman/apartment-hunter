"""
Configuration for the Apartment Hunter bot.
Fill in your API keys from the respective providers.

API Sources (all TOS-compliant):
  - RentCast API: https://www.rentcast.io/api (rental listings)
  - Zillow via RapidAPI: https://rapidapi.com/apimaker/api/zillow-com1
  - Redfin via RapidAPI: https://rapidapi.com/apimaker/api/redfin-com
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class APIKeys:
    """API keys - set via environment variables or fill in directly."""
    rentcast: str = os.getenv("RENTCAST_API_KEY", "")
    rapidapi: str = os.getenv("RAPIDAPI_KEY", "")  # Used for Zillow + Redfin


@dataclass
class SearchCriteria:
    """What we're looking for."""
    city: str = "San Francisco"
    state: str = "CA"
    bedrooms: int = 3
    min_price: Optional[int] = None       # Set to filter by min rent
    max_price: Optional[int] = 8000       # Set to filter by max rent
    property_types: list = field(default_factory=lambda: [
        "apartment", "condo", "townhouse"
    ])


@dataclass
class ScoringWeights:
    """
    Weights for the quality scoring algorithm (0-1 each).
    Adjust these to change what "high quality" means to you.
    """
    price_value: float = 0.20         # Lower price relative to area avg
    size_sqft: float = 0.15           # Larger square footage
    amenities: float = 0.15           # Number of amenities
    location_walkscore: float = 0.15  # Walk score / transit access
    photos_count: float = 0.05        # More photos = more transparent
    recency: float = 0.15             # How recently listed
    pet_friendly: float = 0.05        # Allows pets
    parking: float = 0.05             # Has parking
    laundry: float = 0.05             # In-unit or on-site laundry


@dataclass
class AppConfig:
    """Top-level configuration."""
    keys: APIKeys = field(default_factory=APIKeys)
    search: SearchCriteria = field(default_factory=SearchCriteria)
    scoring: ScoringWeights = field(default_factory=ScoringWeights)

    # Output
    output_dir: str = os.path.expanduser("~/apartment-hunter/output")
    dashboard_filename: str = "dashboard.html"
    data_filename: str = "listings.json"

    # How many days back a listing is considered "new"
    new_listing_days: int = 3

    # Max listings to show on dashboard
    max_dashboard_listings: int = 50

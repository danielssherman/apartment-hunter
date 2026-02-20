"""
TOS-compliant API fetchers for rental listing data.

Each fetcher uses official APIs or authorized data partners.
No scraping is performed.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from config import APIKeys, SearchCriteria

logger = logging.getLogger(__name__)


# ── Unified Listing Model ───────────────────────────────────────────────────

@dataclass
class Listing:
    """Normalized listing from any source."""
    id: str
    source: str                          # "rentcast" | "zillow" | "redfin"
    title: str
    address: str
    city: str
    state: str
    zip_code: str
    price: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    url: str = ""                        # Link to original listing
    image_url: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    listed_date: Optional[str] = None    # ISO format
    property_type: str = ""
    amenities: list = field(default_factory=list)
    pet_friendly: bool = False
    parking: bool = False
    laundry: str = ""                    # "in-unit", "on-site", "none", ""
    photos_count: int = 0
    raw_data: dict = field(default_factory=dict)

    @property
    def days_on_market(self) -> Optional[int]:
        if not self.listed_date:
            return None
        try:
            listed = datetime.fromisoformat(self.listed_date.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - listed).days
        except (ValueError, TypeError):
            return None


# ── Base Fetcher ────────────────────────────────────────────────────────────

class BaseFetcher(ABC):
    """Abstract base for all API fetchers."""

    def __init__(self, keys: APIKeys, criteria: SearchCriteria):
        self.keys = keys
        self.criteria = criteria
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    @abstractmethod
    def fetch(self) -> list[Listing]:
        """Fetch listings matching criteria. Returns normalized Listing objects."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...

    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[dict]:
        """Make an API request with error handling and rate limiting."""
        try:
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 429:
                logger.warning(f"[{self.source_name}] Rate limited. Waiting 60s...")
                time.sleep(60)
                resp = self.session.request(method, url, timeout=30, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"[{self.source_name}] HTTP {e.response.status_code}: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"[{self.source_name}] Request failed: {e}")
        except ValueError:
            logger.error(f"[{self.source_name}] Invalid JSON response")
        return None


# ── RentCast Fetcher ────────────────────────────────────────────────────────

class RentCastFetcher(BaseFetcher):
    """
    Fetches from the RentCast API (https://www.rentcast.io/api).
    Provides rental listings with detailed property data.
    Free tier: 50 requests/month.
    """

    BASE_URL = "https://api.rentcast.io/v1"
    source_name = "rentcast"

    def fetch(self) -> list[Listing]:
        if not self.keys.rentcast:
            logger.warning("RentCast API key not set. Skipping.")
            return []

        self.session.headers.update({"X-Api-Key": self.keys.rentcast})

        params = {
            "city": self.criteria.city,
            "state": self.criteria.state,
            "bedrooms": self.criteria.bedrooms,
            "status": "Active",
            "limit": 50,
        }
        if self.criteria.max_price:
            params["maxPrice"] = self.criteria.max_price
        if self.criteria.min_price:
            params["minPrice"] = self.criteria.min_price

        data = self._safe_request("GET", f"{self.BASE_URL}/listings/rental/long-term", params=params)
        if not data:
            return []

        listings = []
        for item in data if isinstance(data, list) else data.get("listings", data.get("results", [])):
            try:
                listing = self._normalize(item)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"[rentcast] Skipping item: {e}")

        logger.info(f"[rentcast] Fetched {len(listings)} listings")
        return listings

    def _normalize(self, item: dict) -> Optional[Listing]:
        address_parts = [
            item.get("addressLine1", ""),
            item.get("city", ""),
            item.get("state", ""),
            item.get("zipCode", ""),
        ]
        address = ", ".join(p for p in address_parts if p)

        # Build URL to the listing on RentCast or fallback
        listing_id = item.get("id", "")
        url = item.get("listingUrl", "")

        amenities = item.get("amenities", []) or []
        pet_friendly = any("pet" in str(a).lower() for a in amenities)
        parking = any("parking" in str(a).lower() or "garage" in str(a).lower() for a in amenities)
        laundry = ""
        for a in amenities:
            al = str(a).lower()
            if "in-unit" in al or "washer" in al:
                laundry = "in-unit"
                break
            elif "laundry" in al:
                laundry = "on-site"

        return Listing(
            id=f"rc_{listing_id}",
            source="rentcast",
            title=item.get("addressLine1", "3BR Apartment"),
            address=address,
            city=item.get("city", self.criteria.city),
            state=item.get("state", self.criteria.state),
            zip_code=item.get("zipCode", ""),
            price=item.get("price"),
            bedrooms=item.get("bedrooms"),
            bathrooms=item.get("bathrooms"),
            sqft=item.get("squareFootage"),
            url=url,
            image_url=item.get("photoUrl", ""),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            listed_date=item.get("listedDate") or item.get("createdDate"),
            property_type=item.get("propertyType", ""),
            amenities=amenities,
            pet_friendly=pet_friendly,
            parking=parking,
            laundry=laundry,
            photos_count=len(item.get("photos", []) or []),
            raw_data=item,
        )


# ── Zillow Fetcher (via RapidAPI) ──────────────────────────────────────────

class ZillowFetcher(BaseFetcher):
    """
    Fetches from the Zillow API on RapidAPI.
    Endpoint: zillow-com1.p.rapidapi.com
    """

    HOST = "zillow-com1.p.rapidapi.com"
    BASE_URL = f"https://{HOST}"
    source_name = "zillow"

    def fetch(self) -> list[Listing]:
        if not self.keys.rapidapi:
            logger.warning("RapidAPI key not set. Skipping Zillow.")
            return []

        self.session.headers.update({
            "x-rapidapi-key": self.keys.rapidapi,
            "x-rapidapi-host": self.HOST,
        })

        # Search for rentals
        params = {
            "location": f"{self.criteria.city}, {self.criteria.state}",
            "status_type": "ForRent",
            "beds_min": self.criteria.bedrooms,
            "beds_max": self.criteria.bedrooms,
            "sort": "Newest",
            "listing_type": "by_agent",
        }
        if self.criteria.max_price:
            params["price_max"] = self.criteria.max_price
        if self.criteria.min_price:
            params["price_min"] = self.criteria.min_price

        data = self._safe_request("GET", f"{self.BASE_URL}/propertyExtendedSearch", params=params)
        if not data:
            return []

        results = data.get("props", [])
        listings = []
        for item in results:
            try:
                listing = self._normalize(item)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"[zillow] Skipping item: {e}")

        logger.info(f"[zillow] Fetched {len(listings)} listings")
        return listings

    def _normalize(self, item: dict) -> Optional[Listing]:
        zpid = str(item.get("zpid", ""))
        address = item.get("address", "")
        if isinstance(address, dict):
            address = f"{address.get('streetAddress', '')}, {address.get('city', '')}, {address.get('state', '')} {address.get('zipcode', '')}"

        url = item.get("detailUrl", "")
        if url and not url.startswith("http"):
            url = f"https://www.zillow.com{url}"
        elif zpid and not url:
            url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

        return Listing(
            id=f"zl_{zpid}",
            source="zillow",
            title=item.get("streetAddress", item.get("address", "3BR Apartment")),
            address=address if isinstance(address, str) else str(address),
            city=self.criteria.city,
            state=self.criteria.state,
            zip_code=str(item.get("zipcode", "")),
            price=item.get("price"),
            bedrooms=item.get("bedrooms"),
            bathrooms=item.get("bathrooms"),
            sqft=item.get("livingArea"),
            url=url,
            image_url=item.get("imgSrc", ""),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            listed_date=item.get("datePosted"),
            property_type=item.get("propertyType", ""),
            amenities=[],
            photos_count=len(item.get("carouselPhotos", []) or []),
            raw_data=item,
        )


# ── Redfin Fetcher (via RapidAPI) ──────────────────────────────────────────

class RedfinFetcher(BaseFetcher):
    """
    Fetches from the Redfin API on RapidAPI.
    Endpoint: redfin-com.p.rapidapi.com
    """

    HOST = "redfin-com.p.rapidapi.com"
    BASE_URL = f"https://{HOST}"
    source_name = "redfin"

    def fetch(self) -> list[Listing]:
        if not self.keys.rapidapi:
            logger.warning("RapidAPI key not set. Skipping Redfin.")
            return []

        self.session.headers.update({
            "x-rapidapi-key": self.keys.rapidapi,
            "x-rapidapi-host": self.HOST,
        })

        # Step 1: Get region ID for the city
        search_data = self._safe_request(
            "GET",
            f"{self.BASE_URL}/auto-complete",
            params={"location": f"{self.criteria.city}, {self.criteria.state}"}
        )

        region_id = None
        if search_data:
            regions = search_data.get("data", {}).get("regions", [])
            if not regions and isinstance(search_data, list):
                regions = search_data
            for region in regions:
                if "id" in region:
                    region_id = region["id"]
                    break

        if not region_id:
            # Fallback: use known region ID for San Francisco
            region_id = "20330"
            logger.info("[redfin] Using fallback SF region ID")

        # Step 2: Search rentals
        params = {
            "region_id": region_id,
            "region_type": "city",
            "status": "For Rent",
            "beds_min": self.criteria.bedrooms,
            "beds_max": self.criteria.bedrooms,
            "sort": "redfin-recommended",
            "num_homes": 50,
        }
        if self.criteria.max_price:
            params["price_max"] = self.criteria.max_price
        if self.criteria.min_price:
            params["price_min"] = self.criteria.min_price

        data = self._safe_request("GET", f"{self.BASE_URL}/properties/search-rent", params=params)
        if not data:
            return []

        results = data.get("data", {}).get("homes", data.get("homes", []))
        if not results and isinstance(data, list):
            results = data

        listings = []
        for item in results:
            try:
                listing = self._normalize(item)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"[redfin] Skipping item: {e}")

        logger.info(f"[redfin] Fetched {len(listings)} listings")
        return listings

    def _normalize(self, item: dict) -> Optional[Listing]:
        home = item.get("homeData", item)
        address_info = home.get("addressInfo", {})

        street = address_info.get("formattedStreetLine", home.get("streetLine", ""))
        city = address_info.get("city", self.criteria.city)
        state = address_info.get("state", self.criteria.state)
        zipcode = str(address_info.get("zip", ""))
        address = f"{street}, {city}, {state} {zipcode}"

        listing_id = str(home.get("listingId", home.get("propertyId", "")))
        url = home.get("url", "")
        if url and not url.startswith("http"):
            url = f"https://www.redfin.com{url}"

        price_info = home.get("priceInfo", {})
        price = price_info.get("amount", home.get("price", {}).get("value"))
        if price is None:
            price = home.get("price")
            if isinstance(price, dict):
                price = price.get("value")

        beds = home.get("beds", home.get("bedrooms"))
        baths = home.get("baths", home.get("bathrooms"))
        sqft = home.get("sqFt", {})
        if isinstance(sqft, dict):
            sqft = sqft.get("value")

        return Listing(
            id=f"rf_{listing_id}",
            source="redfin",
            title=street or "3BR Apartment",
            address=address,
            city=city,
            state=state,
            zip_code=zipcode,
            price=float(price) if price else None,
            bedrooms=beds,
            bathrooms=baths,
            sqft=int(sqft) if sqft else None,
            url=url,
            image_url=home.get("photos", [{}])[0].get("photoUrl", "") if home.get("photos") else "",
            latitude=address_info.get("centroid", {}).get("centroid", {}).get("latitude")
                     or home.get("latitude"),
            longitude=address_info.get("centroid", {}).get("centroid", {}).get("longitude")
                      or home.get("longitude"),
            listed_date=home.get("listingDate"),
            property_type=home.get("propertyType", ""),
            amenities=[],
            photos_count=len(home.get("photos", []) or []),
            raw_data=item,
        )


# ── Fetch All ───────────────────────────────────────────────────────────────

def fetch_all(keys: APIKeys, criteria: SearchCriteria) -> list[Listing]:
    """Run all fetchers and return deduplicated, combined results."""
    fetchers: list[BaseFetcher] = [
        RentCastFetcher(keys, criteria),
        ZillowFetcher(keys, criteria),
        RedfinFetcher(keys, criteria),
    ]

    all_listings: list[Listing] = []
    for fetcher in fetchers:
        try:
            results = fetcher.fetch()
            all_listings.extend(results)
        except Exception as e:
            logger.error(f"[{fetcher.source_name}] Unexpected error: {e}")

    # Deduplicate by address similarity
    seen_addresses: set[str] = set()
    unique: list[Listing] = []
    for listing in all_listings:
        addr_key = listing.address.lower().replace(" ", "").replace(",", "")[:40]
        if addr_key not in seen_addresses:
            seen_addresses.add(addr_key)
            unique.append(listing)

    logger.info(f"Total: {len(all_listings)} listings, {len(unique)} after dedup")
    return unique

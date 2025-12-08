"""GearGraph Sync API Client.

Client for fetching brand and product data from the GearGraph Sync API
for synchronization to Firebase gearBase collection.

API Endpoint: https://geargraph.gearshack.app/api/sync/changes
Authentication: X-API-Key header
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_API_URL = "https://geargraph.gearshack.app/api/sync/changes"
SYNC_TOKEN_FILE = ".geargraph_sync_token"


@dataclass
class Brand:
    """Brand data from the sync API."""
    id: str
    name: str
    country: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    last_updated: Optional[str] = None
    product_count: int = 0

    def to_firebase_doc(self) -> dict:
        """Convert to Firebase document format."""
        return {
            "brand_name": self.name,
            "brand_aliases": [],
            "brand_logo": self.logo_url or "",
            "brand_url": self.website or "",
            "country": self.country or "",
            "product_count": self.product_count,
            "geargraph_id": self.id,
            "last_synced": datetime.utcnow().isoformat(),
        }


@dataclass
class Product:
    """Product data from the sync API."""
    id: str
    name: str
    brand_id: str
    brand_name: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    image_url: Optional[str] = None
    last_updated: Optional[str] = None

    def to_firebase_doc(self) -> dict:
        """Convert to Firebase document format."""
        return {
            "product_name": self.name,
            "brand": self.brand_name,
            "category": self.category or "",
            "subcategory": self.subcategory or "",
            "image_url": self.image_url or "",
            "geargraph_id": self.id,
            "brand_id": self.brand_id,
            "last_synced": datetime.utcnow().isoformat(),
        }


@dataclass
class SyncResponse:
    """Response from the sync API."""
    brands_added: list[Brand] = field(default_factory=list)
    brands_updated: list[Brand] = field(default_factory=list)
    brands_deleted: list[Brand] = field(default_factory=list)
    products_added: list[Product] = field(default_factory=list)
    products_updated: list[Product] = field(default_factory=list)
    products_deleted: list[Product] = field(default_factory=list)
    next_sync_token: str = ""
    full_sync: bool = False

    @property
    def total_brands(self) -> int:
        return len(self.brands_added) + len(self.brands_updated)

    @property
    def total_products(self) -> int:
        return len(self.products_added) + len(self.products_updated)

    @property
    def total_deleted(self) -> int:
        return len(self.brands_deleted) + len(self.products_deleted)

    def to_dict(self) -> dict:
        return {
            "brands_added": len(self.brands_added),
            "brands_updated": len(self.brands_updated),
            "brands_deleted": len(self.brands_deleted),
            "products_added": len(self.products_added),
            "products_updated": len(self.products_updated),
            "products_deleted": len(self.products_deleted),
            "next_sync_token": self.next_sync_token,
            "full_sync": self.full_sync,
        }


class GearGraphSyncClient:
    """Client for the GearGraph Sync API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
    ):
        """Initialize the sync client.

        Args:
            api_key: GearGraph API key (defaults to GEARGRAPH_API_KEY env var)
            api_url: API endpoint URL (defaults to production URL)
        """
        self.api_key = api_key or os.getenv("GEARGRAPH_API_KEY")
        self.api_url = api_url or os.getenv("GEARGRAPH_SYNC_API_URL", DEFAULT_API_URL)

        if not self.api_key:
            raise ValueError(
                "GearGraph API key not provided. Set GEARGRAPH_API_KEY environment variable."
            )

    def _get_headers(self) -> dict:
        """Get request headers with API key."""
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def fetch_changes(self, since: Optional[str] = None) -> SyncResponse:
        """Fetch changes from the sync API.

        Args:
            since: Optional sync token from previous sync for incremental updates

        Returns:
            SyncResponse with all changes
        """
        url = self.api_url
        if since:
            url = f"{url}?since={since}"

        logger.info(f"Fetching sync data from {url}")

        try:
            response = httpx.get(
                url,
                headers=self._get_headers(),
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

            return self._parse_response(data)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid API key")
            elif e.response.status_code == 429:
                raise ValueError("Rate limited - try again in 60 seconds")
            else:
                raise ValueError(f"API error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            raise ValueError(f"Request failed: {str(e)}")

    def _parse_response(self, data: dict) -> SyncResponse:
        """Parse API response into SyncResponse."""
        response = SyncResponse(
            next_sync_token=data.get("next_sync_token", ""),
            full_sync=data.get("full_sync", False),
        )

        # Parse brands
        brands_data = data.get("brands", {})
        for brand in brands_data.get("added", []):
            response.brands_added.append(self._parse_brand(brand))
        for brand in brands_data.get("updated", []):
            response.brands_updated.append(self._parse_brand(brand))
        for brand in brands_data.get("deleted", []):
            response.brands_deleted.append(self._parse_brand(brand))

        # Parse products
        products_data = data.get("products", {})
        for product in products_data.get("added", []):
            response.products_added.append(self._parse_product(product))
        for product in products_data.get("updated", []):
            response.products_updated.append(self._parse_product(product))
        for product in products_data.get("deleted", []):
            response.products_deleted.append(self._parse_product(product))

        return response

    def _parse_brand(self, data: dict) -> Brand:
        """Parse brand data from API response."""
        return Brand(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            country=data.get("country"),
            logo_url=data.get("logo_url"),
            website=data.get("website"),
            last_updated=data.get("last_updated"),
            product_count=data.get("product_count", 0),
        )

    def _parse_product(self, data: dict) -> Product:
        """Parse product data from API response."""
        return Product(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            brand_id=str(data.get("brand_id", "")),
            brand_name=data.get("brand_name", ""),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
            image_url=data.get("image_url"),
            last_updated=data.get("last_updated"),
        )

    def full_sync(self) -> SyncResponse:
        """Perform a full sync (no token)."""
        return self.fetch_changes(since=None)

    def incremental_sync(self, since: str) -> SyncResponse:
        """Perform an incremental sync from a specific point."""
        return self.fetch_changes(since=since)


def get_saved_sync_token() -> Optional[str]:
    """Get the saved sync token from file."""
    token_file = Path(SYNC_TOKEN_FILE)
    if token_file.exists():
        try:
            data = json.loads(token_file.read_text())
            return data.get("sync_token")
        except Exception as e:
            logger.warning(f"Failed to read sync token: {e}")
    return None


def save_sync_token(token: str):
    """Save the sync token to file."""
    token_file = Path(SYNC_TOKEN_FILE)
    data = {
        "sync_token": token,
        "saved_at": datetime.utcnow().isoformat(),
    }
    token_file.write_text(json.dumps(data, indent=2))
    logger.info(f"Saved sync token: {token}")


def clear_sync_token():
    """Clear the saved sync token (force full sync next time)."""
    token_file = Path(SYNC_TOKEN_FILE)
    if token_file.exists():
        token_file.unlink()
        logger.info("Cleared sync token")


def slugify(name: str) -> str:
    """Convert a name to a URL-safe slug for Firebase document IDs."""
    import re
    if not name:
        return "unknown"
    slug = name.lower()
    slug = re.sub(r"['\"]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "unknown"


def sync_to_firebase(
    sync_response: SyncResponse,
    service_account_path: str,
) -> dict:
    """Sync data from SyncResponse to Firebase Firestore.

    Args:
        sync_response: Data from the sync API
        service_account_path: Path to Firebase service account JSON

    Returns:
        Dict with sync statistics
    """
    import firebase_admin
    from firebase_admin import credentials, firestore

    # Initialize Firebase if not already done
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    stats = {
        "brands_written": 0,
        "products_written": 0,
        "items_deleted": 0,
    }

    # Process added/updated brands
    all_brands = sync_response.brands_added + sync_response.brands_updated
    for brand in all_brands:
        brand_slug = slugify(brand.name)
        brand_ref = db.collection("gearBase").document(brand_slug)
        brand_ref.set(brand.to_firebase_doc(), merge=True)
        stats["brands_written"] += 1

    # Process deleted brands
    for brand in sync_response.brands_deleted:
        brand_slug = slugify(brand.name)
        try:
            db.collection("gearBase").document(brand_slug).delete()
            stats["items_deleted"] += 1
        except Exception as e:
            logger.warning(f"Failed to delete brand {brand_slug}: {e}")

    # Process added/updated products
    all_products = sync_response.products_added + sync_response.products_updated
    for product in all_products:
        brand_slug = slugify(product.brand_name)
        product_slug = slugify(product.name)

        product_ref = (
            db.collection("gearBase")
            .document(brand_slug)
            .collection("products")
            .document(product_slug)
        )
        product_ref.set(product.to_firebase_doc(), merge=True)
        stats["products_written"] += 1

    # Process deleted products
    for product in sync_response.products_deleted:
        brand_slug = slugify(product.brand_name)
        product_slug = slugify(product.name)
        try:
            (
                db.collection("gearBase")
                .document(brand_slug)
                .collection("products")
                .document(product_slug)
                .delete()
            )
            stats["items_deleted"] += 1
        except Exception as e:
            logger.warning(f"Failed to delete product {product_slug}: {e}")

    return stats


def run_sync(
    api_key: Optional[str] = None,
    service_account_path: str = "firebase-service-account.json",
    force_full_sync: bool = False,
) -> dict:
    """Run a complete sync from GearGraph API to Firebase.

    Args:
        api_key: GearGraph API key (defaults to env var)
        service_account_path: Path to Firebase service account JSON
        force_full_sync: If True, ignore saved sync token and do full sync

    Returns:
        Dict with sync statistics
    """
    client = GearGraphSyncClient(api_key=api_key)

    # Get sync token unless forcing full sync
    since = None
    if not force_full_sync:
        since = get_saved_sync_token()

    # Fetch changes
    if since:
        logger.info(f"Running incremental sync from {since}")
        response = client.incremental_sync(since)
    else:
        logger.info("Running full sync")
        response = client.full_sync()

    logger.info(
        f"Fetched: {response.total_brands} brands, "
        f"{response.total_products} products, "
        f"{response.total_deleted} deletions"
    )

    # Sync to Firebase
    if not os.path.exists(service_account_path):
        raise FileNotFoundError(f"Firebase service account not found: {service_account_path}")

    stats = sync_to_firebase(response, service_account_path)

    # Save new sync token
    if response.next_sync_token:
        save_sync_token(response.next_sync_token)

    stats["sync_type"] = "full" if response.full_sync else "incremental"
    stats["sync_token"] = response.next_sync_token

    return stats

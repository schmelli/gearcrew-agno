"""Data Enrichment Agent for GearGraph.

This agent runs in the background to find and enrich gear items with missing data.
It prioritizes key gear categories and uses web search to find product specifications.
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from app.db.memgraph import (
    get_items_needing_enrichment,
    get_enrichment_stats,
    mark_item_enriched,
    merge_gear_item,
    PRIORITY_CATEGORIES,
)
from app.tools.web_scraper import search_web, extract_product_data

logger = logging.getLogger(__name__)


class EnrichmentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class EnrichmentResult:
    """Result of enriching a single item."""
    name: str
    brand: str
    success: bool
    fields_added: list[str]
    error: Optional[str] = None
    search_url: Optional[str] = None


class EnrichmentAgent:
    """Agent that enriches gear items with missing data.

    Runs as a background process, finding items with low completeness scores
    and searching the web for additional specifications.
    """

    def __init__(
        self,
        batch_size: int = 10,
        delay_between_items: float = 2.0,
        max_search_results: int = 3,
    ):
        """Initialize the enrichment agent.

        Args:
            batch_size: Number of items to process per batch
            delay_between_items: Seconds to wait between items (rate limiting)
            max_search_results: Max search results to check per item
        """
        self.batch_size = batch_size
        self.delay_between_items = delay_between_items
        self.max_search_results = max_search_results
        self.status = EnrichmentStatus.IDLE
        self.items_processed = 0
        self.items_enriched = 0
        self.current_item: Optional[str] = None
        self.last_error: Optional[str] = None
        self._stop_requested = False

    def get_status(self) -> dict:
        """Get current enrichment status."""
        stats = get_enrichment_stats()
        return {
            "status": self.status.value,
            "items_processed": self.items_processed,
            "items_enriched": self.items_enriched,
            "current_item": self.current_item,
            "last_error": self.last_error,
            "database_stats": stats,
        }

    def stop(self):
        """Request the agent to stop after current item."""
        self._stop_requested = True

    def _build_search_query(self, name: str, brand: str, category: Optional[str]) -> str:
        """Build an effective search query for a gear item."""
        # Include category-specific terms to get spec pages
        category_terms = {
            "backpack": "specs volume liters weight",
            "tent": "specs weight capacity season",
            "sleeping_bag": "specs temperature rating fill power",
            "sleeping_pad": "specs r-value weight",
            "stove": "specs fuel weight boil time",
            "headlamp": "specs lumens battery life",
            "water_filter": "specs flow rate filter type",
            "jacket": "specs weight waterproof rating",
        }

        # Handle None category
        cat_key = (category or "").lower()
        extra_terms = category_terms.get(cat_key, "specs weight")
        return f"{brand} {name} {extra_terms}"

    def _extract_new_fields(
        self, existing: dict, extracted: dict
    ) -> tuple[dict, list[str]]:
        """Compare existing and extracted data, return new fields to add.

        Args:
            existing: Current item data from database
            extracted: Newly extracted data from web

        Returns:
            Tuple of (fields_to_update, list_of_field_names_added)
        """
        updates = {}
        added_fields = []

        # Field mapping from extracted to database format
        field_map = {
            "product_name": None,  # Don't update name
            "brand": None,  # Don't update brand
            "price": "price_usd",
            "weight_grams": "weight_grams",
            "weight_oz": None,  # Convert to grams
            "description": "description",
            "materials": "materials",
            "features": "features",
            "image_url": "image_url",
            "category": None,  # Don't change category
            # Category-specific
            "volume_liters": "volume_liters",
            "temp_rating_f": "temp_rating_f",
            "temp_rating_c": "temp_rating_c",
            "r_value": "r_value",
            "capacity_persons": "capacity_persons",
            "fill_power": "fill_power",
            "waterproof_rating": "waterproof_rating",
            "lumens": "lumens",
            "burn_time": "burn_time",
            "fuel_type": "fuel_type",
            "filter_type": "filter_type",
            "flow_rate": "flow_rate",
        }

        for ext_field, db_field in field_map.items():
            if db_field is None:
                continue

            ext_value = extracted.get(ext_field)
            existing_value = existing.get(db_field)

            # Only add if we have new data and field is empty
            if ext_value and not existing_value:
                updates[db_field] = ext_value
                added_fields.append(db_field)

        # Handle weight_oz -> weight_grams conversion
        if extracted.get("weight_oz") and not existing.get("weight_grams"):
            weight_g = int(extracted["weight_oz"] * 28.35)
            updates["weight_grams"] = weight_g
            if "weight_grams" not in added_fields:
                added_fields.append("weight_grams")

        return updates, added_fields

    def enrich_single_item(self, item: dict) -> EnrichmentResult:
        """Attempt to enrich a single gear item.

        Args:
            item: Gear item dictionary from database

        Returns:
            EnrichmentResult with success status and details
        """
        name = item.get("name") or ""
        brand = item.get("brand") or ""
        category = item.get("category") or "other"

        self.current_item = f"{brand} {name}"
        logger.info(f"Enriching: {self.current_item}")

        try:
            # Search for product information
            query = self._build_search_query(name, brand, category)
            search_results = search_web(query, num_results=self.max_search_results)

            if not search_results:
                return EnrichmentResult(
                    name=name,
                    brand=brand,
                    success=False,
                    fields_added=[],
                    error="No search results found",
                )

            # Try to extract from each result
            best_result = None
            best_fields = []
            search_url = None

            for result in search_results:
                url = result.get("url", "")
                if not url:
                    continue

                try:
                    extracted = extract_product_data(url)
                    if not extracted:
                        continue

                    # Check if this extraction has useful data
                    updates, added_fields = self._extract_new_fields(item, extracted)

                    if len(added_fields) > len(best_fields):
                        best_result = updates
                        best_fields = added_fields
                        search_url = url

                except Exception as e:
                    logger.debug(f"Failed to extract from {url}: {e}")
                    continue

            if not best_result or not best_fields:
                # Mark as enriched anyway to avoid re-processing
                mark_item_enriched(name, brand)
                return EnrichmentResult(
                    name=name,
                    brand=brand,
                    success=False,
                    fields_added=[],
                    error="No new data found in search results",
                )

            # Update the item in database
            merge_gear_item(
                name=name,
                brand=brand,
                category=category,
                **best_result,
            )
            mark_item_enriched(name, brand)

            logger.info(f"Enriched {self.current_item}: added {best_fields}")

            return EnrichmentResult(
                name=name,
                brand=brand,
                success=True,
                fields_added=best_fields,
                search_url=search_url,
            )

        except Exception as e:
            logger.error(f"Error enriching {self.current_item}: {e}")
            return EnrichmentResult(
                name=name,
                brand=brand,
                success=False,
                fields_added=[],
                error=str(e),
            )

    def run_batch(self, category: Optional[str] = None) -> list[EnrichmentResult]:
        """Run a single batch of enrichment.

        Args:
            category: Optional category to focus on

        Returns:
            List of EnrichmentResult for processed items
        """
        self.status = EnrichmentStatus.RUNNING
        self._stop_requested = False
        results = []

        try:
            items = get_items_needing_enrichment(
                limit=self.batch_size,
                max_score=0.5,  # Only items with <50% completeness
                category=category,
            )

            if not items:
                logger.info("No items needing enrichment")
                self.status = EnrichmentStatus.IDLE
                return results

            for item in items:
                if self._stop_requested:
                    logger.info("Stop requested, ending batch")
                    break

                result = self.enrich_single_item(item)
                results.append(result)
                self.items_processed += 1

                if result.success:
                    self.items_enriched += 1

                # Rate limiting
                time.sleep(self.delay_between_items)

        except Exception as e:
            self.status = EnrichmentStatus.ERROR
            self.last_error = str(e)
            logger.error(f"Batch enrichment error: {e}")

        finally:
            if not self._stop_requested:
                self.status = EnrichmentStatus.IDLE
            self.current_item = None

        return results

    def run_continuous(self, max_iterations: Optional[int] = None):
        """Run enrichment continuously until stopped or complete.

        Args:
            max_iterations: Optional limit on number of batches to run
        """
        iteration = 0

        while not self._stop_requested:
            if max_iterations and iteration >= max_iterations:
                break

            results = self.run_batch()

            if not results:
                # No more items to enrich
                logger.info("Enrichment complete - no more items to process")
                break

            iteration += 1

            # Longer delay between batches
            time.sleep(5.0)

        self.status = EnrichmentStatus.IDLE


# Global agent instance
_enrichment_agent: Optional[EnrichmentAgent] = None


def get_enrichment_agent() -> EnrichmentAgent:
    """Get or create the global enrichment agent instance."""
    global _enrichment_agent
    if _enrichment_agent is None:
        _enrichment_agent = EnrichmentAgent()
    return _enrichment_agent

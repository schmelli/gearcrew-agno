"""Memgraph database connection and utilities for GearGraph.

This module provides the connection to the Memgraph graph database
and utility functions for common operations.
"""

import os
import logging
from typing import Any, Optional

from dotenv import load_dotenv
from gqlalchemy import Memgraph

load_dotenv()

logger = logging.getLogger(__name__)

# Global connection instance
_memgraph: Optional[Memgraph] = None


def _create_connection() -> Optional[Memgraph]:
    """Create a new Memgraph connection.

    Returns:
        Memgraph connection or None if connection fails
    """
    try:
        host = os.getenv("MEMGRAPH_HOST", "geargraph.gearshack.app")
        port = int(os.getenv("MEMGRAPH_PORT", "7687"))
        user = os.getenv("MEMGRAPH_USER", "memgraph")
        password = os.getenv("MEMGRAPH_PASSWORD", "")

        connection = Memgraph(
            host=host,
            port=port,
            username=user,
            password=password,
            encrypted=True,
        )

        logger.info(f"Connected to Memgraph at {host}:{port}")
        return connection

    except Exception as e:
        logger.error(f"Failed to connect to Memgraph: {e}")
        return None


def get_memgraph(force_reconnect: bool = False) -> Optional[Memgraph]:
    """Get or create the Memgraph connection instance.

    Args:
        force_reconnect: If True, create a new connection even if one exists

    Returns:
        Memgraph connection or None if connection fails
    """
    global _memgraph

    if force_reconnect:
        _memgraph = None

    if _memgraph is not None:
        return _memgraph

    _memgraph = _create_connection()
    return _memgraph


def _reconnect_and_retry(func):
    """Decorator to retry database operations with reconnection on failure."""
    def wrapper(*args, **kwargs):
        global _memgraph
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            # Check for connection-related errors
            if any(err in error_msg for err in ["chunk", "connection", "socket", "closed", "timeout"]):
                logger.warning(f"Connection error, attempting reconnect: {e}")
                _memgraph = None
                _memgraph = _create_connection()
                if _memgraph:
                    try:
                        return func(*args, **kwargs)
                    except Exception as retry_e:
                        logger.error(f"Retry failed: {retry_e}")
            raise
    return wrapper


def execute_cypher(query: str, params: Optional[dict] = None) -> bool:
    """Execute a Cypher query without returning results.

    Args:
        query: Cypher query to execute
        params: Optional query parameters

    Returns:
        True if successful, False otherwise
    """
    global _memgraph

    for attempt in range(2):
        db = get_memgraph(force_reconnect=(attempt > 0))
        if db is None:
            logger.error("No database connection available")
            return False

        try:
            if params:
                db.execute(query, params)
            else:
                db.execute(query)
            return True
        except Exception as e:
            error_msg = str(e).lower()
            if attempt == 0 and any(
                err in error_msg for err in ["chunk", "connection", "socket", "closed", "timeout"]
            ):
                logger.warning(f"Connection error on attempt {attempt + 1}, retrying: {e}")
                _memgraph = None
                continue
            logger.error(f"Cypher execution failed: {e}")
            return False

    return False


def execute_and_fetch(query: str, params: Optional[dict] = None) -> list[dict[str, Any]]:
    """Execute a Cypher query and return results.

    Args:
        query: Cypher query to execute
        params: Optional query parameters

    Returns:
        List of result dictionaries
    """
    global _memgraph

    for attempt in range(2):
        db = get_memgraph(force_reconnect=(attempt > 0))
        if db is None:
            logger.error("No database connection available")
            return []

        try:
            if params:
                results = list(db.execute_and_fetch(query, params))
            else:
                results = list(db.execute_and_fetch(query))
            return results
        except Exception as e:
            error_msg = str(e).lower()
            if attempt == 0 and any(
                err in error_msg for err in ["chunk", "connection", "socket", "closed", "timeout"]
            ):
                logger.warning(f"Connection error on attempt {attempt + 1}, retrying: {e}")
                _memgraph = None
                continue
            logger.error(f"Cypher query failed: {e}")
            return []

    return []


def find_similar_nodes(name: str, label: str = "GearItem", limit: int = 5) -> list[dict]:
    """Find nodes with similar names to prevent duplicates.

    Uses case-insensitive substring matching in both directions.

    Args:
        name: Name to search for
        label: Node label to filter by (e.g., 'GearItem', 'OutdoorBrand')
        limit: Maximum number of results

    Returns:
        List of matching nodes with name, labels, and URL
    """
    query = f"""
    MATCH (n:{label})
    WHERE toLower(n.name) CONTAINS toLower($name)
       OR toLower($name) CONTAINS toLower(n.name)
    RETURN n.name as name, labels(n) as labels, n.productUrl as url
    LIMIT $limit
    """

    results = execute_and_fetch(query, {"name": name, "limit": limit})
    return results


def check_node_exists(name: str, label: str, brand: Optional[str] = None) -> Optional[dict]:
    """Check if a node already exists in the graph.

    Args:
        name: Node name to check
        label: Node label (e.g., 'GearItem', 'OutdoorBrand')
        brand: Optional brand name for product lookups

    Returns:
        Node data if found, None otherwise
    """
    if brand and label == "GearItem":
        query = f"""
        MATCH (n:{label})
        WHERE toLower(n.name) = toLower($name)
          AND toLower(n.brand) = toLower($brand)
        RETURN n, labels(n) as labels, id(n) as node_id
        LIMIT 1
        """
        results = execute_and_fetch(query, {"name": name, "brand": brand})
    else:
        query = f"""
        MATCH (n:{label})
        WHERE toLower(n.name) = toLower($name)
        RETURN n, labels(n) as labels, id(n) as node_id
        LIMIT 1
        """
        results = execute_and_fetch(query, {"name": name})

    return results[0] if results else None


def get_graph_stats() -> dict[str, Any]:
    """Get statistics about the graph database.

    Returns:
        Dictionary with node counts, relationship counts, and totals
    """
    stats = {
        "node_counts": {},
        "rel_counts": {},
        "total_nodes": 0,
        "total_rels": 0,
    }

    # Node counts by label
    results = execute_and_fetch(
        "MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC"
    )
    stats["node_counts"] = {r["label"]: r["count"] for r in results}

    # Relationship counts by type
    results = execute_and_fetch(
        "MATCH ()-[r]->() RETURN type(r) as type, count(r) as count ORDER BY count DESC"
    )
    stats["rel_counts"] = {r["type"]: r["count"] for r in results}

    # Total counts
    results = execute_and_fetch("MATCH (n) RETURN count(n) as total")
    if results:
        stats["total_nodes"] = results[0]["total"]

    results = execute_and_fetch("MATCH ()-[r]->() RETURN count(r) as total")
    if results:
        stats["total_rels"] = results[0]["total"]

    return stats


def merge_gear_item(
    name: str,
    brand: str,
    category: str,
    weight_grams: Optional[int] = None,
    price_usd: Optional[float] = None,
    product_url: Optional[str] = None,
    image_url: Optional[str] = None,
    materials: Optional[list[str]] = None,
    source_url: Optional[str] = None,
) -> bool:
    """Merge a gear item into the graph (create or update).

    Uses MERGE to prevent duplicates.

    Args:
        name: Product name
        brand: Brand/manufacturer name
        category: Gear category
        weight_grams: Weight in grams
        price_usd: Price in USD
        product_url: Official product page URL
        image_url: Product image URL
        materials: List of materials
        source_url: URL where this was discovered

    Returns:
        True if successful
    """
    # First ensure the brand exists
    brand_query = """
    MERGE (b:OutdoorBrand {name: $brand})
    RETURN b
    """
    execute_cypher(brand_query, {"brand": brand})

    # Build the SET clause dynamically for optional fields
    set_parts = []
    params = {"name": name, "brand": brand, "category": category}

    if weight_grams is not None:
        set_parts.append("g.weight_grams = $weight_grams")
        params["weight_grams"] = weight_grams

    if price_usd is not None:
        set_parts.append("g.price_usd = $price_usd")
        params["price_usd"] = price_usd

    if product_url:
        set_parts.append("g.productUrl = $product_url")
        params["product_url"] = product_url

    if image_url:
        set_parts.append("g.imageUrl = $image_url")
        params["image_url"] = image_url

    if materials:
        set_parts.append("g.materials = $materials")
        params["materials"] = materials

    if source_url:
        set_parts.append("g.sourceUrl = $source_url")
        params["source_url"] = source_url

    set_clause = ", ".join(set_parts) if set_parts else ""

    # Merge the gear item
    item_query = f"""
    MATCH (b:OutdoorBrand {{name: $brand}})
    MERGE (g:GearItem {{name: $name, brand: $brand}})
    ON CREATE SET g.category = $category, g.createdAt = datetime(){', ' + set_clause if set_clause else ''}
    ON MATCH SET g.updatedAt = datetime(){', ' + set_clause if set_clause else ''}
    MERGE (b)-[:MANUFACTURES_ITEM]->(g)
    RETURN g
    """

    return execute_cypher(item_query, params)


def merge_insight(
    summary: str,
    content: str,
    category: Optional[str] = None,
    related_product: Optional[str] = None,
    source_url: Optional[str] = None,
) -> bool:
    """Merge an insight/tip into the graph.

    Args:
        summary: Short summary of the insight
        content: Full insight content
        category: Insight category (e.g., "Weight Savings", "Durability")
        related_product: Product name this insight relates to
        source_url: URL where this insight was found

    Returns:
        True if successful
    """
    params = {
        "summary": summary,
        "content": content,
    }

    set_parts = []
    if category:
        set_parts.append("i.category = $category")
        params["category"] = category

    if source_url:
        set_parts.append("i.sourceUrl = $source_url")
        params["source_url"] = source_url

    set_clause = ", ".join(set_parts) if set_parts else ""

    insight_query = f"""
    MERGE (i:Insight {{summary: $summary}})
    ON CREATE SET i.content = $content, i.createdAt = datetime(){', ' + set_clause if set_clause else ''}
    ON MATCH SET i.updatedAt = datetime(){', ' + set_clause if set_clause else ''}
    RETURN i
    """

    success = execute_cypher(insight_query, params)

    # Link to product if specified
    if success and related_product:
        link_query = """
        MATCH (i:Insight {summary: $summary})
        MATCH (p) WHERE p.name = $product AND (p:GearItem OR p:ProductFamily)
        MERGE (p)-[:HAS_TIP]->(i)
        """
        execute_cypher(link_query, {"summary": summary, "product": related_product})

    return success


# VideoSource tracking functions

def check_source_exists(url: str) -> Optional[dict]:
    """Check if a source URL has already been processed.

    Args:
        url: The source URL to check

    Returns:
        Source data if found, None otherwise
    """
    query = """
    MATCH (s:VideoSource {url: $url})
    RETURN s.url as url, s.title as title, s.channel as channel,
           s.thumbnailUrl as thumbnail_url, s.processedAt as processed_at,
           s.gearItemsFound as gear_items_found, s.insightsFound as insights_found,
           s.extractionSummary as extraction_summary
    LIMIT 1
    """
    results = execute_and_fetch(query, {"url": url})
    return results[0] if results else None


def save_video_source(
    url: str,
    title: str,
    channel: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    gear_items_found: int = 0,
    insights_found: int = 0,
    extraction_summary: Optional[str] = None,
) -> bool:
    """Save a processed video source to the graph.

    Args:
        url: Video URL (unique identifier)
        title: Video title
        channel: Channel/author name
        thumbnail_url: Thumbnail image URL
        gear_items_found: Number of gear items extracted
        insights_found: Number of insights extracted
        extraction_summary: Full extraction outcome/report

    Returns:
        True if successful
    """
    params = {
        "url": url,
        "title": title,
    }

    set_parts = ["s.title = $title"]

    if channel:
        set_parts.append("s.channel = $channel")
        params["channel"] = channel

    if thumbnail_url:
        set_parts.append("s.thumbnailUrl = $thumbnail_url")
        params["thumbnail_url"] = thumbnail_url

    set_parts.append("s.gearItemsFound = $gear_items_found")
    params["gear_items_found"] = gear_items_found

    set_parts.append("s.insightsFound = $insights_found")
    params["insights_found"] = insights_found

    if extraction_summary:
        set_parts.append("s.extractionSummary = $extraction_summary")
        params["extraction_summary"] = extraction_summary

    set_clause = ", ".join(set_parts)

    query = f"""
    MERGE (s:VideoSource {{url: $url}})
    ON CREATE SET s.processedAt = datetime(), {set_clause}
    ON MATCH SET s.updatedAt = datetime(), {set_clause}
    RETURN s
    """

    return execute_cypher(query, params)


def link_gear_to_source(gear_name: str, brand: str, source_url: str) -> bool:
    """Create a relationship between a gear item and its source.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        source_url: URL of the source

    Returns:
        True if successful
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    MATCH (s:VideoSource {url: $url})
    MERGE (g)-[:EXTRACTED_FROM]->(s)
    """
    return execute_cypher(query, {"name": gear_name, "brand": brand, "url": source_url})


def get_all_video_sources(limit: int = 50) -> list[dict]:
    """Get all processed video sources, ordered by most recent.

    Args:
        limit: Maximum number of sources to return

    Returns:
        List of video source records
    """
    query = """
    MATCH (s:VideoSource)
    RETURN s.url as url, s.title as title, s.channel as channel,
           s.thumbnailUrl as thumbnail_url, s.processedAt as processed_at,
           s.gearItemsFound as gear_items_found, s.insightsFound as insights_found,
           s.extractionSummary as extraction_summary
    ORDER BY s.processedAt DESC
    LIMIT $limit
    """
    return execute_and_fetch(query, {"limit": limit})


def get_gear_from_source(source_url: str) -> list[dict]:
    """Get all gear items extracted from a specific source.

    Args:
        source_url: URL of the source

    Returns:
        List of gear items linked to this source
    """
    query = """
    MATCH (g:GearItem)-[:EXTRACTED_FROM]->(s:VideoSource {url: $url})
    RETURN g.name as name, g.brand as brand, g.category as category,
           g.weight_grams as weight_grams, g.price_usd as price_usd
    """
    return execute_and_fetch(query, {"url": source_url})

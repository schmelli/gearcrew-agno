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


def _is_connection_error(error_msg: str) -> bool:
    """Check if an error message indicates a connection problem."""
    connection_errors = ["chunk", "connection", "socket", "closed", "timeout", "broken pipe"]
    return any(err in error_msg.lower() for err in connection_errors)


def _reconnect_and_retry(func):
    """Decorator to retry database operations with reconnection on failure."""
    def wrapper(*args, **kwargs):
        global _memgraph
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e)
            if _is_connection_error(error_msg):
                logger.debug(f"Connection stale, reconnecting... ({error_msg[:50]})")
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
            error_msg = str(e)
            if attempt == 0 and _is_connection_error(error_msg):
                logger.debug(f"Connection stale, reconnecting... ({error_msg[:50]})")
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
            error_msg = str(e)
            if attempt == 0 and _is_connection_error(error_msg):
                logger.debug(f"Connection stale, reconnecting... ({error_msg[:50]})")
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
    description: Optional[str] = None,
    features: Optional[list[str]] = None,
    # Category-specific specs
    volume_liters: Optional[float] = None,  # Backpacks
    temp_rating_f: Optional[int] = None,  # Sleeping bags
    temp_rating_c: Optional[int] = None,  # Sleeping bags
    r_value: Optional[float] = None,  # Sleeping pads
    capacity_persons: Optional[int] = None,  # Tents
    packed_weight_grams: Optional[int] = None,  # Tents, bags
    packed_size: Optional[str] = None,  # Packed dimensions
    fill_power: Optional[int] = None,  # Down products
    fill_weight_grams: Optional[int] = None,  # Down products
    waterproof_rating: Optional[str] = None,  # Jackets, tents
    lumens: Optional[int] = None,  # Headlamps
    burn_time: Optional[str] = None,  # Stoves, headlamps
    fuel_type: Optional[str] = None,  # Stoves
    filter_type: Optional[str] = None,  # Water filters
    flow_rate: Optional[str] = None,  # Water filters
) -> bool:
    """Merge a gear item into the graph (create or update).

    Uses MERGE to prevent duplicates. Supports category-specific properties.

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
        description: Product description
        features: List of key features
        volume_liters: Volume in liters (backpacks)
        temp_rating_f: Temperature rating Fahrenheit (sleeping bags)
        temp_rating_c: Temperature rating Celsius (sleeping bags)
        r_value: Insulation R-value (sleeping pads)
        capacity_persons: Person capacity (tents)
        packed_weight_grams: Packed weight (tents, sleeping bags)
        packed_size: Packed dimensions as string
        fill_power: Down fill power (sleeping bags, jackets)
        fill_weight_grams: Down fill weight in grams
        waterproof_rating: Waterproof rating (tents, jackets)
        lumens: Light output (headlamps)
        burn_time: Burn time (stoves, headlamps)
        fuel_type: Fuel type (stoves)
        filter_type: Filter type (water filters)
        flow_rate: Flow rate (water filters)

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

    # Core properties
    optional_props = [
        ("weight_grams", weight_grams, "g.weight_grams"),
        ("price_usd", price_usd, "g.price_usd"),
        ("product_url", product_url, "g.productUrl"),
        ("image_url", image_url, "g.imageUrl"),
        ("materials", materials, "g.materials"),
        ("source_url", source_url, "g.sourceUrl"),
        ("description", description, "g.description"),
        ("features", features, "g.features"),
        # Category-specific
        ("volume_liters", volume_liters, "g.volumeLiters"),
        ("temp_rating_f", temp_rating_f, "g.tempRatingF"),
        ("temp_rating_c", temp_rating_c, "g.tempRatingC"),
        ("r_value", r_value, "g.rValue"),
        ("capacity_persons", capacity_persons, "g.capacityPersons"),
        ("packed_weight_grams", packed_weight_grams, "g.packedWeightGrams"),
        ("packed_size", packed_size, "g.packedSize"),
        ("fill_power", fill_power, "g.fillPower"),
        ("fill_weight_grams", fill_weight_grams, "g.fillWeightGrams"),
        ("waterproof_rating", waterproof_rating, "g.waterproofRating"),
        ("lumens", lumens, "g.lumens"),
        ("burn_time", burn_time, "g.burnTime"),
        ("fuel_type", fuel_type, "g.fuelType"),
        ("filter_type", filter_type, "g.filterType"),
        ("flow_rate", flow_rate, "g.flowRate"),
    ]

    for param_name, value, prop_path in optional_props:
        if value is not None:
            set_parts.append(f"{prop_path} = ${param_name}")
            params[param_name] = value

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


def find_potential_duplicates(name: str, brand: Optional[str] = None) -> list[dict]:
    """Find potential duplicate gear items using fuzzy matching.

    Searches for items with similar names, considering:
    - Exact matches (case-insensitive)
    - Substring matches (name contains search or vice versa)
    - Same brand with similar product names
    - Items in ProductFamily relationships

    Args:
        name: Product name to search for
        brand: Optional brand name for more targeted search

    Returns:
        List of potential matches with similarity info
    """
    # Extract key terms from the name (remove common words)
    name_lower = name.lower()
    stop_words = {"the", "a", "an", "and", "or", "for", "with", "ultralight", "lightweight"}
    name_terms = [w for w in name_lower.split() if w not in stop_words and len(w) > 2]

    results = []

    # Search for exact and substring matches
    query = """
    MATCH (g:GearItem)
    WHERE toLower(g.name) CONTAINS toLower($name)
       OR toLower($name) CONTAINS toLower(g.name)
    OPTIONAL MATCH (g)-[:IS_VARIANT_OF]->(pf:ProductFamily)
    OPTIONAL MATCH (b:OutdoorBrand)-[:MANUFACTURES_ITEM]->(g)
    RETURN g.name as name, g.brand as brand, g.category as category,
           g.weight_grams as weight, g.price_usd as price,
           pf.name as product_family,
           b.name as manufacturer,
           'substring_match' as match_type
    LIMIT 10
    """
    substring_matches = execute_and_fetch(query, {"name": name})
    results.extend(substring_matches)

    # If brand provided, also search for same brand products
    if brand:
        brand_query = """
        MATCH (g:GearItem)
        WHERE toLower(g.brand) = toLower($brand)
        OPTIONAL MATCH (g)-[:IS_VARIANT_OF]->(pf:ProductFamily)
        RETURN g.name as name, g.brand as brand, g.category as category,
               g.weight_grams as weight, g.price_usd as price,
               pf.name as product_family,
               'same_brand' as match_type
        LIMIT 10
        """
        brand_matches = execute_and_fetch(brand_query, {"brand": brand})
        # Add only if not already in results
        existing_names = {r["name"].lower() for r in results}
        for match in brand_matches:
            if match["name"].lower() not in existing_names:
                results.append(match)

    # Search ProductFamily nodes
    pf_query = """
    MATCH (pf:ProductFamily)
    WHERE toLower(pf.name) CONTAINS toLower($name)
       OR toLower($name) CONTAINS toLower(pf.name)
    OPTIONAL MATCH (g:GearItem)-[:IS_VARIANT_OF]->(pf)
    RETURN pf.name as product_family, collect(g.name) as variants,
           'product_family' as match_type
    LIMIT 5
    """
    pf_matches = execute_and_fetch(pf_query, {"name": name})
    for pf in pf_matches:
        results.append({
            "name": pf["product_family"],
            "brand": None,
            "category": "ProductFamily",
            "variants": pf.get("variants", []),
            "match_type": "product_family",
        })

    return results


def scan_for_duplicates(min_similarity: int = 2) -> list[dict]:
    """Scan the entire database for potential duplicate gear items.

    Groups items by similar names and identifies potential duplicates.

    Args:
        min_similarity: Minimum number of matching words to consider duplicate

    Returns:
        List of duplicate groups with items and recommendations
    """
    # Get all gear items
    query = """
    MATCH (g:GearItem)
    OPTIONAL MATCH (g)-[:IS_VARIANT_OF]->(pf:ProductFamily)
    RETURN g.name as name, g.brand as brand, g.category as category,
           g.weight_grams as weight, g.price_usd as price,
           pf.name as product_family,
           id(g) as node_id
    ORDER BY g.name
    """
    all_items = execute_and_fetch(query)

    if not all_items:
        return []

    # Group by normalized name tokens
    from collections import defaultdict
    import re

    def normalize_name(name: str) -> set:
        """Extract key tokens from a product name."""
        if not name:
            return set()
        # Remove common words and punctuation
        name_lower = name.lower()
        # Remove punctuation and split
        tokens = re.findall(r'[a-z0-9]+', name_lower)
        # Filter out very common words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'for', 'with', 'ultra',
                      'light', 'lightweight', 'ultralight', 'pro', 'plus', 'new'}
        return {t for t in tokens if t not in stop_words and len(t) > 1}

    def tokens_match(tokens1: set, tokens2: set, min_match: int) -> bool:
        """Check if two token sets have enough overlap."""
        if not tokens1 or not tokens2:
            return False
        common = tokens1 & tokens2
        return len(common) >= min_match

    # Find duplicate groups
    duplicate_groups = []
    processed = set()

    for i, item1 in enumerate(all_items):
        if i in processed:
            continue

        tokens1 = normalize_name(item1.get("name", ""))
        brand1 = (item1.get("brand") or "").lower()

        group = [item1]
        group_indices = {i}

        for j, item2 in enumerate(all_items):
            if j <= i or j in processed:
                continue

            tokens2 = normalize_name(item2.get("name", ""))
            brand2 = (item2.get("brand") or "").lower()

            # Check for match: same brand OR significant token overlap
            same_brand = brand1 and brand2 and brand1 == brand2
            token_overlap = tokens_match(tokens1, tokens2, min_similarity)

            # For same brand, require less token overlap
            if same_brand and tokens_match(tokens1, tokens2, 1):
                group.append(item2)
                group_indices.add(j)
            elif token_overlap:
                group.append(item2)
                group_indices.add(j)

        if len(group) > 1:
            # Determine the best canonical item (most complete data)
            def completeness_score(item):
                score = 0
                if item.get("brand"):
                    score += 2
                if item.get("weight"):
                    score += 1
                if item.get("price"):
                    score += 1
                if item.get("category"):
                    score += 1
                if item.get("product_family"):
                    score += 1
                return score

            group_sorted = sorted(group, key=completeness_score, reverse=True)
            canonical = group_sorted[0]
            duplicates = group_sorted[1:]

            duplicate_groups.append({
                "canonical": canonical,
                "duplicates": duplicates,
                "count": len(group),
                "recommendation": "merge" if len(group) <= 3 else "review",
            })

            processed.update(group_indices)

    # Sort by count (most duplicates first)
    duplicate_groups.sort(key=lambda x: x["count"], reverse=True)

    return duplicate_groups


def merge_gear_items(source_name: str, source_brand: str, target_name: str, target_brand: str) -> bool:
    """Merge a duplicate gear item into an existing one.

    Transfers all relationships from source to target and deletes source.

    Args:
        source_name: Name of the duplicate to remove
        source_brand: Brand of the duplicate
        target_name: Name of the item to keep
        target_brand: Brand of the item to keep

    Returns:
        True if successful
    """
    # Transfer relationships
    transfer_query = """
    MATCH (source:GearItem {name: $source_name, brand: $source_brand})
    MATCH (target:GearItem {name: $target_name, brand: $target_brand})

    // Transfer EXTRACTED_FROM relationships
    OPTIONAL MATCH (source)-[r1:EXTRACTED_FROM]->(vs:VideoSource)
    FOREACH (_ IN CASE WHEN r1 IS NOT NULL THEN [1] ELSE [] END |
        MERGE (target)-[:EXTRACTED_FROM]->(vs)
    )

    // Transfer HAS_TIP relationships
    OPTIONAL MATCH (source)-[r2:HAS_TIP]->(i:Insight)
    FOREACH (_ IN CASE WHEN r2 IS NOT NULL THEN [1] ELSE [] END |
        MERGE (target)-[:HAS_TIP]->(i)
    )

    // Delete the source node and its relationships
    DETACH DELETE source

    RETURN target.name as merged_into
    """
    results = execute_and_fetch(transfer_query, {
        "source_name": source_name,
        "source_brand": source_brand,
        "target_name": target_name,
        "target_brand": target_brand,
    })
    return len(results) > 0


# Glossary term functions

def merge_glossary_term(
    name: str,
    definition: str,
    category: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> bool:
    """Create or update a glossary term.

    Args:
        name: The term name (e.g., "Titanium", "Pertex", "tunnel tent")
        definition: Full definition of the term
        category: Category (material, technology, design, technique, concept)
        aliases: Alternative names or spellings

    Returns:
        True if successful
    """
    params = {
        "name": name,
        "definition": definition,
    }

    set_parts = ["g.definition = $definition"]

    if category:
        set_parts.append("g.category = $category")
        params["category"] = category

    if aliases:
        set_parts.append("g.aliases = $aliases")
        params["aliases"] = aliases

    set_clause = ", ".join(set_parts)

    query = f"""
    MERGE (g:GlossaryTerm {{name: $name}})
    ON CREATE SET g.createdAt = datetime(), {set_clause}
    ON MATCH SET g.updatedAt = datetime(), {set_clause}
    RETURN g
    """

    return execute_cypher(query, params)


def get_glossary_term(name: str) -> Optional[dict]:
    """Get a glossary term by name or alias.

    Args:
        name: Term name or alias to search for

    Returns:
        Term data if found, None otherwise
    """
    query = """
    MATCH (g:GlossaryTerm)
    WHERE toLower(g.name) = toLower($name)
       OR toLower($name) IN [alias IN g.aliases | toLower(alias)]
    RETURN g.name as name, g.definition as definition,
           g.category as category, g.aliases as aliases
    LIMIT 1
    """
    results = execute_and_fetch(query, {"name": name})
    return results[0] if results else None


def get_all_glossary_terms(category: Optional[str] = None) -> list[dict]:
    """Get all glossary terms, optionally filtered by category.

    Args:
        category: Optional category filter

    Returns:
        List of glossary terms
    """
    if category:
        query = """
        MATCH (g:GlossaryTerm)
        WHERE g.category = $category
        RETURN g.name as name, g.definition as definition,
               g.category as category, g.aliases as aliases
        ORDER BY g.name
        """
        return execute_and_fetch(query, {"category": category})
    else:
        query = """
        MATCH (g:GlossaryTerm)
        RETURN g.name as name, g.definition as definition,
               g.category as category, g.aliases as aliases
        ORDER BY g.name
        """
        return execute_and_fetch(query)


def link_gear_to_glossary_term(
    gear_name: str,
    gear_brand: str,
    term_name: str,
) -> bool:
    """Link a gear item to a glossary term.

    Args:
        gear_name: Name of the gear item
        gear_brand: Brand of the gear item
        term_name: Name of the glossary term

    Returns:
        True if successful
    """
    query = """
    MATCH (g:GearItem {name: $gear_name, brand: $gear_brand})
    MATCH (t:GlossaryTerm {name: $term_name})
    MERGE (g)-[:RELATES_TO]->(t)
    RETURN g.name as gear, t.name as term
    """
    results = execute_and_fetch(query, {
        "gear_name": gear_name,
        "gear_brand": gear_brand,
        "term_name": term_name,
    })
    return len(results) > 0


def find_gear_by_glossary_term(term_name: str) -> list[dict]:
    """Find all gear items related to a glossary term.

    Args:
        term_name: Name of the glossary term

    Returns:
        List of gear items linked to this term
    """
    query = """
    MATCH (g:GearItem)-[:RELATES_TO]->(t:GlossaryTerm)
    WHERE toLower(t.name) = toLower($term_name)
       OR toLower($term_name) IN [alias IN t.aliases | toLower(alias)]
    RETURN g.name as name, g.brand as brand, g.category as category,
           g.weight_grams as weight_grams
    ORDER BY g.name
    """
    return execute_and_fetch(query, {"term_name": term_name})


def import_glossary_terms(terms: list[dict]) -> dict:
    """Bulk import glossary terms from a list of dictionaries.

    Args:
        terms: List of term dictionaries with keys:
               - name (required)
               - definition (required)
               - category (optional)
               - aliases (optional list)

    Returns:
        Dictionary with import statistics
    """
    stats = {"created": 0, "updated": 0, "failed": 0}

    for term in terms:
        name = term.get("name")
        definition = term.get("definition")

        if not name or not definition:
            stats["failed"] += 1
            continue

        # Check if exists
        existing = get_glossary_term(name)

        success = merge_glossary_term(
            name=name,
            definition=definition,
            category=term.get("category"),
            aliases=term.get("aliases"),
        )

        if success:
            if existing:
                stats["updated"] += 1
            else:
                stats["created"] += 1
        else:
            stats["failed"] += 1

    return stats


# ============================================================================
# Data Enrichment Functions
# ============================================================================

# Priority categories for enrichment (in order of importance)
PRIORITY_CATEGORIES = [
    "tent",
    "backpack",
    "sleeping_bag",
    "sleeping_pad",
    "stove",
    "water_filter",
    "headlamp",
    "jacket",
    "boots",
    "trekking_poles",
]


def calculate_completeness_score(item: dict) -> float:
    """Calculate a data completeness score for a gear item.

    Score is 0.0 to 1.0 based on how many key fields are populated.

    Args:
        item: Gear item dictionary

    Returns:
        Completeness score (0.0 = empty, 1.0 = fully complete)
    """
    # Core fields (weighted higher)
    core_fields = [
        ("weight_grams", 2),
        ("description", 2),
        ("price_usd", 1),
        ("materials", 1),
        ("features", 1),
        ("productUrl", 1),
    ]

    # Category-specific fields
    category = (item.get("category") or "").lower()
    category_fields = []

    if "backpack" in category:
        category_fields = [("volumeLiters", 2)]
    elif "sleeping_bag" in category or "sleeping bag" in category:
        category_fields = [("tempRatingF", 2), ("fillPower", 1)]
    elif "sleeping_pad" in category or "sleeping pad" in category:
        category_fields = [("rValue", 2)]
    elif "tent" in category:
        category_fields = [("capacityPersons", 2), ("waterproofRating", 1)]
    elif "headlamp" in category:
        category_fields = [("lumens", 2), ("burnTime", 1)]
    elif "stove" in category:
        category_fields = [("fuelType", 2)]
    elif "filter" in category:
        category_fields = [("filterType", 2), ("flowRate", 1)]

    all_fields = core_fields + category_fields
    total_weight = sum(w for _, w in all_fields)

    score = 0
    for field, weight in all_fields:
        value = item.get(field)
        if value is not None and value != "" and value != []:
            score += weight

    return score / total_weight if total_weight > 0 else 0.0


def get_items_needing_enrichment(
    limit: int = 50,
    min_score: float = 0.0,
    max_score: float = 0.5,
    category: Optional[str] = None,
) -> list[dict]:
    """Find gear items that need data enrichment.

    Returns items with low completeness scores, prioritized by category.

    Args:
        limit: Maximum items to return
        min_score: Minimum completeness score (for pagination)
        max_score: Maximum completeness score (items above this are "complete")
        category: Optional category filter

    Returns:
        List of gear items with their completeness scores
    """
    category_filter = ""
    params = {"limit": limit}

    if category:
        category_filter = "AND toLower(g.category) CONTAINS toLower($category)"
        params["category"] = category

    query = f"""
    MATCH (g:GearItem)
    WHERE g.name IS NOT NULL AND g.brand IS NOT NULL
    {category_filter}
    RETURN g.name as name,
           g.brand as brand,
           g.category as category,
           g.weight_grams as weight_grams,
           g.price_usd as price_usd,
           g.description as description,
           g.materials as materials,
           g.features as features,
           g.productUrl as productUrl,
           g.volumeLiters as volumeLiters,
           g.tempRatingF as tempRatingF,
           g.rValue as rValue,
           g.capacityPersons as capacityPersons,
           g.lumens as lumens,
           g.fuelType as fuelType,
           g.filterType as filterType,
           g.fillPower as fillPower,
           g.waterproofRating as waterproofRating,
           g.burnTime as burnTime,
           g.flowRate as flowRate,
           g.enrichedAt as enrichedAt,
           id(g) as node_id
    ORDER BY g.createdAt DESC
    LIMIT {limit * 3}
    """

    results = execute_and_fetch(query, params)

    # Calculate scores and filter
    scored_items = []
    for item in results:
        score = calculate_completeness_score(item)
        if min_score <= score <= max_score:
            item["completeness_score"] = score
            scored_items.append(item)

    # Sort by category priority, then by score (lowest first)
    def sort_key(item):
        cat = (item.get("category") or "other").lower()
        # Find priority index (lower = higher priority)
        try:
            priority = PRIORITY_CATEGORIES.index(cat)
        except ValueError:
            priority = 100  # Unknown categories last

        return (priority, item.get("completeness_score", 1.0))

    scored_items.sort(key=sort_key)

    return scored_items[:limit]


def get_enrichment_stats() -> dict:
    """Get statistics on data enrichment status.

    Returns:
        Dictionary with enrichment statistics
    """
    query = """
    MATCH (g:GearItem)
    WITH g,
         CASE WHEN g.weight_grams IS NOT NULL THEN 1 ELSE 0 END as has_weight,
         CASE WHEN g.description IS NOT NULL AND g.description <> '' THEN 1 ELSE 0 END as has_desc,
         CASE WHEN g.price_usd IS NOT NULL THEN 1 ELSE 0 END as has_price,
         CASE WHEN g.materials IS NOT NULL THEN 1 ELSE 0 END as has_materials,
         CASE WHEN g.features IS NOT NULL THEN 1 ELSE 0 END as has_features,
         CASE WHEN g.enrichedAt IS NOT NULL THEN 1 ELSE 0 END as enriched
    RETURN count(g) as total,
           sum(has_weight) as with_weight,
           sum(has_desc) as with_description,
           sum(has_price) as with_price,
           sum(has_materials) as with_materials,
           sum(has_features) as with_features,
           sum(enriched) as enriched_count
    """
    results = execute_and_fetch(query)

    if results:
        r = results[0]
        total = r.get("total", 0)
        return {
            "total_items": total,
            "with_weight": r.get("with_weight", 0),
            "with_description": r.get("with_description", 0),
            "with_price": r.get("with_price", 0),
            "with_materials": r.get("with_materials", 0),
            "with_features": r.get("with_features", 0),
            "enriched_count": r.get("enriched_count", 0),
            "weight_pct": round(r.get("with_weight", 0) / total * 100, 1) if total else 0,
            "desc_pct": round(r.get("with_description", 0) / total * 100, 1) if total else 0,
            "price_pct": round(r.get("with_price", 0) / total * 100, 1) if total else 0,
        }

    return {"total_items": 0}


def mark_item_enriched(name: str, brand: str) -> bool:
    """Mark a gear item as having been enriched.

    Args:
        name: Item name
        brand: Item brand

    Returns:
        True if successful
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    SET g.enrichedAt = datetime()
    RETURN g.name
    """
    results = execute_and_fetch(query, {"name": name, "brand": brand})
    return len(results) > 0


# ============================================================================
# Field Provenance Tracking
# ============================================================================


def add_field_provenance(
    gear_name: str,
    brand: str,
    field_name: str,
    source_url: str,
    confidence: float = 1.0,
    extracted_at: Optional[str] = None,
) -> bool:
    """Track which source provided a specific field value.

    Creates a FieldSource node linked to the gear item to track provenance.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        field_name: Name of the field (e.g., "weight_grams", "price_usd")
        source_url: URL where this data was found
        confidence: Confidence score 0.0-1.0
        extracted_at: ISO timestamp (defaults to now)

    Returns:
        True if successful
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    MERGE (fs:FieldSource {
        gearName: $name,
        gearBrand: $brand,
        fieldName: $field_name
    })
    ON CREATE SET
        fs.sourceUrl = $source_url,
        fs.confidence = $confidence,
        fs.extractedAt = datetime()
    ON MATCH SET
        fs.sourceUrl = CASE
            WHEN $confidence > fs.confidence THEN $source_url
            ELSE fs.sourceUrl
        END,
        fs.confidence = CASE
            WHEN $confidence > fs.confidence THEN $confidence
            ELSE fs.confidence
        END,
        fs.updatedAt = datetime()
    MERGE (g)-[:HAS_FIELD_SOURCE]->(fs)
    RETURN fs.fieldName
    """
    results = execute_and_fetch(query, {
        "name": gear_name,
        "brand": brand,
        "field_name": field_name,
        "source_url": source_url,
        "confidence": confidence,
    })
    return len(results) > 0


def get_field_provenance(gear_name: str, brand: str) -> list[dict]:
    """Get all field provenance data for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        List of field source records with field name, source URL, confidence
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})-[:HAS_FIELD_SOURCE]->(fs:FieldSource)
    RETURN fs.fieldName as field,
           fs.sourceUrl as source_url,
           fs.confidence as confidence,
           fs.extractedAt as extracted_at
    ORDER BY fs.fieldName
    """
    return execute_and_fetch(query, {"name": gear_name, "brand": brand})


def get_source_contributions(source_url: str) -> list[dict]:
    """Get all data contributions from a specific source.

    Args:
        source_url: The source URL to check

    Returns:
        List of gear items and fields contributed by this source
    """
    query = """
    MATCH (fs:FieldSource {sourceUrl: $url})
    RETURN fs.gearName as gear_name,
           fs.gearBrand as brand,
           collect(fs.fieldName) as fields_contributed
    """
    return execute_and_fetch(query, {"url": source_url})


# ============================================================================
# Dynamic Attributes (Flexible Property Storage)
# ============================================================================


def set_gear_attribute(
    gear_name: str,
    brand: str,
    attr_name: str,
    attr_value: Any,
    source_url: Optional[str] = None,
) -> bool:
    """Set a dynamic attribute on a gear item.

    Use this for non-standard properties that aren't part of the schema.
    Attributes are stored in a flexible map.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        attr_name: Attribute name (e.g., "color_options", "warranty_years")
        attr_value: Attribute value (string, number, or list)
        source_url: Optional source URL for provenance

    Returns:
        True if successful
    """
    # Serialize value if it's a list
    if isinstance(attr_value, list):
        import json
        attr_value = json.dumps(attr_value)

    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    SET g[$attr_name] = $attr_value
    RETURN g.name
    """
    success = execute_cypher(query, {
        "name": gear_name,
        "brand": brand,
        "attr_name": attr_name,
        "attr_value": attr_value,
    })

    # Track provenance if source provided
    if success and source_url:
        add_field_provenance(gear_name, brand, attr_name, source_url)

    return success


def get_gear_attributes(gear_name: str, brand: str) -> dict:
    """Get all attributes of a gear item including dynamic ones.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        Dictionary of all properties on the gear item
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    RETURN properties(g) as props
    """
    results = execute_and_fetch(query, {"name": gear_name, "brand": brand})
    return results[0]["props"] if results else {}


# ============================================================================
# Comparisons and Alternatives
# ============================================================================


def save_gear_comparison(
    gear1_name: str,
    gear1_brand: str,
    gear2_name: str,
    gear2_brand: str,
    comparison_type: str,
    notes: Optional[str] = None,
    winner: Optional[str] = None,
    source_url: Optional[str] = None,
) -> bool:
    """Save a comparison between two gear items.

    Args:
        gear1_name: First item name
        gear1_brand: First item brand
        gear2_name: Second item name
        gear2_brand: Second item brand
        comparison_type: Type of comparison (weight, price, durability, etc.)
        notes: Comparison notes/details
        winner: Which item "wins" this comparison (optional)
        source_url: Where this comparison was found

    Returns:
        True if successful
    """
    query = """
    MATCH (g1:GearItem {name: $name1, brand: $brand1})
    MATCH (g2:GearItem {name: $name2, brand: $brand2})
    MERGE (g1)-[c:COMPARED_TO {comparisonType: $comp_type}]->(g2)
    SET c.notes = $notes,
        c.winner = $winner,
        c.sourceUrl = $source_url,
        c.updatedAt = datetime()
    RETURN g1.name, g2.name
    """
    results = execute_and_fetch(query, {
        "name1": gear1_name,
        "brand1": gear1_brand,
        "name2": gear2_name,
        "brand2": gear2_brand,
        "comp_type": comparison_type,
        "notes": notes,
        "winner": winner,
        "source_url": source_url,
    })
    return len(results) > 0


def save_gear_alternative(
    gear_name: str,
    brand: str,
    alternative_name: str,
    alternative_brand: str,
    reason: Optional[str] = None,
    source_url: Optional[str] = None,
) -> bool:
    """Mark one gear item as an alternative to another.

    Args:
        gear_name: The primary item name
        brand: Primary item brand
        alternative_name: The alternative item name
        alternative_brand: Alternative item brand
        reason: Why this is an alternative (cheaper, lighter, etc.)
        source_url: Where this was mentioned

    Returns:
        True if successful
    """
    query = """
    MATCH (g1:GearItem {name: $name1, brand: $brand1})
    MATCH (g2:GearItem {name: $name2, brand: $brand2})
    MERGE (g1)-[a:HAS_ALTERNATIVE]->(g2)
    SET a.reason = $reason,
        a.sourceUrl = $source_url,
        a.updatedAt = datetime()
    RETURN g1.name, g2.name
    """
    results = execute_and_fetch(query, {
        "name1": gear_name,
        "brand1": brand,
        "name2": alternative_name,
        "brand2": alternative_brand,
        "reason": reason,
        "source_url": source_url,
    })
    return len(results) > 0


def get_gear_comparisons(gear_name: str, brand: str) -> list[dict]:
    """Get all comparisons involving a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        List of comparison records
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    OPTIONAL MATCH (g)-[c:COMPARED_TO]->(other:GearItem)
    OPTIONAL MATCH (g)<-[c2:COMPARED_TO]-(other2:GearItem)
    WITH g,
         collect(DISTINCT {
            otherItem: other.name,
            otherBrand: other.brand,
            comparisonType: c.comparisonType,
            notes: c.notes,
            winner: c.winner,
            direction: 'outgoing'
         }) as outgoing,
         collect(DISTINCT {
            otherItem: other2.name,
            otherBrand: other2.brand,
            comparisonType: c2.comparisonType,
            notes: c2.notes,
            winner: c2.winner,
            direction: 'incoming'
         }) as incoming
    RETURN outgoing + incoming as comparisons
    """
    results = execute_and_fetch(query, {"name": gear_name, "brand": brand})
    if results and results[0].get("comparisons"):
        # Filter out null entries
        return [c for c in results[0]["comparisons"] if c.get("otherItem")]
    return []


def get_gear_alternatives(gear_name: str, brand: str) -> list[dict]:
    """Get all alternatives for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        List of alternative items
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})-[a:HAS_ALTERNATIVE]->(alt:GearItem)
    RETURN alt.name as name, alt.brand as brand, alt.category as category,
           a.reason as reason, a.sourceUrl as source_url
    """
    return execute_and_fetch(query, {"name": gear_name, "brand": brand})


# ============================================================================
# Opinion/Review Tracking
# ============================================================================


def save_gear_opinion(
    gear_name: str,
    brand: str,
    opinion_type: str,
    content: str,
    sentiment: str = "neutral",
    author: Optional[str] = None,
    source_url: Optional[str] = None,
) -> bool:
    """Save an opinion or review about a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        opinion_type: Type (pro, con, tip, warning, experience)
        content: The opinion/review content
        sentiment: positive, negative, or neutral
        author: Who expressed this opinion (reviewer name, channel, etc.)
        source_url: Where this was found

    Returns:
        True if successful
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    CREATE (o:Opinion {
        opinionType: $opinion_type,
        content: $content,
        sentiment: $sentiment,
        author: $author,
        sourceUrl: $source_url,
        createdAt: datetime()
    })
    CREATE (g)-[:HAS_OPINION]->(o)
    RETURN o.content
    """
    results = execute_and_fetch(query, {
        "name": gear_name,
        "brand": brand,
        "opinion_type": opinion_type,
        "content": content,
        "sentiment": sentiment,
        "author": author,
        "source_url": source_url,
    })
    return len(results) > 0


def get_gear_opinions(
    gear_name: str,
    brand: str,
    opinion_type: Optional[str] = None,
) -> list[dict]:
    """Get opinions/reviews for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        opinion_type: Optional filter (pro, con, tip, warning, experience)

    Returns:
        List of opinion records
    """
    type_filter = ""
    params = {"name": gear_name, "brand": brand}

    if opinion_type:
        type_filter = "AND o.opinionType = $opinion_type"
        params["opinion_type"] = opinion_type

    query = f"""
    MATCH (g:GearItem {{name: $name, brand: $brand}})-[:HAS_OPINION]->(o:Opinion)
    WHERE true {type_filter}
    RETURN o.opinionType as type,
           o.content as content,
           o.sentiment as sentiment,
           o.author as author,
           o.sourceUrl as source_url
    ORDER BY o.createdAt DESC
    """
    return execute_and_fetch(query, params)


# ============================================================================
# Usage Context
# ============================================================================


def save_usage_context(
    gear_name: str,
    brand: str,
    context_type: str,
    description: str,
    source_url: Optional[str] = None,
) -> bool:
    """Save a usage context for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        context_type: Type (terrain, weather, activity, skill_level, trip_type)
        description: Description of the context
        source_url: Where this was mentioned

    Returns:
        True if successful
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    MERGE (c:UsageContext {contextType: $context_type, description: $description})
    MERGE (g)-[r:SUITABLE_FOR]->(c)
    SET r.sourceUrl = $source_url,
        r.updatedAt = datetime()
    RETURN c.description
    """
    results = execute_and_fetch(query, {
        "name": gear_name,
        "brand": brand,
        "context_type": context_type,
        "description": description,
        "source_url": source_url,
    })
    return len(results) > 0


def get_gear_usage_contexts(gear_name: str, brand: str) -> list[dict]:
    """Get all usage contexts for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        List of usage context records
    """
    query = """
    MATCH (g:GearItem {name: $name, brand: $brand})-[r:SUITABLE_FOR]->(c:UsageContext)
    RETURN c.contextType as context_type,
           c.description as description,
           r.sourceUrl as source_url
    """
    return execute_and_fetch(query, {"name": gear_name, "brand": brand})

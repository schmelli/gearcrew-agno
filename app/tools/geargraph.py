"""GearGraph database tools for the agent.

These tools allow the agent to interact with the Memgraph graph database
for querying, verifying, and writing gear data.
"""

import os
import json
import logging
from typing import Optional

from rdflib import Graph, RDF, RDFS, OWL

from app.db.memgraph import (
    get_memgraph,
    execute_and_fetch,
    execute_cypher,
    find_similar_nodes,
    check_node_exists,
    get_graph_stats,
    merge_gear_item,
    merge_insight,
    check_source_exists,
    save_video_source,
    link_gear_to_source,
    get_all_video_sources,
    get_gear_from_source,
)

logger = logging.getLogger(__name__)


def find_similar_gear(name: str, label: str = "GearItem") -> str:
    """Search the GearGraph for products with similar names.

    Use this tool to check if a product already exists before adding it,
    to prevent duplicates in the database.

    Args:
        name: Name of the product to search for
        label: Node type to search (GearItem, OutdoorBrand, ProductFamily)

    Returns:
        JSON string with matching nodes or message if none found
    """
    try:
        results = find_similar_nodes(name, label, limit=5)

        if not results:
            return f"No similar nodes to '{name}' found in the graph."

        return f"Found existing nodes: {json.dumps(results, default=str)}"
    except Exception as e:
        logger.error(f"Error searching for similar nodes: {e}")
        return f"Error searching graph: {str(e)}"


def check_gear_exists(name: str, brand: Optional[str] = None) -> str:
    """Check if a specific gear item exists in the database.

    Args:
        name: Product name to check
        brand: Optional brand name for more precise matching

    Returns:
        JSON with node data if found, or message if not found
    """
    try:
        result = check_node_exists(name, "GearItem", brand)

        if result:
            return f"Product found: {json.dumps(result, default=str)}"
        return f"No exact match found for '{name}'" + (f" by {brand}" if brand else "")
    except Exception as e:
        logger.error(f"Error checking node existence: {e}")
        return f"Error checking graph: {str(e)}"


def get_graph_statistics() -> str:
    """Get statistics about the GearGraph database.

    Returns counts of nodes by type, relationships by type, and totals.
    Useful for understanding the current state of the knowledge base.

    Returns:
        JSON string with graph statistics
    """
    try:
        stats = get_graph_stats()
        return json.dumps(stats, indent=2)
    except Exception as e:
        logger.error(f"Error getting graph stats: {e}")
        return f"Error fetching statistics: {str(e)}"


def validate_ontology_label(entity_type: str, check_type: str = "label") -> str:
    """Validate if a node label or relationship type is in the ontology.

    Use this before creating new nodes to ensure they conform to the
    GearGraph ontology schema.

    Args:
        entity_type: The label or relationship type to check
        check_type: Either 'label' for node types or 'relationship' for edges

    Returns:
        Validation result message
    """
    # Standard relationship types that are always valid
    standard_relationships = {
        "MANUFACTURES": "Brand manufactures ProductFamily",
        "MANUFACTURES_ITEM": "Brand manufactures GearItem",
        "PRODUCED_BY": "Product produced by Brand (reverse)",
        "HAS_TIP": "Product has Insight tip",
        "VARIANT_OF": "GearItem is variant of ProductFamily",
        "SIMILAR_TO": "Product is similar to another product",
        "BELONGS_TO": "Item belongs to Category",
    }

    try:
        if check_type == "relationship":
            upper_type = entity_type.upper()
            if upper_type in standard_relationships:
                return (
                    f"VALID RELATIONSHIP: '{upper_type}' - "
                    f"{standard_relationships[upper_type]}"
                )
            valid_rels = ", ".join(standard_relationships.keys())
            return (
                f"WARNING: '{entity_type}' is not a standard relationship. "
                f"Standard relationships are: {valid_rels}"
            )

        # Check against ontology file for labels
        ontology_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "geargraph_ontology.ttl",
        )

        if not os.path.exists(ontology_path):
            return "Warning: Ontology file not found. Assuming valid."

        g = Graph()
        g.parse(ontology_path, format="turtle")

        # Query for classes with matching label
        query = f"""
        SELECT ?subject WHERE {{
            ?subject a owl:Class ;
                     rdfs:label ?label .
            FILTER(LCASE(STR(?label)) = LCASE("{entity_type}"))
        }}
        """
        results = g.query(query)

        if len(results) > 0:
            return f"VALID: '{entity_type}' exists in the GearGraph ontology."
        return f"INVALID: '{entity_type}' not found in the ontology."

    except Exception as e:
        logger.error(f"Ontology validation error: {e}")
        return f"Ontology check error: {str(e)}"


def save_gear_to_graph(
    name: str,
    brand: str,
    category: str,
    weight_grams: Optional[int] = None,
    price_usd: Optional[float] = None,
    product_url: Optional[str] = None,
    image_url: Optional[str] = None,
    materials: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Save a gear item to the GearGraph database.

    Uses MERGE to prevent duplicates - will update existing records.

    Args:
        name: Product name (required)
        brand: Brand/manufacturer name (required)
        category: Gear category (backpack, tent, sleeping_bag, etc.)
        weight_grams: Weight in grams
        price_usd: Price in USD
        product_url: Official product page URL
        image_url: Product image URL
        materials: Comma-separated list of materials
        source_url: URL where this info was found

    Returns:
        Success or error message
    """
    try:
        # Convert materials string to list if provided
        materials_list = None
        if materials:
            materials_list = [m.strip() for m in materials.split(",")]

        success = merge_gear_item(
            name=name,
            brand=brand,
            category=category,
            weight_grams=weight_grams,
            price_usd=price_usd,
            product_url=product_url,
            image_url=image_url,
            materials=materials_list,
            source_url=source_url,
        )

        if success:
            return f"Successfully saved '{name}' by {brand} to GearGraph."
        return f"Failed to save '{name}' to GearGraph."

    except Exception as e:
        logger.error(f"Error saving gear to graph: {e}")
        return f"Error saving to graph: {str(e)}"


def save_insight_to_graph(
    summary: str,
    content: str,
    category: Optional[str] = None,
    related_product: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Save a gear insight/tip to the GearGraph database.

    Args:
        summary: Short summary of the insight (required)
        content: Full insight content (required)
        category: Insight category (e.g., "Weight Savings", "Durability")
        related_product: Product name this insight relates to
        source_url: URL where this insight was found

    Returns:
        Success or error message
    """
    try:
        success = merge_insight(
            summary=summary,
            content=content,
            category=category,
            related_product=related_product,
            source_url=source_url,
        )

        if success:
            msg = f"Successfully saved insight: '{summary}'"
            if related_product:
                msg += f" (linked to {related_product})"
            return msg
        return f"Failed to save insight to GearGraph."

    except Exception as e:
        logger.error(f"Error saving insight to graph: {e}")
        return f"Error saving insight: {str(e)}"


def search_graph(query: str, limit: int = 10) -> str:
    """Search the GearGraph for products, brands, or insights.

    Performs a case-insensitive search across multiple node types.

    Args:
        query: Search term
        limit: Maximum number of results

    Returns:
        JSON string with search results
    """
    try:
        cypher_query = f"""
        MATCH (n)
        WHERE (n:GearItem OR n:OutdoorBrand OR n:ProductFamily OR n:Insight)
          AND (toLower(n.name) CONTAINS toLower($query)
               OR toLower(toString(n.brand)) CONTAINS toLower($query)
               OR toLower(toString(n.summary)) CONTAINS toLower($query))
        RETURN n.name as name, labels(n)[0] as type, n.brand as brand,
               n.weight_grams as weight, n.productUrl as url
        LIMIT $limit
        """

        results = execute_and_fetch(cypher_query, {"query": query, "limit": limit})

        if not results:
            return f"No results found for '{query}'"

        return f"Search results: {json.dumps(results, default=str)}"

    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Search error: {str(e)}"


def check_video_already_processed(url: str) -> str:
    """Check if a video/source URL has already been analyzed.

    Use this BEFORE fetching content to avoid re-processing videos.

    Args:
        url: The YouTube or webpage URL to check

    Returns:
        JSON with source data if already processed, or message if not found
    """
    try:
        result = check_source_exists(url)

        if result:
            return (
                f"ALREADY PROCESSED: This video was analyzed on {result.get('processed_at', 'unknown date')}. "
                f"Found {result.get('gear_items_found', 0)} gear items and {result.get('insights_found', 0)} insights. "
                f"Title: {result.get('title', 'Unknown')} by {result.get('channel', 'Unknown')}. "
                f"Use get_previous_extraction_summary to see the full analysis."
            )
        return f"NEW SOURCE: '{url}' has not been processed before. Proceed with extraction."

    except Exception as e:
        logger.error(f"Error checking source: {e}")
        return f"Error checking source: {str(e)}"


def get_previous_extraction_summary(url: str) -> str:
    """Get the full extraction summary from a previously processed source.

    Args:
        url: The source URL to get the summary for

    Returns:
        The extraction summary or error message
    """
    try:
        result = check_source_exists(url)

        if not result:
            return f"No previous extraction found for '{url}'"

        summary = result.get("extraction_summary", "No summary available")
        gear_items = get_gear_from_source(url)

        output = f"## Previous Extraction for: {result.get('title', 'Unknown')}\n\n"
        output += f"**Channel:** {result.get('channel', 'Unknown')}\n"
        output += f"**Processed:** {result.get('processed_at', 'Unknown')}\n"
        output += f"**Gear Items Found:** {result.get('gear_items_found', 0)}\n"
        output += f"**Insights Found:** {result.get('insights_found', 0)}\n\n"

        if gear_items:
            output += "### Extracted Gear:\n"
            for item in gear_items:
                output += f"- **{item.get('name')}** by {item.get('brand')} ({item.get('category', 'unknown')})\n"

        output += f"\n### Full Summary:\n{summary}"

        return output

    except Exception as e:
        logger.error(f"Error getting extraction summary: {e}")
        return f"Error: {str(e)}"


def save_extraction_result(
    url: str,
    title: str,
    channel: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    gear_items_found: int = 0,
    insights_found: int = 0,
    extraction_summary: str = "",
) -> str:
    """Save the extraction result for a processed video/source.

    Call this AFTER completing extraction to record what was found.

    Args:
        url: The source URL
        title: Video/page title
        channel: Channel or author name
        thumbnail_url: Thumbnail image URL
        gear_items_found: Number of gear items extracted
        insights_found: Number of insights extracted
        extraction_summary: Full markdown summary of what was extracted

    Returns:
        Success or error message
    """
    try:
        success = save_video_source(
            url=url,
            title=title,
            channel=channel,
            thumbnail_url=thumbnail_url,
            gear_items_found=gear_items_found,
            insights_found=insights_found,
            extraction_summary=extraction_summary,
        )

        if success:
            return f"Successfully saved extraction result for '{title}'"
        return "Failed to save extraction result"

    except Exception as e:
        logger.error(f"Error saving extraction result: {e}")
        return f"Error: {str(e)}"


def link_extracted_gear_to_source(gear_name: str, brand: str, source_url: str) -> str:
    """Link a gear item to the source it was extracted from.

    Call this after saving both the gear item and the source.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        source_url: URL of the source

    Returns:
        Success or error message
    """
    try:
        success = link_gear_to_source(gear_name, brand, source_url)

        if success:
            return f"Linked '{gear_name}' to source"
        return f"Failed to link gear to source"

    except Exception as e:
        logger.error(f"Error linking gear to source: {e}")
        return f"Error: {str(e)}"


def execute_read_query(cypher: str) -> str:
    """Execute a read-only Cypher query against GearGraph.

    Only MATCH and RETURN queries are allowed for safety.

    Args:
        cypher: Cypher query to execute

    Returns:
        Query results as JSON or error message
    """
    # Safety check - only allow read queries
    query_upper = cypher.upper().strip()
    forbidden = ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP", "DETACH"]

    for keyword in forbidden:
        if keyword in query_upper:
            return f"Error: Write operation '{keyword}' not allowed. Use save_gear_to_graph instead."

    try:
        results = execute_and_fetch(cypher)
        return json.dumps(results, default=str, indent=2)
    except Exception as e:
        logger.error(f"Query execution error: {e}")
        return f"Query error: {str(e)}"

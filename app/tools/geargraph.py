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
    find_potential_duplicates,
    merge_gear_items,
    scan_for_duplicates,
    # Glossary functions
    merge_glossary_term,
    get_glossary_term,
    get_all_glossary_terms,
    link_gear_to_glossary_term,
    find_gear_by_glossary_term,
    import_glossary_terms,
    # Provenance and extended data functions
    add_field_provenance,
    get_field_provenance,
    set_gear_attribute,
    get_gear_attributes,
    save_gear_comparison,
    save_gear_alternative,
    get_gear_comparisons,
    get_gear_alternatives,
    save_gear_opinion,
    get_gear_opinions,
    save_usage_context,
    get_gear_usage_contexts,
)

logger = logging.getLogger(__name__)


def find_similar_gear(name: str, brand: Optional[str] = None) -> str:
    """Search for potential duplicate gear items before saving.

    **CRITICAL: You MUST call this BEFORE saving any gear item to prevent duplicates.**

    This tool searches for:
    - Exact name matches (case-insensitive)
    - Substring matches (e.g., "BRS-3000T" matches "BRS 3000T Ultralight Stove")
    - Same brand products (to identify product families)
    - Existing ProductFamily nodes

    Args:
        name: Name of the product to search for
        brand: Brand name (highly recommended for accurate matching)

    Returns:
        Detailed report of potential duplicates with recommendations
    """
    try:
        results = find_potential_duplicates(name, brand)

        if not results:
            return (
                f"NO DUPLICATES FOUND for '{name}'" +
                (f" by {brand}" if brand else "") +
                ". Safe to create new GearItem."
            )

        # Format results for the agent
        output = [
            f"**POTENTIAL DUPLICATES FOUND** for '{name}'" +
            (f" by {brand}" if brand else "") + ":\n"
        ]

        for i, match in enumerate(results, 1):
            match_type = match.get("match_type", "unknown")
            if match_type == "product_family":
                output.append(
                    f"{i}. PRODUCT FAMILY: '{match['name']}'\n"
                    f"   Existing variants: {match.get('variants', [])}\n"
                    f"   -> Consider linking to this family instead of creating new item"
                )
            else:
                output.append(
                    f"{i}. {match.get('name', 'Unknown')} by {match.get('brand', 'Unknown brand')}\n"
                    f"   Category: {match.get('category', 'unknown')}\n"
                    f"   Weight: {match.get('weight', 'N/A')}g, Price: ${match.get('price', 'N/A')}\n"
                    f"   Match type: {match_type}"
                )
                if match.get("product_family"):
                    output.append(f"   Part of family: {match['product_family']}")

        output.append("\n**DECISION REQUIRED:**")
        output.append("- If this is THE SAME PRODUCT: Do NOT create a new entry")
        output.append("- If this is a VARIANT: Link to existing ProductFamily")
        output.append("- If truly NEW: Proceed with save_gear_to_graph")

        return "\n".join(output)

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
    description: Optional[str] = None,
    features: Optional[str] = None,
    # Category-specific specs (pass as needed based on category)
    volume_liters: Optional[float] = None,
    temp_rating_f: Optional[int] = None,
    temp_rating_c: Optional[int] = None,
    r_value: Optional[float] = None,
    capacity_persons: Optional[int] = None,
    packed_weight_grams: Optional[int] = None,
    packed_size: Optional[str] = None,
    fill_power: Optional[int] = None,
    fill_weight_grams: Optional[int] = None,
    waterproof_rating: Optional[str] = None,
    lumens: Optional[int] = None,
    burn_time: Optional[str] = None,
    fuel_type: Optional[str] = None,
    filter_type: Optional[str] = None,
    flow_rate: Optional[str] = None,
) -> str:
    """Save a gear item to the GearGraph database with full specifications.

    Uses MERGE to prevent duplicates - will update existing records.
    Pass category-specific parameters based on the gear type.

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
        description: Product description
        features: Comma-separated list of key features

        Category-specific (use based on gear type):
        - Backpacks: volume_liters
        - Sleeping bags: temp_rating_f, temp_rating_c, fill_power, fill_weight_grams
        - Sleeping pads: r_value
        - Tents: capacity_persons, packed_weight_grams, packed_size, waterproof_rating
        - Headlamps: lumens, burn_time
        - Stoves: fuel_type, burn_time
        - Water filters: filter_type, flow_rate

    Returns:
        Success or error message
    """
    try:
        # Convert comma-separated strings to lists
        materials_list = None
        if materials:
            materials_list = [m.strip() for m in materials.split(",")]

        features_list = None
        if features:
            features_list = [f.strip() for f in features.split(",")]

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
            description=description,
            features=features_list,
            volume_liters=volume_liters,
            temp_rating_f=temp_rating_f,
            temp_rating_c=temp_rating_c,
            r_value=r_value,
            capacity_persons=capacity_persons,
            packed_weight_grams=packed_weight_grams,
            packed_size=packed_size,
            fill_power=fill_power,
            fill_weight_grams=fill_weight_grams,
            waterproof_rating=waterproof_rating,
            lumens=lumens,
            burn_time=burn_time,
            fuel_type=fuel_type,
            filter_type=filter_type,
            flow_rate=flow_rate,
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


def merge_duplicate_gear(
    duplicate_name: str,
    duplicate_brand: str,
    canonical_name: str,
    canonical_brand: str,
) -> str:
    """Merge a duplicate gear item into the canonical (correct) entry.

    Use this when you've identified that two entries represent the same product.
    The duplicate will be deleted and its relationships transferred to the canonical item.

    Args:
        duplicate_name: Name of the duplicate item to remove
        duplicate_brand: Brand of the duplicate item
        canonical_name: Name of the correct/canonical item to keep
        canonical_brand: Brand of the canonical item

    Returns:
        Success or error message
    """
    try:
        success = merge_gear_items(
            source_name=duplicate_name,
            source_brand=duplicate_brand,
            target_name=canonical_name,
            target_brand=canonical_brand,
        )

        if success:
            return (
                f"Successfully merged '{duplicate_name}' into '{canonical_name}'. "
                f"The duplicate has been removed and relationships transferred."
            )
        return f"Failed to merge - check that both items exist in the database"

    except Exception as e:
        logger.error(f"Error merging duplicates: {e}")
        return f"Error: {str(e)}"


def update_existing_gear(
    name: str,
    brand: str,
    weight_grams: Optional[int] = None,
    price_usd: Optional[float] = None,
    category: Optional[str] = None,
    product_url: Optional[str] = None,
) -> str:
    """Update an existing gear item with new information.

    Use this instead of creating a new entry when the item already exists
    but you have additional or corrected information.

    Args:
        name: Exact name of the existing item
        brand: Exact brand of the existing item
        weight_grams: Updated weight (optional)
        price_usd: Updated price (optional)
        category: Updated category (optional)
        product_url: Updated product URL (optional)

    Returns:
        Success or error message
    """
    try:
        set_parts = []
        params = {"name": name, "brand": brand}

        if weight_grams is not None:
            set_parts.append("g.weight_grams = $weight")
            params["weight"] = weight_grams

        if price_usd is not None:
            set_parts.append("g.price_usd = $price")
            params["price"] = price_usd

        if category:
            set_parts.append("g.category = $category")
            params["category"] = category

        if product_url:
            set_parts.append("g.productUrl = $url")
            params["url"] = product_url

        if not set_parts:
            return "No updates provided"

        set_parts.append("g.updatedAt = datetime()")
        set_clause = ", ".join(set_parts)

        query = f"""
        MATCH (g:GearItem {{name: $name, brand: $brand}})
        SET {set_clause}
        RETURN g.name as name
        """

        results = execute_and_fetch(query, params)

        if results:
            return f"Successfully updated '{name}' by {brand}"
        return f"Item not found: '{name}' by {brand}"

    except Exception as e:
        logger.error(f"Error updating gear: {e}")
        return f"Error: {str(e)}"


def audit_duplicates() -> str:
    """Scan the entire database for potential duplicate gear items.

    This tool performs a comprehensive audit of all GearItem nodes,
    identifying groups of items that may be duplicates based on:
    - Similar names (token matching)
    - Same brand with similar product names
    - Name variations (e.g., "BRS-3000T" vs "BRS 3000T Ultralight")

    Returns:
        A detailed report of duplicate groups with recommendations
    """
    try:
        groups = scan_for_duplicates(min_similarity=2)

        if not groups:
            return "No potential duplicates found in the database."

        output = [f"## Duplicate Audit Report\n"]
        output.append(f"Found **{len(groups)} duplicate groups** requiring attention:\n")

        total_duplicates = sum(g["count"] - 1 for g in groups)
        output.append(f"Total duplicate entries: {total_duplicates}\n")
        output.append("---\n")

        for i, group in enumerate(groups, 1):
            canonical = group["canonical"]
            duplicates = group["duplicates"]
            recommendation = group["recommendation"]

            output.append(f"### Group {i}: {canonical.get('name', 'Unknown')}")
            output.append(f"**Recommendation:** {recommendation.upper()}")
            output.append(f"**Items in group:** {group['count']}\n")

            output.append("**Keep (canonical):**")
            output.append(f"  - Name: `{canonical.get('name')}`")
            output.append(f"  - Brand: `{canonical.get('brand') or 'None'}`")
            output.append(f"  - Category: {canonical.get('category') or 'N/A'}")
            output.append(f"  - Weight: {canonical.get('weight') or 'N/A'}g")
            output.append(f"  - Price: ${canonical.get('price') or 'N/A'}\n")

            output.append("**Duplicates to merge:**")
            for dup in duplicates:
                output.append(f"  - `{dup.get('name')}` by `{dup.get('brand') or 'None'}`")

            output.append("\n**To merge, use:**")
            for dup in duplicates:
                dup_brand = dup.get('brand') or ''
                can_brand = canonical.get('brand') or ''
                output.append(
                    f"  `merge_duplicate_gear('{dup.get('name')}', '{dup_brand}', "
                    f"'{canonical.get('name')}', '{can_brand}')`"
                )
            output.append("\n---\n")

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error during duplicate audit: {e}")
        return f"Error scanning for duplicates: {str(e)}"


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


# Glossary term agent tools

def save_glossary_term(
    name: str,
    definition: str,
    category: Optional[str] = None,
    aliases: Optional[str] = None,
) -> str:
    """Save a glossary term to the GearGraph database.

    Use this to add terminology from the outdoor/backpacking domain.
    Categories include: material, technology, design, technique, concept.

    Args:
        name: The term (e.g., "Titanium", "Pertex", "tunnel tent")
        definition: Full definition explaining the term
        category: Term category (material, technology, design, technique, concept)
        aliases: Comma-separated alternative names (e.g., "Ti, titanium alloy")

    Returns:
        Success or error message
    """
    try:
        aliases_list = None
        if aliases:
            aliases_list = [a.strip() for a in aliases.split(",")]

        success = merge_glossary_term(
            name=name,
            definition=definition,
            category=category,
            aliases=aliases_list,
        )

        if success:
            return f"Successfully saved glossary term: '{name}'"
        return f"Failed to save glossary term: '{name}'"

    except Exception as e:
        logger.error(f"Error saving glossary term: {e}")
        return f"Error: {str(e)}"


def lookup_glossary_term(term: str) -> str:
    """Look up a glossary term by name or alias.

    Args:
        term: The term or alias to look up

    Returns:
        Term definition and details, or not found message
    """
    try:
        result = get_glossary_term(term)

        if result:
            output = [f"## {result['name']}"]
            if result.get("category"):
                output.append(f"**Category:** {result['category']}")
            output.append(f"\n{result['definition']}")
            if result.get("aliases"):
                output.append(f"\n**Also known as:** {', '.join(result['aliases'])}")
            return "\n".join(output)

        return f"Glossary term '{term}' not found."

    except Exception as e:
        logger.error(f"Error looking up glossary term: {e}")
        return f"Error: {str(e)}"


def list_glossary_terms(category: Optional[str] = None) -> str:
    """List all glossary terms, optionally filtered by category.

    Args:
        category: Optional category filter (material, technology, design, technique, concept)

    Returns:
        List of glossary terms
    """
    try:
        terms = get_all_glossary_terms(category)

        if not terms:
            if category:
                return f"No glossary terms found in category '{category}'"
            return "No glossary terms in database."

        output = [f"## Glossary Terms ({len(terms)} total)"]
        if category:
            output[0] += f" - Category: {category}"

        # Group by category
        by_category = {}
        for term in terms:
            cat = term.get("category") or "Uncategorized"
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(term)

        for cat, cat_terms in sorted(by_category.items()):
            output.append(f"\n### {cat}")
            for term in cat_terms:
                output.append(f"- **{term['name']}**: {term['definition'][:100]}...")

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error listing glossary terms: {e}")
        return f"Error: {str(e)}"


def link_gear_to_term(
    gear_name: str,
    gear_brand: str,
    term_name: str,
) -> str:
    """Link a gear item to a glossary term.

    Creates a RELATES_TO relationship between the gear and the term.
    Use this to connect products to their relevant materials, technologies, etc.

    Args:
        gear_name: Name of the gear item
        gear_brand: Brand of the gear item
        term_name: Name of the glossary term to link

    Returns:
        Success or error message
    """
    try:
        success = link_gear_to_glossary_term(gear_name, gear_brand, term_name)

        if success:
            return f"Linked '{gear_name}' by {gear_brand} to glossary term '{term_name}'"
        return f"Failed to link - ensure both the gear item and glossary term exist"

    except Exception as e:
        logger.error(f"Error linking gear to term: {e}")
        return f"Error: {str(e)}"


def find_gear_with_term(term: str) -> str:
    """Find all gear items that relate to a glossary term.

    Args:
        term: Glossary term name or alias

    Returns:
        List of gear items linked to this term
    """
    try:
        items = find_gear_by_glossary_term(term)

        if not items:
            return f"No gear items linked to glossary term '{term}'"

        output = [f"## Gear items related to '{term}' ({len(items)} found)"]
        for item in items:
            line = f"- **{item['name']}** by {item['brand']}"
            if item.get("category"):
                line += f" [{item['category']}]"
            if item.get("weight_grams"):
                line += f" - {item['weight_grams']}g"
            output.append(line)

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error finding gear: {e}")
        return f"Error: {str(e)}"


def import_glossary_from_json(json_data: str) -> str:
    """Import glossary terms from JSON data.

    Expects a JSON array of term objects with:
    - name (required): The term
    - definition (required): Full definition
    - category (optional): material, technology, design, technique, concept
    - aliases (optional): List of alternative names

    Example:
    [
        {
            "name": "Titanium",
            "definition": "A lightweight, strong metal...",
            "category": "material",
            "aliases": ["Ti", "titanium alloy"]
        }
    ]

    Args:
        json_data: JSON string containing array of term objects

    Returns:
        Import statistics
    """
    try:
        terms = json.loads(json_data)

        if not isinstance(terms, list):
            return "Error: JSON must be an array of term objects"

        stats = import_glossary_terms(terms)

        return (
            f"Glossary import complete!\n"
            f"- Created: {stats['created']} new terms\n"
            f"- Updated: {stats['updated']} existing terms\n"
            f"- Failed: {stats['failed']} terms"
        )

    except json.JSONDecodeError as e:
        return f"Invalid JSON: {str(e)}"
    except Exception as e:
        logger.error(f"Error importing glossary: {e}")
        return f"Error: {str(e)}"


# ============================================================================
# Provenance Tracking Tools
# ============================================================================


def track_field_source(
    gear_name: str,
    brand: str,
    field_name: str,
    source_url: str,
    confidence: float = 1.0,
) -> str:
    """Track which source provided a specific piece of data.

    **IMPORTANT**: Call this AFTER saving gear data to record where each field came from.
    This enables full data provenance tracking - knowing exactly which source provided
    which pieces of information.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        field_name: The field that was populated (e.g., "weight_grams", "price_usd")
        source_url: The URL where this data was found
        confidence: How confident we are in this data (0.0-1.0)

    Returns:
        Success or error message
    """
    try:
        success = add_field_provenance(
            gear_name=gear_name,
            brand=brand,
            field_name=field_name,
            source_url=source_url,
            confidence=confidence,
        )

        if success:
            return f"Tracked source for {field_name} on '{gear_name}' by {brand}"
        return "Failed to track field source"

    except Exception as e:
        logger.error(f"Error tracking field source: {e}")
        return f"Error: {str(e)}"


def get_data_sources(gear_name: str, brand: str) -> str:
    """Get the provenance map showing which sources provided which data.

    Shows exactly where each piece of information came from for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        Formatted provenance report
    """
    try:
        sources = get_field_provenance(gear_name, brand)

        if not sources:
            return f"No provenance data tracked for '{gear_name}' by {brand}"

        output = [f"## Data Sources for {gear_name} by {brand}\n"]

        for src in sources:
            conf_pct = int(src.get("confidence", 1.0) * 100)
            output.append(
                f"- **{src['field']}**: [{src['source_url']}] ({conf_pct}% confidence)"
            )

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error getting field provenance: {e}")
        return f"Error: {str(e)}"


# ============================================================================
# Dynamic Attribute Tools
# ============================================================================


def save_dynamic_attribute(
    gear_name: str,
    brand: str,
    attribute_name: str,
    attribute_value: str,
    source_url: Optional[str] = None,
) -> str:
    """Save a dynamic attribute that isn't part of the standard schema.

    Use this for any data you extract that doesn't fit standard fields.
    Examples: color_options, warranty_years, country_of_manufacture, etc.

    The attribute will be stored directly on the gear item node.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        attribute_name: Name for the attribute (use snake_case)
        attribute_value: The value to store
        source_url: Optional source URL for provenance tracking

    Returns:
        Success or error message
    """
    try:
        success = set_gear_attribute(
            gear_name=gear_name,
            brand=brand,
            attr_name=attribute_name,
            attr_value=attribute_value,
            source_url=source_url,
        )

        if success:
            return f"Saved attribute '{attribute_name}' = '{attribute_value}' on '{gear_name}'"
        return f"Failed to save attribute - ensure the gear item exists"

    except Exception as e:
        logger.error(f"Error saving dynamic attribute: {e}")
        return f"Error: {str(e)}"


def get_all_gear_data(gear_name: str, brand: str) -> str:
    """Get ALL data for a gear item including dynamic attributes.

    Returns all properties stored on the gear item node, including
    both standard schema fields and any dynamic attributes.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        JSON with all gear properties
    """
    try:
        attrs = get_gear_attributes(gear_name, brand)

        if not attrs:
            return f"Gear item '{gear_name}' by {brand} not found"

        return json.dumps(attrs, default=str, indent=2)

    except Exception as e:
        logger.error(f"Error getting gear attributes: {e}")
        return f"Error: {str(e)}"


# ============================================================================
# Comparison and Alternative Tools
# ============================================================================


def save_product_comparison(
    gear1_name: str,
    gear1_brand: str,
    gear2_name: str,
    gear2_brand: str,
    comparison_type: str,
    notes: Optional[str] = None,
    winner: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Save a comparison between two gear items.

    Record when a source compares two products. This builds a comparison
    graph that helps users understand how products relate.

    Args:
        gear1_name: First product name
        gear1_brand: First product brand
        gear2_name: Second product name
        gear2_brand: Second product brand
        comparison_type: What's being compared (weight, price, durability, warmth, etc.)
        notes: Details about the comparison
        winner: Which product "wins" this comparison (optional)
        source_url: Where this comparison was found

    Returns:
        Success or error message
    """
    try:
        success = save_gear_comparison(
            gear1_name=gear1_name,
            gear1_brand=gear1_brand,
            gear2_name=gear2_name,
            gear2_brand=gear2_brand,
            comparison_type=comparison_type,
            notes=notes,
            winner=winner,
            source_url=source_url,
        )

        if success:
            return (
                f"Saved {comparison_type} comparison: "
                f"'{gear1_name}' vs '{gear2_name}'"
                + (f" (winner: {winner})" if winner else "")
            )
        return "Failed to save comparison - ensure both items exist in database"

    except Exception as e:
        logger.error(f"Error saving comparison: {e}")
        return f"Error: {str(e)}"


def save_product_alternative(
    gear_name: str,
    brand: str,
    alternative_name: str,
    alternative_brand: str,
    reason: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Mark one product as an alternative to another.

    Use when a source suggests one product as an alternative/substitute.
    Examples: "If you can't get X, try Y" or "A cheaper option is..."

    Args:
        gear_name: The primary product name
        brand: Primary product brand
        alternative_name: The alternative product name
        alternative_brand: Alternative product brand
        reason: Why it's an alternative (cheaper, lighter, more available, etc.)
        source_url: Where this was mentioned

    Returns:
        Success or error message
    """
    try:
        success = save_gear_alternative(
            gear_name=gear_name,
            brand=brand,
            alternative_name=alternative_name,
            alternative_brand=alternative_brand,
            reason=reason,
            source_url=source_url,
        )

        if success:
            msg = f"'{alternative_name}' marked as alternative to '{gear_name}'"
            if reason:
                msg += f" (reason: {reason})"
            return msg
        return "Failed to save alternative - ensure both items exist"

    except Exception as e:
        logger.error(f"Error saving alternative: {e}")
        return f"Error: {str(e)}"


def get_product_comparisons(gear_name: str, brand: str) -> str:
    """Get all comparisons involving a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        Formatted list of comparisons
    """
    try:
        comparisons = get_gear_comparisons(gear_name, brand)

        if not comparisons:
            return f"No comparisons found for '{gear_name}' by {brand}"

        output = [f"## Comparisons for {gear_name} by {brand}\n"]

        for comp in comparisons:
            other = f"{comp.get('otherItem')} by {comp.get('otherBrand')}"
            comp_type = comp.get("comparisonType", "general")
            winner = comp.get("winner")
            notes = comp.get("notes")

            line = f"- **{comp_type}** vs {other}"
            if winner:
                line += f" (winner: {winner})"
            output.append(line)
            if notes:
                output.append(f"  > {notes}")

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error getting comparisons: {e}")
        return f"Error: {str(e)}"


# ============================================================================
# Opinion and Review Tools
# ============================================================================


def save_product_opinion(
    gear_name: str,
    brand: str,
    opinion_type: str,
    content: str,
    sentiment: str = "neutral",
    author: Optional[str] = None,
    source_url: Optional[str] = None,
) -> str:
    """Save an opinion, review, or observation about a gear item.

    Captures subjective information like pros, cons, tips, warnings,
    and real-world experiences mentioned in sources.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        opinion_type: Type of opinion:
            - "pro": Positive aspect/advantage
            - "con": Negative aspect/disadvantage
            - "tip": Usage tip or recommendation
            - "warning": Potential issue or caution
            - "experience": Real-world usage report
        content: The actual opinion/observation text
        sentiment: positive, negative, or neutral
        author: Who said this (channel name, reviewer, etc.)
        source_url: Where this was found

    Returns:
        Success or error message
    """
    valid_types = ["pro", "con", "tip", "warning", "experience"]
    if opinion_type not in valid_types:
        return f"Invalid opinion_type. Use one of: {valid_types}"

    try:
        success = save_gear_opinion(
            gear_name=gear_name,
            brand=brand,
            opinion_type=opinion_type,
            content=content,
            sentiment=sentiment,
            author=author,
            source_url=source_url,
        )

        if success:
            return f"Saved {opinion_type} ({sentiment}) for '{gear_name}'"
        return "Failed to save opinion - ensure gear item exists"

    except Exception as e:
        logger.error(f"Error saving opinion: {e}")
        return f"Error: {str(e)}"


def get_product_opinions(
    gear_name: str,
    brand: str,
    opinion_type: Optional[str] = None,
) -> str:
    """Get opinions and reviews for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        opinion_type: Optional filter (pro, con, tip, warning, experience)

    Returns:
        Formatted list of opinions
    """
    try:
        opinions = get_gear_opinions(gear_name, brand, opinion_type)

        if not opinions:
            filter_msg = f" of type '{opinion_type}'" if opinion_type else ""
            return f"No opinions{filter_msg} found for '{gear_name}' by {brand}"

        output = [f"## Opinions for {gear_name} by {brand}\n"]

        # Group by type
        by_type = {}
        for op in opinions:
            t = op.get("type", "other")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(op)

        type_emoji = {
            "pro": "+",
            "con": "-",
            "tip": "*",
            "warning": "!",
            "experience": ">",
        }

        for op_type, ops in by_type.items():
            emoji = type_emoji.get(op_type, "")
            output.append(f"### {op_type.upper()}")
            for op in ops:
                author = f" - {op['author']}" if op.get("author") else ""
                output.append(f"{emoji} {op['content']}{author}")

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error getting opinions: {e}")
        return f"Error: {str(e)}"


# ============================================================================
# Usage Context Tools
# ============================================================================


def save_recommended_usage(
    gear_name: str,
    brand: str,
    context_type: str,
    description: str,
    source_url: Optional[str] = None,
) -> str:
    """Save a recommended usage context for a gear item.

    Records when sources mention what conditions/activities a product
    is good for.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item
        context_type: Type of context:
            - "terrain": Ground conditions (rocky, sandy, snow)
            - "weather": Weather conditions (rain, cold, hot)
            - "activity": Activity type (backpacking, mountaineering, car camping)
            - "skill_level": User skill level (beginner, intermediate, expert)
            - "trip_type": Trip style (ultralight, base weight focused, luxury)
        description: Description of the recommended context
        source_url: Where this was mentioned

    Returns:
        Success or error message
    """
    valid_types = ["terrain", "weather", "activity", "skill_level", "trip_type"]
    if context_type not in valid_types:
        return f"Invalid context_type. Use one of: {valid_types}"

    try:
        success = save_usage_context(
            gear_name=gear_name,
            brand=brand,
            context_type=context_type,
            description=description,
            source_url=source_url,
        )

        if success:
            return f"Saved {context_type} context for '{gear_name}': {description}"
        return "Failed to save usage context - ensure gear item exists"

    except Exception as e:
        logger.error(f"Error saving usage context: {e}")
        return f"Error: {str(e)}"


def get_recommended_usage(gear_name: str, brand: str) -> str:
    """Get all recommended usage contexts for a gear item.

    Args:
        gear_name: Name of the gear item
        brand: Brand of the gear item

    Returns:
        Formatted list of usage contexts
    """
    try:
        contexts = get_gear_usage_contexts(gear_name, brand)

        if not contexts:
            return f"No usage contexts found for '{gear_name}' by {brand}"

        output = [f"## Recommended Usage for {gear_name} by {brand}\n"]

        # Group by type
        by_type = {}
        for ctx in contexts:
            t = ctx.get("context_type", "other")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(ctx)

        for ctx_type, ctxs in by_type.items():
            output.append(f"### {ctx_type.replace('_', ' ').title()}")
            for ctx in ctxs:
                output.append(f"- {ctx['description']}")

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Error getting usage contexts: {e}")
        return f"Error: {str(e)}"

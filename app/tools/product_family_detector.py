"""Product Family Detection and Organization for GearGraph.

Detects products that should be grouped into families based on naming patterns,
and provides functions to reorganize the graph structure accordingly.

Examples of families:
- "Altra Lone Peak" family with variants: "Lone Peak 8", "Lone Peak 9", "Lone Peak 9+"
- "Osprey Exos" family with variants: "Exos 55", "Exos 58", "Exos 48"
- "Patagonia Nano Air" family with variants: "Nano Air 20g", "Nano Air 40g"
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.db.memgraph import execute_and_fetch, execute_cypher

logger = logging.getLogger(__name__)


@dataclass
class ProductGroup:
    """A detected group of products that may form a family."""
    family_name: str
    brand: str
    products: list[dict] = field(default_factory=list)
    confidence: float = 0.0  # 0-1 confidence this is a real family
    pattern_type: str = ""  # version_number, size, temperature, etc.

    @property
    def product_count(self) -> int:
        return len(self.products)

    def to_dict(self) -> dict:
        return {
            "family_name": self.family_name,
            "brand": self.brand,
            "products": self.products,
            "product_count": self.product_count,
            "confidence": self.confidence,
            "pattern_type": self.pattern_type,
        }


def extract_base_name(product_name: str) -> tuple[str, str, str]:
    """Extract the base product name, variant identifier, and pattern type.

    Returns:
        Tuple of (base_name, variant_part, pattern_type)

    Examples:
        "Lone Peak 8" -> ("Lone Peak", "8", "version_number")
        "Exos 55" -> ("Exos", "55", "size_number")
        "Nano Air 20g" -> ("Nano Air", "20g", "weight_spec")
        "Ultralight Bed 25°" -> ("Ultralight Bed", "25°", "temperature")
    """
    name = product_name.strip()

    # Pattern: Version numbers (e.g., "Lone Peak 8", "Speedcross 6")
    # Match product name ending with single digit (1-9) or two digits
    version_match = re.match(r'^(.+?)\s+(\d{1,2})(\+)?$', name)
    if version_match:
        base = version_match.group(1).strip()
        variant = version_match.group(2) + (version_match.group(3) or "")
        return (base, variant, "version_number")

    # Pattern: Size numbers (e.g., "Exos 55", "Flash 55", "Atmos AG 65")
    size_match = re.match(r'^(.+?)\s+(\d{2,3})([L]?)$', name, re.IGNORECASE)
    if size_match:
        base = size_match.group(1).strip()
        variant = size_match.group(2) + size_match.group(3)
        return (base, variant, "size_number")

    # Pattern: Weight specs (e.g., "Nano Air 20g", "Nano Air 40g")
    weight_match = re.match(r'^(.+?)\s+(\d+g)$', name, re.IGNORECASE)
    if weight_match:
        base = weight_match.group(1).strip()
        variant = weight_match.group(2)
        return (base, variant, "weight_spec")

    # Pattern: Temperature ratings (e.g., "Ultralight Bed 25°", "Bandit 20°F")
    temp_match = re.match(r'^(.+?)\s+(\d+°[FC]?)$', name)
    if temp_match:
        base = temp_match.group(1).strip()
        variant = temp_match.group(2)
        return (base, variant, "temperature")

    # Pattern: Fill power (e.g., "Muscovy Down 900 Fill", "950 Fill")
    fill_match = re.match(r'^(.+?)\s+(\d{3,4}\s*Fill.*)$', name, re.IGNORECASE)
    if fill_match:
        base = fill_match.group(1).strip()
        variant = fill_match.group(2)
        return (base, variant, "fill_power")

    # Pattern: Year or model number suffix (e.g., "X Ultra 4 GTX")
    model_match = re.match(r'^(.+?)\s+(\d)\s+(GTX|Pro|Plus|Ultra)$', name, re.IGNORECASE)
    if model_match:
        base = model_match.group(1).strip()
        variant = f"{model_match.group(2)} {model_match.group(3)}"
        return (base, variant, "model_suffix")

    # No pattern found
    return (name, "", "none")


def detect_product_families(brand: Optional[str] = None, min_products: int = 2) -> list[ProductGroup]:
    """Detect potential product families in the database.

    Args:
        brand: Optional brand to filter by
        min_products: Minimum number of products to form a family

    Returns:
        List of ProductGroup objects representing detected families
    """
    # Query all gear items
    if brand:
        query = """
        MATCH (g:GearItem)
        WHERE g.brand = $brand
        RETURN g.name as name, g.brand as brand, g.category as category,
               g.weight_grams as weight, g.price_usd as price,
               g.productUrl as url, id(g) as node_id
        ORDER BY g.name
        """
        products = execute_and_fetch(query, {"brand": brand})
    else:
        query = """
        MATCH (g:GearItem)
        WHERE g.brand IS NOT NULL
        RETURN g.name as name, g.brand as brand, g.category as category,
               g.weight_grams as weight, g.price_usd as price,
               g.productUrl as url, id(g) as node_id
        ORDER BY g.brand, g.name
        """
        products = execute_and_fetch(query)

    # Group products by (brand, base_name)
    groups: dict[tuple[str, str], ProductGroup] = {}

    for product in products:
        brand_name = product.get("brand") or "Unknown"
        name = product.get("name") or ""

        base_name, variant, pattern_type = extract_base_name(name)

        # Skip products without a variant pattern
        if pattern_type == "none":
            continue

        key = (brand_name, base_name)

        if key not in groups:
            groups[key] = ProductGroup(
                family_name=base_name,
                brand=brand_name,
                products=[],
                pattern_type=pattern_type,
            )

        groups[key].products.append({
            "name": name,
            "variant": variant,
            "node_id": product.get("node_id"),
            "category": product.get("category"),
            "weight": product.get("weight"),
            "price": product.get("price"),
            "url": product.get("url"),
        })

    # Filter to groups with enough products and calculate confidence
    families = []
    for group in groups.values():
        if group.product_count >= min_products:
            # Calculate confidence based on pattern consistency
            group.confidence = _calculate_confidence(group)
            families.append(group)

    # Sort by confidence descending
    families.sort(key=lambda g: (g.confidence, g.product_count), reverse=True)

    return families


def _calculate_confidence(group: ProductGroup) -> float:
    """Calculate confidence score for a product group being a real family."""
    score = 0.5  # Base score

    # More products = higher confidence
    if group.product_count >= 3:
        score += 0.2
    if group.product_count >= 5:
        score += 0.1

    # Version numbers are high confidence
    if group.pattern_type == "version_number":
        score += 0.2

    # Size numbers for backpacks are high confidence
    if group.pattern_type == "size_number":
        categories = [p.get("category") for p in group.products]
        if "backpack" in categories:
            score += 0.15

    # Check if products share a category
    categories = [p.get("category") for p in group.products if p.get("category")]
    if categories and len(set(categories)) == 1:
        score += 0.1

    return min(score, 1.0)


def find_ungrouped_products(brand: Optional[str] = None) -> list[dict]:
    """Find products that might need family grouping.

    Returns products that:
    - Have numbered suffixes but aren't in a ProductFamily
    - Have similar names to other products in the same brand
    """
    # Get products not already in a family
    if brand:
        query = """
        MATCH (g:GearItem)
        WHERE g.brand = $brand
          AND NOT (g)-[:VARIANT_OF]->(:ProductFamily)
        RETURN g.name as name, g.brand as brand, g.category as category, id(g) as node_id
        ORDER BY g.name
        """
        products = execute_and_fetch(query, {"brand": brand})
    else:
        query = """
        MATCH (g:GearItem)
        WHERE g.brand IS NOT NULL
          AND NOT (g)-[:VARIANT_OF]->(:ProductFamily)
        RETURN g.name as name, g.brand as brand, g.category as category, id(g) as node_id
        ORDER BY g.brand, g.name
        """
        products = execute_and_fetch(query)

    # Filter to products with variant patterns
    ungrouped = []
    for product in products:
        name = product.get("name") or ""
        _, variant, pattern_type = extract_base_name(name)
        if pattern_type != "none":
            product["detected_variant"] = variant
            product["pattern_type"] = pattern_type
            ungrouped.append(product)

    return ungrouped


def create_product_family(
    family_name: str,
    brand: str,
    product_node_ids: list[int],
    category: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Create a ProductFamily and link existing products as variants.

    Args:
        family_name: Name for the product family
        brand: Brand name
        product_node_ids: List of node IDs to link as variants
        category: Optional category for the family
        description: Optional description

    Returns:
        True if successful
    """
    try:
        # Create the ProductFamily node
        create_query = """
        MERGE (pf:ProductFamily {name: $name, brand: $brand})
        ON CREATE SET pf.createdAt = datetime(),
                      pf.category = $category,
                      pf.description = $description
        ON MATCH SET pf.updatedAt = datetime()
        RETURN id(pf) as family_id
        """
        result = execute_and_fetch(create_query, {
            "name": family_name,
            "brand": brand,
            "category": category,
            "description": description,
        })

        if not result:
            logger.error(f"Failed to create ProductFamily: {family_name}")
            return False

        family_id = result[0]["family_id"]

        # Link products to the family
        for node_id in product_node_ids:
            link_query = """
            MATCH (pf:ProductFamily), (g:GearItem)
            WHERE id(pf) = $family_id AND id(g) = $node_id
            MERGE (g)-[:VARIANT_OF]->(pf)
            MERGE (pf)-[:HAS_VARIANT]->(g)
            """
            execute_cypher(link_query, {"family_id": family_id, "node_id": node_id})

        # Try to link brand
        brand_link_query = """
        MATCH (pf:ProductFamily {name: $name, brand: $brand})
        MATCH (b:OutdoorBrand {name: $brand})
        MERGE (b)-[:MANUFACTURES]->(pf)
        MERGE (pf)-[:PRODUCED_BY]->(b)
        """
        execute_cypher(brand_link_query, {"name": family_name, "brand": brand})

        logger.info(f"Created ProductFamily '{family_name}' with {len(product_node_ids)} variants")
        return True

    except Exception as e:
        logger.error(f"Error creating product family: {e}")
        return False


def get_family_candidates_by_brand() -> dict[str, list[ProductGroup]]:
    """Get all family candidates grouped by brand.

    Returns:
        Dict mapping brand name to list of ProductGroup candidates
    """
    all_families = detect_product_families()

    by_brand: dict[str, list[ProductGroup]] = defaultdict(list)
    for family in all_families:
        by_brand[family.brand].append(family)

    # Sort brands by number of candidates
    return dict(sorted(by_brand.items(), key=lambda x: len(x[1]), reverse=True))


def get_family_summary_stats() -> dict:
    """Get summary statistics about product family organization."""
    # Count products in families vs standalone
    family_query = """
    MATCH (g:GearItem)-[:VARIANT_OF]->(pf:ProductFamily)
    RETURN count(DISTINCT g) as in_family, count(DISTINCT pf) as family_count
    """
    family_result = execute_and_fetch(family_query)

    standalone_query = """
    MATCH (g:GearItem)
    WHERE NOT (g)-[:VARIANT_OF]->(:ProductFamily)
    RETURN count(g) as standalone
    """
    standalone_result = execute_and_fetch(standalone_query)

    # Get detected candidates
    candidates = detect_product_families()
    candidate_products = sum(c.product_count for c in candidates)

    return {
        "existing_families": family_result[0]["family_count"] if family_result else 0,
        "products_in_families": family_result[0]["in_family"] if family_result else 0,
        "standalone_products": standalone_result[0]["standalone"] if standalone_result else 0,
        "detected_family_candidates": len(candidates),
        "products_in_candidates": candidate_products,
    }

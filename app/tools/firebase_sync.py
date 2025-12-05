"""Firebase sync module for exporting GearGraph data to Firebase gearBase.

Exports brands and products from Memgraph to Firebase Firestore in the
nested collection structure expected by the GearShack app for autocomplete.

Structure:
    gearBase/{brand_slug}/
        brand_name, brand_aliases, brand_logo, brand_url
        products/{product_slug}/
            description, fun_fact, product_name, product_url, specs
            variants/{variant_slug}/ (if product family)
                product_name, specs
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.db.memgraph import execute_and_fetch, execute_cypher

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """Convert a name to a URL-safe slug for Firebase document IDs."""
    if not name:
        return "unknown"
    # Lowercase, replace spaces and special chars with hyphens
    slug = name.lower()
    slug = re.sub(r"['\"]", "", slug)  # Remove apostrophes/quotes
    slug = re.sub(r"[^a-z0-9]+", "-", slug)  # Replace non-alphanumeric with hyphens
    slug = re.sub(r"-+", "-", slug)  # Collapse multiple hyphens
    slug = slug.strip("-")  # Remove leading/trailing hyphens
    return slug or "unknown"


@dataclass
class SyncStats:
    """Statistics from a sync operation."""
    brands_exported: int = 0
    products_exported: int = 0
    variants_exported: int = 0
    deleted_items: int = 0
    errors: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "brands_exported": self.brands_exported,
            "products_exported": self.products_exported,
            "variants_exported": self.variants_exported,
            "deleted_items": self.deleted_items,
            "errors": self.errors,
            "timestamp": self.timestamp,
        }


def export_brands_for_firebase() -> list[dict]:
    """Export all brands from GearGraph in Firebase-ready format.

    Returns:
        List of brand dicts with: slug, brand_name, brand_aliases, brand_logo, brand_url
    """
    query = """
    MATCH (b:OutdoorBrand)
    WHERE b.deleted_at IS NULL OR b.deleted_at IS NULL
    OPTIONAL MATCH (b)-[:MANUFACTURES_ITEM]->(g:GearItem)
    WITH b, count(g) as product_count
    RETURN b.name as name,
           b.website as website,
           b.logoUrl as logo,
           b.aliases as aliases,
           product_count
    ORDER BY b.name
    """

    results = execute_and_fetch(query)
    brands = []

    for row in results:
        name = row.get("name")
        if not name:
            continue

        brand = {
            "slug": slugify(name),
            "brand_name": name,
            "brand_aliases": row.get("aliases") or [],
            "brand_logo": row.get("logo") or "",
            "brand_url": row.get("website") or "",
            "product_count": row.get("product_count", 0),
        }
        brands.append(brand)

    return brands


def export_products_for_firebase() -> dict[str, list[dict]]:
    """Export all products from GearGraph in Firebase-ready format.

    Products are grouped by brand slug for the nested collection structure.
    Handles both standalone products and product families with variants.

    Returns:
        Dict mapping brand_slug to list of product dicts
    """
    # Query for standalone gear items (not part of a product family)
    standalone_query = """
    MATCH (g:GearItem)
    WHERE g.deleted_at IS NULL
      AND NOT (g)-[:VARIANT_OF]->(:ProductFamily)
    OPTIONAL MATCH (g)-[:PRODUCED_BY]->(b:OutdoorBrand)
    RETURN g.name as name,
           coalesce(b.name, g.brand) as brand,
           g.category as category,
           g.subcategory as subcategory,
           g.product_type as product_type,
           g.weight_grams as weight_grams,
           g.price_usd as price_usd,
           g.productUrl as product_url,
           b.website as brand_url,
           g.imageUrl as image_url,
           g.description as description,
           g.fun_fact as fun_fact,
           g.materials as materials,
           g.features as features,
           g.volume_liters as volume_liters,
           g.temp_rating_f as temp_rating_f,
           g.temp_rating_c as temp_rating_c,
           g.r_value as r_value,
           g.capacity_persons as capacity_persons,
           g.packed_size as packed_size,
           false as is_family
    ORDER BY brand, name
    """

    # Query for product families with their variants
    family_query = """
    MATCH (pf:ProductFamily)
    WHERE pf.deleted_at IS NULL
    OPTIONAL MATCH (pf)-[:PRODUCED_BY]->(b:OutdoorBrand)
    OPTIONAL MATCH (pf)-[:HAS_VARIANT]->(v:GearItem)
    WHERE v.deleted_at IS NULL
    WITH pf, b, collect({
        name: v.name,
        weight_grams: v.weight_grams,
        price_usd: v.price_usd,
        product_url: v.productUrl,
        image_url: v.imageUrl,
        category: v.category,
        subcategory: v.subcategory,
        product_type: v.product_type,
        materials: v.materials,
        features: v.features
    }) as variants
    RETURN pf.name as name,
           coalesce(b.name, pf.brand) as brand,
           pf.category as category,
           pf.subcategory as subcategory,
           pf.product_type as product_type,
           pf.description as description,
           pf.fun_fact as fun_fact,
           b.website as brand_url,
           pf.productUrl as product_url,
           pf.materials as materials,
           pf.features as features,
           variants as variants,
           true as is_family
    ORDER BY brand, name
    """

    standalone_results = execute_and_fetch(standalone_query)
    family_results = execute_and_fetch(family_query)

    # Group products by brand
    products_by_brand: dict[str, list[dict]] = {}

    def add_product(brand_name: str, product: dict):
        brand_slug = slugify(brand_name) if brand_name else "unknown"
        if brand_slug not in products_by_brand:
            products_by_brand[brand_slug] = []
        products_by_brand[brand_slug].append(product)

    # Process standalone products
    for row in standalone_results:
        name = row.get("name")
        if not name:
            continue

        specs = _build_specs(row)

        product = {
            "slug": slugify(name),
            "product_name": name,
            "brand": row.get("brand") or "",
            "category": row.get("category") or "",
            "subcategory": row.get("subcategory") or "",
            "product_type": row.get("product_type") or "",
            "product_url": row.get("product_url") or "",
            "brand_url": row.get("brand_url") or "",
            "image_url": row.get("image_url") or "",
            "description": row.get("description") or "",
            "fun_fact": row.get("fun_fact") or "",
            "specs": specs,
            "is_family": False,
            "variants": [],
        }

        add_product(row.get("brand"), product)

    # Process product families
    for row in family_results:
        name = row.get("name")
        if not name:
            continue

        specs = _build_specs(row)
        raw_variants = row.get("variants") or []

        # Build variants list
        variants = []
        for v in raw_variants:
            if not v.get("name"):
                continue
            variant_specs = _build_specs(v)
            variants.append({
                "slug": slugify(v.get("name")),
                "product_name": v.get("name"),
                "product_url": v.get("product_url") or "",
                "image_url": v.get("image_url") or "",
                "specs": variant_specs,
            })

        product = {
            "slug": slugify(name),
            "product_name": name,
            "brand": row.get("brand") or "",
            "category": row.get("category") or "",
            "subcategory": row.get("subcategory") or "",
            "product_type": row.get("product_type") or "",
            "product_url": row.get("product_url") or "",
            "brand_url": row.get("brand_url") or "",
            "description": row.get("description") or "",
            "fun_fact": row.get("fun_fact") or "",
            "specs": specs,
            "is_family": True,
            "variants": variants,
        }

        add_product(row.get("brand"), product)

    return products_by_brand


def _build_specs(row: dict) -> dict:
    """Build specs dict from a query result row."""
    specs = {}

    if row.get("weight_grams"):
        specs["weight_grams"] = row["weight_grams"]
    if row.get("price_usd"):
        specs["price_usd"] = row["price_usd"]
    if row.get("materials"):
        specs["materials"] = row["materials"]
    if row.get("features"):
        specs["features"] = row["features"]
    if row.get("volume_liters"):
        specs["volume_liters"] = row["volume_liters"]
    if row.get("temp_rating_f"):
        specs["temp_rating_f"] = row["temp_rating_f"]
    if row.get("temp_rating_c"):
        specs["temp_rating_c"] = row["temp_rating_c"]
    if row.get("r_value"):
        specs["r_value"] = row["r_value"]
    if row.get("capacity_persons"):
        specs["capacity_persons"] = row["capacity_persons"]
    if row.get("packed_size"):
        specs["packed_size"] = row["packed_size"]

    return specs


def export_deleted_items() -> dict[str, list[str]]:
    """Export items marked as deleted for removal from Firebase.

    Returns:
        Dict with 'brands' and 'products' lists of slugs to delete
    """
    deleted = {"brands": [], "products": []}

    # Get deleted brands
    brand_query = """
    MATCH (b:OutdoorBrand)
    WHERE b.deleted_at IS NOT NULL
    RETURN b.name as name
    """
    brand_results = execute_and_fetch(brand_query)
    deleted["brands"] = [slugify(r["name"]) for r in brand_results if r.get("name")]

    # Get deleted products
    product_query = """
    MATCH (g:GearItem)
    WHERE g.deleted_at IS NOT NULL
    RETURN g.name as name, g.brand as brand
    """
    product_results = execute_and_fetch(product_query)
    for r in product_results:
        if r.get("name"):
            deleted["products"].append({
                "brand_slug": slugify(r.get("brand") or "unknown"),
                "product_slug": slugify(r["name"]),
            })

    # Get deleted product families
    family_query = """
    MATCH (pf:ProductFamily)
    WHERE pf.deleted_at IS NOT NULL
    RETURN pf.name as name, pf.brand as brand
    """
    family_results = execute_and_fetch(family_query)
    for r in family_results:
        if r.get("name"):
            deleted["products"].append({
                "brand_slug": slugify(r.get("brand") or "unknown"),
                "product_slug": slugify(r["name"]),
            })

    return deleted


def export_full_gearbase() -> dict:
    """Export the complete gearBase structure for Firebase.

    Returns:
        Complete export dict with brands, products by brand, and deleted items
    """
    brands = export_brands_for_firebase()
    products_by_brand = export_products_for_firebase()
    deleted = export_deleted_items()

    # Build the full structure
    gearbase = {
        "metadata": {
            "exported_at": datetime.utcnow().isoformat(),
            "brand_count": len(brands),
            "product_count": sum(len(prods) for prods in products_by_brand.values()),
            "deleted_brand_count": len(deleted["brands"]),
            "deleted_product_count": len(deleted["products"]),
        },
        "brands": {},
        "deleted": deleted,
    }

    # Build brand entries with nested products
    for brand in brands:
        slug = brand["slug"]
        brand_products = products_by_brand.get(slug, [])

        gearbase["brands"][slug] = {
            "brand_name": brand["brand_name"],
            "brand_aliases": brand["brand_aliases"],
            "brand_logo": brand["brand_logo"],
            "brand_url": brand["brand_url"],
            "products": {p["slug"]: p for p in brand_products},
        }

    # Add products for brands not in brand list (orphan products)
    for brand_slug, products in products_by_brand.items():
        if brand_slug not in gearbase["brands"]:
            # Create placeholder brand entry
            brand_name = products[0].get("brand", brand_slug) if products else brand_slug
            gearbase["brands"][brand_slug] = {
                "brand_name": brand_name,
                "brand_aliases": [],
                "brand_logo": "",
                "brand_url": "",
                "products": {p["slug"]: p for p in products},
            }

    return gearbase


def soft_delete_item(item_type: str, name: str, brand: Optional[str] = None) -> bool:
    """Mark an item as deleted (soft delete).

    Args:
        item_type: 'brand', 'product', or 'family'
        name: Item name
        brand: Brand name (required for product/family)

    Returns:
        True if successful
    """
    timestamp = datetime.utcnow().isoformat()

    if item_type == "brand":
        query = """
        MATCH (b:OutdoorBrand {name: $name})
        SET b.deleted_at = $timestamp
        RETURN b.name as name
        """
        params = {"name": name, "timestamp": timestamp}
    elif item_type == "product":
        query = """
        MATCH (g:GearItem {name: $name, brand: $brand})
        SET g.deleted_at = $timestamp
        RETURN g.name as name
        """
        params = {"name": name, "brand": brand, "timestamp": timestamp}
    elif item_type == "family":
        query = """
        MATCH (pf:ProductFamily {name: $name})
        WHERE pf.brand = $brand OR $brand IS NULL
        SET pf.deleted_at = $timestamp
        RETURN pf.name as name
        """
        params = {"name": name, "brand": brand, "timestamp": timestamp}
    else:
        logger.error(f"Unknown item type: {item_type}")
        return False

    results = execute_and_fetch(query, params)
    return len(results) > 0


def clear_deleted_items() -> int:
    """Permanently remove all soft-deleted items from GearGraph.

    Call this after successfully syncing deletions to Firebase.

    Returns:
        Number of items permanently deleted
    """
    count = 0

    # Delete soft-deleted brands
    brand_query = """
    MATCH (b:OutdoorBrand)
    WHERE b.deleted_at IS NOT NULL
    DETACH DELETE b
    RETURN count(*) as deleted
    """
    result = execute_and_fetch(brand_query)
    if result:
        count += result[0].get("deleted", 0)

    # Delete soft-deleted gear items
    gear_query = """
    MATCH (g:GearItem)
    WHERE g.deleted_at IS NOT NULL
    DETACH DELETE g
    RETURN count(*) as deleted
    """
    result = execute_and_fetch(gear_query)
    if result:
        count += result[0].get("deleted", 0)

    # Delete soft-deleted product families
    family_query = """
    MATCH (pf:ProductFamily)
    WHERE pf.deleted_at IS NOT NULL
    DETACH DELETE pf
    RETURN count(*) as deleted
    """
    result = execute_and_fetch(family_query)
    if result:
        count += result[0].get("deleted", 0)

    return count


def export_to_json(output_path: str = "gearbase_export.json") -> str:
    """Export full gearBase to a JSON file.

    Args:
        output_path: Path for the output JSON file

    Returns:
        Path to the exported file
    """
    gearbase = export_full_gearbase()

    with open(output_path, "w") as f:
        json.dump(gearbase, f, indent=2, default=str)

    logger.info(f"Exported gearBase to {output_path}")
    return output_path

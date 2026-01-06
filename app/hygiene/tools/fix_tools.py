"""Fix application tools for the hygiene agent."""

from typing import Optional

from app.db.memgraph import execute_cypher, execute_and_fetch
from app.hygiene.issues import Fix, FixType, HygieneIssue, IssueType
from app.hygiene.auto_fixer import AutoFixer, FixResult


# Re-use existing AutoFixer for actual fix application
_fixer: Optional[AutoFixer] = None


def get_fixer() -> AutoFixer:
    """Get the AutoFixer instance."""
    global _fixer
    if _fixer is None:
        _fixer = AutoFixer()
    return _fixer


def apply_field_update(
    entity_id: str,
    field: str,
    old_value: str,
    new_value: str,
    entity_type: str = "GearItem",
) -> dict:
    """Apply a field update fix.

    Args:
        entity_id: Database ID
        field: Field to update
        old_value: Current value
        new_value: New value
        entity_type: Type of entity

    Returns:
        Dict with success status
    """
    # Create HygieneIssue for AutoFixer
    issue = HygieneIssue(
        issue_type=IssueType.TYPO,
        entity_type=entity_type,
        entity_id=entity_id,
        description=f"Update {field}: '{old_value}' -> '{new_value}'",
        suggested_fix=Fix(
            fix_type=FixType.UPDATE_FIELD,
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            target_field=field,
            old_value=old_value,
            new_value=new_value,
            confidence=0.95,
            reasoning="Agent-initiated fix",
        ),
        confidence=0.95,
    )

    fixer = get_fixer()
    result = fixer.apply_fix(issue, force=True)

    return {
        "success": result.success,
        "message": result.message,
        "was_auto_fixed": result.was_auto_fixed,
    }


def apply_brand_standardization(old_brand: str, new_brand: str) -> dict:
    """Standardize brand name across all items.

    Args:
        old_brand: Current brand name
        new_brand: Canonical brand name

    Returns:
        Dict with update count
    """
    query = """
    MATCH (g:GearItem)
    WHERE g.brand = $old_brand
    SET g.brand = $new_brand, g.updatedAt = datetime()
    RETURN count(g) as updated_count
    """

    results = execute_and_fetch(
        query,
        {
            "old_brand": old_brand,
            "new_brand": new_brand,
        },
    )

    count = results[0].get("updated_count", 0) if results else 0

    return {
        "success": count > 0,
        "updated_count": count,
        "message": f"Standardized '{old_brand}' -> '{new_brand}' for {count} items",
    }


def merge_duplicate_items(
    source_id: str,
    target_id: str,
) -> dict:
    """Merge a duplicate item into the canonical one.

    Args:
        source_id: ID of duplicate to remove
        target_id: ID of canonical item to keep

    Returns:
        Dict with merge result
    """
    # Transfer relationships
    queries = [
        # Transfer EXTRACTED_FROM
        """
        MATCH (source:GearItem), (target:GearItem)
        WHERE id(source) = $source_id AND id(target) = $target_id
        OPTIONAL MATCH (source)-[r:EXTRACTED_FROM]->(v:VideoSource)
        FOREACH (_ IN CASE WHEN r IS NOT NULL THEN [1] ELSE [] END |
            MERGE (target)-[:EXTRACTED_FROM]->(v)
        )
        RETURN count(r) as transferred
        """,
        # Transfer HAS_TIP
        """
        MATCH (source:GearItem), (target:GearItem)
        WHERE id(source) = $source_id AND id(target) = $target_id
        OPTIONAL MATCH (source)-[r:HAS_TIP]->(i:Insight)
        FOREACH (_ IN CASE WHEN r IS NOT NULL THEN [1] ELSE [] END |
            MERGE (target)-[:HAS_TIP]->(i)
        )
        RETURN count(r) as transferred
        """,
        # Transfer HAS_OPINION
        """
        MATCH (source:GearItem), (target:GearItem)
        WHERE id(source) = $source_id AND id(target) = $target_id
        OPTIONAL MATCH (source)-[r:HAS_OPINION]->(o:Opinion)
        FOREACH (_ IN CASE WHEN r IS NOT NULL THEN [1] ELSE [] END |
            MERGE (target)-[:HAS_OPINION]->(o)
        )
        RETURN count(r) as transferred
        """,
    ]

    params = {
        "source_id": int(source_id),
        "target_id": int(target_id),
    }

    transferred = 0
    for query in queries:
        try:
            results = execute_and_fetch(query, params)
            if results:
                transferred += results[0].get("transferred", 0)
        except Exception:
            pass

    # Get source info before delete
    info_query = """
    MATCH (source:GearItem)
    WHERE id(source) = $source_id
    RETURN source.name as name, source.brand as brand
    """
    info = execute_and_fetch(info_query, {"source_id": int(source_id)})
    source_name = info[0].get("name", "Unknown") if info else "Unknown"

    # Delete source
    delete_query = """
    MATCH (source:GearItem)
    WHERE id(source) = $source_id
    DETACH DELETE source
    RETURN true as deleted
    """
    execute_cypher(delete_query, {"source_id": int(source_id)})

    return {
        "success": True,
        "source_deleted": source_name,
        "relationships_transferred": transferred,
        "message": f"Merged '{source_name}' into target, transferred {transferred} relationships",
    }


def create_source_link(
    gear_name: str,
    brand: str,
    source_url: str,
) -> dict:
    """Link a gear item to its source.

    Args:
        gear_name: Name of gear item
        brand: Brand of gear item
        source_url: URL of source

    Returns:
        Dict with link result
    """
    # Ensure VideoSource exists
    source_query = """
    MERGE (s:VideoSource {url: $url})
    ON CREATE SET s.createdAt = datetime()
    RETURN s.url
    """
    execute_cypher(source_query, {"url": source_url})

    # Create link
    link_query = """
    MATCH (g:GearItem {name: $name, brand: $brand})
    MATCH (s:VideoSource {url: $url})
    MERGE (g)-[:EXTRACTED_FROM]->(s)
    RETURN g.name as gear, s.url as source
    """
    results = execute_and_fetch(
        link_query,
        {
            "name": gear_name,
            "brand": brand,
            "url": source_url,
        },
    )

    return {
        "success": len(results) > 0,
        "message": (
            f"Linked {gear_name} to {source_url}" if results else "Failed to create link"
        ),
    }


def clear_invalid_brand(entity_id: str) -> dict:
    """Clear an invalid/generic brand from an item.

    Args:
        entity_id: Database ID of item

    Returns:
        Dict with result
    """
    query = """
    MATCH (g:GearItem)
    WHERE id(g) = $id
    SET g.brand = '', g.updatedAt = datetime()
    RETURN g.name as name
    """
    results = execute_and_fetch(query, {"id": int(entity_id)})

    if results:
        return {
            "success": True,
            "message": f"Cleared brand for '{results[0].get('name')}'",
        }
    return {
        "success": False,
        "message": "Item not found",
    }


def remove_brand_from_name(
    entity_id: str,
    brand: str,
    current_name: str,
    new_name: str,
) -> dict:
    """Remove redundant brand prefix from product name.

    Args:
        entity_id: Database ID
        brand: Brand name (for logging)
        current_name: Current product name
        new_name: New product name (with brand removed)

    Returns:
        Dict with result
    """
    if not new_name or new_name == current_name:
        return {
            "success": False,
            "message": "Invalid new name",
        }

    return apply_field_update(
        entity_id=entity_id,
        field="name",
        old_value=current_name,
        new_value=new_name,
        entity_type="GearItem",
    )

"""Evaluation tools for the hygiene agent."""

import re
from typing import Optional

from app.db.memgraph import execute_and_fetch, find_potential_duplicates
from app.hygiene.issues import (
    KNOWN_TRANSCRIPTION_ERRORS,
    CANONICAL_BRANDS,
)


def check_whitespace(name: str, brand: str = "") -> dict:
    """Check for whitespace issues in name and brand.

    Args:
        name: Product name
        brand: Brand name

    Returns:
        Dict with issue found and suggested fix
    """
    issues = []
    fixes = []

    # Check name
    if name != name.strip():
        issues.append("name has leading/trailing whitespace")
        fixes.append({"field": "name", "old": name, "new": name.strip()})
    elif "  " in name:
        issues.append("name has multiple consecutive spaces")
        cleaned = " ".join(name.split())
        fixes.append({"field": "name", "old": name, "new": cleaned})

    # Check brand
    if brand:
        if brand != brand.strip():
            issues.append("brand has leading/trailing whitespace")
            fixes.append({"field": "brand", "old": brand, "new": brand.strip()})
        elif "  " in brand:
            issues.append("brand has multiple consecutive spaces")
            cleaned = " ".join(brand.split())
            fixes.append({"field": "brand", "old": brand, "new": cleaned})

    return {
        "issue_found": len(issues) > 0,
        "issues": issues,
        "suggested_fixes": fixes,
        "confidence": 1.0,
        "auto_fixable": True,
        "reasoning": "; ".join(issues) if issues else "No whitespace issues",
    }


def check_case_normalization(name: str, brand: str = "") -> dict:
    """Check for case normalization issues.

    Args:
        name: Product name
        brand: Brand name

    Returns:
        Dict with issue found and suggested fix
    """
    issues = []
    fixes = []

    # Check if name is all caps (but allow short acronyms)
    if name.isupper() and len(name) > 4:
        issues.append("name is all uppercase")
        fixes.append({"field": "name", "old": name, "new": name.title()})

    # Check brand - should follow canonical form if known
    if brand:
        brand_lower = brand.lower()
        if brand_lower in CANONICAL_BRANDS:
            canonical = CANONICAL_BRANDS[brand_lower]
            if brand != canonical:
                issues.append(f"brand should be '{canonical}'")
                fixes.append({"field": "brand", "old": brand, "new": canonical})

    return {
        "issue_found": len(issues) > 0,
        "issues": issues,
        "suggested_fixes": fixes,
        "confidence": 0.95,
        "auto_fixable": len(issues) > 0,
        "reasoning": "; ".join(issues) if issues else "No case issues",
    }


def check_known_transcription_errors(name: str, brand: str = "") -> dict:
    """Check for known transcription errors.

    Args:
        name: Product name
        brand: Brand name

    Returns:
        Dict with issue found and suggested correction
    """
    issues = []
    fixes = []

    # Check name
    for error, correction in KNOWN_TRANSCRIPTION_ERRORS.items():
        if error.lower() in name.lower():
            # Use word boundary matching
            pattern = r"\b" + re.escape(error) + r"\b"
            if re.search(pattern, name, re.IGNORECASE):
                # Don't flag if the correction is already present
                if correction.lower() not in name.lower():
                    corrected = re.sub(pattern, correction, name, flags=re.IGNORECASE)
                    issues.append(f"transcription error: '{error}' -> '{correction}'")
                    fixes.append({"field": "name", "old": name, "new": corrected})

    # Check brand
    for error, correction in KNOWN_TRANSCRIPTION_ERRORS.items():
        if error.lower() == brand.lower():
            issues.append(f"brand transcription error: '{error}' -> '{correction}'")
            fixes.append({"field": "brand", "old": brand, "new": correction})

    return {
        "issue_found": len(issues) > 0,
        "issues": issues,
        "suggested_fixes": fixes,
        "confidence": 0.90,
        "auto_fixable": len(issues) == 1,  # Multiple errors need review
        "reasoning": "; ".join(issues) if issues else "No transcription errors found",
    }


def check_brand_in_graph(brand: str) -> dict:
    """Check if brand exists in the graph and how many items it has.

    Args:
        brand: Brand name to check

    Returns:
        Dict with brand information
    """
    if not brand:
        return {
            "brand_exists": False,
            "item_count": 0,
            "issue_found": True,
            "reasoning": "Brand is empty",
        }

    query = """
    MATCH (g:GearItem)
    WHERE toLower(g.brand) = toLower($brand)
    RETURN count(g) as item_count,
           collect(DISTINCT g.name)[0..5] as sample_items
    """
    results = execute_and_fetch(query, {"brand": brand})

    if results and results[0].get("item_count", 0) > 0:
        count = results[0]["item_count"]
        samples = results[0].get("sample_items", [])
        return {
            "brand_exists": True,
            "item_count": count,
            "sample_items": samples,
            "issue_found": False,
            "confidence": 1.0 if count > 5 else 0.8,
            "reasoning": f"Brand '{brand}' found with {count} items",
        }

    # Check for similar brands
    query2 = """
    MATCH (g:GearItem)
    WHERE toLower(g.brand) CONTAINS toLower($brand)
       OR toLower($brand) CONTAINS toLower(g.brand)
    RETURN DISTINCT g.brand as similar_brand, count(g) as count
    ORDER BY count DESC
    LIMIT 5
    """
    similar = execute_and_fetch(query2, {"brand": brand})

    return {
        "brand_exists": False,
        "item_count": 0,
        "similar_brands": [s["similar_brand"] for s in similar] if similar else [],
        "issue_found": True,
        "confidence": 0.7,
        "reasoning": (
            f"Brand '{brand}' not found, similar: {[s['similar_brand'] for s in similar]}"
            if similar
            else f"Brand '{brand}' not found in database"
        ),
    }


def find_duplicates_for_item(name: str, brand: str, threshold: int = 75) -> dict:
    """Find potential duplicates for an item.

    Args:
        name: Product name
        brand: Brand name
        threshold: Minimum similarity score

    Returns:
        Dict with duplicate information
    """
    matches = find_potential_duplicates(name, brand, threshold=threshold)

    if not matches:
        return {
            "issue_found": False,
            "duplicates": [],
            "confidence": 1.0,
            "reasoning": "No potential duplicates found",
        }

    # Filter out exact self-match
    filtered = [
        m
        for m in matches
        if not (
            m.get("name", "").lower() == name.lower()
            and m.get("brand", "").lower() == brand.lower()
        )
    ]

    if not filtered:
        return {
            "issue_found": False,
            "duplicates": [],
            "confidence": 1.0,
            "reasoning": "No potential duplicates found",
        }

    high_confidence = [m for m in filtered if m.get("similarity", 0) >= 90]

    return {
        "issue_found": True,
        "duplicates": filtered[:5],
        "high_confidence_duplicates": high_confidence,
        "confidence": max(m.get("similarity", 0) for m in filtered) / 100,
        "needs_merge": len(high_confidence) > 0,
        "reasoning": f"Found {len(filtered)} potential duplicate(s), {len(high_confidence)} high-confidence",
    }


def check_orphaned_node(entity_id: str, entity_type: str = "GearItem") -> dict:
    """Check if a node has no relationships.

    Args:
        entity_id: Database ID
        entity_type: Node type

    Returns:
        Dict with orphan status
    """
    try:
        query = f"""
        MATCH (n:{entity_type})
        WHERE id(n) = $id
        OPTIONAL MATCH (n)-[r]-()
        RETURN count(r) as rel_count,
               collect(DISTINCT type(r)) as rel_types
        """
        results = execute_and_fetch(query, {"id": int(entity_id)})

        if results:
            rel_count = results[0].get("rel_count", 0)
            rel_types = results[0].get("rel_types", [])

            return {
                "is_orphaned": rel_count == 0,
                "relationship_count": rel_count,
                "relationship_types": rel_types,
                "issue_found": rel_count == 0,
                "confidence": 1.0,
                "reasoning": (
                    "Node has no relationships"
                    if rel_count == 0
                    else f"Node has {rel_count} relationships: {rel_types}"
                ),
            }

        return {
            "is_orphaned": True,
            "issue_found": True,
            "confidence": 0.5,
            "reasoning": "Node not found",
        }
    except Exception as e:
        return {
            "is_orphaned": False,
            "issue_found": False,
            "error": str(e),
            "reasoning": f"Error checking node: {e}",
        }


def check_provenance(entity_id: str, entity_type: str = "GearItem") -> dict:
    """Check if an item has source provenance.

    Args:
        entity_id: Database ID
        entity_type: Node type

    Returns:
        Dict with provenance status
    """
    try:
        query = """
        MATCH (g:GearItem)
        WHERE id(g) = $id
        OPTIONAL MATCH (g)-[:EXTRACTED_FROM]->(s:VideoSource)
        OPTIONAL MATCH (g)-[:HAS_FIELD_SOURCE]->(fs:FieldSource)
        RETURN g.sourceUrl as source_url,
               count(DISTINCT s) as video_sources,
               count(DISTINCT fs) as field_sources,
               collect(DISTINCT s.url)[0..3] as source_urls
        """
        results = execute_and_fetch(query, {"id": int(entity_id)})

        if results:
            r = results[0]
            has_provenance = (
                r.get("source_url")
                or r.get("video_sources", 0) > 0
                or r.get("field_sources", 0) > 0
            )

            return {
                "has_provenance": has_provenance,
                "source_url": r.get("source_url"),
                "video_source_count": r.get("video_sources", 0),
                "field_source_count": r.get("field_sources", 0),
                "source_urls": r.get("source_urls", []),
                "issue_found": not has_provenance,
                "confidence": 1.0,
                "reasoning": (
                    "Has source provenance"
                    if has_provenance
                    else "Missing source provenance"
                ),
            }

        return {
            "has_provenance": False,
            "issue_found": True,
            "confidence": 0.5,
            "reasoning": "Node not found",
        }
    except Exception as e:
        return {
            "has_provenance": False,
            "issue_found": False,
            "error": str(e),
            "reasoning": f"Error checking provenance: {e}",
        }


def check_data_completeness(item_data: dict) -> dict:
    """Check data completeness for an item.

    Args:
        item_data: Item properties dict

    Returns:
        Dict with completeness assessment
    """
    # Required fields
    required = ["name", "brand"]
    # Important fields
    important = ["weight_grams", "description", "category"]
    # Nice to have
    optional = ["price_usd", "materials", "features", "productUrl"]

    missing_required = [f for f in required if not item_data.get(f)]
    missing_important = [f for f in important if not item_data.get(f)]
    missing_optional = [f for f in optional if not item_data.get(f)]

    # Calculate score
    total_fields = len(required) + len(important) + len(optional)
    missing_count = len(missing_required) + len(missing_important) + len(missing_optional)
    score = 1 - (missing_count / total_fields)

    # Weight required fields more heavily
    if missing_required:
        score -= 0.3

    return {
        "completeness_score": max(0, score),
        "missing_required": missing_required,
        "missing_important": missing_important,
        "missing_optional": missing_optional,
        "issue_found": len(missing_required) > 0 or len(missing_important) > 1,
        "priority_fields_to_fill": missing_important,
        "confidence": 1.0,
        "reasoning": (
            f"Completeness: {score:.0%}. Missing: {missing_required + missing_important}"
            if missing_required or missing_important
            else f"Data is {score:.0%} complete"
        ),
    }


def check_weight_consistency(entity_id: str) -> dict:
    """Check for conflicting weight values (snake_case vs camelCase fields).

    This detects items with both weight_grams and weightGrams fields that
    have different values - a common data quality issue from mixed import sources.

    Args:
        entity_id: Database ID

    Returns:
        Dict with consistency assessment and recommended fix
    """
    try:
        query = """
        MATCH (g:GearItem)
        WHERE id(g) = $id
        RETURN g.name as name,
               g.brand as brand,
               g.weight_grams as weight_grams,
               g.weightGrams as weightGrams,
               g.weight_oz as weight_oz,
               g.weightOunces as weightOunces,
               g.weight as weight,
               [k IN keys(g) WHERE k CONTAINS 'weight' OR k CONTAINS 'Weight'] as weight_keys
        """
        results = execute_and_fetch(query, {"id": int(entity_id)})

        if not results:
            return {
                "issue_found": False,
                "confidence": 0.5,
                "reasoning": "Item not found",
            }

        r = dict(results[0])
        weight_keys = r.get("weight_keys", [])

        # Check for naming convention conflicts
        has_snake = any("_" in k for k in weight_keys)
        has_camel = any(
            k[0].islower() and any(c.isupper() for c in k) for k in weight_keys
        )

        if not (has_snake and has_camel):
            return {
                "issue_found": False,
                "weight_keys": weight_keys,
                "confidence": 1.0,
                "reasoning": "Consistent weight field naming",
            }

        # Check for value conflicts
        snake_grams = r.get("weight_grams")
        camel_grams = r.get("weightGrams")
        conflicts = []

        if snake_grams and camel_grams and snake_grams != camel_grams:
            diff_percent = abs(snake_grams - camel_grams) / max(snake_grams, camel_grams) * 100
            conflicts.append({
                "field_pair": ("weight_grams", "weightGrams"),
                "values": (snake_grams, camel_grams),
                "difference_percent": diff_percent,
            })

        snake_oz = r.get("weight_oz")
        camel_oz = r.get("weightOunces")
        if snake_oz and camel_oz and snake_oz != camel_oz:
            diff_percent = abs(snake_oz - camel_oz) / max(snake_oz, camel_oz) * 100
            conflicts.append({
                "field_pair": ("weight_oz", "weightOunces"),
                "values": (snake_oz, camel_oz),
                "difference_percent": diff_percent,
            })

        # Determine recommended value (prefer snake_case as canonical)
        recommended_grams = snake_grams or camel_grams
        recommendation = "consolidate_to_snake_case"

        return {
            "issue_found": len(conflicts) > 0,
            "has_naming_conflict": True,
            "has_value_conflict": len(conflicts) > 0,
            "weight_keys": weight_keys,
            "conflicts": conflicts,
            "current_values": {
                "weight_grams": snake_grams,
                "weightGrams": camel_grams,
                "weight_oz": snake_oz,
                "weightOunces": camel_oz,
            },
            "recommended_value": recommended_grams,
            "recommendation": recommendation,
            "confidence": 0.9 if conflicts else 0.7,
            "reasoning": (
                f"Found {len(conflicts)} value conflicts between snake_case and camelCase weight fields. "
                f"Values: weight_grams={snake_grams}, weightGrams={camel_grams}"
                if conflicts
                else f"Has mixed naming ({weight_keys}) but values are consistent"
            ),
        }

    except Exception as e:
        return {
            "issue_found": False,
            "error": str(e),
            "reasoning": f"Error checking weight consistency: {e}",
        }

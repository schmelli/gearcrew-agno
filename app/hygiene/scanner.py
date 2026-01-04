"""Scanner module for detecting data quality issues in the GearGraph."""

import re
from datetime import datetime
from typing import Optional

from rapidfuzz import fuzz

from app.db.memgraph import execute_and_fetch, calculate_completeness_score
from app.hygiene.issues import (
    IssueType,
    FixType,
    HygieneIssue,
    Fix,
    KNOWN_TRANSCRIPTION_ERRORS,
    CANONICAL_BRANDS,
)


class HygieneScanner:
    """Scans the GearGraph database for data quality issues."""

    def __init__(self):
        """Initialize the scanner."""
        self.issues: list[HygieneIssue] = []

    def run_full_scan(self) -> list[HygieneIssue]:
        """Run all scanners and return detected issues.

        Returns:
            List of all detected hygiene issues, sorted by risk level
        """
        self.issues = []

        print("Starting full hygiene scan...")

        # Run each scanner
        print("  Scanning for transcription errors...")
        self.issues.extend(self.scan_transcription_errors())

        print("  Scanning for duplicates...")
        self.issues.extend(self.scan_duplicates())

        print("  Scanning for incomplete data...")
        self.issues.extend(self.scan_incomplete_data())

        print("  Scanning for orphaned nodes...")
        self.issues.extend(self.scan_orphaned_nodes())

        print("  Scanning for brand standardization...")
        self.issues.extend(self.scan_brand_standardization())

        # Sort by risk level (HIGH first) and confidence (low confidence first)
        risk_order = {"high": 0, "medium": 1, "low": 2}
        self.issues.sort(
            key=lambda x: (risk_order.get(x.risk_level.value, 3), x.confidence)
        )

        print(f"Scan complete. Found {len(self.issues)} issues.")
        return self.issues

    def scan_transcription_errors(self) -> list[HygieneIssue]:
        """Scan for known transcription errors in gear names and brands.

        Returns:
            List of transcription error issues
        """
        issues = []

        # Query all gear items
        query = """
        MATCH (g:GearItem)
        RETURN g.name AS name, g.brand AS brand, id(g) AS id
        """
        results = execute_and_fetch(query)

        for item in results:
            name = item.get("name", "")
            brand = item.get("brand", "")
            item_id = str(item.get("id", ""))

            # Check name for transcription errors
            for error_pattern, correct_value in KNOWN_TRANSCRIPTION_ERRORS.items():
                if error_pattern.lower() in name.lower():
                    corrected_name = re.sub(
                        re.escape(error_pattern),
                        correct_value,
                        name,
                        flags=re.IGNORECASE
                    )

                    # Calculate confidence based on exact vs partial match
                    confidence = 0.95 if error_pattern.lower() == name.lower() else 0.85

                    issues.append(HygieneIssue(
                        issue_type=IssueType.TYPO,
                        entity_type="GearItem",
                        entity_id=item_id,
                        description=f"Possible transcription error in name: '{name}' -> '{corrected_name}'",
                        suggested_fix=Fix(
                            fix_type=FixType.UPDATE_FIELD,
                            target_entity_type="GearItem",
                            target_entity_id=item_id,
                            target_field="name",
                            old_value=name,
                            new_value=corrected_name,
                            confidence=confidence,
                            reasoning=f"Known transcription error: '{error_pattern}' -> '{correct_value}'",
                        ),
                        confidence=confidence,
                        source_channel="youtube",  # Most transcription errors come from YouTube
                    ))
                    break  # Only report first match per item

            # Check brand for transcription errors
            for error_pattern, correct_value in KNOWN_TRANSCRIPTION_ERRORS.items():
                if error_pattern.lower() == brand.lower():
                    confidence = 0.95

                    issues.append(HygieneIssue(
                        issue_type=IssueType.TYPO,
                        entity_type="GearItem",
                        entity_id=item_id,
                        description=f"Possible transcription error in brand: '{brand}' -> '{correct_value}'",
                        suggested_fix=Fix(
                            fix_type=FixType.UPDATE_FIELD,
                            target_entity_type="GearItem",
                            target_entity_id=item_id,
                            target_field="brand",
                            old_value=brand,
                            new_value=correct_value,
                            confidence=confidence,
                            reasoning=f"Known transcription error: '{error_pattern}' -> '{correct_value}'",
                        ),
                        confidence=confidence,
                        source_channel="youtube",
                    ))
                    break

        return issues

    def scan_duplicates(self, similarity_threshold: float = 0.85) -> list[HygieneIssue]:
        """Scan for duplicate gear items using fuzzy matching.

        Args:
            similarity_threshold: Minimum similarity score to consider duplicates

        Returns:
            List of duplicate detection issues
        """
        issues = []

        # Query all gear items grouped by brand
        query = """
        MATCH (g:GearItem)
        RETURN g.name AS name, g.brand AS brand, id(g) AS id,
               g.weight_grams AS weight, g.price_usd AS price
        ORDER BY g.brand, g.name
        """
        results = execute_and_fetch(query)

        # Group by brand for efficient comparison
        by_brand: dict[str, list[dict]] = {}
        for item in results:
            brand = (item.get("brand") or "unknown").lower()
            if brand not in by_brand:
                by_brand[brand] = []
            by_brand[brand].append(item)

        # Compare items within the same brand
        seen_pairs: set[tuple[str, str]] = set()

        for brand, items in by_brand.items():
            for i, item1 in enumerate(items):
                for item2 in items[i + 1:]:
                    # Skip if we've already compared this pair
                    pair_key = tuple(sorted([str(item1["id"]), str(item2["id"])]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    # Calculate similarity
                    name1 = item1.get("name", "")
                    name2 = item2.get("name", "")

                    # Use multiple fuzzy matching methods
                    ratio = fuzz.ratio(name1.lower(), name2.lower()) / 100
                    partial = fuzz.partial_ratio(name1.lower(), name2.lower()) / 100
                    token_sort = fuzz.token_sort_ratio(name1.lower(), name2.lower()) / 100
                    token_set = fuzz.token_set_ratio(name1.lower(), name2.lower()) / 100

                    # Weighted average
                    similarity = (ratio * 0.3 + partial * 0.2 + token_sort * 0.25 + token_set * 0.25)

                    if similarity >= similarity_threshold:
                        # Determine which item should be canonical (most complete)
                        score1 = self._item_completeness(item1)
                        score2 = self._item_completeness(item2)

                        if score1 >= score2:
                            canonical, duplicate = item1, item2
                        else:
                            canonical, duplicate = item2, item1

                        issues.append(HygieneIssue(
                            issue_type=IssueType.DUPLICATE_MERGE,
                            entity_type="GearItem",
                            entity_id=str(duplicate["id"]),
                            description=f"Possible duplicate: '{duplicate['name']}' ({duplicate['brand']}) "
                                       f"similar to '{canonical['name']}' ({canonical['brand']}) "
                                       f"[similarity: {similarity:.0%}]",
                            suggested_fix=Fix(
                                fix_type=FixType.MERGE_ENTITIES,
                                target_entity_type="GearItem",
                                target_entity_id=str(duplicate["id"]),
                                merge_target_id=str(canonical["id"]),
                                confidence=similarity,
                                reasoning=f"Names are {similarity:.0%} similar. "
                                         f"Canonical item has completeness score {score1:.0%} vs {score2:.0%}",
                            ),
                            confidence=similarity,
                        ))

        return issues

    def _item_completeness(self, item: dict) -> float:
        """Calculate simple completeness score for an item.

        Args:
            item: Item dictionary with fields

        Returns:
            Completeness score 0.0-1.0
        """
        fields = ["name", "brand", "weight", "price"]
        filled = sum(1 for f in fields if item.get(f) is not None)
        return filled / len(fields)

    def scan_incomplete_data(self, threshold: float = 0.3) -> list[HygieneIssue]:
        """Scan for gear items with low completeness scores.

        Args:
            threshold: Report items below this completeness score

        Returns:
            List of incomplete data issues
        """
        issues = []

        # Query items with their properties
        query = """
        MATCH (g:GearItem)
        RETURN g.name AS name, g.brand AS brand, id(g) AS id,
               g.weight_grams AS weight_grams, g.price_usd AS price_usd,
               g.description AS description, g.category AS category,
               g.materials AS materials, g.features AS features,
               g.productUrl AS productUrl
        """
        results = execute_and_fetch(query)

        for item in results:
            # Calculate completeness score
            score = self._calculate_completeness(item)

            if score < threshold:
                missing_fields = self._get_missing_fields(item)

                issues.append(HygieneIssue(
                    issue_type=IssueType.INCOMPLETE_DATA,
                    entity_type="GearItem",
                    entity_id=str(item.get("id", "")),
                    description=f"Low completeness ({score:.0%}): '{item['name']}' by {item['brand']}. "
                               f"Missing: {', '.join(missing_fields)}",
                    suggested_fix=Fix(
                        fix_type=FixType.UPDATE_FIELD,
                        target_entity_type="GearItem",
                        target_entity_id=str(item.get("id", "")),
                        target_field="multiple",
                        old_value=None,
                        new_value=None,
                        confidence=0.99,  # High confidence that data is missing
                        reasoning=f"Item has {score:.0%} completeness. "
                                 f"Missing fields: {', '.join(missing_fields)}",
                    ),
                    confidence=0.99,
                ))

        return issues

    def _calculate_completeness(self, item: dict) -> float:
        """Calculate completeness score for an item.

        Args:
            item: Item dictionary

        Returns:
            Score 0.0-1.0
        """
        # Core fields (weight 2)
        core_fields = ["weight_grams", "description"]
        # Standard fields (weight 1)
        standard_fields = ["price_usd", "materials", "features", "productUrl", "category"]

        total_weight = len(core_fields) * 2 + len(standard_fields) * 1
        score = 0

        for field in core_fields:
            if item.get(field):
                score += 2

        for field in standard_fields:
            value = item.get(field)
            if value and (not isinstance(value, list) or len(value) > 0):
                score += 1

        return score / total_weight

    def _get_missing_fields(self, item: dict) -> list[str]:
        """Get list of missing important fields.

        Args:
            item: Item dictionary

        Returns:
            List of missing field names
        """
        important_fields = [
            "weight_grams", "price_usd", "description",
            "category", "materials", "features", "productUrl"
        ]
        missing = []

        for field in important_fields:
            value = item.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)

        return missing

    def scan_orphaned_nodes(self) -> list[HygieneIssue]:
        """Scan for orphaned nodes (nodes with no relationships).

        Returns:
            List of orphaned node issues
        """
        issues = []

        # Orphaned brands (no products)
        query = """
        MATCH (b:OutdoorBrand)
        WHERE NOT (b)-[:MANUFACTURES_ITEM]->()
        RETURN b.name AS name, id(b) AS id, 'OutdoorBrand' AS type
        """
        results = execute_and_fetch(query)

        for item in results:
            issues.append(HygieneIssue(
                issue_type=IssueType.ORPHANED_NODE,
                entity_type="OutdoorBrand",
                entity_id=str(item.get("id", "")),
                description=f"Orphaned brand with no products: '{item['name']}'",
                suggested_fix=Fix(
                    fix_type=FixType.DELETE_ENTITY,
                    target_entity_type="OutdoorBrand",
                    target_entity_id=str(item.get("id", "")),
                    confidence=0.90,
                    reasoning="Brand has no associated gear items",
                ),
                confidence=0.90,
            ))

        # Orphaned insights (not linked to gear)
        query = """
        MATCH (i:Insight)
        WHERE NOT ()-[:HAS_TIP]->(i)
        RETURN i.summary AS summary, id(i) AS id, 'Insight' AS type
        """
        results = execute_and_fetch(query)

        for item in results:
            summary = (item.get("summary") or "")[:50]
            issues.append(HygieneIssue(
                issue_type=IssueType.ORPHANED_NODE,
                entity_type="Insight",
                entity_id=str(item.get("id", "")),
                description=f"Orphaned insight not linked to any gear: '{summary}...'",
                suggested_fix=Fix(
                    fix_type=FixType.DELETE_ENTITY,
                    target_entity_type="Insight",
                    target_entity_id=str(item.get("id", "")),
                    confidence=0.85,
                    reasoning="Insight is not associated with any gear item",
                ),
                confidence=0.85,
            ))

        # Orphaned product families (no variants)
        query = """
        MATCH (f:ProductFamily)
        WHERE NOT ()-[:IS_VARIANT_OF]->(f)
        RETURN f.name AS name, id(f) AS id, 'ProductFamily' AS type
        """
        results = execute_and_fetch(query)

        for item in results:
            issues.append(HygieneIssue(
                issue_type=IssueType.ORPHANED_NODE,
                entity_type="ProductFamily",
                entity_id=str(item.get("id", "")),
                description=f"Orphaned product family with no variants: '{item['name']}'",
                suggested_fix=Fix(
                    fix_type=FixType.DELETE_ENTITY,
                    target_entity_type="ProductFamily",
                    target_entity_id=str(item.get("id", "")),
                    confidence=0.85,
                    reasoning="Product family has no associated gear variants",
                ),
                confidence=0.85,
            ))

        return issues

    def scan_brand_standardization(self) -> list[HygieneIssue]:
        """Scan for non-canonical brand names that should be standardized.

        Returns:
            List of brand standardization issues
        """
        issues = []

        # Query all unique brands
        query = """
        MATCH (g:GearItem)
        RETURN DISTINCT g.brand AS brand, count(g) AS count
        """
        results = execute_and_fetch(query)

        for item in results:
            brand = item.get("brand", "")
            brand_lower = brand.lower()

            # Check if this brand has a canonical form
            if brand_lower in CANONICAL_BRANDS:
                canonical = CANONICAL_BRANDS[brand_lower]

                # Only report if different from current
                if brand != canonical:
                    issues.append(HygieneIssue(
                        issue_type=IssueType.BRAND_STANDARDIZATION,
                        entity_type="GearItem",
                        entity_id=f"brand:{brand}",  # Special ID for brand-wide fix
                        description=f"Non-standard brand name: '{brand}' -> '{canonical}' "
                                   f"(affects {item['count']} items)",
                        suggested_fix=Fix(
                            fix_type=FixType.UPDATE_FIELD,
                            target_entity_type="GearItem",
                            target_entity_id=f"brand:{brand}",
                            target_field="brand",
                            old_value=brand,
                            new_value=canonical,
                            confidence=0.95,
                            reasoning=f"Standardizing brand name to canonical form: '{canonical}'",
                        ),
                        confidence=0.95,
                    ))

        return issues

    def get_issues_by_risk(self, risk_level: Optional[str] = None) -> list[HygieneIssue]:
        """Get issues filtered by risk level.

        Args:
            risk_level: 'low', 'medium', 'high', or None for all

        Returns:
            Filtered list of issues
        """
        if risk_level is None:
            return self.issues

        return [i for i in self.issues if i.risk_level.value == risk_level]

    def get_auto_fixable_issues(self) -> list[HygieneIssue]:
        """Get issues that can be auto-fixed.

        Returns:
            List of auto-fixable issues
        """
        return [i for i in self.issues if i.can_auto_fix]

    def get_approval_required_issues(self) -> list[HygieneIssue]:
        """Get issues that require human approval.

        Returns:
            List of issues requiring approval
        """
        return [i for i in self.issues if not i.can_auto_fix]


def run_hygiene_scan() -> dict:
    """Run a full hygiene scan and return summary.

    Returns:
        Summary dict with issue counts and details
    """
    scanner = HygieneScanner()
    issues = scanner.run_full_scan()

    summary = {
        "total_issues": len(issues),
        "by_risk": {
            "low": len(scanner.get_issues_by_risk("low")),
            "medium": len(scanner.get_issues_by_risk("medium")),
            "high": len(scanner.get_issues_by_risk("high")),
        },
        "auto_fixable": len(scanner.get_auto_fixable_issues()),
        "approval_required": len(scanner.get_approval_required_issues()),
        "by_type": {},
        "issues": issues,
    }

    # Count by type
    for issue in issues:
        type_name = issue.issue_type.value
        summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1

    return summary

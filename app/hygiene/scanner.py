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
    INVALID_BRAND_PATTERNS,
)
from app.hygiene.validator import (
    get_validator,
    ValidationResult,
    ValidationOutcome,
)


class HygieneScanner:
    """Scans the GearGraph database for data quality issues."""

    def __init__(self, enable_web_validation: bool = False):
        """Initialize the scanner.

        Args:
            enable_web_validation: If True, use web search to validate uncertain fixes.
                                   This is slower but more accurate.
        """
        self.issues: list[HygieneIssue] = []
        self.enable_web_validation = enable_web_validation
        self._validator = None

    @property
    def validator(self):
        """Lazy-load the validator."""
        if self._validator is None:
            self._validator = get_validator()
        return self._validator

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

        print("  Scanning for invalid/generic brands...")
        self.issues.extend(self.scan_invalid_brands())

        print("  Scanning for redundant brand in product names...")
        self.issues.extend(self.scan_redundant_brand_in_name())

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
            name_issue = self._check_transcription_error(
                name, "name", item_id
            )
            if name_issue:
                issues.append(name_issue)

            # Check brand for transcription errors
            brand_issue = self._check_transcription_error(
                brand, "brand", item_id
            )
            if brand_issue:
                issues.append(brand_issue)

        return issues

    def _check_transcription_error(
        self, value: str, field: str, item_id: str
    ) -> Optional[HygieneIssue]:
        """Check a value for transcription errors with proper validation.

        Args:
            value: The string to check
            field: Field name (name or brand)
            item_id: The item's database ID

        Returns:
            HygieneIssue if an error is found, None otherwise
        """
        if not value:
            return None

        value_lower = value.lower()

        for error_pattern, correct_value in KNOWN_TRANSCRIPTION_ERRORS.items():
            error_lower = error_pattern.lower()
            correct_lower = correct_value.lower()

            # Skip if the correct value is already present
            if correct_lower in value_lower:
                continue

            # Skip if the error pattern isn't in the value
            if error_lower not in value_lower:
                continue

            # Use word boundary matching to avoid partial replacements
            # Match: "Durst X-Mid" but not "Durston" (which contains "Durst")
            word_boundary_pattern = r'\b' + re.escape(error_pattern) + r'\b'
            if not re.search(word_boundary_pattern, value, re.IGNORECASE):
                # No word boundary match - check if it's a prefix issue
                # e.g., "Durstin" should match and become "Durston"
                # but "Durston" should NOT match (correct value already there)
                if value_lower.startswith(error_lower):
                    # It's a prefix - check if replacing makes sense
                    suffix = value[len(error_pattern):]
                    # If suffix starts with letters that would create nonsense, skip
                    if suffix and suffix[0].isalpha() and not suffix.startswith(" "):
                        # Check if the result would be valid
                        test_result = correct_value + suffix
                        # Skip if this creates a duplicate prefix (e.g., Durstonon)
                        if correct_lower in test_result.lower()[len(correct_value):].lower():
                            continue
                else:
                    continue

            # Perform the replacement
            corrected_value = re.sub(
                re.escape(error_pattern),
                correct_value,
                value,
                count=1,  # Only replace first occurrence
                flags=re.IGNORECASE
            )

            # Validate the result doesn't contain obvious errors
            if not self._validate_correction(value, corrected_value, correct_value):
                continue

            # Calculate base confidence
            if error_lower == value_lower:
                confidence = 0.95  # Exact match
            elif re.search(r'\b' + re.escape(error_pattern) + r'\b', value, re.IGNORECASE):
                confidence = 0.90  # Word boundary match
            else:
                confidence = 0.75  # Partial match - needs review

            # Validate correction against known brands/products
            validation_result = self._validate_suggested_correction(
                corrected_value, field, value
            )

            if validation_result:
                # Validation found a better match or confirmed/rejected
                if validation_result.result == ValidationResult.INVALID:
                    continue  # Skip this correction
                elif validation_result.result == ValidationResult.CORRECTED:
                    # Use the validator's suggested value instead
                    corrected_value = validation_result.suggested_value
                    confidence = max(confidence, validation_result.confidence)
                elif validation_result.result == ValidationResult.VALID:
                    # Boost confidence since it's validated
                    confidence = min(0.98, confidence + 0.05)
                # UNCERTAIN - keep original suggestion but lower confidence
                elif validation_result.result == ValidationResult.UNCERTAIN:
                    confidence = min(confidence, 0.70)

            reasoning = f"Known transcription error: '{error_pattern}' -> '{correct_value}'"
            if validation_result and validation_result.reasoning:
                reasoning += f". Validation: {validation_result.reasoning}"

            return HygieneIssue(
                issue_type=IssueType.TYPO,
                entity_type="GearItem",
                entity_id=item_id,
                description=f"Possible transcription error in {field}: "
                           f"'{value}' -> '{corrected_value}'",
                suggested_fix=Fix(
                    fix_type=FixType.UPDATE_FIELD,
                    target_entity_type="GearItem",
                    target_entity_id=item_id,
                    target_field=field,
                    old_value=value,
                    new_value=corrected_value,
                    confidence=confidence,
                    reasoning=reasoning,
                ),
                confidence=confidence,
                source_channel="youtube",
            )

        return None

    def _validate_suggested_correction(
        self, corrected_value: str, field: str, original_value: str
    ) -> Optional[ValidationOutcome]:
        """Validate a suggested correction against known data and web.

        Args:
            corrected_value: The proposed corrected value
            field: Field name (name or brand)
            original_value: The original value being corrected

        Returns:
            ValidationOutcome or None if validation skipped
        """
        try:
            if field == "brand":
                # Validate brand name
                return self.validator.validate_brand(corrected_value)
            elif field == "name":
                # For product names, try to extract brand and validate product
                # Look for brand at the start of the name
                parts = corrected_value.split(" ", 1)
                if len(parts) >= 2:
                    potential_brand = parts[0]
                    # Check if first word is a known brand
                    brand_result = self.validator.validate_brand(potential_brand)
                    if brand_result.result == ValidationResult.VALID:
                        # Validate the full product name
                        return self.validator.validate_product(
                            corrected_value, potential_brand
                        )
                # Can't extract brand - validate product without brand context
                if self.enable_web_validation:
                    return self.validator.validate_product(corrected_value)
            return None
        except Exception:
            # Validation failed - return None to use original suggestion
            return None

    def _validate_correction(
        self, original: str, corrected: str, correct_value: str
    ) -> bool:
        """Validate that a correction makes sense.

        Args:
            original: Original value
            corrected: Proposed corrected value
            correct_value: The correct replacement string

        Returns:
            True if the correction is valid
        """
        # Reject if no change
        if original == corrected:
            return False

        original_lower = original.lower()
        correct_lower = correct_value.lower()
        corrected_lower = corrected.lower()

        # Reject if the correct value was already in the original
        # (this means we created nonsense like "Durstonon" from "Durston")
        if correct_lower in original_lower:
            return False

        # Count occurrences of the correct value in result
        count = corrected_lower.count(correct_lower)
        if count > 1:
            return False

        # Check for stuttered patterns (e.g., "tonon", "packpack", "restrest", "ulul")
        # Look for repeated substrings that indicate bad replacement
        # Remove non-alphanumeric for comparison
        corrected_alpha = re.sub(r'[^a-z0-9]', '', corrected_lower)
        for length in range(2, min(8, len(corrected_alpha) // 2 + 1)):
            for i in range(len(corrected_alpha) - length * 2 + 1):
                chunk = corrected_alpha[i:i+length]
                if chunk == corrected_alpha[i+length:i+length*2]:
                    return False

        # Check that the corrected value is reasonable length
        len_diff = abs(len(corrected) - len(original))
        if len_diff > len(correct_value) + 5:
            return False

        return True

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

    def _detect_category_from_text(self, text: str) -> Optional[str]:
        """Detect gear category from insight text content.

        Args:
            text: The insight text to analyze

        Returns:
            Detected category name or None if not detected
        """
        if not text:
            return None

        text_lower = text.lower()

        # Category keywords mapping - order matters (more specific first)
        category_patterns = {
            "stove": [
                "stove", "burner", "canister", "fuel", "cooking system",
                "jetboil", "msr", "brs", "pocket rocket", "windburner",
                "alcohol stove", "esbit", "white gas", "isobutane",
            ],
            "tent": [
                "tent", "shelter", "tarp", "bivy", "bivouac", "vestibule",
                "fly", "footprint", "groundsheet", "stakes", "guylines",
                "freestanding", "non-freestanding", "inner tent",
            ],
            "sleeping_bag": [
                "sleeping bag", "quilt", "down bag", "synthetic bag",
                "mummy bag", "temperature rating", "fill power", "draft collar",
                "footbox", "sleeping system",
            ],
            "sleeping_pad": [
                "sleeping pad", "mattress", "inflatable pad", "foam pad",
                "r-value", "thermarest", "neoair", "zlite", "ccf pad",
            ],
            "backpack": [
                "backpack", "pack", "rucksack", "daypack", "frameless",
                "frame", "hip belt", "load lifter", "shoulder strap",
                "pack volume", "liters", "ultralight pack",
            ],
            "water_filter": [
                "water filter", "filtration", "purification", "sawyer",
                "katadyn", "befree", "squeeze", "gravity filter",
                "water treatment", "aquamira", "chlorine dioxide",
            ],
            "clothing": [
                "jacket", "pants", "shirt", "layer", "base layer",
                "mid layer", "insulation", "rain gear", "windshirt",
                "puffy", "down jacket", "fleece", "merino", "softshell",
            ],
            "footwear": [
                "shoes", "boots", "trail runner", "hiking boot",
                "sandals", "camp shoes", "socks", "gaiters", "insoles",
            ],
            "cookware": [
                "pot", "pan", "mug", "spork", "utensil", "bowl",
                "titanium pot", "cook kit", "lid", "windscreen",
            ],
            "lighting": [
                "headlamp", "flashlight", "lantern", "lumens",
                "nitecore", "petzl", "black diamond",
            ],
            "navigation": [
                "compass", "gps", "map", "navigation", "garmin", "inreach",
            ],
            "trekking_poles": [
                "trekking pole", "hiking pole", "walking stick",
                "carbon pole", "aluminum pole", "pole tip",
            ],
            "electronics": [
                "battery", "power bank", "solar panel", "charger",
                "usb", "phone", "camera", "satellite communicator",
            ],
        }

        # Check each category's patterns
        for category, patterns in category_patterns.items():
            for pattern in patterns:
                if pattern in text_lower:
                    return category

        return None

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
        RETURN i.summary AS summary, i.content AS content, id(i) AS id, 'Insight' AS type
        """
        results = execute_and_fetch(query)

        for item in results:
            summary = (item.get("summary") or "")[:50]
            content = (item.get("content") or item.get("summary") or "")

            # Try to detect relevant category from insight text
            detected_category = self._detect_category_from_text(content)

            if detected_category:
                # Suggest linking to category instead of deleting
                issues.append(HygieneIssue(
                    issue_type=IssueType.ORPHANED_NODE,
                    entity_type="Insight",
                    entity_id=str(item.get("id", "")),
                    description=f"Orphaned insight about {detected_category}: '{summary}...'",
                    suggested_fix=Fix(
                        fix_type=FixType.CREATE_RELATIONSHIP,
                        target_entity_type="Insight",
                        target_entity_id=str(item.get("id", "")),
                        target_field=detected_category,  # Store detected category
                        confidence=0.80,
                        reasoning=f"Link this insight to all {detected_category} items",
                    ),
                    confidence=0.80,
                ))
            else:
                # No category detected - flag for manual review
                issues.append(HygieneIssue(
                    issue_type=IssueType.ORPHANED_NODE,
                    entity_type="Insight",
                    entity_id=str(item.get("id", "")),
                    description=f"Orphaned insight (needs categorization): '{summary}...'",
                    suggested_fix=Fix(
                        fix_type=FixType.CREATE_RELATIONSHIP,
                        target_entity_type="Insight",
                        target_entity_id=str(item.get("id", "")),
                        confidence=0.50,
                        reasoning="Manual review needed - could not detect gear category",
                    ),
                    confidence=0.50,
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

    def scan_invalid_brands(self) -> list[HygieneIssue]:
        """Scan for generic terms used as brand names.

        These are category names, descriptors, or other non-brand terms
        that got incorrectly extracted as brand names.

        Returns:
            List of invalid brand issues
        """
        issues = []

        # Query all unique brands with their item counts
        query = """
        MATCH (g:GearItem)
        WHERE g.brand IS NOT NULL AND g.brand <> ''
        RETURN DISTINCT g.brand AS brand, count(g) AS count,
               collect(id(g))[0..5] AS sample_ids,
               collect(g.name)[0..3] AS sample_names
        """
        results = execute_and_fetch(query)

        for item in results:
            brand = item.get("brand", "")
            brand_lower = brand.lower().strip()
            count = item.get("count", 0)
            sample_names = item.get("sample_names", [])

            # Check if brand matches any invalid pattern
            if brand_lower in INVALID_BRAND_PATTERNS:
                # High confidence - exact match
                confidence = 0.95
                reasoning = f"'{brand}' is a generic term, not a brand name"
            elif self._is_likely_invalid_brand(brand_lower):
                # Medium confidence - pattern match
                confidence = 0.85
                reasoning = f"'{brand}' appears to be a category/descriptor, not a brand"
            else:
                continue

            # Format sample names for description
            samples = ", ".join(f"'{n}'" for n in sample_names[:3])
            sample_text = f" (e.g., {samples})" if samples else ""

            issues.append(HygieneIssue(
                issue_type=IssueType.INVALID_BRAND,
                entity_type="GearItem",
                entity_id=f"brand:{brand}",  # Special ID for brand-wide fix
                description=f"Generic term used as brand: '{brand}' "
                           f"(affects {count} items){sample_text}",
                suggested_fix=Fix(
                    fix_type=FixType.UPDATE_FIELD,
                    target_entity_type="GearItem",
                    target_entity_id=f"brand:{brand}",
                    target_field="brand",
                    old_value=brand,
                    new_value="",  # Clear the invalid brand
                    confidence=confidence,
                    reasoning=reasoning,
                ),
                confidence=confidence,
            ))

        return issues

    def _is_likely_invalid_brand(self, brand: str) -> bool:
        """Check if a brand name is likely invalid using pattern matching.

        Args:
            brand: The brand name to check (lowercase)

        Returns:
            True if brand appears to be invalid
        """
        # Check for partial matches with category keywords
        category_keywords = [
            "jacket", "pants", "shirt", "layer", "bag", "pad",
            "tent", "tarp", "pack", "pole", "filter", "stove",
            "gear", "kit", "system", "setup",
        ]

        for keyword in category_keywords:
            if keyword in brand and len(brand) > len(keyword):
                # Brand contains a category keyword - likely invalid
                return True

        # Check for descriptive patterns
        if brand.startswith(("my ", "the ", "a ", "best ", "top ")):
            return True

        # Check for size/temp patterns (e.g., "20 degree quilt")
        if re.match(r'^\d+\s*(degree|oz|g|l|liter)', brand):
            return True

        return False

    def scan_redundant_brand_in_name(self) -> list[HygieneIssue]:
        """Scan for product names that redundantly include the brand name.

        Examples:
            - "Durston Gear X-Dome" by "Durston Gear" -> "X-Dome"
            - "Zpacks Arc Blast" by "Zpacks" -> "Arc Blast"
            - "Big Agnes Copper Spur" by "Big Agnes" -> "Copper Spur"

        Returns:
            List of redundant brand issues
        """
        issues = []

        # Query all gear items with both name and brand
        query = """
        MATCH (g:GearItem)
        WHERE g.name IS NOT NULL AND g.brand IS NOT NULL
          AND g.name <> '' AND g.brand <> ''
        RETURN g.name AS name, g.brand AS brand, id(g) AS id
        """
        results = execute_and_fetch(query)

        for item in results:
            name = item.get("name", "").strip()
            brand = item.get("brand", "").strip()
            item_id = str(item.get("id", ""))

            if not name or not brand:
                continue

            # Check if brand appears at the start of the product name
            cleaned_name = self._remove_brand_from_name(name, brand)

            if cleaned_name and cleaned_name != name:
                # Calculate confidence based on match quality
                confidence = self._calculate_brand_removal_confidence(
                    name, brand, cleaned_name
                )

                # Skip low-confidence matches
                if confidence < 0.80:
                    continue

                issues.append(HygieneIssue(
                    issue_type=IssueType.REDUNDANT_BRAND,
                    entity_type="GearItem",
                    entity_id=item_id,
                    description=f"Brand in product name: '{name}' by '{brand}' "
                               f"-> '{cleaned_name}'",
                    suggested_fix=Fix(
                        fix_type=FixType.UPDATE_FIELD,
                        target_entity_type="GearItem",
                        target_entity_id=item_id,
                        target_field="name",
                        old_value=name,
                        new_value=cleaned_name,
                        confidence=confidence,
                        reasoning=f"Remove redundant brand '{brand}' from product name",
                    ),
                    confidence=confidence,
                ))

        return issues

    def _remove_brand_from_name(self, name: str, brand: str) -> Optional[str]:
        """Remove brand prefix from product name if present.

        Handles various patterns:
        - Exact match: "Zpacks Arc Blast" with brand "Zpacks" -> "Arc Blast"
        - Multi-word brand: "Big Agnes Copper Spur" with brand "Big Agnes" -> "Copper Spur"
        - Partial match: "Durston X-Mid" with brand "Durston Gear" -> "X-Mid"

        Args:
            name: The product name
            brand: The brand name

        Returns:
            Cleaned product name or None if no match
        """
        name_lower = name.lower()
        brand_lower = brand.lower()

        # Case 1: Name starts with exact brand + space
        if name_lower.startswith(brand_lower + " "):
            cleaned = name[len(brand):].strip()
            if cleaned:  # Don't return empty string
                return cleaned

        # Case 2: Name starts with first word(s) of multi-word brand
        brand_words = brand.split()
        if len(brand_words) > 1:
            # Try matching first word(s) of brand
            for i in range(len(brand_words), 0, -1):
                partial_brand = " ".join(brand_words[:i])
                partial_lower = partial_brand.lower()
                if name_lower.startswith(partial_lower + " "):
                    cleaned = name[len(partial_brand):].strip()
                    if cleaned:
                        return cleaned

        # Case 3: First word of name matches first word of brand
        name_words = name.split()
        if name_words and brand_words:
            if name_words[0].lower() == brand_words[0].lower():
                # Check similarity to confirm it's the brand
                first_word_len = len(name_words[0])
                if first_word_len >= 3:  # Minimum length to avoid false positives
                    cleaned = " ".join(name_words[1:])
                    if cleaned:
                        return cleaned

        return None

    def _calculate_brand_removal_confidence(
        self, name: str, brand: str, cleaned_name: str
    ) -> float:
        """Calculate confidence score for brand removal.

        Args:
            name: Original product name
            brand: Brand name
            cleaned_name: Cleaned product name

        Returns:
            Confidence score 0.0-1.0
        """
        name_lower = name.lower()
        brand_lower = brand.lower()

        # High confidence: Name starts with exact full brand
        if name_lower.startswith(brand_lower + " "):
            return 0.98

        # High confidence: Name starts with most of multi-word brand
        brand_words = brand.split()
        if len(brand_words) > 1:
            for i in range(len(brand_words), 0, -1):
                partial_brand = " ".join(brand_words[:i]).lower()
                if name_lower.startswith(partial_brand + " "):
                    # More words matched = higher confidence
                    match_ratio = i / len(brand_words)
                    return 0.85 + (0.13 * match_ratio)

        # Medium confidence: First word match
        name_words = name.split()
        if name_words and brand_words:
            if name_words[0].lower() == brand_words[0].lower():
                # Longer first word = higher confidence
                word_len = len(name_words[0])
                if word_len >= 6:
                    return 0.92
                elif word_len >= 4:
                    return 0.88
                else:
                    return 0.80

        return 0.70

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


def run_hygiene_scan(enable_web_validation: bool = False) -> dict:
    """Run a full hygiene scan and return summary.

    Args:
        enable_web_validation: If True, use web search to validate uncertain fixes.
                               This is slower but more accurate.

    Returns:
        Summary dict with issue counts and details
    """
    scanner = HygieneScanner(enable_web_validation=enable_web_validation)
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

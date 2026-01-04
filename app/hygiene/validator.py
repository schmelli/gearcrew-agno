"""Validator module for verifying brand and product names.

Implements a tiered validation approach:
1. Fuzzy matching against known brands/products in the database
2. Web search to verify unknown brands
3. Manufacturer page lookup for product verification
"""

import re
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from rapidfuzz import fuzz, process

from app.db.memgraph import execute_and_fetch


class ValidationResult(Enum):
    """Result of a validation check."""
    VALID = "valid"  # Confirmed to exist
    INVALID = "invalid"  # Confirmed to not exist
    UNCERTAIN = "uncertain"  # Could not determine
    CORRECTED = "corrected"  # Found a better match


@dataclass
class ValidationOutcome:
    """Outcome of a validation check."""
    result: ValidationResult
    confidence: float
    suggested_value: Optional[str] = None
    source: str = "unknown"  # db, web_search, manufacturer, etc.
    reasoning: str = ""


class BrandProductValidator:
    """Validates brand and product names using multiple sources."""

    def __init__(self):
        """Initialize the validator with cached data."""
        self._known_brands: Optional[set[str]] = None
        self._known_products: Optional[dict[str, list[str]]] = None
        self._brand_to_canonical: Optional[dict[str, str]] = None

    def _load_known_brands(self) -> set[str]:
        """Load known brands from the database.

        Returns:
            Set of known brand names (lowercase for matching)
        """
        if self._known_brands is not None:
            return self._known_brands

        query = """
        MATCH (g:GearItem)
        WHERE g.brand IS NOT NULL AND g.brand <> ''
        RETURN DISTINCT g.brand AS brand, count(g) AS count
        ORDER BY count DESC
        """
        results = execute_and_fetch(query)

        self._known_brands = set()
        self._brand_to_canonical = {}

        for item in results:
            brand = item.get("brand", "")
            if brand:
                self._known_brands.add(brand.lower())
                # Store the most common casing
                if brand.lower() not in self._brand_to_canonical:
                    self._brand_to_canonical[brand.lower()] = brand

        # Also load OutdoorBrand nodes
        query2 = """
        MATCH (b:OutdoorBrand)
        RETURN b.name AS name
        """
        results2 = execute_and_fetch(query2)
        for item in results2:
            name = item.get("name", "")
            if name:
                self._known_brands.add(name.lower())
                if name.lower() not in self._brand_to_canonical:
                    self._brand_to_canonical[name.lower()] = name

        return self._known_brands

    def _load_known_products(self) -> dict[str, list[str]]:
        """Load known products grouped by brand.

        Returns:
            Dict mapping brand (lowercase) to list of product names
        """
        if self._known_products is not None:
            return self._known_products

        query = """
        MATCH (g:GearItem)
        WHERE g.name IS NOT NULL AND g.brand IS NOT NULL
        RETURN g.name AS name, g.brand AS brand
        """
        results = execute_and_fetch(query)

        self._known_products = {}
        for item in results:
            name = item.get("name", "")
            brand = (item.get("brand") or "").lower()
            if name and brand:
                if brand not in self._known_products:
                    self._known_products[brand] = []
                self._known_products[brand].append(name)

        return self._known_products

    def validate_brand(self, brand: str) -> ValidationOutcome:
        """Validate a brand name using tiered approach.

        Args:
            brand: The brand name to validate

        Returns:
            ValidationOutcome with result and details
        """
        if not brand or not brand.strip():
            return ValidationOutcome(
                result=ValidationResult.INVALID,
                confidence=1.0,
                reasoning="Empty brand name",
            )

        brand_clean = brand.strip()
        brand_lower = brand_clean.lower()

        # Tier 1: Exact match in database
        known_brands = self._load_known_brands()
        if brand_lower in known_brands:
            canonical = self._brand_to_canonical.get(brand_lower, brand_clean)
            if canonical != brand_clean:
                return ValidationOutcome(
                    result=ValidationResult.CORRECTED,
                    confidence=0.98,
                    suggested_value=canonical,
                    source="database",
                    reasoning=f"Found exact match with different casing: '{canonical}'",
                )
            return ValidationOutcome(
                result=ValidationResult.VALID,
                confidence=0.98,
                source="database",
                reasoning=f"Brand '{brand}' exists in database",
            )

        # Tier 2: Fuzzy match against known brands
        fuzzy_result = self._fuzzy_match_brand(brand_clean, known_brands)
        if fuzzy_result:
            return fuzzy_result

        # Tier 3: Web search validation
        web_result = self._validate_brand_via_web(brand_clean)
        if web_result.result != ValidationResult.UNCERTAIN:
            return web_result

        # Could not validate
        return ValidationOutcome(
            result=ValidationResult.UNCERTAIN,
            confidence=0.3,
            source="none",
            reasoning=f"Could not validate brand '{brand}' through any source",
        )

    def _fuzzy_match_brand(
        self, brand: str, known_brands: set[str]
    ) -> Optional[ValidationOutcome]:
        """Try to fuzzy match a brand against known brands.

        Args:
            brand: Brand to match
            known_brands: Set of known brand names (lowercase)

        Returns:
            ValidationOutcome if a good match found, None otherwise
        """
        if not known_brands:
            return None

        brand_lower = brand.lower()

        # Use rapidfuzz to find best matches
        matches = process.extract(
            brand_lower,
            list(known_brands),
            scorer=fuzz.WRatio,
            limit=3,
        )

        if not matches:
            return None

        best_match, score, _ = matches[0]

        # High confidence match (>90%)
        if score >= 90:
            canonical = self._brand_to_canonical.get(best_match, best_match)
            return ValidationOutcome(
                result=ValidationResult.CORRECTED,
                confidence=score / 100,
                suggested_value=canonical,
                source="database_fuzzy",
                reasoning=f"Fuzzy match to known brand '{canonical}' ({score:.0f}% similar)",
            )

        # Medium confidence match (75-90%)
        if score >= 75:
            canonical = self._brand_to_canonical.get(best_match, best_match)
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=score / 100,
                suggested_value=canonical,
                source="database_fuzzy",
                reasoning=f"Possible match to '{canonical}' ({score:.0f}% similar) - needs verification",
            )

        return None

    def _validate_brand_via_web(self, brand: str) -> ValidationOutcome:
        """Validate a brand by searching the web.

        Args:
            brand: Brand name to validate

        Returns:
            ValidationOutcome from web search
        """
        try:
            from app.tools.web_scraper import search_web

            # Search for the brand as an outdoor gear company
            query = f'"{brand}" outdoor gear company'
            results = search_web(query, num_results=5)

            if not results:
                return ValidationOutcome(
                    result=ValidationResult.UNCERTAIN,
                    confidence=0.3,
                    source="web_search",
                    reasoning="No web results found for brand",
                )

            # Analyze results to determine if brand is legitimate
            brand_lower = brand.lower()
            confidence = 0.0
            found_official = False

            for result in results:
                title = (result.get("title") or "").lower()
                snippet = (result.get("snippet") or "").lower()
                url = (result.get("url") or "").lower()

                # Check if brand name appears in results
                if brand_lower in title or brand_lower in snippet:
                    confidence += 0.15

                # Check for official-looking URLs
                brand_slug = re.sub(r'[^a-z0-9]', '', brand_lower)
                if brand_slug in url:
                    confidence += 0.2
                    found_official = True

                # Check for gear-related context
                gear_terms = ["gear", "equipment", "outdoor", "hiking", "backpacking"]
                if any(term in snippet for term in gear_terms):
                    confidence += 0.1

            confidence = min(confidence, 0.95)

            if confidence >= 0.7:
                return ValidationOutcome(
                    result=ValidationResult.VALID,
                    confidence=confidence,
                    source="web_search",
                    reasoning=f"Brand '{brand}' appears legitimate based on web search",
                )
            elif confidence >= 0.4:
                return ValidationOutcome(
                    result=ValidationResult.UNCERTAIN,
                    confidence=confidence,
                    source="web_search",
                    reasoning=f"Brand '{brand}' found online but uncertain if legitimate outdoor brand",
                )
            else:
                return ValidationOutcome(
                    result=ValidationResult.INVALID,
                    confidence=1 - confidence,
                    source="web_search",
                    reasoning=f"Brand '{brand}' does not appear to be a legitimate outdoor gear brand",
                )

        except ImportError:
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.3,
                source="web_search_unavailable",
                reasoning="Web search tools not available",
            )
        except Exception as e:
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.3,
                source="web_search_error",
                reasoning=f"Web search failed: {str(e)}",
            )

    def validate_product(
        self, product_name: str, brand: Optional[str] = None
    ) -> ValidationOutcome:
        """Validate a product name, optionally with brand context.

        Args:
            product_name: The product name to validate
            brand: Optional brand name for context

        Returns:
            ValidationOutcome with result and details
        """
        if not product_name or not product_name.strip():
            return ValidationOutcome(
                result=ValidationResult.INVALID,
                confidence=1.0,
                reasoning="Empty product name",
            )

        product_clean = product_name.strip()

        # Tier 1: Check against known products in database
        db_result = self._validate_product_in_db(product_clean, brand)
        if db_result.result != ValidationResult.UNCERTAIN:
            return db_result

        # Tier 2: Check manufacturer website (if brand known)
        if brand:
            mfr_result = self._validate_product_via_manufacturer(product_clean, brand)
            if mfr_result.result != ValidationResult.UNCERTAIN:
                return mfr_result

        # Tier 3: General web search
        web_result = self._validate_product_via_web(product_clean, brand)
        return web_result

    def _validate_product_in_db(
        self, product: str, brand: Optional[str]
    ) -> ValidationOutcome:
        """Check if a product exists in the database.

        Args:
            product: Product name
            brand: Optional brand for filtering

        Returns:
            ValidationOutcome
        """
        known_products = self._load_known_products()
        product_lower = product.lower()

        # If brand specified, search within that brand first
        if brand:
            brand_lower = brand.lower()
            brand_products = known_products.get(brand_lower, [])

            if brand_products:
                # Exact match
                for p in brand_products:
                    if p.lower() == product_lower:
                        return ValidationOutcome(
                            result=ValidationResult.VALID,
                            confidence=0.98,
                            source="database",
                            reasoning=f"Product '{product}' by {brand} exists in database",
                        )

                # Fuzzy match within brand
                matches = process.extract(
                    product_lower,
                    [p.lower() for p in brand_products],
                    scorer=fuzz.WRatio,
                    limit=3,
                )

                if matches and matches[0][1] >= 85:
                    best_match_lower = matches[0][0]
                    # Find original casing
                    original = next(
                        (p for p in brand_products if p.lower() == best_match_lower),
                        best_match_lower
                    )
                    return ValidationOutcome(
                        result=ValidationResult.CORRECTED,
                        confidence=matches[0][1] / 100,
                        suggested_value=original,
                        source="database_fuzzy",
                        reasoning=f"Similar product found: '{original}' ({matches[0][1]:.0f}% match)",
                    )

        # Search across all brands
        all_products = []
        for brand_name, products in known_products.items():
            for p in products:
                all_products.append((p, brand_name))

        if all_products:
            product_names = [p[0].lower() for p in all_products]
            matches = process.extract(
                product_lower,
                product_names,
                scorer=fuzz.WRatio,
                limit=3,
            )

            if matches and matches[0][1] >= 90:
                idx = product_names.index(matches[0][0])
                original_name, original_brand = all_products[idx]
                return ValidationOutcome(
                    result=ValidationResult.CORRECTED,
                    confidence=matches[0][1] / 100,
                    suggested_value=original_name,
                    source="database_fuzzy",
                    reasoning=f"Similar product found: '{original_name}' by {original_brand} ({matches[0][1]:.0f}% match)",
                )

        return ValidationOutcome(
            result=ValidationResult.UNCERTAIN,
            confidence=0.3,
            source="database",
            reasoning="Product not found in database",
        )

    def _validate_product_via_manufacturer(
        self, product: str, brand: str
    ) -> ValidationOutcome:
        """Validate a product by checking the manufacturer's website.

        Args:
            product: Product name
            brand: Brand/manufacturer name

        Returns:
            ValidationOutcome
        """
        try:
            from app.tools.web_scraper import search_web

            # First, try to find the manufacturer's website
            brand_slug = re.sub(r'[^a-z0-9]', '', brand.lower())
            possible_domains = [
                f"{brand_slug}.com",
                f"www.{brand_slug}.com",
                f"{brand_slug}gear.com",
            ]

            # Search for manufacturer site
            search_query = f'"{brand}" official website outdoor gear'
            search_results = search_web(search_query, num_results=3)

            manufacturer_url = None
            for result in search_results or []:
                url = result.get("url", "")
                if brand_slug in url.lower():
                    manufacturer_url = url
                    break

            if not manufacturer_url:
                return ValidationOutcome(
                    result=ValidationResult.UNCERTAIN,
                    confidence=0.3,
                    source="manufacturer_not_found",
                    reasoning=f"Could not find {brand}'s official website",
                )

            # Search for product on manufacturer site
            product_query = f'site:{manufacturer_url} "{product}"'
            product_results = search_web(product_query, num_results=5)

            if product_results:
                product_lower = product.lower()
                for result in product_results:
                    title = (result.get("title") or "").lower()
                    snippet = (result.get("snippet") or "").lower()

                    if product_lower in title or product_lower in snippet:
                        return ValidationOutcome(
                            result=ValidationResult.VALID,
                            confidence=0.9,
                            source="manufacturer_website",
                            reasoning=f"Product '{product}' found on {brand}'s website",
                        )

                # Product search returned results but no exact match
                return ValidationOutcome(
                    result=ValidationResult.UNCERTAIN,
                    confidence=0.5,
                    source="manufacturer_website",
                    reasoning=f"Found {brand}'s website but product '{product}' not clearly listed",
                )

            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.4,
                source="manufacturer_website",
                reasoning=f"Could not search {brand}'s website for product",
            )

        except ImportError:
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.3,
                source="web_tools_unavailable",
                reasoning="Web tools not available for manufacturer lookup",
            )
        except Exception as e:
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.3,
                source="manufacturer_lookup_error",
                reasoning=f"Manufacturer lookup failed: {str(e)}",
            )

    def _validate_product_via_web(
        self, product: str, brand: Optional[str]
    ) -> ValidationOutcome:
        """Validate a product using general web search.

        Args:
            product: Product name
            brand: Optional brand name

        Returns:
            ValidationOutcome
        """
        try:
            from app.tools.web_scraper import search_web

            # Build search query
            if brand:
                query = f'"{brand}" "{product}" outdoor gear review'
            else:
                query = f'"{product}" outdoor gear hiking backpacking'

            results = search_web(query, num_results=5)

            if not results:
                return ValidationOutcome(
                    result=ValidationResult.UNCERTAIN,
                    confidence=0.3,
                    source="web_search",
                    reasoning="No web results found for product",
                )

            # Analyze results
            product_lower = product.lower()
            brand_lower = (brand or "").lower()
            confidence = 0.0

            for result in results:
                title = (result.get("title") or "").lower()
                snippet = (result.get("snippet") or "").lower()

                # Product name in results
                if product_lower in title:
                    confidence += 0.2
                elif product_lower in snippet:
                    confidence += 0.1

                # Brand mentioned with product
                if brand_lower and brand_lower in title + snippet:
                    confidence += 0.1

                # Review/gear site indicators
                review_indicators = ["review", "specs", "weight", "price", "gear"]
                if any(ind in snippet for ind in review_indicators):
                    confidence += 0.1

            confidence = min(confidence, 0.9)

            if confidence >= 0.6:
                return ValidationOutcome(
                    result=ValidationResult.VALID,
                    confidence=confidence,
                    source="web_search",
                    reasoning=f"Product '{product}' appears legitimate based on web search",
                )
            elif confidence >= 0.35:
                return ValidationOutcome(
                    result=ValidationResult.UNCERTAIN,
                    confidence=confidence,
                    source="web_search",
                    reasoning=f"Product '{product}' found but could not confirm authenticity",
                )
            else:
                return ValidationOutcome(
                    result=ValidationResult.INVALID,
                    confidence=1 - confidence,
                    source="web_search",
                    reasoning=f"Product '{product}' does not appear to be a real outdoor gear product",
                )

        except ImportError:
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.3,
                source="web_search_unavailable",
                reasoning="Web search tools not available",
            )
        except Exception as e:
            return ValidationOutcome(
                result=ValidationResult.UNCERTAIN,
                confidence=0.3,
                source="web_search_error",
                reasoning=f"Web search failed: {str(e)}",
            )

    def clear_cache(self):
        """Clear cached data to force reload."""
        self._known_brands = None
        self._known_products = None
        self._brand_to_canonical = None


# Global validator instance
_validator: Optional[BrandProductValidator] = None


def get_validator() -> BrandProductValidator:
    """Get the global validator instance.

    Returns:
        BrandProductValidator instance
    """
    global _validator
    if _validator is None:
        _validator = BrandProductValidator()
    return _validator


def validate_brand(brand: str) -> ValidationOutcome:
    """Convenience function to validate a brand name.

    Args:
        brand: Brand name to validate

    Returns:
        ValidationOutcome
    """
    return get_validator().validate_brand(brand)


def validate_product(product: str, brand: Optional[str] = None) -> ValidationOutcome:
    """Convenience function to validate a product name.

    Args:
        product: Product name to validate
        brand: Optional brand name

    Returns:
        ValidationOutcome
    """
    return get_validator().validate_product(product, brand)

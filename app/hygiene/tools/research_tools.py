"""Research tools for the hygiene agent."""

import re
from typing import Optional

from app.hygiene.validator import get_validator, ValidationResult


def verify_brand_via_web(brand: str) -> dict:
    """Verify a brand exists via web search.

    Args:
        brand: Brand name to verify

    Returns:
        Dict with verification result
    """
    if not brand:
        return {
            "verified": False,
            "result": "invalid",
            "confidence": 0.0,
            "reasoning": "Brand is empty",
        }

    try:
        validator = get_validator()
        result = validator.validate_brand(brand)

        return {
            "verified": result.result == ValidationResult.VALID,
            "result": result.result.value,
            "confidence": result.confidence,
            "source": result.source,
            "reasoning": result.reasoning,
            "suggested_correction": result.suggested_value,
        }
    except Exception as e:
        return {
            "verified": False,
            "result": "error",
            "confidence": 0.0,
            "reasoning": f"Error verifying brand: {e}",
        }


def research_missing_weight(name: str, brand: str) -> dict:
    """Research to find missing weight data.

    Args:
        name: Product name
        brand: Brand name

    Returns:
        Dict with weight if found
    """
    try:
        from app.tools.web_scraper import search_web
    except ImportError:
        return {
            "found": False,
            "error": "Web search not available",
        }

    query = f'"{brand}" "{name}" weight grams oz specifications'

    try:
        results = search_web(query, num_results=5)

        if not results:
            return {
                "found": False,
                "message": "No search results",
            }

        # Look for weight patterns in snippets
        weight_patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:g|grams)",
            r"(\d+(?:\.\d+)?)\s*(?:oz|ounces?)",
            r"weight[:\s]+(\d+(?:\.\d+)?)\s*(?:g|grams)",
        ]

        weights_found = []
        sources = []

        for result in results:
            snippet = result.get("snippet", "").lower()
            url = result.get("url", "")

            for pattern in weight_patterns:
                matches = re.findall(pattern, snippet)
                for match in matches:
                    weight = float(match)
                    # Convert oz to grams if needed
                    if "oz" in snippet or "ounce" in snippet:
                        weight = weight * 28.35
                    weights_found.append(weight)
                    sources.append(url)

        if weights_found:
            # Return most common or median weight
            avg_weight = sum(weights_found) / len(weights_found)
            return {
                "found": True,
                "weight_grams": int(avg_weight),
                "confidence": min(0.8, len(weights_found) * 0.2),
                "sources": sources[:3],
                "all_weights_found": weights_found,
            }

        return {
            "found": False,
            "message": "Weight not found in search results",
            "search_results": [r.get("url") for r in results],
        }

    except Exception as e:
        return {
            "found": False,
            "error": str(e),
        }


def research_current_price(name: str, brand: str) -> dict:
    """Research current price for a product.

    Args:
        name: Product name
        brand: Brand name

    Returns:
        Dict with price if found
    """
    try:
        from app.tools.web_scraper import search_web
    except ImportError:
        return {
            "found": False,
            "error": "Web search not available",
        }

    query = f'"{brand}" "{name}" price USD buy'

    try:
        results = search_web(query, num_results=5)

        if not results:
            return {
                "found": False,
                "message": "No search results",
            }

        # Look for price patterns
        price_patterns = [
            r"\$(\d+(?:\.\d{2})?)",
            r"USD\s*(\d+(?:\.\d{2})?)",
            r"(\d+(?:\.\d{2})?)\s*(?:USD|dollars)",
        ]

        prices_found = []
        sources = []

        for result in results:
            snippet = result.get("snippet", "")
            url = result.get("url", "")

            for pattern in price_patterns:
                matches = re.findall(pattern, snippet)
                for match in matches:
                    price = float(match)
                    if 5 < price < 2000:  # Reasonable gear price range
                        prices_found.append(price)
                        sources.append(url)

        if prices_found:
            avg_price = sum(prices_found) / len(prices_found)
            return {
                "found": True,
                "price_usd": round(avg_price, 2),
                "confidence": min(0.7, len(prices_found) * 0.15),
                "sources": sources[:3],
                "price_range": [min(prices_found), max(prices_found)],
            }

        return {
            "found": False,
            "message": "Price not found in search results",
        }

    except Exception as e:
        return {
            "found": False,
            "error": str(e),
        }


def research_product_details(name: str, brand: str) -> dict:
    """Research comprehensive product details.

    Args:
        name: Product name
        brand: Brand name

    Returns:
        Dict with found details
    """
    try:
        from app.tools.web_scraper import search_web
    except ImportError:
        return {
            "found": False,
            "error": "Web search not available",
        }

    # Try to find manufacturer page
    brand_domain = brand.lower().replace(" ", "").replace("-", "")
    query = f'site:{brand_domain}.com "{name}"'

    try:
        results = search_web(query, num_results=3)

        if not results:
            # Fallback to general search
            query = f'"{brand}" "{name}" specifications features'
            results = search_web(query, num_results=5)

        if not results:
            return {"found": False, "message": "No results found"}

        details = {
            "found": True,
            "sources": [],
            "snippets": [],
            "manufacturer_url": None,
        }

        for result in results:
            url = result.get("url", "")
            snippet = result.get("snippet", "")

            details["sources"].append(url)
            details["snippets"].append(snippet)

            # Check if this is manufacturer site
            if brand_domain in url.lower():
                details["manufacturer_url"] = url

        return details

    except Exception as e:
        return {
            "found": False,
            "error": str(e),
        }

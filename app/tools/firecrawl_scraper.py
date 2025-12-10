"""Firecrawl-based scraper functions for GearCrew.

This module contains Firecrawl-specific extraction functions that use
the API for structured data extraction with schemas.

Uses SmartFirecrawlClient for automatic self-hosted → cloud fallback.
These are typically used as fallback when Playwright doesn't work,
or for advanced extraction requiring LLM-based schema parsing.

When cloud Firecrawl extract is unavailable (out of credits), falls back to:
1. Scraping the page with self-hosted Firecrawl
2. Parsing the markdown manually to extract product data
"""

import logging
import re
from typing import Optional

from app.tools.smart_firecrawl import get_smart_firecrawl

logger = logging.getLogger(__name__)


def _get_firecrawl_client():
    """Get SmartFirecrawl client instance with self-hosted + cloud fallback."""
    return get_smart_firecrawl()


def _parse_product_from_markdown(markdown: str, url: str = "") -> dict:
    """Parse product data from markdown content (fallback when extract unavailable).

    This is a best-effort extraction using regex patterns for common product page formats.
    """
    result = {
        "source": "markdown_fallback",
        "source_url": url,
    }

    # Extract product name from title (usually first # heading)
    title_match = re.search(r'^#\s+(.+?)(?:\n|$)', markdown, re.MULTILINE)
    if title_match:
        result["product_name"] = title_match.group(1).strip()

    # Try to extract price
    price_patterns = [
        r'\$(\d+(?:\.\d{2})?)',
        r'(?:Price|MSRP|Cost):\s*\$?(\d+(?:\.\d{2})?)',
    ]
    for pattern in price_patterns:
        match = re.search(pattern, markdown, re.IGNORECASE)
        if match:
            try:
                result["price"] = float(match.group(1))
                break
            except ValueError:
                pass

    # Extract weight (grams or oz)
    weight_patterns = [
        (r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\b', 'g'),
        (r'(\d+(?:\.\d+)?)\s*(?:oz|ounces?)\b', 'oz'),
        (r'Weight:\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)', 'g'),
        (r'Weight:\s*(\d+(?:\.\d+)?)\s*(?:oz|ounces?)', 'oz'),
    ]
    for pattern, unit in weight_patterns:
        match = re.search(pattern, markdown, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
                if unit == 'g':
                    result["weight_grams"] = int(value)
                else:
                    result["weight_oz"] = value
                    result["weight_grams"] = int(value * 28.35)
                break
            except ValueError:
                pass

    # Extract volume (liters) for backpacks
    volume_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:L|liters?|litres?)\b', markdown, re.IGNORECASE)
    if volume_match:
        try:
            result["volume_liters"] = float(volume_match.group(1))
        except ValueError:
            pass

    # Extract R-value for sleeping pads
    rvalue_match = re.search(r'R[- ]?[Vv]alue:?\s*(\d+(?:\.\d+)?)', markdown)
    if rvalue_match:
        try:
            result["r_value"] = float(rvalue_match.group(1))
        except ValueError:
            pass

    # Extract temperature rating
    temp_match = re.search(r'(-?\d+)\s*°?\s*F\b', markdown)
    if temp_match:
        try:
            result["temp_rating_f"] = int(temp_match.group(1))
        except ValueError:
            pass

    # Extract description (first paragraph after title)
    desc_match = re.search(r'^#.+?\n\n(.+?)(?:\n\n|\n#)', markdown, re.MULTILINE | re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()
        if len(desc) > 20 and len(desc) < 1000:
            result["description"] = desc

    return result


def _parse_products_list_from_markdown(markdown: str, url: str = "") -> list[dict]:
    """Parse multiple products from a gear guide/list markdown.

    Looks for patterns like:
    - ## Product Name
    - **Product Name** - description
    - 1. Product Name
    """
    products = []

    # Split by headings or numbered lists
    sections = re.split(r'(?:^#{1,3}\s+|\n\d+\.\s+|\n\*\*)', markdown, flags=re.MULTILINE)

    for section in sections[1:]:  # Skip first empty section
        if len(section) < 20:
            continue

        product = _parse_product_from_markdown(section, url)
        if product.get("product_name"):
            products.append(product)

    return products


def extract_multiple_products(url: str) -> dict:
    """Extract multiple product references from a list/guide page.

    Uses Firecrawl's extract() with a comprehensive schema to pull ALL products
    mentioned on pages like gear guides, comparison articles, or best-of lists.
    Captures detailed specs including weight, materials, and category-specific data.

    Args:
        url: URL of the gear list/guide page

    Returns:
        Dictionary with 'products' array containing detailed info for each item

    Raises:
        ValueError: If extraction fails
    """
    schema = {
        "type": "object",
        "properties": {
            "products": {
                "type": "array",
                "description": "All hiking/backpacking gear products on the page",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Full product name including model number"
                        },
                        "brand": {
                            "type": "string",
                            "description": "Brand/manufacturer name"
                        },
                        "category": {
                            "type": "string",
                            "description": "Gear category: backpack, tent, sleeping_bag, sleeping_pad, stove, water_filter, headlamp, jacket, boots, trekking_poles, cookware, or other"
                        },
                        "description": {
                            "type": "string",
                            "description": "Product description, why it's recommended, or key selling points"
                        },
                        "price_usd": {
                            "type": "number",
                            "description": "Price in USD"
                        },
                        "weight_grams": {
                            "type": "number",
                            "description": "Weight in grams (convert from oz if needed: 1oz = 28.35g)"
                        },
                        "weight_oz": {
                            "type": "number",
                            "description": "Weight in ounces if specified"
                        },
                        "materials": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Materials used (nylon, Dyneema, down, synthetic, etc.)"
                        },
                        "features": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Key features mentioned"
                        },
                        "product_url": {
                            "type": "string",
                            "description": "Link to product page (Amazon, REI, manufacturer)"
                        },
                        # Category-specific fields
                        "volume_liters": {
                            "type": "number",
                            "description": "Volume in liters (for backpacks)"
                        },
                        "temp_rating_f": {
                            "type": "number",
                            "description": "Temperature rating in Fahrenheit (sleeping bags)"
                        },
                        "r_value": {
                            "type": "number",
                            "description": "R-value insulation rating (sleeping pads)"
                        },
                        "capacity_persons": {
                            "type": "number",
                            "description": "Person capacity (tents)"
                        },
                        "fill_power": {
                            "type": "number",
                            "description": "Down fill power (sleeping bags, jackets)"
                        },
                        "waterproof_rating": {
                            "type": "string",
                            "description": "Waterproof rating (tents, jackets)"
                        },
                        "lumens": {
                            "type": "number",
                            "description": "Light output in lumens (headlamps)"
                        },
                        "fuel_type": {
                            "type": "string",
                            "description": "Fuel type (stoves): canister, alcohol, wood, etc."
                        },
                        "filter_type": {
                            "type": "string",
                            "description": "Filter type (water filters): squeeze, pump, gravity, UV"
                        }
                    },
                    "required": ["product_name", "brand"]
                }
            },
            "page_title": {
                "type": "string",
                "description": "Title of the page/article"
            },
            "total_products": {
                "type": "number",
                "description": "Total number of products found"
            }
        },
        "required": ["products"]
    }

    try:
        client = _get_firecrawl_client()

        result = client.extract(
            urls=[url],
            schema=schema,
            prompt="""Extract ALL hiking, backpacking, and outdoor gear products from this page.
For EACH product, capture as much detail as possible:
- Full product name and brand
- Category (backpack, tent, sleeping_bag, sleeping_pad, stove, water_filter, headlamp, jacket, boots, etc.)
- Description or why it's recommended
- Price in USD
- Weight (in grams AND/OR ounces - convert if needed: 1oz = 28.35g)
- Materials used
- Key features
- Product/affiliate URL
- Category-specific specs: volume (backpacks), temp rating (sleeping bags), R-value (pads), capacity (tents), lumens (headlamps), etc.

Be thorough - extract EVERY product mentioned, even if some details are missing."""
        )

        # Check if we got a scrape fallback response
        if isinstance(result, dict) and result.get("source") == "scrape_fallback":
            logger.info(f"[Extract] Using scrape fallback for {url}")
            fallback_data = result.get("data", [])
            if fallback_data and isinstance(fallback_data, list):
                # Parse products from markdown
                markdown = fallback_data[0].get("markdown", "")
                if markdown:
                    products = _parse_products_list_from_markdown(markdown, url)
                    return {
                        "products": products,
                        "total_products": len(products),
                        "source": "scrape_fallback",
                    }
            return {"products": [], "total_products": 0, "source": "scrape_fallback"}

        # Handle normal cloud extract response
        if hasattr(result, 'data') and result.data:
            data = result.data[0] if isinstance(result.data, list) else result.data
            return data
        elif isinstance(result, dict):
            data = result.get('data', result)
            if isinstance(data, list) and data:
                return data[0]
            return data
        elif isinstance(result, list) and result:
            return result[0]

        return {"products": [], "total_products": 0}

    except Exception as e:
        raise ValueError(f"Failed to extract products from {url}: {str(e)}")


def extract_product_data(url: str, schema: dict = None) -> dict:
    """Extract structured product data from a webpage.

    Uses Firecrawl's extract() function with a schema to pull
    specific product information.

    Args:
        url: URL of the product page
        schema: Optional JSON schema for extraction (uses default gear schema if not provided)

    Returns:
        Extracted product data as dictionary

    Raises:
        ValueError: If extraction fails
    """
    # Default schema for outdoor gear products
    if schema is None:
        schema = {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Full name of the product"
                },
                "brand": {
                    "type": "string",
                    "description": "Brand or manufacturer name"
                },
                "price": {
                    "type": "number",
                    "description": "Price in USD"
                },
                "weight_grams": {
                    "type": "number",
                    "description": "Weight in grams"
                },
                "weight_oz": {
                    "type": "number",
                    "description": "Weight in ounces"
                },
                "category": {
                    "type": "string",
                    "description": "Product category (tent, backpack, sleeping bag, etc.)"
                },
                "description": {
                    "type": "string",
                    "description": "Product description"
                },
                "materials": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Materials used in the product"
                },
                "features": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key features of the product"
                },
                "specifications": {
                    "type": "object",
                    "description": "Technical specifications"
                },
                "image_url": {
                    "type": "string",
                    "description": "Main product image URL"
                }
            },
            "required": ["product_name"]
        }

    try:
        client = _get_firecrawl_client()

        # Firecrawl v2 extract API - pass schema and prompt as direct kwargs
        result = client.extract(
            urls=[url],
            schema=schema,
            prompt="Extract product information for outdoor/hiking/backpacking gear."
        )

        # Check if we got a scrape fallback response
        if isinstance(result, dict) and result.get("source") == "scrape_fallback":
            logger.info(f"[Extract] Using scrape fallback for single product: {url}")
            fallback_data = result.get("data", [])
            if fallback_data and isinstance(fallback_data, list):
                markdown = fallback_data[0].get("markdown", "")
                if markdown:
                    return _parse_product_from_markdown(markdown, url)
            return {"source": "scrape_fallback", "source_url": url}

        # Handle normal cloud extract response
        if hasattr(result, 'data') and result.data:
            return result.data[0] if isinstance(result.data, list) else result.data
        elif isinstance(result, dict):
            data = result.get('data', result)
            if isinstance(data, list) and data:
                return data[0]
            return data
        elif isinstance(result, list) and result:
            return result[0]

        return {}

    except Exception as e:
        raise ValueError(f"Failed to extract product data from {url}: {str(e)}")


def batch_extract_products(urls: list[str], max_concurrent: int = 5) -> list[dict]:
    """Extract product data from multiple URLs.

    Args:
        urls: List of product page URLs
        max_concurrent: Maximum concurrent extractions

    Returns:
        List of extracted product data dictionaries

    Raises:
        ValueError: If extraction fails
    """
    results = []

    # Process in batches
    for i in range(0, len(urls), max_concurrent):
        batch = urls[i:i + max_concurrent]

        for url in batch:
            try:
                data = extract_product_data(url)
                if data:
                    data['source_url'] = url
                    results.append(data)
            except Exception as e:
                results.append({
                    'source_url': url,
                    'error': str(e)
                })

    return results

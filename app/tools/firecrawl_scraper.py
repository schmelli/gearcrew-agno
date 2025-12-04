"""Firecrawl-based scraper functions for GearCrew.

This module contains Firecrawl-specific extraction functions that use
the API for structured data extraction with schemas.

Uses SmartFirecrawlClient for automatic self-hosted → cloud fallback.
These are typically used as fallback when Playwright doesn't work,
or for advanced extraction requiring LLM-based schema parsing.
"""

from app.tools.smart_firecrawl import get_smart_firecrawl


def _get_firecrawl_client():
    """Get SmartFirecrawl client instance with self-hosted + cloud fallback."""
    return get_smart_firecrawl()


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

        # Handle response
        if hasattr(result, 'data') and result.data:
            data = result.data[0] if isinstance(result.data, list) else result.data
            return data
        elif isinstance(result, dict):
            return result.get('data', result)
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

        # Handle response
        if hasattr(result, 'data') and result.data:
            return result.data[0] if isinstance(result.data, list) else result.data
        elif isinstance(result, dict):
            return result.get('data', result)
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

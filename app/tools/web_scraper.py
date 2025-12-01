"""Web scraping and search tools using Firecrawl."""

import os
import re
from typing import Optional
from urllib.parse import urlparse

from firecrawl import FirecrawlApp


def _get_firecrawl_client() -> FirecrawlApp:
    """Get Firecrawl client instance."""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY environment variable is required")
    return FirecrawlApp(api_key=api_key)


def _is_product_url(url: str) -> bool:
    """Check if a URL looks like a product page."""
    url_lower = url.lower()
    # Common product page patterns
    product_patterns = [
        r'/product[s]?/',
        r'/p/',
        r'/item/',
        r'/gear/',
        r'/shop/',
        r'/store/',
        r'/buy/',
        r'/collections?/.+/',
        r'/catalog/',
    ]
    for pattern in product_patterns:
        if re.search(pattern, url_lower):
            return True
    return False


def _filter_product_urls(urls: list[str], base_domain: str) -> list[str]:
    """Filter URLs to likely product pages."""
    product_urls = []
    seen = set()

    for url in urls:
        # Skip if already seen or not on same domain
        if url in seen:
            continue
        seen.add(url)

        parsed = urlparse(url)
        if base_domain not in parsed.netloc:
            continue

        # Skip common non-product pages
        skip_patterns = [
            '/cart', '/checkout', '/account', '/login', '/register',
            '/about', '/contact', '/faq', '/help', '/support',
            '/privacy', '/terms', '/shipping', '/returns',
            '/blog', '/news', '/press', '/careers',
            '.pdf', '.jpg', '.png', '.gif',
        ]
        if any(pattern in url.lower() for pattern in skip_patterns):
            continue

        # Prefer URLs that look like product pages
        if _is_product_url(url):
            product_urls.append(url)

    return product_urls


def scrape_webpage(url: str, include_markdown: bool = True) -> str:
    """Scrape content from a webpage.

    Args:
        url: The URL to scrape
        include_markdown: Whether to return markdown format (default: True)

    Returns:
        Scraped content as text or markdown

    Raises:
        ValueError: If scraping fails
    """
    try:
        client = _get_firecrawl_client()

        # New Firecrawl v2 API
        formats = ["markdown"] if include_markdown else ["html"]
        result = client.scrape(url, formats=formats)

        # Handle Document response object
        if hasattr(result, "markdown") and result.markdown:
            return result.markdown
        elif hasattr(result, "html") and result.html:
            return result.html
        elif hasattr(result, "raw_html") and result.raw_html:
            return result.raw_html
        else:
            return str(result)

    except Exception as e:
        raise ValueError(f"Failed to scrape {url}: {str(e)}")


def search_web(query: str, num_results: int = 5) -> list[dict]:
    """Search the web and return results.

    Args:
        query: Search query
        num_results: Number of results to return (default: 5)

    Returns:
        List of search results with url, title, and snippet

    Raises:
        ValueError: If search fails
    """
    try:
        client = _get_firecrawl_client()

        # New Firecrawl v2 API
        result = client.search(query, limit=num_results)

        search_results = []

        # Handle SearchData response - results are in 'web' attribute
        if hasattr(result, "web") and result.web:
            for item in result.web[:num_results]:
                search_results.append(
                    {
                        "url": getattr(item, "url", ""),
                        "title": getattr(item, "title", ""),
                        "snippet": getattr(item, "description", ""),
                    }
                )
        # Fall back to other possible structures
        elif hasattr(result, "results") and result.results:
            for item in result.results[:num_results]:
                search_results.append(
                    {
                        "url": getattr(item, "url", ""),
                        "title": getattr(item, "title", ""),
                        "snippet": getattr(item, "description", ""),
                    }
                )

        return search_results

    except Exception as e:
        raise ValueError(f"Search failed for '{query}': {str(e)}")


def map_website(url: str, max_pages: int = 100) -> dict:
    """Map a website to discover all pages.

    Uses Firecrawl's map() function to crawl a website and find all URLs.
    Useful for discovering product pages on manufacturer websites.

    Args:
        url: Base URL of the website to map
        max_pages: Maximum number of pages to discover

    Returns:
        Dictionary with:
        - all_urls: List of all discovered URLs
        - product_urls: Filtered list of likely product pages
        - count: Total URLs found

    Raises:
        ValueError: If mapping fails
    """
    try:
        client = _get_firecrawl_client()

        # Use Firecrawl map to discover URLs
        result = client.map(url, limit=max_pages)

        # Extract URLs from result
        all_urls = []
        if hasattr(result, 'links') and result.links:
            # Handle LinkResult objects - extract URL string from each
            for link in result.links:
                if hasattr(link, 'url'):
                    all_urls.append(link.url)
                elif isinstance(link, str):
                    all_urls.append(link)
                else:
                    all_urls.append(str(link))
        elif isinstance(result, dict) and 'links' in result:
            all_urls = result['links']
        elif isinstance(result, list):
            all_urls = result

        # Get base domain for filtering
        parsed = urlparse(url)
        base_domain = parsed.netloc.replace('www.', '')

        # Filter to product URLs
        product_urls = _filter_product_urls(all_urls, base_domain)

        return {
            "all_urls": all_urls,
            "product_urls": product_urls,
            "total_count": len(all_urls),
            "product_count": len(product_urls),
        }

    except Exception as e:
        raise ValueError(f"Failed to map website {url}: {str(e)}")


def extract_multiple_products(url: str) -> dict:
    """Extract multiple product references from a list/guide page.

    Uses Firecrawl's extract() with an array schema to pull ALL products
    mentioned on pages like gear guides, comparison articles, or best-of lists.

    Args:
        url: URL of the gear list/guide page

    Returns:
        Dictionary with 'products' array containing basic info for each item

    Raises:
        ValueError: If extraction fails
    """
    schema = {
        "type": "object",
        "properties": {
            "products": {
                "type": "array",
                "description": "All hiking/backpacking gear products mentioned on the page",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Full product name including model"
                        },
                        "brand": {
                            "type": "string",
                            "description": "Brand/manufacturer name"
                        },
                        "category": {
                            "type": "string",
                            "description": "Gear category (backpack, tent, boots, etc.)"
                        },
                        "price": {
                            "type": "number",
                            "description": "Price in USD if mentioned"
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description or why it's recommended"
                        },
                        "affiliate_url": {
                            "type": "string",
                            "description": "Link to product (Amazon, REI, etc.)"
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
            prompt="Extract ALL hiking, backpacking, and outdoor gear products mentioned on this page. Include every product with its brand, category, and any price or link information."
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

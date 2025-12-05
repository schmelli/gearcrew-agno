"""Web scraping and search tools with Playwright-first, Firecrawl-fallback."""

import logging
import os
import re
from urllib.parse import urlparse

import httpx

# Import Playwright scraper functions
from app.tools.browser_scraper import (
    scrape_page_sync,
    extract_products_sync,
    map_website_sync as playwright_map_website,
)

# Import SmartFirecrawlClient
from app.tools.smart_firecrawl import get_smart_firecrawl

# Import Firecrawl-specific functions (for re-export)
from app.tools.firecrawl_scraper import (
    extract_multiple_products,
    extract_product_data,
    batch_extract_products,
)

logger = logging.getLogger(__name__)

# Configuration
USE_PLAYWRIGHT_FIRST = True  # Set to False to use Firecrawl as primary

# Re-export Firecrawl functions for backward compatibility
__all__ = [
    "scrape_webpage",
    "search_web",
    "search_images",
    "search_product_weights",
    "research_product",
    "map_website",
    "extract_multiple_products",
    "extract_product_data",
    "batch_extract_products",
    "quick_count_products",
    "discover_catalog",
]


def _get_firecrawl_client():
    """Get SmartFirecrawl client instance with self-hosted + cloud fallback."""
    return get_smart_firecrawl()


def _is_product_url(url: str) -> bool:
    """Check if a URL looks like a product page."""
    url_lower = url.lower()
    product_patterns = [
        r'/product[s]?/',
        r'/p/',
        r'/item/',
        r'/gear/',
        r'/shop/',
        r'/store/',
        r'/buy/',
        r'/catalog/',
    ]
    for pattern in product_patterns:
        if re.search(pattern, url_lower):
            return True
    return False


def _is_collection_url(url: str) -> bool:
    """Check if a URL looks like a collection/category page."""
    url_lower = url.lower()
    collection_patterns = [
        r'/collections?/[^/]+$',
        r'/categories?/[^/]+$',
        r'/category/[^/]+$',
        r'/c/[^/]+$',
        r'/shop/[^/]+$',
    ]
    for pattern in collection_patterns:
        if re.search(pattern, url_lower):
            return True
    return False


def _filter_product_urls(urls: list[str], base_domain: str) -> tuple[list[str], list[str]]:
    """Filter URLs to product pages and collection pages."""
    url_by_path: dict[str, str] = {}

    for url in urls:
        parsed = urlparse(url)
        if base_domain not in parsed.netloc:
            continue

        skip_patterns = [
            '/cart', '/checkout', '/account', '/login', '/register',
            '/about', '/contact', '/faq', '/help', '/support',
            '/privacy', '/terms', '/shipping', '/returns',
            '/blog', '/news', '/press', '/careers',
            '.pdf', '.jpg', '.png', '.gif',
            '/sitemap', '.xml', '/pages/',
        ]
        if any(pattern in url.lower() for pattern in skip_patterns):
            continue

        path = parsed.path.lower()
        normalized_path = re.sub(r'^/(en-ca|fr-ca|en-gb|en-us|de-de|es-es)/', '/', path)
        is_locale_variant = bool(re.match(r'^/(en-ca|fr-ca|en-gb|en-us|de-de|es-es)/', path))

        if normalized_path not in url_by_path:
            url_by_path[normalized_path] = url
        elif not is_locale_variant:
            url_by_path[normalized_path] = url

    product_urls = []
    collection_urls = []

    for normalized_path, url in url_by_path.items():
        if _is_collection_url(url) or _is_collection_url(f"https://example.com{normalized_path}"):
            collection_urls.append(url)
        elif _is_product_url(url):
            product_urls.append(url)

    return product_urls, collection_urls


def scrape_webpage(url: str, include_markdown: bool = True) -> str:
    """Scrape content from a webpage. Uses Playwright first, Firecrawl fallback."""
    if USE_PLAYWRIGHT_FIRST:
        try:
            logger.info(f"Scraping {url} with Playwright")
            result = scrape_page_sync(url)
            if not result.get("error"):
                return result.get("text", result.get("html", ""))
            logger.warning(f"Playwright failed: {result['error']}")
        except Exception as e:
            logger.warning(f"Playwright failed: {e}")

    try:
        logger.info(f"Scraping {url} with Firecrawl")
        client = _get_firecrawl_client()
        formats = ["markdown"] if include_markdown else ["html"]
        result = client.scrape(url, formats=formats)

        if hasattr(result, "markdown") and result.markdown:
            return result.markdown
        elif hasattr(result, "html") and result.html:
            return result.html
        elif hasattr(result, "raw_html") and result.raw_html:
            return result.raw_html
        return str(result)
    except Exception as e:
        raise ValueError(f"Failed to scrape {url}: {str(e)}")


def search_web(query: str, num_results: int = 5) -> list[dict]:
    """Search the web and return results. Uses Firecrawl API."""
    try:
        client = _get_firecrawl_client()
        result = client.search(query, limit=num_results)

        search_results = []
        if hasattr(result, "web") and result.web:
            for item in result.web[:num_results]:
                search_results.append({
                    "url": getattr(item, "url", ""),
                    "title": getattr(item, "title", ""),
                    "snippet": getattr(item, "description", ""),
                })
        elif hasattr(result, "results") and result.results:
            for item in result.results[:num_results]:
                search_results.append({
                    "url": getattr(item, "url", ""),
                    "title": getattr(item, "title", ""),
                    "snippet": getattr(item, "description", ""),
                })
        return search_results
    except Exception as e:
        raise ValueError(f"Search failed for '{query}': {str(e)}")


def search_images(query: str, num_results: int = 5) -> list[dict]:
    """Search for images using Serper.dev API.

    Returns list of dicts with 'imageUrl', 'title', 'source' keys.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.warning("SERPER_API_KEY not set, image search unavailable")
        return []

    try:
        response = httpx.post(
            "https://google.serper.dev/images",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": num_results},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        images = data.get("images", [])[:num_results]
        return [{"imageUrl": img.get("imageUrl", ""), "title": img.get("title", ""),
                 "source": img.get("source", "")} for img in images]
    except Exception as e:
        logger.error(f"Image search failed for '{query}': {e}")
        return []


def _extract_weights_from_text(text: str) -> list[dict]:
    """Extract weight values from text content."""
    weights = []
    # Match patterns like "Weight: 450g", "12.5 oz", "1 lb 2 oz", "450 grams"
    patterns = [
        (r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\b', 'g'),
        (r'(\d+(?:\.\d+)?)\s*(?:oz|ounces?)\b', 'oz'),
        (r'(\d+(?:\.\d+)?)\s*(?:lb|lbs|pounds?)\b', 'lb'),
        (r'(\d+)\s*lb[s]?\s*(\d+(?:\.\d+)?)\s*oz', 'lb_oz'),  # "1 lb 2 oz"
    ]
    for pattern, unit in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                if unit == 'g':
                    grams = float(match.group(1))
                elif unit == 'oz':
                    grams = float(match.group(1)) * 28.3495
                elif unit == 'lb':
                    grams = float(match.group(1)) * 453.592
                elif unit == 'lb_oz':
                    grams = float(match.group(1)) * 453.592 + float(match.group(2)) * 28.3495
                else:
                    continue
                if 10 < grams < 20000:  # Filter unrealistic weights
                    weights.append({"grams": round(grams), "original": match.group(0)})
            except (ValueError, IndexError):
                continue
    return weights


def search_product_weights(product_name: str, brand: str = "", num_sources: int = 4) -> list[dict]:
    """Search for product weight from multiple online sources."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return []

    query = f"{brand} {product_name} weight specs".strip() if brand else f"{product_name} weight specs"
    results = []
    try:
        resp = httpx.post("https://google.serper.dev/search",
                          headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                          json={"q": query, "num": num_sources * 2}, timeout=10.0)
        resp.raise_for_status()
        organic = resp.json().get("organic", [])

        for item in organic[:num_sources * 2]:
            url, snippet = item.get("link", ""), item.get("snippet", "")
            weights = _extract_weights_from_text(snippet)
            if weights:
                results.append({"source": urlparse(url).netloc.replace("www.", ""), "url": url,
                                "title": item.get("title", ""), "weight_grams": weights[0]["grams"],
                                "original_text": weights[0]["original"], "snippet": snippet[:200]})
                if len(results) >= num_sources:
                    break

        # If not enough, try scraping pages
        if len(results) < 2:
            for item in organic[:4]:
                if len(results) >= num_sources:
                    break
                url = item.get("link", "")
                if any(r["url"] == url for r in results):
                    continue
                try:
                    weights = _extract_weights_from_text(scrape_webpage(url)[:5000])
                    if weights:
                        results.append({"source": urlparse(url).netloc.replace("www.", ""), "url": url,
                                        "title": item.get("title", ""), "weight_grams": weights[0]["grams"],
                                        "original_text": weights[0]["original"], "snippet": item.get("snippet", "")[:200]})
                except Exception:
                    continue
        return results[:num_sources]
    except Exception as e:
        logger.error(f"Weight search failed: {e}")
        return []


def research_product(product_name: str, brand: str = "", num_results: int = 5) -> list[dict]:
    """Research a product online to gather specs and verify information.

    Searches for product information and returns structured results with
    key specs like weight, price, category, and descriptions.

    Args:
        product_name: Name of the product to research
        brand: Optional brand name for more accurate results
        num_results: Number of search results to return

    Returns:
        List of dicts with 'title', 'url', 'snippet', 'source', and extracted specs
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.warning("SERPER_API_KEY not set, product research unavailable")
        return []

    query = f"{brand} {product_name} specs specifications".strip() if brand else f"{product_name} specs"
    results = []

    try:
        resp = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": num_results * 2},
            timeout=10.0,
        )
        resp.raise_for_status()
        organic = resp.json().get("organic", [])

        for item in organic[:num_results]:
            url = item.get("link", "")
            snippet = item.get("snippet", "")
            title = item.get("title", "")

            # Extract any weights from snippet
            weights = _extract_weights_from_text(snippet)
            weight_grams = weights[0]["grams"] if weights else None

            # Extract price from snippet
            price_match = re.search(r'\$(\d+(?:\.\d{2})?)', snippet)
            price_usd = float(price_match.group(1)) if price_match else None

            results.append({
                "title": title,
                "url": url,
                "source": urlparse(url).netloc.replace("www.", ""),
                "snippet": snippet[:300],
                "weight_grams": weight_grams,
                "price_usd": price_usd,
            })

        return results
    except Exception as e:
        logger.error(f"Product research failed for '{product_name}': {e}")
        return []


def map_website(url: str, max_pages: int = 100) -> dict:
    """Map a website to discover all pages. Uses Playwright first, Firecrawl fallback."""
    if USE_PLAYWRIGHT_FIRST:
        try:
            logger.info(f"Mapping {url} with Playwright")
            result = playwright_map_website(url, max_pages=max_pages)
            if not result.get("error"):
                collection_urls = result.get("all_collection_urls", [])
                return {
                    "all_urls": collection_urls,
                    "product_urls": [],
                    "collection_urls": collection_urls,
                    "total_count": len(collection_urls),
                    "product_count": 0,
                    "collection_count": len(collection_urls),
                    "categories": result.get("categories", []),
                    "brand_name": result.get("brand_name", ""),
                }
            logger.warning(f"Playwright failed: {result['error']}")
        except Exception as e:
            logger.warning(f"Playwright failed: {e}")

    try:
        logger.info(f"Mapping {url} with Firecrawl")
        client = _get_firecrawl_client()
        result = client.map(url, limit=max_pages)

        all_urls = []
        if hasattr(result, 'links') and result.links:
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

        parsed = urlparse(url)
        base_domain = parsed.netloc.replace('www.', '')
        product_urls, collection_urls = _filter_product_urls(all_urls, base_domain)

        return {
            "all_urls": all_urls,
            "product_urls": product_urls,
            "collection_urls": collection_urls,
            "total_count": len(all_urls),
            "product_count": len(product_urls),
            "collection_count": len(collection_urls),
        }
    except Exception as e:
        raise ValueError(f"Failed to map website {url}: {str(e)}")


def quick_count_products(url: str) -> dict:
    """Quickly count products on a collection page. Playwright first, Firecrawl fallback."""
    if USE_PLAYWRIGHT_FIRST:
        try:
            logger.info(f"Quick counting at {url} with Playwright")
            result = extract_products_sync(url)
            if not result.get("error"):
                products = result.get("products", [])
                return {
                    "url": url,
                    "category_name": result.get("category_name", _extract_category_from_url(url)),
                    "product_count": len(products),
                    "product_names": [p.get("name", "") for p in products if p.get("name")],
                    "has_subcategories": False,
                    "subcategory_names": [],
                }
            logger.warning(f"Playwright failed: {result['error']}")
        except Exception as e:
            logger.warning(f"Playwright failed: {e}")

    try:
        logger.info(f"Quick counting at {url} with Firecrawl")
        client = _get_firecrawl_client()
        result = client.scrape(url, formats=["markdown"])

        content = ""
        if hasattr(result, "markdown") and result.markdown:
            content = result.markdown
        elif hasattr(result, "html") and result.html:
            content = result.html

        product_names = _parse_products_from_content(content)
        return {
            "url": url,
            "category_name": _extract_category_from_url(url),
            "product_count": len(product_names),
            "product_names": product_names,
            "has_subcategories": False,
            "subcategory_names": [],
        }
    except Exception as e:
        return {
            "url": url,
            "category_name": _extract_category_from_url(url),
            "product_count": 0,
            "product_names": [],
            "error": str(e),
        }


def _parse_products_from_content(content: str) -> list[str]:
    """Parse product names from page content."""
    product_names = []
    skip_patterns = ['cart', 'checkout', 'login', 'sign up', 'newsletter',
                   'contact', 'about us', 'footer', 'header', 'menu',
                   'privacy', 'terms', 'cookie', 'subscribe']
    noise_patterns = [
        'you are', 'sale price', 'price', 'regular price', 'or 4 interest',
        'add to cart', 'buy now', 'shop now', 'view all', 'see all',
        'learn more', 'read more', 'click here', 'installment',
        'free shipping', 'in stock', 'out of stock', 'sold out',
        'reviews', 'rating', 'compare', 'wishlist', 'favorite',
    ]

    for line in content.split('\n'):
        line = line.strip()
        if not line or any(p in line.lower() for p in skip_patterns):
            continue

        if re.search(r'\$\d+', line):
            match = re.match(r'^[\*\#\s]*\[?([^\]$\n]+?)[\]]*\s*[\(\[]?\$', line)
            if match:
                name = match.group(1).strip(' *#[]|')
                if 3 < len(name) < 100:
                    product_names.append(name)

        for name in re.findall(r'\[([^\]]+)\]\([^)]+/products?/[^)]+\)', line):
            name = name.strip()
            if 3 < len(name) < 100 and name not in product_names:
                product_names.append(name)

    seen = set()
    unique = []
    for name in product_names:
        name_lower = name.lower().strip()
        if any(p in name_lower for p in noise_patterns) or len(name_lower) < 5:
            continue
        if name_lower not in seen:
            seen.add(name_lower)
            unique.append(name)
    return unique


def _extract_category_from_url(url: str) -> str:
    """Extract category name from URL."""
    parsed = urlparse(url)
    segments = [s for s in parsed.path.rstrip('/').split('/') if s]
    if segments:
        return segments[-1].replace('-', ' ').replace('_', ' ').title()
    return "Unknown Category"


def discover_catalog(url: str, max_pages: int = 300) -> dict:
    """Discover a manufacturer's product catalog. Playwright first, Firecrawl fallback."""
    if USE_PLAYWRIGHT_FIRST:
        try:
            logger.info(f"Discovering catalog for {url} with Playwright")
            result = playwright_map_website(url, max_pages=max_pages)
            if not result.get("error"):
                return {
                    "brand_name": result.get("brand_name", "Unknown"),
                    "website_url": url,
                    "total_categories": result.get("total_categories", 0),
                    "total_products_estimated": result.get("total_products_estimated", 0),
                    "individual_product_pages": result.get("individual_product_pages", 0),
                    "categories": result.get("categories", []),
                    "product_urls": [],
                }
            logger.warning(f"Playwright failed: {result['error']}")
        except Exception as e:
            logger.warning(f"Playwright failed: {e}")

    try:
        logger.info(f"Discovering catalog for {url} with Firecrawl")
        map_result = map_website(url, max_pages=max_pages)

        collection_urls = map_result.get('collection_urls', [])
        product_urls = map_result.get('product_urls', [])

        categories = []
        total_products = 0
        for coll_url in collection_urls:
            count_result = quick_count_products(coll_url)
            categories.append(count_result)
            total_products += count_result.get('product_count', 0)

        categories.sort(key=lambda x: x.get('product_count', 0), reverse=True)

        parsed = urlparse(url)
        brand_name = parsed.netloc.replace('www.', '').split('.')[0].title()

        return {
            "brand_name": brand_name,
            "website_url": url,
            "total_categories": len(categories),
            "total_products_estimated": total_products,
            "individual_product_pages": len(product_urls),
            "categories": categories,
            "product_urls": product_urls[:20],
        }
    except Exception as e:
        raise ValueError(f"Failed to discover catalog for {url}: {str(e)}")

"""Playwright-based browser scraper for GearCrew.

Primary scraping method using local browser automation.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# E-commerce selectors (Shopify and common patterns)
PRODUCT_SELECTORS = [
    ".product-card", ".product-item", ".product-grid-item", "[data-product-id]",
    ".grid__item .card", ".product", ".product-tile",
    'a[href*="/products/"]', 'a[href*="/product/"]',  # Both plural and singular
    ".woocommerce-loop-product__link",  # WooCommerce
]
PRODUCT_NAME_SELECTORS = [
    ".product-card__title", ".product-item__title", ".product__title",
    ".card__heading", ".product-title", ".product-name", "[data-product-title]",
    ".woocommerce-loop-product__title",  # WooCommerce
    "h2", "h3",  # Fallback headings
]
PRODUCT_PRICE_SELECTORS = [".price", ".product-price", ".money", "[data-price]", ".amount"]
COLLECTION_LINK_SELECTORS = [
    'a[href*="/collections/"]', 'a[href*="/category/"]',
    'a[href*="/product-category/"]',  # WooCommerce
    ".nav a", ".menu a",
]

# URLs to exclude from categories (non-product pages)
NON_PRODUCT_URL_PATTERNS = [
    "/faq", "/terms", "/privacy", "/policy", "/policies",
    "/shipping", "/returns", "/contact", "/about",
    "/payment", "/pricing", "/production-time",
    "/company", "/legal", "/impressum", "/agb",
    "/customers-outside", "/free-shipping",
    "/cart", "/checkout", "/account", "/login", "/register",
    "/blog", "/news", "/press",
]

# Category name patterns that indicate non-product pages
NON_PRODUCT_CATEGORY_NAMES = [
    "faq", "terms", "conditions", "privacy", "policy",
    "shipping", "returns", "contact", "about us", "about",
    "payment", "pricing", "production time", "production",
    "company", "legal", "impressum", "agb",
    "customers outside", "free shipping",
    "cart", "checkout", "account", "login", "register",
    "blog", "news", "press",
]


def _is_product_url(url: str) -> bool:
    """Check if URL looks like a product page."""
    path = urlparse(url).path.lower()
    # Check for non-product patterns
    for pattern in NON_PRODUCT_URL_PATTERNS:
        if pattern in path:
            return False
    # Check for product patterns
    return "/product/" in path or "/products/" in path


def _is_non_product_category(name: str) -> bool:
    """Check if category name indicates a non-product page."""
    name_lower = name.lower().strip()
    for pattern in NON_PRODUCT_CATEGORY_NAMES:
        if pattern in name_lower or name_lower in pattern:
            return True
    return False


class BrowserScraper:
    """Playwright-based scraper for manufacturer websites."""

    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Start the browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

    async def close(self):
        """Close the browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _new_page(self) -> Page:
        """Create a new page with common settings."""
        if not self._browser:
            await self.start()

        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        page.set_default_timeout(self.timeout)
        return page

    async def scrape_page(self, url: str) -> dict:
        """Scrape a single page and return its content.

        Returns:
            dict with keys: url, title, html, text, links
        """
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="load")
            await self._wait_for_content(page)

            title = await page.title()
            html = await page.content()
            text = await page.inner_text("body")

            # Extract all links
            links = await page.eval_on_selector_all(
                "a[href]",
                "elements => elements.map(e => ({href: e.href, text: e.innerText.trim()}))"
            )

            return {
                "url": url,
                "title": title,
                "html": html,
                "text": text,
                "links": links,
            }
        except PlaywrightTimeout:
            logger.warning(f"Timeout scraping {url}")
            return {"url": url, "error": "Timeout"}
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return {"url": url, "error": str(e)}
        finally:
            await page.context.close()

    async def _wait_for_content(self, page: Page):
        """Wait for dynamic content to load."""
        # Try to wait for common product containers
        for selector in PRODUCT_SELECTORS[:3]:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                return
            except PlaywrightTimeout:
                continue

        # Fallback: wait a bit for any JS to execute
        await page.wait_for_timeout(2000)

    async def extract_products_from_collection(self, url: str) -> dict:
        """Extract product information from a collection/category page.

        Returns:
            dict with keys: url, category_name, products, product_count
        """
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="load")
            await self._wait_for_content(page)

            # Try to get category name from page title or h1
            category_name = await self._extract_category_name(page, url)

            # Extract products using various selectors
            products = await self._extract_products(page, url)

            return {
                "url": url,
                "category_name": category_name,
                "products": products,
                "product_count": len(products),
            }
        except PlaywrightTimeout:
            logger.warning(f"Timeout extracting products from {url}")
            return {"url": url, "error": "Timeout", "products": [], "product_count": 0}
        except Exception as e:
            logger.error(f"Error extracting products from {url}: {e}")
            return {"url": url, "error": str(e), "products": [], "product_count": 0}
        finally:
            await page.context.close()

    async def _extract_category_name(self, page: Page, url: str) -> str:
        """Extract category name from page."""
        try:
            h1 = await page.query_selector("h1")
            if h1 and (text := await h1.inner_text()) and text.strip():
                return text.strip()
        except Exception:
            pass
        try:
            if title := await page.title():
                return re.split(r'\s*[\|–-]\s*', title)[0].strip()
        except Exception:
            pass

        # Fallback: extract from URL
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p and p not in ("collections", "category")]
        if parts:
            return parts[-1].replace("-", " ").replace("_", " ").title()

        return "Unknown Category"

    async def _extract_products(self, page: Page, base_url: str) -> list[dict]:
        """Extract product information from page."""
        products = []
        seen_urls = set()

        # Method 1: Try to find product cards with structured data
        for selector in PRODUCT_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                if not elements:
                    continue

                for element in elements:
                    product = await self._extract_product_from_element(element, base_url)
                    if product and product.get("url") and product["url"] not in seen_urls:
                        seen_urls.add(product["url"])
                        products.append(product)

                if products:
                    break  # Found products with this selector
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue

        # Method 2: If no products found, try extracting from product links
        if not products:
            products = await self._extract_products_from_links(page, base_url, seen_urls)

        return products

    async def _extract_product_from_element(self, element, base_url: str) -> Optional[dict]:
        """Extract product info from a product card element."""
        try:
            link = await element.query_selector("a[href]")
            href = await (link.get_attribute("href") if link else element.get_attribute("href"))
            if not href:
                return None
            # Check if it's a product URL (handles /product/ and /products/)
            if not _is_product_url(href):
                return None

            product_url = urljoin(base_url, href)
            name = None
            for selector in PRODUCT_NAME_SELECTORS:
                try:
                    if name_elem := await element.query_selector(selector):
                        if name := await name_elem.inner_text():
                            break
                except Exception:
                    continue
            if not name:
                try:
                    name = (await element.inner_text()).split("\n")[0].strip()
                except Exception:
                    return None
            if not name:
                return None

            price = None
            for selector in PRODUCT_PRICE_SELECTORS:
                try:
                    if price_elem := await element.query_selector(selector):
                        if price := await price_elem.inner_text():
                            break
                except Exception:
                    continue

            return {"name": name.strip()[:200], "url": product_url, "price": price.strip() if price else None}
        except Exception:
            return None

    async def _extract_products_from_links(
        self, page: Page, base_url: str, seen_urls: set
    ) -> list[dict]:
        """Extract products by finding product links on the page."""
        products = []

        try:
            # Match both /product/ (singular) and /products/ (plural)
            links = await page.eval_on_selector_all(
                'a[href*="/product"]',
                """elements => elements.map(e => ({
                    href: e.href,
                    text: e.innerText.trim(),
                    title: e.title || ''
                }))"""
            )

            for link in links:
                href = link.get("href", "")
                if not href or href in seen_urls:
                    continue

                # Skip non-product links using our filter
                if not _is_product_url(href):
                    continue

                # Skip anchor/script links
                if any(x in href.lower() for x in ["#", "javascript:", "mailto:"]):
                    continue

                name = link.get("text") or link.get("title") or ""
                name = name.split("\n")[0].strip()

                if name and len(name) > 2 and len(name) < 200:
                    seen_urls.add(href)
                    products.append({
                        "name": name,
                        "url": href,
                        "price": None,
                    })
        except Exception as e:
            logger.debug(f"Error extracting products from links: {e}")

        return products

    async def discover_collection_urls(self, url: str) -> dict:
        """Discover all collection/category URLs from a website.

        Returns:
            dict with keys: base_url, collections, product_pages
        """
        page = await self._new_page()
        try:
            # Use 'load' instead of 'networkidle' for better reliability
            # Many modern sites never reach networkidle due to analytics/tracking
            await page.goto(url, wait_until="load")
            await page.wait_for_timeout(3000)  # Give extra time for JS to render

            base_domain = urlparse(url).netloc
            collections = set()
            product_pages = set()

            # Get all links from the page
            links = await page.eval_on_selector_all(
                "a[href]",
                "elements => elements.map(e => e.href)"
            )

            for href in links:
                if not href or not isinstance(href, str):
                    continue

                parsed = urlparse(href)
                if parsed.netloc and parsed.netloc != base_domain:
                    continue  # Skip external links

                path = parsed.path.lower()

                # Skip locale variants, keep base paths
                normalized_path = re.sub(r'^/(en-ca|fr-ca|en-us|fr|de|es)/', '/', path)

                if "/collections/" in normalized_path or "/category/" in normalized_path:
                    # Skip pagination and filter URLs
                    if "?" not in href and "#" not in href:
                        collections.add(href)
                elif "/products/" in normalized_path or "/product/" in normalized_path:
                    product_pages.add(href)

            # Also check navigation menus for more collections
            nav_collections = await self._extract_nav_collections(page, base_domain)
            collections.update(nav_collections)

            return {
                "base_url": url,
                "collections": list(collections),
                "product_pages": list(product_pages),
                "collection_count": len(collections),
                "product_page_count": len(product_pages),
            }
        except PlaywrightTimeout:
            logger.warning(f"Timeout discovering collections from {url}")
            return {"base_url": url, "error": "Timeout", "collections": [], "product_pages": []}
        except Exception as e:
            logger.error(f"Error discovering collections from {url}: {e}")
            return {"base_url": url, "error": str(e), "collections": [], "product_pages": []}
        finally:
            await page.context.close()

    async def _extract_nav_collections(self, page: Page, base_domain: str) -> set:
        """Extract collection URLs from navigation menus."""
        collections = set()

        # Try to expand any dropdown menus
        try:
            # Hover over nav items to reveal dropdowns
            nav_items = await page.query_selector_all(
                ".nav-item, .menu-item, [data-dropdown], .has-dropdown"
            )
            for item in nav_items[:10]:  # Limit to first 10
                try:
                    await item.hover()
                    await page.wait_for_timeout(300)
                except Exception:
                    continue
        except Exception:
            pass

        # Now extract collection links
        for selector in COLLECTION_LINK_SELECTORS:
            try:
                links = await page.eval_on_selector_all(
                    selector,
                    "elements => elements.map(e => e.href)"
                )
                for href in links:
                    if href and base_domain in href:
                        if "?" not in href and "#" not in href:
                            collections.add(href)
            except Exception:
                continue

        return collections

    async def map_website(self, url: str, max_pages: int = 100) -> dict:
        """Map a website by crawling from the homepage.

        This discovers all collection pages and counts products.
        Also handles non-Shopify sites that use /products/ or /product/ pages.

        Returns:
            dict with website structure
        """
        # First discover collections from homepage
        discovery = await self.discover_collection_urls(url)

        if discovery.get("error"):
            return discovery

        collections = discovery.get("collections", [])
        product_pages = set(discovery.get("product_pages", []))

        # Deduplicate and filter collections
        seen_paths = set()
        unique_collections = []
        for coll_url in collections:
            path = urlparse(coll_url).path.lower()
            # Normalize locale prefixes
            normalized = re.sub(r'^/(en-ca|fr-ca|en-us|fr|de|es)/', '/', path)
            # Skip non-product pages
            skip = False
            for pattern in NON_PRODUCT_URL_PATTERNS:
                if pattern in normalized:
                    skip = True
                    break
            if not skip and normalized not in seen_paths:
                seen_paths.add(normalized)
                unique_collections.append(coll_url)

        # Limit collections to crawl
        collections_to_crawl = unique_collections[:max_pages]

        # Crawl each collection to count products
        categories = []
        for coll_url in collections_to_crawl:
            result = await self.extract_products_from_collection(coll_url)
            if result.get("products"):
                cat_name = result.get("category_name", "Unknown")
                # Skip non-product category names
                if _is_non_product_category(cat_name):
                    continue
                categories.append({
                    "url": coll_url,
                    "category_name": cat_name,
                    "product_count": result.get("product_count", 0),
                    "product_names": [p["name"] for p in result.get("products", [])[:10]],
                })
                # Add discovered product pages
                for p in result.get("products", []):
                    if p.get("url"):
                        product_pages.add(p["url"])

        # If no collections found, try to extract products directly from common product list URLs
        if not categories:
            logger.info(f"No collections found, trying direct product extraction from {url}")
            base_url = url.rstrip("/")
            product_list_urls = [
                f"{base_url}/products/",
                f"{base_url}/products",
                f"{base_url}/shop/",
                f"{base_url}/shop",
                base_url,  # Try homepage itself
            ]

            for list_url in product_list_urls:
                result = await self.extract_products_from_collection(list_url)
                products = result.get("products", [])
                if products:
                    # Filter out non-product URLs
                    filtered_products = [
                        p for p in products if p.get("url") and _is_product_url(p["url"])
                    ]
                    if filtered_products:
                        categories.append({
                            "url": list_url,
                            "category_name": "All Products",
                            "product_count": len(filtered_products),
                            "product_names": [p["name"] for p in filtered_products[:10]],
                        })
                        for p in filtered_products:
                            product_pages.add(p["url"])
                        break  # Found products, stop trying

        # Extract brand name from URL
        domain = urlparse(url).netloc.replace("www.", "")
        brand_name = domain.split(".")[0].replace("-", " ").title()

        return {
            "website_url": url,
            "brand_name": brand_name,
            "categories": categories,
            "total_categories": len(categories),
            "total_products_estimated": sum(c.get("product_count", 0) for c in categories),
            "individual_product_pages": len(product_pages),
            "all_collection_urls": unique_collections,
        }


# Synchronous wrapper functions for non-async code
def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


def scrape_page_sync(url: str) -> dict:
    """Synchronous wrapper for scrape_page."""
    async def _scrape():
        async with BrowserScraper() as scraper:
            return await scraper.scrape_page(url)
    return _run_async(_scrape())


def extract_products_sync(url: str) -> dict:
    """Synchronous wrapper for extract_products_from_collection."""
    async def _extract():
        async with BrowserScraper() as scraper:
            return await scraper.extract_products_from_collection(url)
    return _run_async(_extract())


def discover_collections_sync(url: str) -> dict:
    """Synchronous wrapper for discover_collection_urls."""
    async def _discover():
        async with BrowserScraper() as scraper:
            return await scraper.discover_collection_urls(url)
    return _run_async(_discover())


def map_website_sync(url: str, max_pages: int = 100) -> dict:
    """Synchronous wrapper for map_website."""
    async def _map():
        async with BrowserScraper() as scraper:
            return await scraper.map_website(url, max_pages)
    return _run_async(_map())

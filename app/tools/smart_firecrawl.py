"""Smart Firecrawl client with self-hosted primary and cloud fallback.

Uses self-hosted Firecrawl instance (free) as primary, with automatic
fallback to cloud API (paid) on failure. Includes retry logic, timeout
handling, and usage statistics tracking.

Note: Self-hosted Firecrawl uses v1 API, cloud uses v2 API via library.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx
from firecrawl import FirecrawlApp

logger = logging.getLogger(__name__)


class ScrapeMode(str, Enum):
    """Scraping mode selection for SmartFirecrawlClient."""

    AUTO = "auto"  # Try Firecrawl first, fall back to Playwright if blocked
    FIRECRAWL = "firecrawl"  # Only use Firecrawl (cloud)
    PLAYWRIGHT = "playwright"  # Only use Playwright browser


class ScrapeCache:
    """File-based cache for scrape results to avoid re-scraping the same URLs."""

    def __init__(self, cache_dir: str = ".cache/firecrawl_scrapes", max_age_days: int = 30):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = max_age_days
        self._hits = 0
        self._misses = 0

    def _get_cache_path(self, url: str) -> Path:
        """Get the cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{url_hash}.json"

    def get(self, url: str) -> Optional[dict]:
        """Retrieve cached scrape result for a URL."""
        cache_path = self._get_cache_path(url)

        if not cache_path.exists():
            self._misses += 1
            return None

        try:
            with open(cache_path, "r") as f:
                data = json.load(f)

            # Check if cache is expired
            cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            if datetime.now() - cached_at > timedelta(days=self.max_age_days):
                cache_path.unlink()
                self._misses += 1
                logger.debug(f"Cache expired for {url}")
                return None

            self._hits += 1
            logger.info(f"[Cache HIT] Using cached scrape for {url[:60]}...")
            return data.get("result")

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Invalid cache entry for {url}: {e}")
            cache_path.unlink(missing_ok=True)
            self._misses += 1
            return None

    def set(self, url: str, result: dict) -> None:
        """Store scrape result in cache."""
        cache_path = self._get_cache_path(url)

        # Ensure result is a simple dict with only string values
        safe_result = {
            "markdown": str(result.get("markdown", "")),
            "html": str(result.get("html", "")),
            "metadata": result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {},
        }

        data = {
            "url": url,
            "cached_at": datetime.now().isoformat(),
            "result": safe_result,
        }

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Cached scrape result for {url[:60]}...")
        except Exception as e:
            logger.warning(f"Failed to cache scrape result: {e}")
            # Remove partial file if it exists
            cache_path.unlink(missing_ok=True)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_percent": round(hit_rate, 1),
        }

    def clear_expired(self) -> int:
        """Remove expired cache entries. Returns count of removed entries."""
        removed = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
                if datetime.now() - cached_at > timedelta(days=self.max_age_days):
                    cache_file.unlink()
                    removed += 1
            except Exception:
                pass
        return removed


@dataclass
class UsageStats:
    """Track Firecrawl usage statistics."""
    self_hosted_calls: int = 0
    cloud_calls: int = 0
    total_credits: int = 0
    self_hosted_failures: int = 0

    @property
    def estimated_cost(self) -> float:
        """Estimated cost in USD (~$0.005 per credit)."""
        return self.total_credits * 0.005

    @property
    def self_hosted_percentage(self) -> float:
        """Percentage of calls handled by self-hosted."""
        total = self.self_hosted_calls + self.cloud_calls
        return (self.self_hosted_calls / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for reporting."""
        return {
            "self_hosted_calls": self.self_hosted_calls,
            "cloud_calls": self.cloud_calls,
            "total_credits": self.total_credits,
            "estimated_cost_usd": self.estimated_cost,
            "self_hosted_percentage": round(self.self_hosted_percentage, 1),
            "self_hosted_failures": self.self_hosted_failures,
        }


@dataclass
class FirecrawlConfig:
    """Configuration for SmartFirecrawlClient."""
    self_hosted_url: str = ""
    self_hosted_key: str = "local-dev-key"
    cloud_api_key: str = ""
    timeout: float = 30.0
    max_retries: int = 2
    enable_fallback: bool = True

    @classmethod
    def from_env(cls) -> "FirecrawlConfig":
        """Load configuration from environment variables."""
        return cls(
            self_hosted_url=os.getenv("FIRECRAWL_SELF_HOSTED_URL", ""),
            self_hosted_key=os.getenv("FIRECRAWL_SELF_HOSTED_KEY", "local-dev-key"),
            cloud_api_key=os.getenv("FIRECRAWL_API_KEY", ""),
            timeout=float(os.getenv("FIRECRAWL_TIMEOUT", "30")),
            max_retries=int(os.getenv("FIRECRAWL_MAX_RETRIES", "2")),
            enable_fallback=os.getenv("FIRECRAWL_ENABLE_FALLBACK", "true").lower() == "true",
        )


@dataclass
class ScrapeResult:
    """Result from a scrape operation."""
    success: bool
    data: Any = None
    markdown: str = ""
    html: str = ""
    metadata: dict = field(default_factory=dict)
    source: str = ""  # "self-hosted" or "cloud"
    cost: int = 0
    error: str = ""


class SelfHostedFirecrawl:
    """Direct HTTP client for self-hosted Firecrawl v1 API."""

    def __init__(self, api_url: str, api_key: str, timeout: float = 30.0):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def scrape(self, url: str, formats: list[str] = None, **kwargs) -> dict:
        """Scrape a URL using v1 API."""
        endpoint = f"{self.api_url}/v1/scrape"
        payload = {"url": url}
        if formats:
            payload["formats"] = formats
        payload.update(kwargs)

        response = httpx.post(endpoint, headers=self._headers(), json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            raise ValueError(data.get("error", "Scrape failed"))
        return data.get("data", {})

    def search(self, query: str, limit: int = 5) -> dict:
        """Search using v1 API."""
        endpoint = f"{self.api_url}/v1/search"
        payload = {"query": query, "limit": limit}

        response = httpx.post(endpoint, headers=self._headers(), json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def map(self, url: str, limit: int = 100) -> dict:
        """Map a website using v1 API."""
        endpoint = f"{self.api_url}/v1/map"
        payload = {"url": url, "limit": limit}

        response = httpx.post(endpoint, headers=self._headers(), json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            raise ValueError(data.get("error", "Map failed"))
        return data

    # NOTE: extract() is NOT supported by self-hosted Firecrawl v1
    # The /v1/extract endpoint doesn't exist on self-hosted instances
    # Use SmartFirecrawlClient.extract() which goes directly to cloud


class PlaywrightScraper:
    """Fallback scraper using Playwright for sites that block Firecrawl."""

    # Markers that indicate a 404/blocked page
    BLOCKED_MARKERS = ['wegweiser404', 'Seite nicht gefunden', 'Page not found', '404-banner']

    @staticmethod
    def is_blocked_response(content: str) -> bool:
        """Check if content looks like a 404/blocked page."""
        if not content or len(content) < 500:
            return True
        return any(marker in content for marker in PlaywrightScraper.BLOCKED_MARKERS)

    @staticmethod
    def discover_urls(base_url: str, max_urls: int = 500) -> list[str]:
        """Discover all URLs on a website using Playwright browser.

        Crawls the homepage and navigates through categories to find product URLs.

        Args:
            base_url: Starting URL (usually homepage)
            max_urls: Maximum number of URLs to collect

        Returns:
            List of discovered URLs
        """
        try:
            from playwright.sync_api import sync_playwright
            from urllib.parse import urljoin, urlparse
        except ImportError:
            logger.warning("Playwright not installed, cannot discover URLs")
            return []

        try:
            logger.info(f"[Playwright] Starting URL discovery from {base_url}")
            parsed_base = urlparse(base_url)
            base_domain = parsed_base.netloc

            discovered_urls: set[str] = set()
            visited_pages: set[str] = set()
            pages_to_visit = [base_url]
            category_pages: list[str] = []
            cookies_accepted = False

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                )
                page = context.new_page()

                def extract_links_from_page():
                    """Extract all links from current page."""
                    return page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href]'))
                            .map(a => a.href)
                            .filter(href => href && href.startsWith('http') && !href.includes('#'));
                    }''')

                def is_category_url(path: str) -> bool:
                    """Check if URL looks like a category page."""
                    path_lower = path.lower()

                    # Exclude common non-category pages
                    non_categories = [
                        'konto', 'login', 'passwort', 'account', 'cart', 'checkout',
                        'wishlist', 'merkzettel', 'vergleich', 'bestellstatus',
                        'kontakt', 'faq', 'hilfe', 'help', 'service', 'impressum',
                        'datenschutz', 'agb', 'versand', 'rueckgabe', 'zahlungs',
                        'newsletter', 'blog', 'jobs', 'basislager', 'marken/'
                    ]
                    if any(excl in path_lower for excl in non_categories):
                        return False

                    # Category indicators - product listing pages
                    category_indicators = [
                        '/outdoor-', '/fuer--', '/jacken', '/hosen', '/schuhe',
                        '/bekleidung', '/ausruestung', '/zubehoer', '/accessoires',
                        '/zelte', '/schlafsaecke', '/rucksaecke', '/kocher',
                        '/klettern', '/camping', '/trekking', '/wandern',
                        '/ski', '/winter', '/bike', '/lauf', '/trail',
                        '-hose', '-jacke', '-schuh', 'westen', 'pullover',
                        'shirts', 'handschuhe', 'socken', 'unterwaesche'
                    ]
                    if any(cat in path_lower for cat in category_indicators):
                        return True

                    # Short root-level paths that are likely categories
                    parts = path.strip('/').split('/')
                    if len(parts) <= 2:
                        slug = parts[-1]
                        # Short plural words are often categories
                        if slug.endswith('en') or slug.endswith('e') or slug.endswith('s'):
                            if len(slug) < 25 and slug.count('-') < 3:
                                return True

                    return False

                def is_product_url(path: str) -> bool:
                    """Check if URL looks like a product page."""
                    parts = path.strip('/').split('/')
                    if len(parts) == 1:
                        slug = parts[0]
                        # Products are typically long slugs with brand-model-type pattern
                        return len(slug) > 25 and slug.count('-') >= 3
                    return False

                # Phase 1: Crawl homepage to find categories
                logger.info(f"[Playwright] Phase 1: Crawling homepage for categories")
                try:
                    page.goto(base_url, wait_until='networkidle', timeout=20000)
                    page.wait_for_timeout(2000)

                    # Accept cookies
                    for selector in ['button:has-text("Akzeptieren")', 'button:has-text("Accept")', '[data-testid="cookie-accept"]']:
                        try:
                            page.click(selector, timeout=2000)
                            cookies_accepted = True
                            page.wait_for_timeout(500)
                            break
                        except:
                            pass

                    links = extract_links_from_page()
                    for link in links:
                        parsed = urlparse(link)
                        if parsed.netloc != base_domain:
                            continue
                        path = parsed.path.rstrip('/')
                        if not path or path == '/':
                            continue

                        # Skip utility pages
                        path_lower = path.lower()
                        if any(skip in path_lower for skip in [
                            '/login', '/cart', '/checkout', '/account', '/wishlist', '/konto',
                            '/search', '/newsletter', '/service', '/hilfe', '/help', '/faq',
                            '/impressum', '/datenschutz', '/agb', '/kontakt', '/versand',
                            '/rueckgabe', '/zahlungsmittel', '/bestellstatus', '/mein-',
                            '.pdf', '.jpg', '.png', '.gif', '/blog/', '/jobs/', '/basislager'
                        ]):
                            continue

                        clean_url = f"https://{base_domain}{path}"
                        discovered_urls.add(clean_url)

                        if is_category_url(path) and clean_url not in category_pages:
                            category_pages.append(clean_url)

                    visited_pages.add(base_url)
                    logger.info(f"[Playwright] Found {len(category_pages)} category URLs from homepage")

                except Exception as e:
                    logger.error(f"[Playwright] Homepage crawl failed: {e}")

                # Phase 2: Crawl category pages to find products
                logger.info(f"[Playwright] Phase 2: Crawling category pages for products")
                max_categories = min(15, len(category_pages))  # Limit to 15 category pages
                product_count = sum(1 for u in discovered_urls if is_product_url(urlparse(u).path))

                for i, cat_url in enumerate(category_pages[:max_categories]):
                    # Stop when we have enough PRODUCT URLs (not just any URLs)
                    if product_count >= max_urls:
                        logger.info(f"[Playwright] Reached {product_count} product URLs, stopping")
                        break

                    if cat_url in visited_pages:
                        continue
                    visited_pages.add(cat_url)

                    try:
                        logger.info(f"[Playwright] ({i+1}/{max_categories}) Visiting category: {cat_url}")
                        page.goto(cat_url, wait_until='networkidle', timeout=20000)
                        page.wait_for_timeout(1500)

                        # Scroll to load lazy content
                        page.evaluate('window.scrollTo(0, document.body.scrollHeight / 3)')
                        page.wait_for_timeout(800)

                        links = extract_links_from_page()
                        products_found = 0
                        for link in links:
                            parsed = urlparse(link)
                            if parsed.netloc != base_domain:
                                continue
                            path = parsed.path.rstrip('/')
                            if not path or path == '/':
                                continue

                            # Skip utility pages
                            path_lower = path.lower()
                            if any(skip in path_lower for skip in [
                                '/login', '/cart', '/checkout', '/account', '/wishlist', '/konto',
                                '/search', '/newsletter', '/service', '/hilfe', '/help',
                                '.pdf', '.jpg', '.png', '/blog/', '/jobs/'
                            ]):
                                continue

                            clean_url = f"https://{base_domain}{path}"
                            if clean_url not in discovered_urls:
                                discovered_urls.add(clean_url)
                                if is_product_url(path):
                                    products_found += 1
                                    product_count += 1

                        logger.info(f"[Playwright]   Found {products_found} product URLs on this page (total: {product_count})")

                    except Exception as e:
                        logger.debug(f"[Playwright] Error on category {cat_url}: {e}")
                        continue

                browser.close()

            # Count product vs category URLs
            product_count = sum(1 for u in discovered_urls if is_product_url(urlparse(u).path))
            logger.info(f"[Playwright] Discovered {len(discovered_urls)} URLs ({product_count} products) from {len(visited_pages)} pages")
            return list(discovered_urls)

        except Exception as e:
            logger.error(f"[Playwright] URL discovery failed: {e}")
            return []

    @staticmethod
    def scrape(url: str) -> Optional[str]:
        """Scrape a URL using Playwright browser.

        Returns markdown-like text content or None on failure.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not installed, cannot use browser fallback")
            return None

        try:
            logger.info(f"[Playwright] Browser scraping: {url}")

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                page.goto(url, wait_until='networkidle', timeout=30000)
                page.wait_for_timeout(2000)

                # Remove cookie overlays that block interaction
                page.evaluate('''
                    document.querySelectorAll('[class*="cookie"]').forEach(el => el.remove());
                    document.querySelectorAll('[data-cookie-permission]').forEach(el => el.remove());
                    document.querySelectorAll('[class*="modal"]').forEach(el => el.remove());
                    document.querySelectorAll('[class*="overlay"]').forEach(el => el.remove());
                ''')
                page.wait_for_timeout(500)

                # Try to click product detail tabs to reveal more content
                for tab_selector in ['a[title="Produktdetails"]', 'text=Produktdetails', 'text=Product Details', 'text=Specifications', 'text=Technical Details']:
                    try:
                        page.click(tab_selector, timeout=1500)
                        page.wait_for_timeout(800)
                        logger.debug(f"Clicked tab: {tab_selector}")
                        break
                    except:
                        pass

                # Get text content
                text = page.inner_text('body')
                browser.close()

                logger.info(f"[Playwright] ✓ Got {len(text)} chars of content")
                return text

        except Exception as e:
            logger.error(f"[Playwright] Browser scrape failed: {e}")
            return None


class SmartFirecrawlClient:
    """Firecrawl client with automatic self-hosted → cloud fallback, caching, and Playwright fallback."""

    def __init__(
        self,
        config: Optional[FirecrawlConfig] = None,
        cache_days: int = 30,
        scrape_mode: ScrapeMode = ScrapeMode.AUTO,
    ):
        """Initialize the client with optional config (defaults to env vars).

        Args:
            config: Optional FirecrawlConfig (defaults to env vars)
            cache_days: Number of days to cache scrape results (default: 30)
            scrape_mode: Scraping mode - AUTO, FIRECRAWL, or PLAYWRIGHT
        """
        self.config = config or FirecrawlConfig.from_env()
        self.stats = UsageStats()
        self.cache = ScrapeCache(max_age_days=cache_days)
        self.scrape_mode = scrape_mode
        self._self_hosted: Optional[SelfHostedFirecrawl] = None
        self._cloud_client: Optional[FirecrawlApp] = None
        self._init_clients()
        logger.info(f"Firecrawl cache enabled (max age: {cache_days} days), mode: {scrape_mode.value}")

    def _init_clients(self):
        """Initialize Firecrawl client instances."""
        # TEMPORARILY DISABLED: Self-hosted Firecrawl has issues
        # TODO: Re-enable once self-hosted container is fixed
        # if self.config.self_hosted_url:
        #     self._self_hosted = SelfHostedFirecrawl(
        #         self.config.self_hosted_url,
        #         self.config.self_hosted_key,
        #         self.config.timeout,
        #     )
        #     logger.info(f"Self-hosted Firecrawl configured: {self.config.self_hosted_url}")
        logger.info("Self-hosted Firecrawl DISABLED - using cloud only")

        if self.config.cloud_api_key:
            try:
                self._cloud_client = FirecrawlApp(api_key=self.config.cloud_api_key)
                logger.info("Cloud Firecrawl configured")
            except Exception as e:
                logger.warning(f"Failed to init cloud client: {e}")

        if not self._self_hosted and not self._cloud_client:
            raise ValueError("No Firecrawl client available. Set FIRECRAWL_SELF_HOSTED_URL or FIRECRAWL_API_KEY")

    def set_scrape_mode(self, mode: ScrapeMode) -> None:
        """Change the scraping mode at runtime.

        Args:
            mode: New scraping mode (AUTO, FIRECRAWL, or PLAYWRIGHT)
        """
        self.scrape_mode = mode
        logger.info(f"Scrape mode changed to: {mode.value}")

    def scrape_url(self, url: str, formats: list[str] = None, use_cache: bool = True, **kwargs) -> ScrapeResult:
        """Scrape a URL with automatic fallback and caching.

        Args:
            url: URL to scrape
            formats: List of formats to return (default: ["markdown"])
            use_cache: Whether to use cached results (default: True)
            **kwargs: Additional arguments passed to scraper

        Returns:
            ScrapeResult with success status and content
        """
        formats = formats or ["markdown"]
        self_hosted_empty = False

        # Check cache first (only for markdown requests without special kwargs)
        if use_cache and formats == ["markdown"] and not kwargs:
            cached = self.cache.get(url)
            if cached:
                return ScrapeResult(
                    success=True,
                    data=cached,
                    markdown=cached.get("markdown", ""),
                    html=cached.get("html", ""),
                    metadata=cached.get("metadata", {}),
                    source="cache",
                    cost=0,
                )

        # PLAYWRIGHT-ONLY MODE: Skip Firecrawl entirely
        if self.scrape_mode == ScrapeMode.PLAYWRIGHT:
            logger.info(f"[Mode: PLAYWRIGHT] Using Playwright directly for {url}")
            return self._scrape_with_playwright(url, use_cache, formats)

        # Try self-hosted first (for AUTO and FIRECRAWL modes)
        if self._self_hosted:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted scrape attempt {attempt + 1}: {url}")
                    result = self._self_hosted.scrape(url, formats=formats, **kwargs)

                    markdown = result.get("markdown", "")
                    html = result.get("html", result.get("rawHtml", ""))

                    # Check if we actually got content
                    if not markdown and not html:
                        logger.warning(f"[Firecrawl] Self-hosted returned empty content for {url}")
                        self_hosted_empty = True
                        break  # Don't retry, try cloud instead

                    self.stats.self_hosted_calls += 1
                    logger.info(f"[Firecrawl] ✅ Self-hosted success (total: {self.stats.self_hosted_calls})")

                    # Cache the result
                    if use_cache and formats == ["markdown"]:
                        cache_data = {"markdown": markdown, "html": html, "metadata": result.get("metadata", {})}
                        self.cache.set(url, cache_data)

                    return ScrapeResult(
                        success=True,
                        data=result,
                        markdown=markdown,
                        html=html,
                        metadata=result.get("metadata", {}),
                        source="self-hosted",
                        cost=0,
                    )

                except Exception as e:
                    logger.warning(f"[Firecrawl] ⚠️ Self-hosted attempt {attempt + 1} failed: {e}")
                    self.stats.self_hosted_failures += 1

                    if attempt < self.config.max_retries:
                        time.sleep((attempt + 1) * 1.0)
                    else:
                        logger.warning("[Firecrawl] All self-hosted retries exhausted")

            if not self.config.enable_fallback and not self_hosted_empty:
                return ScrapeResult(success=False, error="Self-hosted failed and fallback disabled")

        # Fallback to cloud
        if self._cloud_client and (self_hosted_empty or not self._self_hosted or self.config.enable_fallback):
            if self_hosted_empty:
                logger.info("[Firecrawl] Self-hosted returned empty content, trying cloud...")
            try:
                logger.info(f"[Firecrawl] 💰 Using cloud API: {url}")
                result = self._cloud_client.scrape(url, formats=formats, **kwargs)

                self.stats.cloud_calls += 1
                self.stats.total_credits += 1
                logger.info(f"[Firecrawl] Cloud success (calls: {self.stats.cloud_calls})")

                markdown = getattr(result, "markdown", "") or ""
                html = getattr(result, "html", "") or ""
                metadata = getattr(result, "metadata", {}) or {}

                # Check if we got a blocked/404 response
                if PlaywrightScraper.is_blocked_response(markdown):
                    logger.warning(f"[Firecrawl] Cloud returned blocked/404 page, trying Playwright")
                    # Fall through to Playwright fallback
                else:
                    # Cache the result
                    if use_cache and formats == ["markdown"]:
                        cache_data = {"markdown": markdown, "html": html, "metadata": metadata}
                        self.cache.set(url, cache_data)

                    return ScrapeResult(
                        success=True,
                        data=result,
                        markdown=markdown,
                        html=html,
                        metadata=metadata,
                        source="cloud",
                        cost=1,
                    )

            except Exception as e:
                logger.error(f"[Firecrawl] ❌ Cloud API also failed: {e}")
                # Fall through to Playwright fallback (if not in FIRECRAWL-only mode)

        # Try Playwright as final fallback for blocked sites (only in AUTO mode)
        if self.scrape_mode == ScrapeMode.AUTO:
            logger.info(f"[Mode: AUTO] Trying Playwright browser fallback for {url}")
            return self._scrape_with_playwright(url, use_cache, formats)
        else:
            # FIRECRAWL mode - don't use Playwright fallback
            return ScrapeResult(success=False, error="Firecrawl failed and Playwright fallback disabled (mode: FIRECRAWL)")

    def _scrape_with_playwright(self, url: str, use_cache: bool, formats: list[str]) -> ScrapeResult:
        """Scrape a URL using Playwright browser.

        Args:
            url: URL to scrape
            use_cache: Whether to cache the result
            formats: Formats requested (for cache compatibility check)

        Returns:
            ScrapeResult with success status and content
        """
        playwright_content = PlaywrightScraper.scrape(url)
        if playwright_content and not PlaywrightScraper.is_blocked_response(playwright_content):
            self.stats.self_hosted_calls += 1  # Count as self-hosted (free)

            # Cache the result
            if use_cache and formats == ["markdown"]:
                cache_data = {"markdown": playwright_content, "html": "", "metadata": {"source": "playwright"}}
                self.cache.set(url, cache_data)

            return ScrapeResult(
                success=True,
                data={"markdown": playwright_content},
                markdown=playwright_content,
                html="",
                metadata={"source": "playwright"},
                source="playwright",
                cost=0,
            )

        return ScrapeResult(success=False, error="Playwright scraping failed or returned blocked content")

    def scrape(self, url: str, formats: list[str] = None, **kwargs) -> Any:
        """Scrape URL - returns raw result for backward compatibility."""
        result = self.scrape_url(url, formats, **kwargs)
        if not result.success:
            raise ValueError(result.error)
        return result.data

    def search(self, query: str, limit: int = 5) -> Any:
        """Search the web with automatic fallback."""
        if self._self_hosted:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted search: {query}")
                    result = self._self_hosted.search(query, limit=limit)
                    self.stats.self_hosted_calls += 1
                    return result
                except Exception as e:
                    logger.warning(f"[Firecrawl] Self-hosted search failed: {e}")
                    if attempt < self.config.max_retries:
                        time.sleep((attempt + 1) * 1.0)

        if self._cloud_client and self.config.enable_fallback:
            try:
                logger.info(f"[Firecrawl] 💰 Cloud search: {query}")
                result = self._cloud_client.search(query, limit=limit)
                self.stats.cloud_calls += 1
                self.stats.total_credits += limit
                return result
            except Exception as e:
                raise ValueError(f"Search failed: {e}")

        raise ValueError("No Firecrawl client available for search")

    def map(self, url: str, limit: int = 100) -> Any:
        """Map a website with automatic fallback."""
        last_error = None

        if self._self_hosted:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted map attempt {attempt + 1}: {url}")
                    result = self._self_hosted.map(url, limit=limit)
                    self.stats.self_hosted_calls += 1
                    return result
                except Exception as e:
                    last_error = e
                    logger.warning(f"[Firecrawl] Self-hosted map failed: {e}")
                    self.stats.self_hosted_failures += 1
                    if attempt < self.config.max_retries:
                        time.sleep((attempt + 1) * 1.0)
                    else:
                        logger.warning("[Firecrawl] All self-hosted map retries exhausted")

        # Try cloud fallback
        if self._cloud_client and self.config.enable_fallback:
            try:
                logger.info(f"[Firecrawl] ☁️ Falling back to cloud map: {url}")
                result = self._cloud_client.map(url, limit=limit)
                self.stats.cloud_calls += 1
                self.stats.total_credits += 1
                logger.info(f"[Firecrawl] ✅ Cloud map succeeded")
                return result
            except Exception as e:
                logger.error(f"[Firecrawl] ❌ Cloud map also failed: {e}")
                raise ValueError(f"Map failed (both self-hosted and cloud): {e}")
        elif not self._cloud_client:
            logger.warning("[Firecrawl] No cloud client configured for fallback")
        elif not self.config.enable_fallback:
            logger.warning("[Firecrawl] Fallback disabled in config")

        raise ValueError(f"Map failed: {last_error or 'No client available'}")

    def extract(self, urls: list[str], schema: dict, prompt: str = "") -> Any:
        """Extract structured data - cloud only, with scrape+parse fallback.

        Note: Self-hosted Firecrawl doesn't support /extract endpoint.
        Falls back to scraping + manual parsing if cloud is unavailable/out of credits.
        """
        # Try cloud Firecrawl first (self-hosted doesn't support extract)
        if self._cloud_client:
            try:
                logger.info(f"[Firecrawl] 💰 Cloud extract: {urls}")
                result = self._cloud_client.extract(urls=urls, schema=schema, prompt=prompt)
                self.stats.cloud_calls += 1
                self.stats.total_credits += len(urls) * 5
                return result
            except Exception as e:
                error_str = str(e).lower()
                if "credit" in error_str or "limit" in error_str or "429" in error_str:
                    logger.warning(f"[Firecrawl] Cloud extract out of credits: {e}")
                else:
                    logger.warning(f"[Firecrawl] Cloud extract failed: {e}")
                # Fall through to scrape fallback

        # Fallback: scrape the page and return raw content for manual parsing
        logger.info(f"[Firecrawl] Using scrape fallback for extract: {urls}")
        fallback_results = []

        for url in urls:
            try:
                scrape_result = self.scrape_url(url, formats=["markdown"])
                if scrape_result.success:
                    fallback_results.append({
                        "url": url,
                        "markdown": scrape_result.markdown,
                        "metadata": scrape_result.metadata,
                        "source": "scrape_fallback",
                    })
                else:
                    fallback_results.append({
                        "url": url,
                        "error": scrape_result.error,
                        "source": "scrape_fallback",
                    })
            except Exception as e:
                fallback_results.append({
                    "url": url,
                    "error": str(e),
                    "source": "scrape_fallback",
                })

        # Return in a format similar to extract API
        return {
            "success": True,
            "data": fallback_results,
            "source": "scrape_fallback",
            "note": "Cloud extract unavailable, using scrape fallback - manual parsing required",
        }

    def get_usage_stats(self) -> dict:
        """Get usage statistics including cache stats."""
        stats = self.stats.to_dict()
        stats["cache"] = self.cache.get_stats()
        return stats

    def reset_stats(self):
        """Reset usage statistics."""
        self.stats = UsageStats()
        self.cache._hits = 0
        self.cache._misses = 0

    def clear_expired_cache(self) -> int:
        """Clear expired cache entries. Returns count of removed entries."""
        return self.cache.clear_expired()


# Singleton instance - initialized lazily
_client_instance: Optional[SmartFirecrawlClient] = None


def get_smart_firecrawl(scrape_mode: Optional[ScrapeMode] = None) -> SmartFirecrawlClient:
    """Get or create the singleton SmartFirecrawlClient instance.

    Args:
        scrape_mode: Optional scrape mode to set. If the client already exists,
                     this will change its mode. If creating a new client, this
                     will be the initial mode.

    Returns:
        The singleton SmartFirecrawlClient instance
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = SmartFirecrawlClient(scrape_mode=scrape_mode or ScrapeMode.AUTO)
    elif scrape_mode is not None:
        _client_instance.set_scrape_mode(scrape_mode)
    return _client_instance


def reset_client():
    """Reset the singleton instance (useful for testing)."""
    global _client_instance
    _client_instance = None

"""Smart site analyzer using LLM to discover URL patterns.

This module provides intelligent website analysis that uses an LLM to understand
site structure rather than relying on hardcoded URL patterns.
"""

import hashlib
import json
import logging
import os
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from openai import OpenAI

from app.tools.site_patterns import ExtractionResult, SitePatterns
from app.tools.smart_firecrawl import PlaywrightScraper, ScrapeMode, get_smart_firecrawl

logger = logging.getLogger(__name__)


@dataclass
class ProgressState:
    """Tracks progress state for reporting."""

    phase: str = ""
    message: str = ""
    current: int = 0
    total: int = 0
    details: dict = field(default_factory=dict)


class ProgressReporter:
    """Reports progress to the user with friendly messages."""

    def __init__(self, verbose: bool = True, callback: Optional[Callable[[ProgressState], None]] = None):
        self.verbose = verbose
        self.callback = callback
        self._last_phase = ""

    def _print(self, message: str, emoji: str = "", end: str = "\n"):
        """Print a progress message."""
        if self.verbose:
            prefix = f"{emoji} " if emoji else ""
            print(f"{prefix}{message}", end=end, flush=True)

    def report(self, state: ProgressState):
        """Report progress state."""
        if self.callback:
            self.callback(state)

        if not self.verbose:
            return

        # Print phase headers
        if state.phase != self._last_phase:
            self._last_phase = state.phase
            print()  # Blank line before new phase

        # Format message based on phase
        if state.phase == "init":
            self._print(state.message, "🔍")
        elif state.phase == "mapping":
            self._print(state.message, "🗺️")
        elif state.phase == "analyzing":
            self._print(state.message, "🧠")
        elif state.phase == "discovering":
            if state.total > 0:
                pct = (state.current / state.total) * 100
                bar = self._progress_bar(state.current, state.total)
                self._print(f"{state.message} {bar} {state.current}/{state.total}", "🔎", end="\r")
            else:
                self._print(state.message, "🔎")
        elif state.phase == "scraping":
            if state.total > 0:
                bar = self._progress_bar(state.current, state.total)
                products = state.details.get("products_found", 0)
                self._print(
                    f"Extracting products... {bar} {state.current}/{state.total} ({products} found)",
                    "📦",
                    end="\r",
                )
            else:
                self._print(state.message, "📦")
        elif state.phase == "product":
            # Individual product extracted
            name = state.details.get("name", "Unknown")
            brand = state.details.get("brand", "")
            weight = state.details.get("weight")
            info = f"{brand} {name}".strip()
            if weight:
                info += f" ({weight}g)"
            self._print(f"  ✓ {info}", "")
        elif state.phase == "saving":
            # Product being saved to database
            name = state.details.get("name", "Unknown")
            brand = state.details.get("brand", "")
            success = state.details.get("success", True)
            icon = "💾" if success else "⚠️"
            info = f"{brand} {name}".strip()
            self._print(f"  {icon} Saved: {info}", "")
        elif state.phase == "save_batch":
            # Batch save progress
            saved = state.details.get("saved", 0)
            failed = state.details.get("failed", 0)
            total = state.details.get("total", 0)
            self._print(f"Batch saved: {saved}/{total} items ({failed} failed)", "💾")
        elif state.phase == "complete":
            print()  # Clear progress line
            self._print(state.message, "✅")
        elif state.phase == "error":
            self._print(state.message, "❌")
        else:
            self._print(state.message, "ℹ️")

    def _progress_bar(self, current: int, total: int, width: int = 20) -> str:
        """Create a simple progress bar."""
        if total == 0:
            return "[" + " " * width + "]"
        filled = int(width * current / total)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"

    def phase_start(self, phase: str, message: str, total: int = 0):
        """Start a new phase."""
        self.report(ProgressState(phase=phase, message=message, total=total))

    def phase_progress(self, phase: str, current: int, total: int, message: str = "", **details):
        """Update progress within a phase."""
        self.report(ProgressState(phase=phase, message=message, current=current, total=total, details=details))

    def product_found(self, name: str, brand: str = "", weight: Optional[int] = None):
        """Report a product was found."""
        self.report(
            ProgressState(
                phase="product",
                message=f"Found: {brand} {name}",
                details={"name": name, "brand": brand, "weight": weight},
            )
        )

    def complete(self, products_found: int, time_taken: float):
        """Report completion."""
        self.report(
            ProgressState(
                phase="complete",
                message=f"Done! Found {products_found} products in {time_taken:.1f}s",
                details={"products_found": products_found, "time_taken": time_taken},
            )
        )

    def error(self, message: str):
        """Report an error."""
        self.report(ProgressState(phase="error", message=message))

    def product_saved(self, name: str, brand: str = "", success: bool = True, error: str = ""):
        """Report a product was saved to the database."""
        self.report(
            ProgressState(
                phase="saving",
                message=f"Saved: {brand} {name}".strip(),
                details={"name": name, "brand": brand, "success": success, "error": error},
            )
        )

    def batch_saved(self, saved: int, failed: int, total: int):
        """Report a batch of products was saved."""
        self.report(
            ProgressState(
                phase="save_batch",
                message=f"Batch saved: {saved}/{total}",
                details={"saved": saved, "failed": failed, "total": total},
            )
        )


class StreamlitProgressReporter(ProgressReporter):
    """Progress reporter that updates Streamlit UI components.

    Usage with st.status():
        with st.status("Extracting products...", expanded=True) as status:
            reporter = StreamlitProgressReporter(status_container=status)
            result = analyzer.analyze_and_extract(url, progress=reporter)
    """

    def __init__(self, status_container=None):
        """Initialize with Streamlit status container.

        Args:
            status_container: The st.status() context manager object
        """
        super().__init__(verbose=False)  # Don't use print()
        self.status = status_container
        self._progress_bar = None
        self._current_phase = ""
        self._products_container = None
        self._last_products: list[str] = []
        self._saved_products: list[str] = []

    def report(self, state: ProgressState):
        """Update Streamlit UI based on progress state."""
        if not self.status:
            return

        try:
            import streamlit as st

            phase = state.phase

            # Phase transitions - update status label
            if phase != self._current_phase:
                self._current_phase = phase
                self._update_phase_header(phase, state)

            # Handle specific phases
            if phase == "init":
                st.write(f"🔍 {state.message}")

            elif phase == "mapping":
                st.write(f"🗺️ {state.message}")

            elif phase == "analyzing":
                st.write(f"🧠 {state.message}")

            elif phase == "info":
                st.write(f"ℹ️ {state.message}")

            elif phase == "discovering":
                if state.total > 0:
                    progress = state.current / state.total
                    if self._progress_bar is None:
                        st.write(f"🔎 Crawling {state.total} categories...")
                        self._progress_bar = st.progress(0, text="Starting...")
                    self._progress_bar.progress(
                        progress,
                        text=f"Category {state.current}/{state.total}"
                    )
                else:
                    st.write(f"🔎 {state.message}")

            elif phase == "scraping":
                if state.total > 0:
                    progress = state.current / state.total
                    products = state.details.get("products_found", 0)
                    if self._progress_bar is None:
                        st.write(f"📦 Extracting from {state.total} product pages...")
                        self._progress_bar = st.progress(0, text="Starting...")
                    self._progress_bar.progress(
                        progress,
                        text=f"Page {state.current}/{state.total} ({products} products found)"
                    )
                else:
                    st.write(f"📦 {state.message}")

            elif phase == "product":
                # Collect products to show
                name = state.details.get("name", "Unknown")
                brand = state.details.get("brand", "")
                weight = state.details.get("weight")
                info = f"{brand} {name}".strip()
                if weight:
                    info += f" ({weight}g)"
                self._last_products.append(f"✓ {info}")

                # Show last 5 products in an expander (update periodically)
                if len(self._last_products) % 5 == 0:
                    self._show_recent_products(st)

            elif phase == "saving":
                # Product saved to database
                name = state.details.get("name", "Unknown")
                brand = state.details.get("brand", "")
                success = state.details.get("success", True)
                icon = "💾" if success else "⚠️"
                info = f"{brand} {name}".strip()
                self._saved_products.append(f"{icon} {info}")
                # Show saved products periodically
                if len(self._saved_products) % 5 == 0:
                    self._show_saved_products(st)

            elif phase == "save_batch":
                saved = state.details.get("saved", 0)
                failed = state.details.get("failed", 0)
                total = state.details.get("total", 0)
                st.write(f"💾 **Batch saved:** {saved}/{total} items" + (f" ({failed} failed)" if failed else ""))

            elif phase == "complete":
                # Clear progress bar and show completion
                self._progress_bar = None
                products = state.details.get("products_found", 0)
                time_taken = state.details.get("time_taken", 0)
                self.status.update(
                    label=f"✅ Found {products} products in {time_taken:.0f}s",
                    state="complete",
                    expanded=False
                )

            elif phase == "error":
                self.status.update(label=f"❌ {state.message}", state="error")

        except Exception as e:
            # Don't crash on UI errors
            pass

    def _update_phase_header(self, phase: str, state: ProgressState):
        """Update the status container label for phase changes."""
        labels = {
            "init": "🔍 Starting discovery...",
            "mapping": "🗺️ Mapping website...",
            "analyzing": "🧠 Analyzing patterns...",
            "discovering": "🔎 Deep crawling categories...",
            "scraping": "📦 Extracting products...",
        }
        if phase in labels:
            self.status.update(label=labels[phase], state="running")

        # Reset progress bar on phase change
        if phase in ("discovering", "scraping"):
            self._progress_bar = None

    def _show_recent_products(self, st):
        """Show the most recently found products."""
        recent = self._last_products[-5:]
        with st.expander(f"Recent products ({len(self._last_products)} total)", expanded=False):
            for p in recent:
                st.text(p)

    def _show_saved_products(self, st):
        """Show the most recently saved products."""
        recent = self._saved_products[-5:]
        with st.expander(f"💾 Saved to graph ({len(self._saved_products)} total)", expanded=True):
            for p in recent:
                st.text(p)

    def phase_start(self, phase: str, message: str, total: int = 0):
        """Start a new phase."""
        self.report(ProgressState(phase=phase, message=message, total=total))

    def complete(self, products_found: int, time_taken: float):
        """Report completion."""
        self.report(
            ProgressState(
                phase="complete",
                message=f"Done! Found {products_found} products",
                details={"products_found": products_found, "time_taken": time_taken},
            )
        )


# Default silent reporter for non-interactive use
_silent_reporter = ProgressReporter(verbose=False)


# Fallback trigger thresholds
MIN_URLS_FOR_ANALYSIS = 5
MIN_ANALYSIS_CONFIDENCE = 0.6
MIN_PRODUCT_PATTERN_CONFIDENCE = 0.7
MAX_SCRAPE_FAILURE_RATE = 0.3


class SiteAnalysisCache:
    """File-based cache for site analysis results."""

    def __init__(self, cache_dir: str = ".cache/site_analysis", max_age_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_hours = max_age_hours
        self._memory_cache: dict[str, SitePatterns] = {}

    def _get_cache_path(self, domain: str) -> Path:
        """Get the cache file path for a domain."""
        domain_hash = hashlib.md5(domain.encode()).hexdigest()[:8]
        safe_domain = domain.replace(".", "_").replace("/", "_")
        return self.cache_dir / f"{safe_domain}_{domain_hash}.json"

    def get(self, domain: str) -> Optional[SitePatterns]:
        """Retrieve cached analysis for a domain."""
        # Check memory cache first
        if domain in self._memory_cache:
            cached = self._memory_cache[domain]
            if not cached.is_expired(self.max_age_hours):
                logger.info(f"Using memory-cached analysis for {domain}")
                return cached

        # Check file cache
        cache_path = self._get_cache_path(domain)
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    data = json.load(f)
                patterns = SitePatterns.from_dict(data)

                if patterns.is_expired(self.max_age_hours):
                    cache_path.unlink()
                    return None

                self._memory_cache[domain] = patterns
                logger.info(f"Using file-cached analysis for {domain}")
                return patterns

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid cache for {domain}: {e}")
                cache_path.unlink()

        return None

    def set(self, domain: str, patterns: SitePatterns) -> None:
        """Store analysis in cache."""
        self._memory_cache[domain] = patterns

        cache_path = self._get_cache_path(domain)
        with open(cache_path, "w") as f:
            json.dump(patterns.to_dict(), f, indent=2)

        logger.info(f"Cached analysis for {domain}")

    def invalidate(self, domain: str) -> None:
        """Remove cached analysis for a domain."""
        if domain in self._memory_cache:
            del self._memory_cache[domain]

        cache_path = self._get_cache_path(domain)
        if cache_path.exists():
            cache_path.unlink()


class SmartSiteAnalyzer:
    """LLM-driven site structure analyzer for intelligent scraping."""

    def __init__(self):
        self.cache = SiteAnalysisCache()
        self._firecrawl = None
        self._llm_client = None

    @property
    def firecrawl(self):
        """Lazy-load Firecrawl client."""
        if self._firecrawl is None:
            self._firecrawl = get_smart_firecrawl()
        return self._firecrawl

    @property
    def llm_client(self):
        """Lazy-load LLM client (DeepSeek)."""
        if self._llm_client is None:
            self._llm_client = OpenAI(
                api_key=os.environ.get("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com",
            )
        return self._llm_client

    def analyze_and_extract(
        self,
        base_url: str,
        max_products: int = 100,
        force_reanalyze: bool = False,
        deep_discovery: bool = False,
        progress: Optional[ProgressReporter] = None,
        save_callback: Optional[Callable[[list[dict], ProgressReporter], tuple[int, int]]] = None,
        save_batch_size: int = 10,
        scrape_mode: ScrapeMode = ScrapeMode.AUTO,
    ) -> ExtractionResult:
        """Main entry point for smart extraction.

        Args:
            base_url: Website base URL to analyze
            max_products: Maximum products to extract (0 = no limit)
            force_reanalyze: Skip cache and re-analyze
            deep_discovery: If True, crawl all category pages to find ALL products
            progress: Progress reporter for status updates
            save_callback: Optional callback to save products incrementally.
                           Signature: (products: list[dict], progress: ProgressReporter) -> (saved_count, failed_count)
                           If provided, products are saved every `save_batch_size` items during extraction.
            save_batch_size: Number of products to collect before calling save_callback (default: 10)
            scrape_mode: Scraping mode - AUTO (Firecrawl with Playwright fallback),
                         FIRECRAWL (only Firecrawl), or PLAYWRIGHT (only Playwright browser)

        Returns:
            ExtractionResult with products and metadata
        """
        # Set the scrape mode for this extraction
        self._current_scrape_mode = scrape_mode
        get_smart_firecrawl(scrape_mode=scrape_mode)
        start_time = time.time()
        prog = progress or _silent_reporter

        parsed = urlparse(base_url)
        domain = parsed.netloc.replace("www.", "")
        estimated_cost = 0.0

        mode_names = {ScrapeMode.AUTO: "Auto (Firecrawl→Playwright)", ScrapeMode.FIRECRAWL: "Firecrawl only", ScrapeMode.PLAYWRIGHT: "Playwright only"}
        prog.phase_start("init", f"Starting smart discovery for {domain} [Mode: {mode_names.get(scrape_mode, scrape_mode.value)}]...")

        # Step 1: Check cache
        patterns = None
        from_cache = False

        if not force_reanalyze:
            patterns = self.cache.get(domain)
            if patterns:
                from_cache = True
                prog.phase_start("info", f"Using cached site patterns (platform: {patterns.platform})")
                logger.info(f"Using cached patterns for {domain}")

        # Step 2: Map the website if no cached patterns
        if patterns is None:
            prog.phase_start("mapping", f"Mapping {domain} to discover all URLs...")
            logger.info(f"Mapping website: {base_url}")
            all_urls = self._map_website(base_url)

            if len(all_urls) < MIN_URLS_FOR_ANALYSIS:
                prog.error(f"Only found {len(all_urls)} URLs - not enough to analyze")
                logger.warning(f"Map returned only {len(all_urls)} URLs, triggering fallback")
                return self._cloud_crawl_fallback(base_url, f"Map returned only {len(all_urls)} URLs")

            prog.phase_start("info", f"Found {len(all_urls)} URLs on the site")

            # Step 3: Sample URLs for LLM analysis
            sampled_urls = self._sample_urls_strategically(all_urls, sample_size=50)

            # Step 4: Analyze with LLM
            prog.phase_start("analyzing", f"AI analyzing site structure from {len(sampled_urls)} sample URLs...")
            logger.info(f"Analyzing {len(sampled_urls)} sampled URLs with LLM")
            patterns = self._analyze_with_llm(domain, sampled_urls)
            estimated_cost += 0.01  # Approximate cost for DeepSeek analysis

            if patterns is None or not patterns.is_valid():
                reason = "LLM analysis failed" if patterns is None else f"Low confidence: {patterns.overall_confidence:.1%}"
                prog.error(f"Pattern analysis failed: {reason}")
                logger.warning(f"Pattern analysis invalid: {reason}")
                return self._cloud_crawl_fallback(base_url, reason)

            prog.phase_start(
                "info",
                f"Detected {patterns.platform} site with {len(patterns.product_patterns)} product patterns "
                f"(confidence: {patterns.overall_confidence:.0%})",
            )

            # Step 5: Cache the patterns
            self.cache.set(domain, patterns)
        else:
            # Re-map to get current URLs
            prog.phase_start("mapping", f"Mapping {domain} for current URLs...")
            all_urls = self._map_website(base_url)

        # Step 6: Filter URLs using discovered patterns
        product_urls = []
        category_urls = []

        for url in all_urls:
            path = urlparse(url).path

            if patterns.should_skip(path):
                continue
            elif patterns.matches_product(path):
                product_urls.append(url)
            elif patterns.matches_category(path):
                category_urls.append(url)

        prog.phase_start("info", f"Identified {len(product_urls)} product pages, {len(category_urls)} categories")
        logger.info(f"Found {len(product_urls)} product URLs, {len(category_urls)} category URLs")

        # Step 7: Deep discovery if requested - crawl ALL category pages to find ALL products
        if deep_discovery and category_urls:
            prog.phase_start("discovering", f"Deep crawling {len(category_urls)} categories to find all products...")
            logger.info("Deep discovery enabled - crawling all category pages for complete product list...")
            all_discovered_products = self.deep_discover_products(category_urls, patterns, progress=prog)
            # Merge with already found product URLs and deduplicate
            all_product_urls = list(set(product_urls + all_discovered_products))
            prog.phase_start(
                "info", f"Deep discovery found {len(all_discovered_products)} additional products "
                f"(total: {len(all_product_urls)} unique)"
            )
            logger.info(f"Deep discovery found {len(all_discovered_products)} products, total unique: {len(all_product_urls)}")
            product_urls = all_product_urls

        # Step 8: Extract products
        # Prioritize direct product URLs over category crawling
        if product_urls:
            # Scrape product pages directly (sample if too many, unless max_products=0 means no limit)
            if max_products > 0 and len(product_urls) > max_products:
                urls_to_scrape = product_urls[:max_products]
            else:
                urls_to_scrape = product_urls

            prog.phase_start("scraping", f"Extracting product details from {len(urls_to_scrape)} pages...")
            logger.info(f"Scraping {len(urls_to_scrape)} product pages directly")
            products, scrape_stats = self._scrape_product_pages(
                urls_to_scrape, patterns, progress=prog,
                save_callback=save_callback, save_batch_size=save_batch_size,
                source_url=base_url
            )
        elif category_urls:
            # Fall back to category crawling only if no product URLs found
            prog.phase_start("scraping", f"No direct product URLs, crawling {len(category_urls)} categories...")
            logger.info(f"No direct product URLs, crawling {len(category_urls)} category pages")
            products, scrape_stats = self._scrape_category_pages(category_urls, patterns, max_products, progress=prog)
        else:
            prog.error("No product or category URLs found!")
            products, scrape_stats = [], {"scrape_attempts": 0, "scrape_failures": 0, "products_found": 0}

        # Check scrape failure rate
        if scrape_stats.get("scrape_attempts", 0) > 0:
            failure_rate = scrape_stats.get("scrape_failures", 0) / scrape_stats["scrape_attempts"]
            if failure_rate > MAX_SCRAPE_FAILURE_RATE:
                logger.warning(f"High scrape failure rate: {failure_rate:.1%}")
                # Could trigger fallback here, but for now just log

        # Report completion
        elapsed = time.time() - start_time
        prog.complete(len(products), elapsed)

        return ExtractionResult(
            products=products,
            source="smart_extraction",
            patterns=patterns,
            from_cache=from_cache,
            estimated_cost=estimated_cost,
            stats=scrape_stats,
        )

    def _map_website(self, url: str, limit: int = 500) -> list[str]:
        """Discover all URLs on a website.

        In PLAYWRIGHT mode, uses Playwright browser to crawl and discover URLs.
        Otherwise, uses Firecrawl map() API with cloud fallback.
        """
        all_urls = []

        # Get current scrape mode (default to AUTO if not set)
        scrape_mode = getattr(self, '_current_scrape_mode', ScrapeMode.AUTO)

        # PLAYWRIGHT MODE: Use browser-based discovery
        if scrape_mode == ScrapeMode.PLAYWRIGHT:
            logger.info(f"[Mode: PLAYWRIGHT] Using browser to discover URLs from {url}")
            all_urls = PlaywrightScraper.discover_urls(url, max_urls=limit)
            logger.info(f"[Playwright] Discovered {len(all_urls)} URLs")

            if len(all_urls) >= MIN_URLS_FOR_ANALYSIS:
                return all_urls
            else:
                logger.warning(f"Playwright only found {len(all_urls)} URLs, trying Firecrawl as backup")

        # FIRECRAWL/AUTO MODE: Use Firecrawl map API
        self_hosted_failed = False

        # Try via SmartFirecrawlClient (handles self-hosted with cloud fallback)
        try:
            result = self.firecrawl.map(url, limit=limit)
            firecrawl_urls = self._extract_urls_from_map_result(result)
            logger.info(f"Firecrawl map returned {len(firecrawl_urls)} URLs from {url}")

            # Use whichever found more URLs
            if len(firecrawl_urls) > len(all_urls):
                all_urls = firecrawl_urls
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Firecrawl map failed for {url}: {error_msg}")
            self_hosted_failed = True

            # Check for specific errors that indicate self-hosted is down
            if "502" in error_msg or "503" in error_msg or "Connection" in error_msg:
                logger.info("Self-hosted Firecrawl appears to be down, trying cloud directly...")

        # If we don't have enough URLs, explicitly try cloud API
        if len(all_urls) < MIN_URLS_FOR_ANALYSIS:
            cloud_key = os.environ.get("FIRECRAWL_API_KEY")
            if not cloud_key:
                logger.warning("No FIRECRAWL_API_KEY - cannot use cloud fallback")
            else:
                logger.info(
                    f"Need more URLs (got {len(all_urls)}, need {MIN_URLS_FOR_ANALYSIS}), "
                    f"trying cloud Firecrawl directly..."
                )
                try:
                    from firecrawl import FirecrawlApp
                    cloud_app = FirecrawlApp(api_key=cloud_key)
                    cloud_result = cloud_app.map(url, limit=limit)
                    cloud_urls = self._extract_urls_from_map_result(cloud_result)
                    logger.info(f"☁️ Cloud Firecrawl map returned {len(cloud_urls)} URLs")

                    if len(cloud_urls) > len(all_urls):
                        all_urls = cloud_urls
                        logger.info(f"Using {len(all_urls)} URLs from cloud Firecrawl")

                except Exception as e:
                    logger.error(f"Cloud Firecrawl map also failed: {e}")

        # Final fallback to Playwright if we still don't have enough URLs
        if len(all_urls) < MIN_URLS_FOR_ANALYSIS and scrape_mode != ScrapeMode.PLAYWRIGHT:
            logger.info(f"Firecrawl found only {len(all_urls)} URLs, trying Playwright discovery as fallback")
            playwright_urls = PlaywrightScraper.discover_urls(url, max_urls=limit)
            if len(playwright_urls) > len(all_urls):
                all_urls = playwright_urls
                logger.info(f"Using {len(all_urls)} URLs from Playwright discovery")

        if not all_urls:
            logger.error(
                "All URL discovery methods failed. "
                "Check: 1) Site is accessible 2) Firecrawl API key is valid 3) Playwright is installed"
            )

        return all_urls

    def _extract_urls_from_map_result(self, result) -> list[str]:
        """Extract URL strings from various map result formats."""
        urls = []

        # Handle list of MapData objects (cloud API v2)
        if isinstance(result, list):
            for item in result:
                if hasattr(item, "url"):
                    urls.append(item.url)
                elif isinstance(item, str):
                    urls.append(item)
                elif isinstance(item, dict) and "url" in item:
                    urls.append(item["url"])
        # Handle dict with "links" key (self-hosted v1 API)
        elif isinstance(result, dict) and "links" in result:
            links = result["links"]
            if isinstance(links, list):
                for link in links:
                    if isinstance(link, str):
                        urls.append(link)
                    elif hasattr(link, "url"):
                        urls.append(link.url)
                    elif isinstance(link, dict) and "url" in link:
                        urls.append(link["url"])
        # Handle object with links attribute
        elif hasattr(result, "links") and result.links:
            for link in result.links:
                if hasattr(link, "url"):
                    urls.append(link.url)
                elif isinstance(link, str):
                    urls.append(link)

        return urls

    def _sample_urls_strategically(self, urls: list[str], sample_size: int = 50) -> list[str]:
        """Sample URLs to give LLM a representative view of the site structure."""
        if len(urls) <= sample_size:
            return urls

        sampled = []

        # Group by URL depth
        depth_groups = defaultdict(list)
        for url in urls:
            path = urlparse(url).path
            depth = len([p for p in path.split("/") if p])
            depth_groups[depth].append(url)

        # Sample from each depth level
        for depth in sorted(depth_groups.keys()):
            group = depth_groups[depth]
            n_from_group = min(len(group), max(2, sample_size // max(len(depth_groups), 1)))
            sampled.extend(random.sample(group, min(n_from_group, len(group))))

        # Ensure we include URLs with product-like indicators
        product_keywords = ["product", "produkt", "item", "artikel", "shop", "/p/", "products/"]
        category_keywords = ["collection", "category", "kategorie", "kategorien", "sortiment", "/c/"]

        for url in urls:
            url_lower = url.lower()
            if any(kw in url_lower for kw in product_keywords + category_keywords):
                if url not in sampled:
                    sampled.append(url)
                    if len(sampled) >= sample_size * 1.5:
                        break

        # Deduplicate and limit
        seen = set()
        unique = []
        for url in sampled:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return unique[:sample_size]

    def _analyze_with_llm(self, domain: str, sample_urls: list[str]) -> Optional[SitePatterns]:
        """Use DeepSeek to analyze site structure from sample URLs."""
        url_list = "\n".join([f"- {url}" for url in sample_urls])

        prompt = f"""Analyze the following URLs from the website "{domain}":

{url_list}

Based on these sample URLs, identify the URL patterns for:
1. Product pages (individual product detail pages)
2. Category/collection pages (pages listing multiple products)
3. Pages to skip (non-product pages)

Also determine the e-commerce platform and provide confidence scores.

Return your analysis as a JSON object with this structure:
{{
  "domain": "{domain}",
  "platform": "shopify|woocommerce|magento|prestashop|custom|unknown",
  "platform_confidence": 0.0-1.0,
  "product_patterns": [
    {{"regex": "pattern", "description": "...", "confidence": 0.0-1.0, "example_matches": [...]}}
  ],
  "category_patterns": [
    {{"regex": "pattern", "description": "...", "confidence": 0.0-1.0, "example_matches": [...]}}
  ],
  "skip_patterns": [
    {{"regex": "pattern", "reason": "..."}}
  ],
  "overall_confidence": 0.0-1.0,
  "analysis_notes": "..."
}}"""

        system_prompt = """You are an expert web scraping analyst specializing in e-commerce site structure analysis.
Your task is to analyze URLs and identify patterns for product pages vs category pages.

CRITICAL: Generate regex patterns that match URL PATHS ONLY (not full URLs).
- Correct: ^/produkt/[a-z0-9-]+/?$
- Wrong: ^https?://example.com/produkt/...

Key indicators for PRODUCT pages: /product/, /produkt/, /p/, /item/, /artikel/, URLs with product slugs
Key indicators for CATEGORY pages: /collection/, /category/, /kategorie/, /c/, /shop/ with subcategory

Always return valid JSON. Be specific with regex patterns matching URL paths. Include confidence scores."""

        try:
            response = self.llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
            )

            content = response.choices[0].message.content

            # Extract JSON from response (handle markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            patterns = SitePatterns.from_json(content.strip())
            logger.info(
                f"LLM analysis complete: platform={patterns.platform}, "
                f"confidence={patterns.overall_confidence:.1%}, "
                f"{len(patterns.product_patterns)} product patterns, "
                f"{len(patterns.category_patterns)} category patterns"
            )
            return patterns

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return None

    def _scrape_product_pages(
        self,
        product_urls: list[str],
        patterns: SitePatterns,
        progress: Optional[ProgressReporter] = None,
        save_callback: Optional[Callable[[list[dict], ProgressReporter], tuple[int, int]]] = None,
        save_batch_size: int = 10,
        source_url: str = "",
    ) -> tuple[list[dict], dict]:
        """Scrape individual product pages using self-hosted Firecrawl.

        Args:
            product_urls: URLs to scrape
            patterns: Site patterns for parsing
            progress: Progress reporter
            save_callback: Optional callback to save products incrementally
            save_batch_size: Batch size for incremental saves
            source_url: Original source URL for tracking

        Returns:
            Tuple of (all_products, stats)
        """
        prog = progress or _silent_reporter
        all_products = []  # All products extracted
        pending_save = []  # Products waiting to be saved
        stats = {
            "scrape_attempts": 0,
            "scrape_failures": 0,
            "products_found": 0,
            "products_saved": 0,
            "save_failures": 0,
        }
        total = len(product_urls)

        for i, url in enumerate(product_urls, 1):
            stats["scrape_attempts"] += 1

            # Update progress
            prog.phase_progress("scraping", i, total, products_found=stats["products_found"])

            try:
                result = self.firecrawl.scrape(url, formats=["markdown"])

                markdown = ""
                if hasattr(result, "markdown") and result.markdown:
                    markdown = result.markdown
                elif isinstance(result, dict):
                    markdown = result.get("markdown", result.get("html", ""))

                logger.debug(f"Scraped {url}: got {len(markdown)} chars of markdown")

                if markdown:
                    product = self._parse_product_from_markdown(markdown, url)
                    if product:
                        all_products.append(product)
                        pending_save.append(product)
                        stats["products_found"] += 1

                        # Report individual product found
                        prog.product_found(
                            name=product.get("name", "Unknown"),
                            brand=product.get("brand", ""),
                            weight=product.get("weight_grams"),
                        )

                        # INCREMENTAL SAVE: Save every N products
                        if save_callback and len(pending_save) >= save_batch_size:
                            saved, failed = save_callback(pending_save, prog)
                            stats["products_saved"] += saved
                            stats["save_failures"] += failed
                            prog.batch_saved(saved, failed, len(pending_save))
                            pending_save = []  # Clear pending

            except Exception as e:
                logger.warning(f"Failed to scrape {url}: {e}")
                stats["scrape_failures"] += 1

        # Save any remaining products
        if save_callback and pending_save:
            saved, failed = save_callback(pending_save, prog)
            stats["products_saved"] += saved
            stats["save_failures"] += failed
            prog.batch_saved(saved, failed, len(pending_save))

        logger.info(
            f"Scraped {stats['products_found']} products from {stats['scrape_attempts']} URLs "
            f"({stats['scrape_failures']} failures). "
            f"Saved: {stats['products_saved']}, Save failures: {stats['save_failures']}"
        )
        return all_products, stats

    def _scrape_category_pages(
        self,
        category_urls: list[str],
        patterns: SitePatterns,
        max_products: int,
        progress: Optional[ProgressReporter] = None,
    ) -> tuple[list[dict], dict]:
        """Scrape category pages to find products."""
        prog = progress or _silent_reporter
        products = []
        stats = {"scrape_attempts": 0, "scrape_failures": 0, "products_found": 0}

        for cat_url in category_urls:
            if len(products) >= max_products:
                break

            stats["scrape_attempts"] += 1
            try:
                result = self.firecrawl.scrape(cat_url, formats=["markdown", "links"])

                # Extract product links from category page
                links = []
                if hasattr(result, "links"):
                    links = result.links
                elif isinstance(result, dict):
                    links = result.get("links", [])

                # Filter to product URLs
                for link in links:
                    if len(products) >= max_products:
                        break

                    link_url = link if isinstance(link, str) else getattr(link, "url", str(link))
                    path = urlparse(link_url).path

                    if patterns.matches_product(path):
                        # Scrape individual product page
                        try:
                            prod_result = self.firecrawl.scrape(link_url, formats=["markdown"])
                            markdown = ""
                            if hasattr(prod_result, "markdown"):
                                markdown = prod_result.markdown
                            elif isinstance(prod_result, dict):
                                markdown = prod_result.get("markdown", "")

                            if markdown:
                                product = self._parse_product_from_markdown(markdown, link_url)
                                if product:
                                    products.append(product)
                                    stats["products_found"] += 1
                        except Exception as e:
                            logger.debug(f"Failed to scrape product {link_url}: {e}")

            except Exception as e:
                logger.warning(f"Failed to scrape category {cat_url}: {e}")
                stats["scrape_failures"] += 1

        return products, stats

    def deep_discover_products(
        self,
        category_urls: list[str],
        patterns: SitePatterns,
        max_pages_per_category: int = 20,
        progress: Optional[ProgressReporter] = None,
    ) -> list[str]:
        """Deep discovery: crawl all category pages including pagination to find ALL product URLs.

        Args:
            category_urls: Initial category URLs to crawl
            patterns: Site patterns for matching product/category URLs
            max_pages_per_category: Max pagination depth per category
            progress: Progress reporter for status updates

        Returns:
            List of unique product URLs discovered
        """
        prog = progress or _silent_reporter
        all_product_urls: set[str] = set()
        visited_pages: set[str] = set()
        categories_to_crawl = list(category_urls)
        initial_count = len(categories_to_crawl)

        logger.info(f"Starting deep discovery from {len(categories_to_crawl)} categories...")

        while categories_to_crawl:
            cat_url = categories_to_crawl.pop(0)

            if cat_url in visited_pages:
                continue
            visited_pages.add(cat_url)

            # Report progress - show crawled pages vs initial + any new ones found
            prog.phase_progress(
                "discovering",
                len(visited_pages),
                initial_count + len(categories_to_crawl),
                message=f"Crawling categories... ({len(all_product_urls)} products found)",
            )

            logger.info(f"Deep crawling: {cat_url} (found {len(all_product_urls)} products so far)")

            try:
                result = self.firecrawl.scrape(cat_url, formats=["links"])

                links = []
                if hasattr(result, "links"):
                    links = result.links
                elif isinstance(result, dict):
                    links = result.get("links", [])

                for link in links:
                    link_url = link if isinstance(link, str) else getattr(link, "url", str(link))

                    # Skip external links and empty URLs
                    if not link_url or "://" in link_url and patterns.domain not in link_url:
                        continue

                    # Skip URLs with query parameters or fragments (filters, wishlist, etc.)
                    if "?" in link_url or "#" in link_url:
                        continue

                    # Normalize URL
                    if link_url.startswith("/"):
                        link_url = f"https://{patterns.domain}{link_url}"

                    # Clean trailing slashes for consistency
                    link_url = link_url.rstrip("/")

                    path = urlparse(link_url).path

                    # Check if it's a product page
                    if patterns.matches_product(path):
                        all_product_urls.add(link_url)

                    # Check if it's a category/subcategory page we haven't visited
                    elif patterns.matches_category(path) and link_url not in visited_pages:
                        # Check pagination pattern (page/2, page/3, etc.)
                        if "/page/" in link_url:
                            try:
                                page_num = int(link_url.split("/page/")[-1].rstrip("/") or "1")
                                if page_num <= max_pages_per_category:
                                    categories_to_crawl.append(link_url)
                            except ValueError:
                                pass  # Skip invalid page numbers
                        else:
                            categories_to_crawl.append(link_url)

            except Exception as e:
                logger.warning(f"Failed to deep crawl {cat_url}: {e}")

        logger.info(f"Deep discovery complete: {len(all_product_urls)} unique products from {len(visited_pages)} pages")
        return list(all_product_urls)

    def _parse_product_from_markdown(self, markdown: str, url: str) -> Optional[dict]:
        """Extract product information using LLM for comprehensive data capture.

        Uses DeepSeek to intelligently extract ALL valuable product information
        including weight, dimensions, materials, features, use cases, etc.
        """
        # Skip common boilerplate patterns at the start (cookie banners, nav, etc.)
        content = markdown

        # Look for product-related markers to find where actual content starts
        product_markers = ['Warenkorb', 'In den', 'Preis', '€', 'Beschreibung', 'Produktdetails',
                          'Add to cart', 'Buy now', 'Product', 'Details', 'Artikelnummer']
        for marker in product_markers:
            idx = content.find(marker)
            if idx > 500 and idx < len(content) - 1000:  # Found marker after initial boilerplate
                # Go back a bit to capture product name/price that might precede it
                start_idx = max(0, idx - 500)
                content = content[start_idx:]
                logger.debug(f"Skipped {start_idx} chars of boilerplate, starting from '{marker}'")
                break

        # Now truncate to reasonable length for LLM
        content = content[:6000] if len(content) > 6000 else content

        # If content is too short, it's probably not a product page
        if len(content) < 200:
            logger.warning(f"Content too short ({len(content)} chars) for {url}")
            return None

        extraction_prompt = f"""Extract ALL product information from this page content. Be thorough - capture every detail.

Page URL: {url}

Page Content:
{content}

Extract and return a JSON object with these fields (use null for missing data):
{{
  "name": "Full product name without brand",
  "brand": "Manufacturer/brand name",
  "price": 0.00,
  "currency": "EUR or USD",
  "weight_grams": 0,
  "dimensions": "e.g., 15.5 × 10 cm",
  "materials": ["list of materials used"],
  "features": ["list of key features and benefits"],
  "use_cases": ["camping", "hiking", "travel", etc.],
  "category": "cookware/tent/sleeping_bag/backpack/clothing/lighting/etc.",
  "description": "Comprehensive description of the product",
  "specs": {{
    "any_other_specs": "value"
  }},
  "insights": ["valuable tips or knowledge about this product"]
}}

IMPORTANT:
- Extract weight even if mentioned casually (e.g., "16 Gramm" or "weighs only 16g")
- Convert all weights to grams
- Extract dimensions in original format
- Capture ALL features mentioned, not just the first few
- Include use cases and scenarios where the product excels
- Extract any tips, recommendations, or insights about the product
- If text is in German, translate key fields to English but keep original German insights

Return ONLY valid JSON, no other text."""

        try:
            response = self.llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a product data extraction expert. Extract comprehensive, detailed product information from web pages. Always return valid JSON.",
                    },
                    {"role": "user", "content": extraction_prompt},
                ],
                temperature=0.1,
                max_tokens=1500,
            )

            content = response.choices[0].message.content

            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            product_data = json.loads(content.strip())

            # Add source URL
            product_data["source_url"] = url

            # Clean up null values
            product_data = {k: v for k, v in product_data.items() if v is not None}

            # Ensure we have at least a name
            if not product_data.get("name"):
                logger.warning(f"LLM extraction returned no name for {url}")
                return None

            logger.info(
                f"LLM extracted product: {product_data.get('brand', '')} {product_data.get('name', '')} "
                f"(weight: {product_data.get('weight_grams', 'N/A')}g)"
            )
            return product_data

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"LLM response was: {content[:500]}...")
            return self._fallback_regex_parse(markdown, url)
        except Exception as e:
            logger.error(f"LLM extraction failed for {url}: {type(e).__name__}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return self._fallback_regex_parse(markdown, url)

    def _fallback_regex_parse(self, markdown: str, url: str) -> Optional[dict]:
        """Fallback to basic regex parsing if LLM fails."""
        import re

        product = {"source_url": url}

        # Try to extract product name from first heading
        name_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        if name_match:
            product["name"] = name_match.group(1).strip()

        # Try to extract price
        price_patterns = [
            r"(\d+[.,]\d{2})\s*(?:EUR|USD|\$|€)",
            r"(?:EUR|USD|\$|€)\s*(\d+[.,]\d{2})",
        ]
        for pattern in price_patterns:
            match = re.search(pattern, markdown, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(",", ".")
                try:
                    product["price"] = float(price_str)
                except ValueError:
                    pass
                break

        # Try to extract weight
        weight_patterns = [
            r"(\d+(?:[.,]\d+)?)\s*(?:Gramm|grams?|g)\b",
            r"(?:Gewicht|Weight)[:\s]*(\d+(?:[.,]\d+)?)",
        ]
        for pattern in weight_patterns:
            match = re.search(pattern, markdown, re.IGNORECASE)
            if match:
                value = float(match.group(1).replace(",", "."))
                product["weight_grams"] = int(value)
                break

        if "name" in product:
            return product
        return None

    def _cloud_crawl_fallback(self, url: str, reason: str) -> ExtractionResult:
        """Fallback to cloud Firecrawl when smart extraction isn't possible."""
        logger.info(f"Cloud fallback triggered: {reason}")

        # For now, return empty result with fallback indicator
        # Full cloud crawl implementation would go here
        return ExtractionResult(
            products=[],
            source="cloud_crawl_fallback",
            patterns=None,
            from_cache=False,
            estimated_cost=0.0,
            stats={"fallback_reason": reason},
        )


# Singleton instance
_analyzer: Optional[SmartSiteAnalyzer] = None


def get_site_analyzer() -> SmartSiteAnalyzer:
    """Get or create the singleton SmartSiteAnalyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = SmartSiteAnalyzer()
    return _analyzer

"""Smart Firecrawl client with self-hosted primary and cloud fallback.

Uses self-hosted Firecrawl instance (free) as primary, with automatic
fallback to cloud API (paid) on failure. Includes retry logic, timeout
handling, and usage statistics tracking.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from firecrawl import FirecrawlApp

logger = logging.getLogger(__name__)


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


class SmartFirecrawlClient:
    """Firecrawl client with automatic self-hosted → cloud fallback."""

    def __init__(self, config: Optional[FirecrawlConfig] = None):
        """Initialize the client with optional config (defaults to env vars)."""
        self.config = config or FirecrawlConfig.from_env()
        self.stats = UsageStats()
        self._self_hosted_client: Optional[FirecrawlApp] = None
        self._cloud_client: Optional[FirecrawlApp] = None
        self._init_clients()

    def _init_clients(self):
        """Initialize Firecrawl client instances."""
        # Self-hosted client (primary)
        if self.config.self_hosted_url:
            try:
                self._self_hosted_client = FirecrawlApp(
                    api_key=self.config.self_hosted_key,
                    api_url=self.config.self_hosted_url,
                )
                logger.info(f"Self-hosted Firecrawl configured: {self.config.self_hosted_url}")
            except Exception as e:
                logger.warning(f"Failed to init self-hosted client: {e}")

        # Cloud client (fallback)
        if self.config.cloud_api_key:
            try:
                self._cloud_client = FirecrawlApp(api_key=self.config.cloud_api_key)
                logger.info("Cloud Firecrawl configured")
            except Exception as e:
                logger.warning(f"Failed to init cloud client: {e}")

        if not self._self_hosted_client and not self._cloud_client:
            raise ValueError("No Firecrawl client available. Set FIRECRAWL_SELF_HOSTED_URL or FIRECRAWL_API_KEY")

    def _scrape_with_timeout(self, client: FirecrawlApp, url: str, **kwargs) -> Any:
        """Execute scrape with timeout."""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(client.scrape, url, **kwargs)
            try:
                return future.result(timeout=self.config.timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"Scrape timed out after {self.config.timeout}s")

    def scrape_url(self, url: str, formats: list[str] = None, **kwargs) -> ScrapeResult:
        """Scrape a URL with automatic fallback.

        Args:
            url: URL to scrape
            formats: Output formats (e.g., ["markdown", "html"])
            **kwargs: Additional arguments passed to Firecrawl

        Returns:
            ScrapeResult with data and metadata
        """
        formats = formats or ["markdown"]
        kwargs["formats"] = formats

        # Try self-hosted first
        if self._self_hosted_client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted scrape attempt {attempt + 1}: {url}")
                    result = self._scrape_with_timeout(self._self_hosted_client, url, **kwargs)

                    self.stats.self_hosted_calls += 1
                    logger.info(f"[Firecrawl] ✅ Self-hosted success (total: {self.stats.self_hosted_calls})")

                    return self._parse_result(result, source="self-hosted", cost=0)

                except Exception as e:
                    logger.warning(f"[Firecrawl] ⚠️ Self-hosted attempt {attempt + 1} failed: {e}")
                    self.stats.self_hosted_failures += 1

                    if attempt < self.config.max_retries:
                        time.sleep((attempt + 1) * 1.0)  # Exponential backoff
                    else:
                        logger.warning("[Firecrawl] All self-hosted retries exhausted")

            if not self.config.enable_fallback:
                return ScrapeResult(success=False, error="Self-hosted failed and fallback disabled")

        # Fallback to cloud
        if self._cloud_client:
            try:
                logger.info(f"[Firecrawl] 💰 Using cloud API: {url}")
                result = self._cloud_client.scrape(url, **kwargs)

                self.stats.cloud_calls += 1
                self.stats.total_credits += 1
                logger.info(
                    f"[Firecrawl] Cloud success (calls: {self.stats.cloud_calls}, "
                    f"cost: ~${self.stats.estimated_cost:.3f})"
                )

                return self._parse_result(result, source="cloud", cost=1)

            except Exception as e:
                logger.error(f"[Firecrawl] ❌ Cloud API also failed: {e}")
                return ScrapeResult(success=False, error=f"Both self-hosted and cloud failed: {e}")

        return ScrapeResult(success=False, error="No Firecrawl client available")

    def scrape(self, url: str, formats: list[str] = None, **kwargs) -> Any:
        """Scrape URL - returns raw result for backward compatibility."""
        result = self.scrape_url(url, formats, **kwargs)
        if not result.success:
            raise ValueError(result.error)
        return result.data

    def search(self, query: str, limit: int = 5) -> Any:
        """Search the web with automatic fallback."""
        if self._self_hosted_client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted search: {query}")
                    result = self._self_hosted_client.search(query, limit=limit)
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
                self.stats.total_credits += limit  # Search costs ~1 credit per result
                return result
            except Exception as e:
                raise ValueError(f"Search failed: {e}")

        raise ValueError("No Firecrawl client available for search")

    def map(self, url: str, limit: int = 100) -> Any:
        """Map a website with automatic fallback."""
        if self._self_hosted_client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted map: {url}")
                    result = self._self_hosted_client.map(url, limit=limit)
                    self.stats.self_hosted_calls += 1
                    return result
                except Exception as e:
                    logger.warning(f"[Firecrawl] Self-hosted map failed: {e}")
                    if attempt < self.config.max_retries:
                        time.sleep((attempt + 1) * 1.0)

        if self._cloud_client and self.config.enable_fallback:
            try:
                logger.info(f"[Firecrawl] 💰 Cloud map: {url}")
                result = self._cloud_client.map(url, limit=limit)
                self.stats.cloud_calls += 1
                self.stats.total_credits += 1
                return result
            except Exception as e:
                raise ValueError(f"Map failed: {e}")

        raise ValueError("No Firecrawl client available for map")

    def extract(self, urls: list[str], schema: dict, prompt: str = "") -> Any:
        """Extract structured data with automatic fallback."""
        if self._self_hosted_client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"[Firecrawl] Self-hosted extract: {urls}")
                    result = self._self_hosted_client.extract(urls=urls, schema=schema, prompt=prompt)
                    self.stats.self_hosted_calls += 1
                    return result
                except Exception as e:
                    logger.warning(f"[Firecrawl] Self-hosted extract failed: {e}")
                    if attempt < self.config.max_retries:
                        time.sleep((attempt + 1) * 1.0)

        if self._cloud_client and self.config.enable_fallback:
            try:
                logger.info(f"[Firecrawl] 💰 Cloud extract: {urls}")
                result = self._cloud_client.extract(urls=urls, schema=schema, prompt=prompt)
                self.stats.cloud_calls += 1
                self.stats.total_credits += len(urls) * 5  # Extract is more expensive
                return result
            except Exception as e:
                raise ValueError(f"Extract failed: {e}")

        raise ValueError("No Firecrawl client available for extract")

    def _parse_result(self, result: Any, source: str, cost: int) -> ScrapeResult:
        """Parse Firecrawl result into ScrapeResult."""
        markdown = ""
        html = ""
        metadata = {}

        if hasattr(result, "markdown"):
            markdown = result.markdown or ""
        if hasattr(result, "html"):
            html = result.html or ""
        if hasattr(result, "metadata"):
            metadata = result.metadata if isinstance(result.metadata, dict) else {}

        return ScrapeResult(
            success=True,
            data=result,
            markdown=markdown,
            html=html,
            metadata=metadata,
            source=source,
            cost=cost,
        )

    def get_usage_stats(self) -> dict:
        """Get usage statistics."""
        return self.stats.to_dict()

    def reset_stats(self):
        """Reset usage statistics."""
        self.stats = UsageStats()


# Singleton instance - initialized lazily
_client_instance: Optional[SmartFirecrawlClient] = None


def get_smart_firecrawl() -> SmartFirecrawlClient:
    """Get or create the singleton SmartFirecrawlClient instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = SmartFirecrawlClient()
    return _client_instance


def reset_client():
    """Reset the singleton instance (useful for testing)."""
    global _client_instance
    _client_instance = None

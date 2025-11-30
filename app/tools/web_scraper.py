"""Web scraping and search tools using Firecrawl."""

import os
from typing import Optional

from firecrawl import FirecrawlApp


def _get_firecrawl_client() -> FirecrawlApp:
    """Get Firecrawl client instance."""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY environment variable is required")
    return FirecrawlApp(api_key=api_key)


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

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
        result = client.scrape_url(
            url,
            params={
                "formats": ["markdown"] if include_markdown else ["text"],
            },
        )

        if include_markdown and "markdown" in result:
            return result["markdown"]
        elif "text" in result:
            return result["text"]
        elif "content" in result:
            return result["content"]
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
        result = client.search(query, params={"limit": num_results})

        search_results = []
        if isinstance(result, dict) and "data" in result:
            for item in result["data"][:num_results]:
                search_results.append(
                    {
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                        "snippet": item.get("description", item.get("snippet", "")),
                    }
                )
        elif isinstance(result, list):
            for item in result[:num_results]:
                search_results.append(
                    {
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                        "snippet": item.get("description", item.get("snippet", "")),
                    }
                )

        return search_results

    except Exception as e:
        raise ValueError(f"Search failed for '{query}': {str(e)}")

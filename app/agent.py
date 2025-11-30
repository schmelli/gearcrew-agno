"""GearCrew Agent - Extracts hiking/backpacking gear information from web sources."""

import os
from typing import Optional

import langwatch
from agno.agent import Agent
from agno.models.anthropic import Claude
from dotenv import load_dotenv

from app.models.gear import ExtractionResult, GearItem, KnowledgeFact, Manufacturer
from app.tools.youtube import get_youtube_transcript
from app.tools.web_scraper import scrape_webpage, search_web
from app.tools.geargraph import (
    find_similar_gear,
    check_gear_exists,
    get_graph_statistics,
    save_gear_to_graph,
    save_insight_to_graph,
    search_graph,
)

load_dotenv()


def _get_system_prompt() -> str:
    """Fetch the system prompt from LangWatch."""
    prompt = langwatch.prompts.get("gear-extractor")
    messages = prompt.messages if hasattr(prompt, "messages") else []
    for msg in messages:
        if msg.get("role") == "system":
            return msg.get("content", "")
    return ""


def fetch_youtube_transcript(video_url: str) -> str:
    """Fetch transcript from a YouTube video.

    Args:
        video_url: YouTube video URL or ID

    Returns:
        Full transcript text
    """
    try:
        return get_youtube_transcript(video_url)
    except ValueError as e:
        return f"Error fetching transcript: {str(e)}"


def fetch_webpage_content(url: str) -> str:
    """Fetch and parse content from a webpage.

    Args:
        url: The URL to scrape

    Returns:
        Webpage content as markdown
    """
    try:
        return scrape_webpage(url)
    except ValueError as e:
        return f"Error scraping webpage: {str(e)}"


def search_gear_info(query: str) -> str:
    """Search the web for gear information.

    Args:
        query: Search query about hiking/backpacking gear

    Returns:
        Search results with URLs, titles, and snippets
    """
    try:
        results = search_web(query, num_results=5)
        if not results:
            return "No search results found."

        output = []
        for i, result in enumerate(results, 1):
            output.append(f"{i}. {result['title']}")
            output.append(f"   URL: {result['url']}")
            output.append(f"   {result['snippet']}")
            output.append("")

        return "\n".join(output)
    except ValueError as e:
        return f"Error searching: {str(e)}"


def create_gear_agent() -> Agent:
    """Create and configure the gear extraction agent.

    Returns:
        Configured Agno Agent instance
    """
    system_prompt = _get_system_prompt()

    agent = Agent(
        name="GearCrew",
        model=Claude(id="claude-sonnet-4-20250514"),
        instructions=system_prompt,
        tools=[
            # Content fetching tools
            fetch_youtube_transcript,
            fetch_webpage_content,
            search_gear_info,
            # GearGraph database tools
            find_similar_gear,
            check_gear_exists,
            get_graph_statistics,
            save_gear_to_graph,
            save_insight_to_graph,
            search_graph,
        ],
        markdown=True,
    )

    return agent


_agent: Optional[Agent] = None


def get_agent() -> Agent:
    """Get or create the singleton agent instance.

    Returns:
        The gear extraction agent
    """
    global _agent
    if _agent is None:
        _agent = create_gear_agent()
    return _agent


@langwatch.trace()
def extract_gear_info(source_url: str) -> ExtractionResult:
    """Extract gear information from a given source URL.

    Args:
        source_url: URL to extract gear information from (YouTube, blog, etc.)

    Returns:
        Structured extraction result with gear items and facts
    """
    agent = get_agent()

    prompt = f"""Please analyze the following source and extract all hiking/backpacking gear information:

Source URL: {source_url}

1. First, fetch the content from this URL using the appropriate tool (YouTube transcript or webpage scraper)
2. Extract all gear items mentioned with their specifications
3. Identify any manufacturers and their details
4. Extract valuable knowledge facts, tips, and reviews

Return the structured extraction result."""

    response = agent.run(prompt)

    if isinstance(response.content, ExtractionResult):
        return response.content

    return ExtractionResult(
        source_url=source_url,
        source_type="unknown",
        gear_items=[],
        manufacturers=[],
        knowledge_facts=[],
        raw_content=str(response.content) if response.content else None,
    )


def run_agent_chat(message: str) -> str:
    """Run the agent in chat mode for interactive conversations.

    Args:
        message: User message to process

    Returns:
        Agent's response as string
    """
    agent = get_agent()
    response = agent.run(message)
    return str(response.content) if response.content else ""

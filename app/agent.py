"""GearCrew Agent - Extracts hiking/backpacking gear information from web sources.

Uses tiered Claude models for different task complexities:
- Haiku 4.5: Fast, simple tasks (quick lookups, simple questions)
- Sonnet 4.5: Standard tasks (extraction, analysis, most interactions)
- Opus 4.5 + Thinking: Complex tasks (verification, conflict resolution, deep analysis)
"""

import os
import re
from typing import Optional, Literal

import langwatch
from agno.agent import Agent
from agno.models.anthropic import Claude
from dotenv import load_dotenv

from app.models.gear import ExtractionResult, GearItem, KnowledgeFact, Manufacturer
from app.tools.youtube import get_youtube_transcript
from app.tools.web_scraper import (
    scrape_webpage,
    search_web,
    map_website,
    extract_product_data,
    batch_extract_products,
)
from app.tools.geargraph import (
    find_similar_gear,
    check_gear_exists,
    get_graph_statistics,
    save_gear_to_graph,
    save_insight_to_graph,
    search_graph,
    check_video_already_processed,
    get_previous_extraction_summary,
    save_extraction_result,
    link_extracted_gear_to_source,
    merge_duplicate_gear,
    update_existing_gear,
    audit_duplicates,
)

load_dotenv()

# Model tier definitions
ModelTier = Literal["haiku", "sonnet", "opus"]

CLAUDE_MODELS = {
    "haiku": Claude(
        id="claude-haiku-4-5-20251001",
        max_tokens=4096,
    ),
    "sonnet": Claude(
        id="claude-sonnet-4-5-20250929",
        max_tokens=8192,
    ),
    "opus": Claude(
        id="claude-opus-4-5-20251101",
        max_tokens=16384,
        thinking={"type": "enabled", "budget_tokens": 10000},
    ),
}


def _get_system_prompt() -> str:
    """Fetch the system prompt from LangWatch."""
    prompt = langwatch.prompts.get("gear-extractor")
    messages = prompt.messages if hasattr(prompt, "messages") else []
    for msg in messages:
        if msg.get("role") == "system":
            return msg.get("content", "")
    return ""


def _classify_task_complexity(message: str) -> ModelTier:
    """Classify the complexity of a task to select appropriate model.

    Args:
        message: User message or task description

    Returns:
        Model tier: 'haiku', 'sonnet', or 'opus'
    """
    message_lower = message.lower()

    # Opus-level tasks (complex analysis, verification, conflicts)
    opus_patterns = [
        r"verify|verification|validate|fact.?check",
        r"conflict|discrepancy|contradiction",
        r"compare.*multiple|analyze.*depth|comprehensive",
        r"why.*different|explain.*difference",
        r"reconcile|resolve.*issue",
        r"complex|difficult|challenging",
    ]
    for pattern in opus_patterns:
        if re.search(pattern, message_lower):
            return "opus"

    # Haiku-level tasks (simple lookups, quick questions)
    haiku_patterns = [
        r"^(what|who|where|when|which)\s+is\b",
        r"^(list|show|get|find)\s+(me\s+)?(the\s+)?",
        r"how\s+much\s+(does|is)",
        r"^(yes|no)\?",
        r"search\s+(for|the)\s+graph",
        r"graph\s+stats|statistics",
    ]
    for pattern in haiku_patterns:
        if re.search(pattern, message_lower):
            return "haiku"

    # Check message length - very short messages likely simple
    if len(message) < 50 and "?" in message:
        return "haiku"

    # Default to Sonnet for standard extraction and analysis tasks
    return "sonnet"


# Tool functions
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


def discover_product_pages(website_url: str) -> str:
    """Map a manufacturer's website to discover all product pages.

    Use this when given a manufacturer's main website URL to find
    all their product pages for extraction.

    Args:
        website_url: Base URL of the manufacturer's website (e.g., https://durstongear.com)

    Returns:
        List of discovered product page URLs
    """
    try:
        result = map_website(website_url, max_pages=100)

        output = [f"## Website Map Results for {website_url}\n"]
        output.append(f"Total pages found: {result['total_count']}")
        output.append(f"Product pages identified: {result['product_count']}\n")

        if result['product_urls']:
            output.append("### Product Pages:")
            for i, url in enumerate(result['product_urls'][:20], 1):
                output.append(f"{i}. {url}")

            if len(result['product_urls']) > 20:
                output.append(f"\n... and {len(result['product_urls']) - 20} more")

            output.append("\n**Next steps:**")
            output.append("- Use `extract_gear_from_page(url)` to extract gear data from specific pages")
            output.append("- Or analyze multiple pages in sequence")
        else:
            output.append("No obvious product pages found.")
            output.append("Try using `fetch_webpage_content` on specific pages instead.")

        return "\n".join(output)

    except ValueError as e:
        return f"Error mapping website: {str(e)}"


def extract_gear_from_page(url: str) -> str:
    """Extract structured gear information from a product page.

    Uses AI-powered extraction to pull product data from any gear page.
    Works with manufacturer sites, review sites, and retailers.

    Args:
        url: URL of the product page to extract from

    Returns:
        Extracted product information in structured format
    """
    try:
        data = extract_product_data(url)

        if not data or (isinstance(data, dict) and not data.get('product_name')):
            return f"Could not extract product data from {url}. Try using fetch_webpage_content instead."

        output = ["## Extracted Product Data\n"]

        # Format the extracted data
        if isinstance(data, dict):
            for key, value in data.items():
                if value and key != 'source_url':
                    if isinstance(value, list):
                        output.append(f"**{key.replace('_', ' ').title()}:**")
                        for item in value:
                            output.append(f"  - {item}")
                    elif isinstance(value, dict):
                        output.append(f"**{key.replace('_', ' ').title()}:**")
                        for k, v in value.items():
                            output.append(f"  - {k}: {v}")
                    else:
                        output.append(f"**{key.replace('_', ' ').title()}:** {value}")

            output.append(f"\n**Source URL:** {url}")

            # Reminder about duplicate check
            output.append("\n---")
            output.append("**IMPORTANT:** Before saving, use `find_similar_gear` to check for duplicates!")

        return "\n".join(output)

    except ValueError as e:
        return f"Error extracting product data: {str(e)}"


# All available tools for agents
AGENT_TOOLS = [
    # Content fetching tools
    fetch_youtube_transcript,
    fetch_webpage_content,
    search_gear_info,
    # GearGraph database tools - DUPLICATE CHECK FIRST!
    find_similar_gear,  # MUST call before save_gear_to_graph
    check_gear_exists,
    get_graph_statistics,
    save_gear_to_graph,
    save_insight_to_graph,
    search_graph,
    # Duplicate management tools
    audit_duplicates,  # Scan entire database for duplicates
    merge_duplicate_gear,
    update_existing_gear,
    # Source tracking tools
    check_video_already_processed,
    get_previous_extraction_summary,
    save_extraction_result,
    link_extracted_gear_to_source,
    # Website extraction tools
    discover_product_pages,  # Map manufacturer sites to find product URLs
    extract_gear_from_page,  # Extract structured data from single product page
]


def create_gear_agent(model_tier: ModelTier = "sonnet") -> Agent:
    """Create and configure a gear extraction agent with specified model tier.

    Args:
        model_tier: Which Claude model to use ('haiku', 'sonnet', 'opus')

    Returns:
        Configured Agno Agent instance
    """
    system_prompt = _get_system_prompt()
    model = CLAUDE_MODELS[model_tier]

    agent = Agent(
        name=f"GearCrew-{model_tier.capitalize()}",
        model=model,
        instructions=system_prompt,
        tools=AGENT_TOOLS,
        markdown=True,
    )

    return agent


# Cached agent instances per tier
_agents: dict[ModelTier, Agent] = {}


def get_agent(model_tier: ModelTier = "sonnet") -> Agent:
    """Get or create an agent instance for the specified model tier.

    Args:
        model_tier: Which Claude model to use ('haiku', 'sonnet', 'opus')

    Returns:
        The gear extraction agent
    """
    global _agents
    if model_tier not in _agents:
        _agents[model_tier] = create_gear_agent(model_tier)
    return _agents[model_tier]


@langwatch.trace()
def extract_gear_info(source_url: str) -> ExtractionResult:
    """Extract gear information from a given source URL.

    Uses Sonnet for standard extraction tasks.

    Args:
        source_url: URL to extract gear information from (YouTube, blog, etc.)

    Returns:
        Structured extraction result with gear items and facts
    """
    # Extraction is a standard complexity task - use Sonnet
    agent = get_agent("sonnet")

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


def run_agent_chat(message: str, model_tier: ModelTier | None = None) -> str:
    """Run the agent in chat mode for interactive conversations.

    Automatically selects the appropriate model tier based on task complexity,
    or uses the specified tier if provided.

    Args:
        message: User message to process
        model_tier: Optional model tier override ('haiku', 'sonnet', 'opus')

    Returns:
        Agent's response as string
    """
    # Auto-classify if not specified
    if model_tier is None:
        model_tier = _classify_task_complexity(message)

    agent = get_agent(model_tier)
    response = agent.run(message)
    return str(response.content) if response.content else ""


def run_agent_chat_with_tier(message: str) -> tuple[str, ModelTier]:
    """Run the agent and return both response and which model tier was used.

    Args:
        message: User message to process

    Returns:
        Tuple of (response string, model tier used)
    """
    model_tier = _classify_task_complexity(message)
    response = run_agent_chat(message, model_tier)
    return response, model_tier

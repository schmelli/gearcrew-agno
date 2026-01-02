"""GearCrew Agent - Extracts hiking/backpacking gear information from web sources.

Supports multiple LLM providers for cost optimization:
- DeepSeek (default): Very cost-effective, good for extraction tasks
- Claude: Higher quality but more expensive (Haiku/Sonnet/Opus tiers)

Set LLM_PROVIDER env var to switch: "deepseek" (default) or "anthropic"
"""

import os
import re
from typing import Optional, Literal

import langwatch
from agno.agent import Agent, RunEvent
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from dotenv import load_dotenv
from typing import Iterator, Callable

from app.models.gear import ExtractionResult, GearItem, KnowledgeFact, Manufacturer
from app.tools.youtube import (
    get_youtube_transcript,
    get_playlist_videos,
    get_playlist_info,
)
from app.tools.lighterpack_importer import import_lighterpack_sync
from app.tools.web_scraper import (
    scrape_webpage,
    search_web,
    map_website,
    extract_product_data,
    extract_multiple_products,
    batch_extract_products,
    discover_catalog,
    quick_count_products,
    verify_brand_product,
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
    # Glossary tools
    save_glossary_term,
    lookup_glossary_term,
    list_glossary_terms,
    link_gear_to_term,
    find_gear_with_term,
    import_glossary_from_json,
)

load_dotenv()

# Model tier definitions
ModelTier = Literal["haiku", "sonnet", "opus"]
LLMProvider = Literal["deepseek", "anthropic"]

# Get configured provider (default to deepseek for cost savings)
LLM_PROVIDER: LLMProvider = os.getenv("LLM_PROVIDER", "deepseek").lower()  # type: ignore

# DeepSeek models (very cost-effective: ~$0.14/M input, $0.28/M output)
# Note: deepseek-reasoner doesn't support tool calls, so we use deepseek-chat for all tiers
DEEPSEEK_MODELS = {
    "haiku": DeepSeek(
        id="deepseek-chat",
        max_tokens=4096,
    ),
    "sonnet": DeepSeek(
        id="deepseek-chat",
        max_tokens=8192,
    ),
    "opus": DeepSeek(
        id="deepseek-chat",  # deepseek-reasoner doesn't support tool calls
        max_tokens=16384,
    ),
}

# Claude models (higher quality but more expensive)
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


def _get_model(tier: ModelTier):
    """Get the appropriate model based on configured provider and tier."""
    if LLM_PROVIDER == "anthropic":
        return CLAUDE_MODELS[tier]
    else:
        return DEEPSEEK_MODELS[tier]


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

    Supports multiple languages including English and German.
    Will try to get transcript in preferred languages, or fall back to any available.

    Args:
        video_url: YouTube video URL or ID

    Returns:
        Full transcript text
    """
    try:
        # Try English and German first, then fall back to any available language
        return get_youtube_transcript(video_url, languages=["en", "de"])
    except ValueError as e:
        return f"Error fetching transcript: {str(e)}"


def fetch_youtube_playlist(playlist_url: str) -> str:
    """Fetch videos from a YouTube playlist and show which are already processed.

    Use this when given a YouTube playlist URL to see all videos and identify
    which ones have not yet been processed for gear extraction.

    Args:
        playlist_url: YouTube playlist URL (e.g., https://youtube.com/playlist?list=...)

    Returns:
        List of videos with processing status
    """
    try:
        # Get playlist info
        info = get_playlist_info(playlist_url)
        videos = get_playlist_videos(playlist_url)

        output = [f"## Playlist: {info['title']}"]
        output.append(f"Channel: {info['channel']}")
        output.append(f"Total videos: {info['video_count']}\n")

        # Check which videos have been processed
        processed_count = 0
        unprocessed = []

        output.append("### Videos:\n")
        for i, video in enumerate(videos, 1):
            url = video["url"]
            is_processed = check_video_already_processed(url)

            status = "✅ Processed" if "already been processed" in is_processed else "⏳ Not processed"
            if "not yet been processed" in is_processed:
                unprocessed.append(video)
            else:
                processed_count += 1

            duration_str = ""
            if video.get("duration"):
                mins = video["duration"] // 60
                secs = video["duration"] % 60
                duration_str = f" ({mins}:{secs:02d})"

            output.append(f"{i}. [{status}] {video['title']}{duration_str}")
            output.append(f"   {url}\n")

        # Summary
        output.append("---")
        output.append(f"**Summary:** {processed_count} processed, {len(unprocessed)} remaining\n")

        if unprocessed:
            output.append("**Unprocessed videos to extract from:**")
            for v in unprocessed[:10]:
                output.append(f"- {v['title']}: {v['url']}")
            if len(unprocessed) > 10:
                output.append(f"... and {len(unprocessed) - 10} more")

            output.append("\n**Next step:** Use `fetch_youtube_transcript(url)` on each unprocessed video to extract gear info.")

        return "\n".join(output)

    except ValueError as e:
        return f"Error fetching playlist: {str(e)}"


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
    """Map a manufacturer's website to discover all product and collection pages.

    Use this when given a manufacturer's main website URL to find
    all their product pages for extraction.

    **IMPORTANT**: Collection pages (like /collections/sleeping-pads) contain
    multiple products and should be extracted using `extract_gear_list_page`.
    Individual product pages should use `extract_gear_from_page`.

    Args:
        website_url: Base URL of the manufacturer's website (e.g., https://durstongear.com)

    Returns:
        List of discovered product page URLs and collection URLs
    """
    try:
        result = map_website(website_url, max_pages=200)

        output = [f"## Website Map Results for {website_url}\n"]
        output.append(f"Total pages found: {result['total_count']}")
        output.append(f"Individual product pages: {result['product_count']}")
        output.append(f"Collection/category pages: {result.get('collection_count', 0)}\n")

        # Show collection pages first - these are more valuable for bulk extraction
        collection_urls = result.get('collection_urls', [])
        if collection_urls:
            output.append("### Collection Pages (EXTRACT FIRST - contain multiple products):")
            for i, url in enumerate(collection_urls, 1):
                output.append(f"{i}. {url}")
            output.append("")
            output.append("**IMPORTANT**: Use `extract_gear_list_page(url)` on collection pages")
            output.append("to extract ALL products from each category in one go!\n")

        if result['product_urls']:
            output.append("### Individual Product Pages:")
            for i, url in enumerate(result['product_urls'][:30], 1):
                output.append(f"{i}. {url}")

            if len(result['product_urls']) > 30:
                output.append(f"\n... and {len(result['product_urls']) - 30} more")

        output.append("\n---")
        output.append("## Recommended Extraction Strategy:")
        if collection_urls:
            output.append("1. **FIRST**: Extract from collection pages using `extract_gear_list_page(url)`")
            output.append("   - Each collection page contains many products")
            output.append("   - This is much more efficient than individual pages")
        output.append("2. **THEN**: Extract from individual product pages if needed")
        output.append("   - Use `extract_gear_from_page(url)` for detailed single-product extraction")
        output.append("3. **ALWAYS**: Check for duplicates with `find_similar_gear` before saving")

        if not result['product_urls'] and not collection_urls:
            output.append("\nNo obvious product or collection pages found.")
            output.append("Try using `fetch_webpage_content` on specific pages instead.")

        return "\n".join(output)

    except ValueError as e:
        return f"Error mapping website: {str(e)}"


def extract_gear_from_page(url: str) -> str:
    """Extract structured gear information from a SINGLE product page.

    Best for: Individual product pages on manufacturer or retailer sites.
    NOT for: List pages, gear guides, or "best of" articles with multiple products.

    For pages with multiple products, use `extract_gear_list_page` instead.

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


def extract_gear_list_page(url: str) -> str:
    """Extract ALL gear items from a list page, gear guide, or comparison article.

    Use this for pages that mention MULTIPLE products, such as:
    - "Best hiking gear" guides
    - Gear comparison articles
    - "What's in my pack" posts
    - Product roundups and recommendations

    For single product pages, use `extract_gear_from_page` instead.

    Args:
        url: URL of the gear list/guide page

    Returns:
        List of all products found with detailed specs for each
    """
    try:
        data = extract_multiple_products(url)

        products = data.get('products', [])
        page_title = data.get('page_title', 'Unknown Page')

        if not products:
            return f"No products found on {url}. The page may not be a gear list, or try using fetch_webpage_content to analyze manually."

        output = [f"## Gear List Extraction: {page_title}\n"]
        output.append(f"**Source:** {url}")
        output.append(f"**Products Found:** {len(products)}\n")
        output.append("---\n")

        for i, product in enumerate(products, 1):
            name = product.get('product_name', 'Unknown')
            brand = product.get('brand', 'Unknown')
            category = product.get('category', '')
            price = product.get('price_usd') or product.get('price')
            desc = product.get('description', '')
            link = product.get('product_url') or product.get('affiliate_url', '')
            weight_g = product.get('weight_grams')
            weight_oz = product.get('weight_oz')
            materials = product.get('materials', [])
            features = product.get('features', [])

            output.append(f"### {i}. {brand} {name}")
            if category:
                output.append(f"**Category:** {category}")
            if price:
                output.append(f"**Price:** ${price}")

            # Weight info
            weight_str = []
            if weight_g:
                weight_str.append(f"{weight_g}g")
            if weight_oz:
                weight_str.append(f"{weight_oz}oz")
            if weight_str:
                output.append(f"**Weight:** {' / '.join(weight_str)}")

            # Category-specific specs
            specs = []
            if product.get('volume_liters'):
                specs.append(f"Volume: {product['volume_liters']}L")
            if product.get('temp_rating_f'):
                specs.append(f"Temp Rating: {product['temp_rating_f']}°F")
            if product.get('r_value'):
                specs.append(f"R-Value: {product['r_value']}")
            if product.get('capacity_persons'):
                specs.append(f"Capacity: {product['capacity_persons']}P")
            if product.get('fill_power'):
                specs.append(f"Fill Power: {product['fill_power']}")
            if product.get('waterproof_rating'):
                specs.append(f"Waterproof: {product['waterproof_rating']}")
            if product.get('lumens'):
                specs.append(f"Lumens: {product['lumens']}")
            if product.get('fuel_type'):
                specs.append(f"Fuel: {product['fuel_type']}")
            if product.get('filter_type'):
                specs.append(f"Filter: {product['filter_type']}")
            if specs:
                output.append(f"**Specs:** {', '.join(specs)}")

            if materials:
                output.append(f"**Materials:** {', '.join(materials)}")
            if features:
                output.append(f"**Features:** {', '.join(features[:5])}")  # Limit to 5
            if desc:
                # Truncate long descriptions
                desc_short = desc[:200] + "..." if len(desc) > 200 else desc
                output.append(f"**Description:** {desc_short}")
            if link:
                output.append(f"**Link:** {link}")
            output.append("")

        output.append("---")
        output.append(f"**Total: {len(products)} products found**")

        # Stats on data quality
        with_weight = sum(1 for p in products if p.get('weight_grams') or p.get('weight_oz'))
        with_price = sum(1 for p in products if p.get('price_usd') or p.get('price'))
        with_desc = sum(1 for p in products if p.get('description'))
        output.append(f"\n**Data Quality:** {with_weight}/{len(products)} have weight, {with_price}/{len(products)} have price, {with_desc}/{len(products)} have description")

        output.append("\n**Next steps:**")
        output.append("- Use `find_similar_gear` to check each item for duplicates")
        output.append("- Use `save_gear_to_graph` with ALL available fields (description, features, weight_grams, category-specific specs)")
        output.append("- Link all items to source with `link_extracted_gear_to_source`")

        return "\n".join(output)

    except ValueError as e:
        return f"Error extracting gear list: {str(e)}"


def discover_manufacturer_catalog(website_url: str) -> str:
    """Discover a manufacturer's complete product catalog structure.

    This is Phase 1 of the two-phase extraction process. It quickly maps
    the website and counts products in each category WITHOUT doing full extraction.

    Use this BEFORE extracting products to:
    1. See what product categories the manufacturer has
    2. Know how many products are in each category
    3. Let the user decide which categories to extract

    Args:
        website_url: Base URL of the manufacturer's website (e.g., https://bigagnes.com)

    Returns:
        Structured catalog overview with categories and product counts
    """
    try:
        catalog = discover_catalog(website_url, max_pages=300)

        output = [f"# {catalog['brand_name']} Product Catalog\n"]
        output.append(f"**Website:** {catalog['website_url']}")
        output.append(f"**Total Categories:** {catalog['total_categories']}")
        output.append(f"**Estimated Products:** {catalog['total_products_estimated']}")
        output.append(f"**Individual Product Pages:** {catalog['individual_product_pages']}\n")

        output.append("---\n")
        output.append("## Product Categories\n")

        categories = catalog.get('categories', [])
        if categories:
            for i, cat in enumerate(categories, 1):
                cat_name = cat.get('category_name', f'Category {i}')
                count = cat.get('product_count', 0)
                url = cat.get('url', '')

                output.append(f"### {i}. {cat_name} ({count} products)")
                output.append(f"   URL: {url}")

                # Show product names preview
                product_names = cat.get('product_names', [])
                if product_names:
                    output.append("   Products:")
                    for name in product_names[:5]:
                        output.append(f"   - {name}")
                    if len(product_names) > 5:
                        output.append(f"   - ... and {len(product_names) - 5} more")

                # Show subcategories if any
                if cat.get('has_subcategories'):
                    subcats = cat.get('subcategory_names', [])
                    if subcats:
                        output.append(f"   Subcategories: {', '.join(subcats)}")

                output.append("")
        else:
            output.append("No product categories found.")

        output.append("---\n")
        output.append("## Next Steps\n")
        output.append("The catalog discovery is complete. The user can now select which")
        output.append("categories they want to extract. Wait for user input before proceeding.")
        output.append("\nTo extract a specific category, use `extract_gear_list_page(url)` with")
        output.append("the category URL from the list above.")

        return "\n".join(output)

    except ValueError as e:
        return f"Error discovering catalog: {str(e)}"


def extract_category_products(category_url: str, brand_name: str = "") -> str:
    """Extract ALL products from a specific category/collection page.

    This is Phase 2 of the two-phase extraction process. Use this AFTER
    catalog discovery, when the user has selected specific categories.

    IMPORTANT: This extracts EVERY product in the category. Do not skip
    any products or try to "save tokens."

    Args:
        category_url: URL of the category/collection page to extract
        brand_name: Name of the brand (for context)

    Returns:
        Extraction results with all products found
    """
    try:
        # Use the existing extract_gear_list_page function
        result = extract_gear_list_page(category_url)

        # Add reminder about next steps
        result += "\n\n---\n"
        result += "## IMPORTANT: Complete the extraction!\n"
        result += "For EACH product listed above:\n"
        result += "1. Call `find_similar_gear(name, brand)` to check for duplicates\n"
        result += "2. If new, call `save_gear_to_graph` with ALL available details\n"
        result += "3. Call `link_extracted_gear_to_source` to link to this category page\n"
        result += "\nDo NOT skip any products. Extract the complete list."

        return result

    except ValueError as e:
        return f"Error extracting category products: {str(e)}"


def verify_product_brand(product_name: str, heard_brand: str) -> str:
    """VERIFY a brand name before saving ANY product to the database.

    **CRITICAL - MUST USE THIS TOOL** when:
    - Brand name was heard in audio/video (transcription errors are VERY common!)
    - Brand name spelling is uncertain
    - Brand is unfamiliar or you haven't verified it before in this session

    This tool searches the web to find the ACTUAL manufacturer.

    Common errors this catches:
    - "Atote" -> "Adotec Gear" (misheard brand)
    - "Arc'o" -> "Zpacks" (misheard product name "Arc Haul")
    - "Thermarest" -> "Therm-a-Rest" (spelling variation)

    DO NOT claim a brand is "verified" unless you have called this tool!

    Args:
        product_name: The product name as heard/read
        heard_brand: The brand name as heard/read (may be wrong!)

    Returns:
        Verification result with correct brand name and evidence
    """
    try:
        result = verify_brand_product(product_name, heard_brand)

        output = ["## Brand Verification Result\n"]
        output.append(f"**Product:** {product_name}")
        output.append(f"**Heard Brand:** {heard_brand}")
        output.append(f"**Verified:** {'YES' if result['verified'] else 'NO'}")
        output.append(f"**Correct Brand:** {result['correct_brand']}")
        output.append(f"**Confidence:** {result['confidence']}")

        if result['manufacturer_url']:
            output.append(f"**Manufacturer URL:** {result['manufacturer_url']}")

        if result['evidence']:
            output.append("\n**Evidence URLs:**")
            for url in result['evidence']:
                output.append(f"- {url}")

        output.append(f"\n**Notes:** {result['notes']}")

        if not result['verified']:
            output.append("\n---")
            output.append("**WARNING:** Could not verify this brand!")
            output.append("DO NOT save with unverified brand name.")
            output.append("Search for more information or skip this product.")

        return "\n".join(output)

    except Exception as e:
        return f"Error verifying brand: {str(e)}"


def import_lighterpack_list(url: str, auto_research: bool = True) -> str:
    """Import a gear list from LighterPack and add items to GearGraph.

    This tool:
    1. Parses the LighterPack list to extract all gear items
    2. Checks if each item already exists in the database
    3. For new items, automatically researches them online and adds to database

    Use this when the user provides a LighterPack URL like:
    - https://lighterpack.com/r/abc123

    Args:
        url: LighterPack list URL
        auto_research: If True, automatically research and add missing items (default: True)

    Returns:
        Import summary with statistics
    """
    try:
        stats = import_lighterpack_sync(url, auto_research=auto_research)

        output = ["## LighterPack Import Complete\n"]
        output.append(f"**Total Items:** {stats['total_items']}")
        output.append(f"**Found in Database:** {stats['found_in_db']}")
        output.append(f"**Researched & Added:** {stats['researched']}")
        output.append(f"**Skipped:** {stats['skipped']}")
        output.append(f"**Errors:** {stats['errors']}")

        if stats['errors'] > 0:
            output.append("\n**Note:** Some items had errors during research.")
            output.append("You may want to manually check and add them.")

        return "\n".join(output)

    except Exception as e:
        return f"Error importing LighterPack list: {str(e)}"


# All available tools for agents
AGENT_TOOLS = [
    # Content fetching tools
    fetch_youtube_transcript,
    fetch_youtube_playlist,  # Fetch playlist and check which videos need processing
    fetch_webpage_content,
    search_gear_info,
    # LighterPack import
    import_lighterpack_list,  # Import gear lists from LighterPack URLs
    # Brand verification - MUST USE before saving unfamiliar brands!
    verify_product_brand,  # Verify brand names heard in audio before saving
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
    extract_gear_list_page,  # Extract ALL products from list/guide pages
    # Two-phase catalog extraction tools
    discover_manufacturer_catalog,  # Phase 1: Discover catalog structure and count products
    extract_category_products,  # Phase 2: Extract all products from selected category
    # Glossary tools
    save_glossary_term,
    lookup_glossary_term,
    list_glossary_terms,
    link_gear_to_term,
    find_gear_with_term,
    import_glossary_from_json,
]


def create_gear_agent(model_tier: ModelTier = "sonnet") -> Agent:
    """Create and configure a gear extraction agent with specified model tier.

    Args:
        model_tier: Which model tier to use ('haiku', 'sonnet', 'opus')
            - With DeepSeek: haiku/sonnet use deepseek-chat, opus uses deepseek-reasoner
            - With Anthropic: uses respective Claude models

    Returns:
        Configured Agno Agent instance
    """
    system_prompt = _get_system_prompt()
    model = _get_model(model_tier)

    agent = Agent(
        name=f"GearCrew-{LLM_PROVIDER.capitalize()}-{model_tier.capitalize()}",
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


def extract_gear_with_context(
    source_url: str,
    user_context: str = "",
    video_title: str = "",
) -> str:
    """Extract gear from a video with additional user-provided context.

    Args:
        source_url: URL to extract gear information from
        user_context: Additional context/notes from user to include in prompt
        video_title: Title of the video (for better prompting)

    Returns:
        Agent's extraction response as string
    """
    agent = get_agent("sonnet")

    context_section = ""
    if user_context:
        context_section = f"""
## Important Context from User:
{user_context}

Please keep this context in mind during extraction.
"""

    title_section = ""
    if video_title:
        title_section = f"Video Title: {video_title}\n"

    prompt = f"""Please analyze the following source and extract all hiking/backpacking gear information:

{title_section}Source URL: {source_url}
{context_section}
Instructions:
1. First, fetch the content from this URL using the appropriate tool (YouTube transcript or webpage scraper)
2. Extract all gear items mentioned with their specifications
3. Identify any manufacturers and their details
4. Extract valuable knowledge facts, tips, and reviews
5. IMPORTANT: Check for duplicates using find_similar_gear before saving any new gear
6. Save all extracted gear items and insights to the database
7. Link each gear item to this source using link_extracted_gear_to_source
8. **CRITICAL - MUST DO**: Call save_extraction_result at the end with:
   - url: "{source_url}"
   - title: The video/page title
   - channel: The channel or author name
   - gear_items_found: Count of gear items extracted
   - insights_found: Count of insights extracted
   - extraction_summary: A markdown summary of what was found

This final step is REQUIRED - without it, the video won't appear in the archive!

Please proceed with the extraction."""

    response = agent.run(prompt)
    return str(response.content) if response.content else ""


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


# Human-readable tool name mapping
TOOL_DISPLAY_NAMES = {
    "get_youtube_transcript": "Fetching YouTube transcript",
    "scrape_webpage": "Scraping webpage content",
    "search_web": "Searching the web",
    "map_website": "Mapping website structure",
    "discover_catalog": "Discovering product catalog",
    "quick_count_products": "Counting products on page",
    "extract_product_data": "Extracting product data",
    "extract_multiple_products": "Extracting multiple products",
    "batch_extract_products": "Batch extracting products",
    "find_similar_gear": "Checking for duplicates",
    "check_gear_exists": "Checking if gear exists",
    "save_gear_to_graph": "Saving gear to database",
    "save_insight_to_graph": "Saving insight to database",
    "search_graph": "Searching gear database",
    "check_video_already_processed": "Checking if already processed",
    "save_extraction_result": "Saving extraction result",
    "link_extracted_gear_to_source": "Linking gear to source",
    "merge_duplicate_gear": "Merging duplicate entries",
    "update_existing_gear": "Updating existing gear",
    "verify_brand_product": "Verifying brand name",
    "research_product": "Researching product online",
    "search_product_weights": "Searching for weight data",
    "search_images": "Searching for images",
    "save_glossary_term": "Saving glossary term",
    "lookup_glossary_term": "Looking up glossary term",
}


def _get_tool_display_name(tool_name: str) -> str:
    """Get human-readable display name for a tool."""
    return TOOL_DISPLAY_NAMES.get(tool_name, f"Running {tool_name}")


def extract_gear_streaming(
    source_url: str,
    user_context: str = "",
    video_title: str = "",
    on_progress: Callable[[str, str], None] | None = None,
) -> Iterator[dict]:
    """Extract gear with streaming progress updates.

    Yields progress events that can be displayed in the UI.

    Args:
        source_url: URL to extract gear from
        user_context: Additional context from user
        video_title: Title of the video
        on_progress: Optional callback for progress updates (status, detail)

    Yields:
        Dict with event info: {"event": str, "detail": str, "content": str | None}
    """
    agent = get_agent("sonnet")

    context_section = ""
    if user_context:
        context_section = f"""
## Important Context from User:
{user_context}

Please keep this context in mind during extraction.
"""

    title_section = ""
    if video_title:
        title_section = f"Video Title: {video_title}\n"

    prompt = f"""Please analyze the following source and extract all hiking/backpacking gear information:

{title_section}Source URL: {source_url}
{context_section}
Instructions:
1. First, fetch the content from this URL using the appropriate tool (YouTube transcript or webpage scraper)
2. Extract all gear items mentioned with their specifications
3. Identify any manufacturers and their details
4. Extract valuable knowledge facts, tips, and reviews
5. IMPORTANT: Check for duplicates using find_similar_gear before saving any new gear
6. Save all extracted gear items and insights to the database
7. Link each gear item to this source using link_extracted_gear_to_source
8. **CRITICAL - MUST DO**: Call save_extraction_result at the end with:
   - url: "{source_url}"
   - title: The video/page title
   - channel: The channel or author name
   - gear_items_found: Count of gear items extracted
   - insights_found: Count of insights extracted
   - extraction_summary: A markdown summary of what was found

This final step is REQUIRED - without it, the video won't appear in the archive!

Please proceed with the extraction."""

    yield {"event": "started", "detail": "Starting extraction...", "content": None}

    final_content = ""
    tools_called = []

    # Run with streaming events
    for event in agent.run(prompt, stream=True, stream_events=True):
        if hasattr(event, "event"):
            if event.event == RunEvent.tool_call_started:
                tool_name = getattr(event, "tool_name", None) or getattr(
                    getattr(event, "tool", None), "name", "unknown"
                )
                display_name = _get_tool_display_name(tool_name)
                tools_called.append(tool_name)
                yield {
                    "event": "tool_started",
                    "detail": display_name,
                    "tool": tool_name,
                    "content": None,
                }
                if on_progress:
                    on_progress("tool", display_name)

            elif event.event == RunEvent.tool_call_completed:
                tool_name = getattr(event, "tool_name", None) or getattr(
                    getattr(event, "tool", None), "name", "unknown"
                )
                display_name = _get_tool_display_name(tool_name)
                yield {
                    "event": "tool_completed",
                    "detail": f"{display_name} - done",
                    "tool": tool_name,
                    "content": None,
                }

            elif event.event == RunEvent.run_content:
                content = getattr(event, "content", "")
                if content:
                    final_content += str(content)
                    yield {
                        "event": "content",
                        "detail": "Generating response...",
                        "content": str(content),
                    }

            elif event.event == RunEvent.reasoning_step:
                step = getattr(event, "content", "")
                if step:
                    yield {
                        "event": "reasoning",
                        "detail": "Thinking...",
                        "content": str(step),
                    }

        elif hasattr(event, "content") and event.content:
            final_content = str(event.content)

    yield {
        "event": "completed",
        "detail": f"Extraction complete ({len(tools_called)} tools used)",
        "content": final_content,
        "tools_used": tools_called,
    }


def run_agent_streaming(
    message: str,
    model_tier: ModelTier | None = None,
    on_progress: Callable[[str, str], None] | None = None,
) -> Iterator[dict]:
    """Run agent with streaming progress updates.

    Args:
        message: User message to process
        model_tier: Optional model tier override
        on_progress: Optional callback for progress updates

    Yields:
        Dict with event info
    """
    if model_tier is None:
        model_tier = _classify_task_complexity(message)

    agent = get_agent(model_tier)

    yield {"event": "started", "detail": f"Using {LLM_PROVIDER}/{model_tier}..."}

    final_content = ""

    for event in agent.run(message, stream=True, stream_events=True):
        if hasattr(event, "event"):
            if event.event == RunEvent.tool_call_started:
                tool_name = getattr(event, "tool_name", None) or getattr(
                    getattr(event, "tool", None), "name", "unknown"
                )
                display_name = _get_tool_display_name(tool_name)
                yield {"event": "tool_started", "detail": display_name, "tool": tool_name}
                if on_progress:
                    on_progress("tool", display_name)

            elif event.event == RunEvent.tool_call_completed:
                tool_name = getattr(event, "tool_name", None) or getattr(
                    getattr(event, "tool", None), "name", "unknown"
                )
                yield {"event": "tool_completed", "detail": f"Done: {tool_name}"}

            elif event.event == RunEvent.run_content:
                content = getattr(event, "content", "")
                if content:
                    final_content += str(content)
                    yield {"event": "content", "detail": "...", "content": str(content)}

        elif hasattr(event, "content") and event.content:
            final_content = str(event.content)

    yield {"event": "completed", "detail": "Done", "content": final_content}

"""Website Extractor UI Component for GearCrew.

Provides two extraction modes:
1. Single Page Extraction - Extract gear from a specific product/review page
2. Manufacturer Site Crawl - Map a manufacturer's website and extract from product pages
"""

import streamlit as st
from urllib.parse import urlparse

from app.task_queue import get_task_queue, TaskStatus


def is_valid_url(url: str) -> bool:
    """Check if a string is a valid URL."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def get_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return url


def render_single_page_extraction():
    """Render the single page extraction form."""
    st.subheader("Page Extraction")
    st.caption(
        "Extract gear information from product pages, reviews, or gear lists."
    )

    url = st.text_input(
        "Page URL",
        placeholder="https://example.com/best-hiking-gear",
        key="single_page_url",
    )

    # Page type selector
    page_type = st.radio(
        "What type of page is this?",
        ["Single Product", "Gear List / Guide"],
        horizontal=True,
        key="page_type",
        help="Single Product: One item per page. Gear List: Multiple products mentioned.",
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        extract_btn = st.button("Extract Gear", type="primary", key="extract_single")

    if extract_btn:
        if not url:
            st.error("Please enter a URL")
            return

        if not is_valid_url(url):
            st.error("Please enter a valid URL (include https://)")
            return

        domain = get_domain(url)
        task_queue = get_task_queue()

        if page_type == "Single Product":
            prompt = f"""Please extract gear information from this SINGLE PRODUCT page:

URL: {url}

Steps:
1. Use `extract_gear_from_page` to extract structured product data
2. Use `find_similar_gear` to check for duplicates
3. Only save if truly new using `save_gear_to_graph`
4. Link the item to the source URL

Report what gear was found and whether it was new or already in the database."""
            description = f"Extracting product from {domain}"
        else:
            prompt = f"""Please extract ALL gear items from this LIST/GUIDE page:

URL: {url}

Steps:
1. Use `extract_gear_list_page` to extract ALL products mentioned on the page
2. For EACH product found:
   a. Use `find_similar_gear` to check for duplicates
   b. Only save truly new items using `save_gear_to_graph`
   c. Link each item to the source URL using `link_extracted_gear_to_source`
3. Track the source with `save_extraction_result`

Report:
- Total products found on the page
- How many were new vs already in database
- List of all gear items extracted"""
            description = f"Extracting gear list from {domain}"

        task_id = task_queue.submit(prompt, description)
        st.success(f"Extraction started! Task ID: {task_id[:8]}...")
        st.info("You can switch to other views - the extraction runs in the background.")
        st.rerun()


def render_manufacturer_crawl():
    """Render the manufacturer website crawl form."""
    st.subheader("Manufacturer Website Crawl")
    st.caption(
        "Map a manufacturer's entire website to discover and extract all product pages."
    )

    url = st.text_input(
        "Manufacturer Website URL",
        placeholder="https://durstongear.com",
        key="manufacturer_url",
    )

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        max_pages = st.number_input(
            "Max Pages to Map",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
            key="max_pages",
        )
    with col2:
        auto_extract = st.checkbox(
            "Auto-extract products",
            value=True,
            help="Automatically extract gear from discovered product pages",
            key="auto_extract",
        )

    col1, col2 = st.columns([1, 3])
    with col1:
        crawl_btn = st.button("Start Crawl", type="primary", key="start_crawl")

    if crawl_btn:
        if not url:
            st.error("Please enter a URL")
            return

        if not is_valid_url(url):
            st.error("Please enter a valid URL (include https://)")
            return

        domain = get_domain(url)
        task_queue = get_task_queue()

        if auto_extract:
            prompt = f"""Please crawl this manufacturer's website and extract all gear:

Website URL: {url}
Max Pages: {max_pages}

Steps:
1. Use `discover_product_pages` to map the website and find product pages
2. For each product page found (up to 20):
   a. Use `extract_gear_from_page` to get structured data
   b. Use `find_similar_gear` to check for duplicates
   c. Only save truly new items with `save_gear_to_graph`
   d. Link items to their source URLs

Report:
- Total pages discovered
- Number of product pages found
- Gear items extracted (new vs existing)
- Any errors encountered"""
        else:
            prompt = f"""Please map this manufacturer's website to discover product pages:

Website URL: {url}
Max Pages: {max_pages}

Steps:
1. Use `discover_product_pages` to map the website
2. List all discovered product pages

Report the total pages found and list the product page URLs."""

        description = f"Crawling {domain}" if not auto_extract else f"Crawling & extracting {domain}"
        task_id = task_queue.submit(prompt, description)
        st.success(f"Crawl started! Task ID: {task_id[:8]}...")
        st.info("This may take a while. You can switch to other views.")
        st.rerun()


def render_active_extractions():
    """Show currently running extraction tasks."""
    task_queue = get_task_queue()
    active_tasks = task_queue.get_active_tasks()

    # Filter to extraction-related tasks
    extraction_tasks = [
        t for t in active_tasks
        if "extract" in t.description.lower() or "crawl" in t.description.lower()
    ]

    if extraction_tasks:
        st.markdown("### Active Extractions")
        for task in extraction_tasks:
            status_icon = "🔄" if task.status == TaskStatus.RUNNING else "⏳"
            duration = f" ({int(task.duration_seconds)}s)" if task.duration_seconds else ""

            with st.container():
                st.markdown(f"{status_icon} **{task.description}**{duration}")
                if task.status == TaskStatus.RUNNING:
                    st.progress(0.5, text="Processing...")

        st.markdown("---")


def render_recent_extractions():
    """Show recently completed extraction tasks."""
    task_queue = get_task_queue()
    recent = task_queue.get_recent_completed(limit=10)

    # Filter to extraction-related tasks
    extraction_tasks = [
        t for t in recent
        if "extract" in t.description.lower() or "crawl" in t.description.lower()
    ]

    if extraction_tasks:
        st.markdown("### Recent Extractions")
        for task in extraction_tasks:
            if task.status == TaskStatus.COMPLETED:
                with st.expander(f"**{task.description}** - Completed", expanded=False):
                    if task.result:
                        st.markdown(task.result)
                    if task.duration_seconds:
                        st.caption(f"Duration: {int(task.duration_seconds)} seconds")
            else:
                with st.expander(f"**{task.description}** - Failed", expanded=False):
                    if task.error:
                        st.error(task.error)

        st.markdown("---")


def render_website_extractor():
    """Render the main website extractor page."""
    st.header("Website Gear Extractor")
    st.caption("Extract gear information from product pages and manufacturer websites")

    # Show active extractions first
    render_active_extractions()

    # Tab layout for two modes
    tab1, tab2 = st.tabs(["Single Page", "Manufacturer Crawl"])

    with tab1:
        render_single_page_extraction()

    with tab2:
        render_manufacturer_crawl()

    # Show recent extractions
    st.markdown("---")
    render_recent_extractions()

    # Help section
    with st.expander("How it works"):
        st.markdown("""
### Single Page Extraction
Use this when you have a direct URL to a gear product page or review article.
The agent will:
1. Scrape the page content using Firecrawl
2. Extract structured gear data (name, brand, price, weight, specs)
3. Check for duplicates in the database
4. Save new gear items to the graph

**Good for:** Individual product pages, gear reviews, comparison articles

### Manufacturer Website Crawl
Use this to scan an entire manufacturer's website and extract all their products.
The agent will:
1. Map the website to discover all pages
2. Identify product pages using URL patterns
3. Extract gear data from each product page
4. Deduplicate against existing database entries

**Good for:** Adding a manufacturer's full catalog, updating product lines

### Tips
- Start with smaller `Max Pages` values (50-100) for initial testing
- Use the Graph Explorer to verify extracted data
- Check the Agent Chat for detailed extraction logs
""")

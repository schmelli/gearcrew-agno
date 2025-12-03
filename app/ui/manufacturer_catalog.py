"""Manufacturer Catalog Discovery UI Component for GearCrew.

Implements a two-phase extraction process:
1. Discovery Phase: Map website and count products per category
2. Extraction Phase: Extract only from user-selected categories
"""

import re
import streamlit as st
from urllib.parse import urlparse
from typing import Optional

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


def render_discovery_phase():
    """Render the catalog discovery form (Phase 1)."""
    st.subheader("Phase 1: Discover Product Catalog")
    st.caption(
        "First, let's map the manufacturer's website to see what product categories "
        "are available and how many products are in each."
    )

    url = st.text_input(
        "Manufacturer Website URL",
        placeholder="https://www.bigagnes.com",
        key="catalog_discovery_url",
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        discover_btn = st.button(
            "Discover Catalog",
            type="primary",
            key="discover_catalog_btn"
        )

    if discover_btn:
        if not url:
            st.error("Please enter a URL")
            return

        if not is_valid_url(url):
            st.error("Please enter a valid URL (include https://)")
            return

        domain = get_domain(url)
        task_queue = get_task_queue()

        prompt = f"""Please discover the product catalog for this manufacturer:

Website URL: {url}

Use the `discover_manufacturer_catalog` tool to:
1. Map the website and find all product category pages
2. Count how many products are in each category
3. Return a structured overview of their catalog

DO NOT extract full product details yet - just discover and count.
This is Phase 1 of a two-phase process.

Report the catalog structure with:
- Brand name
- List of product categories found
- Number of products in each category
- Total estimated products"""

        description = f"Discovering catalog for {domain}"
        task_id = task_queue.submit(prompt, description)
        st.session_state.catalog_discovery_task_id = task_id
        st.success(f"Discovery started! Task ID: {task_id[:8]}...")
        st.rerun()


def render_catalog_results():
    """Render discovered catalog results and category selection."""
    if "discovered_catalog" not in st.session_state:
        return

    catalog = st.session_state.discovered_catalog

    st.subheader("Phase 2: Select Categories to Extract")

    # Brand header
    brand_name = catalog.get("brand_name", "Unknown Brand")
    st.markdown(f"## {brand_name} Product Catalog")

    # Summary stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Categories", catalog.get("total_categories", 0))
    with col2:
        st.metric("Est. Products", catalog.get("total_products_estimated", 0))
    with col3:
        st.metric("Individual Pages", catalog.get("individual_product_pages", 0))

    st.markdown("---")

    # Category selection
    st.markdown("### Select Categories to Extract")
    st.caption("Check the categories you want to fully extract. "
               "Unchecked categories will be skipped.")

    categories = catalog.get("categories", [])

    if not categories:
        st.warning("No product categories were found.")
        return

    # Initialize selection state
    if "selected_categories" not in st.session_state:
        st.session_state.selected_categories = {}

    # Select all / none buttons
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("Select All", key="select_all_cats"):
            for cat in categories:
                st.session_state.selected_categories[cat["url"]] = True
            st.rerun()
    with col2:
        if st.button("Select None", key="select_none_cats"):
            st.session_state.selected_categories = {}
            st.rerun()

    # Category checkboxes with product counts
    selected_count = 0
    selected_products = 0

    for i, cat in enumerate(categories):
        cat_url = cat.get("url", "")
        cat_name = cat.get("category_name", f"Category {i+1}")
        product_count = cat.get("product_count", 0)
        product_names = cat.get("product_names", [])

        # Create checkbox
        is_selected = st.session_state.selected_categories.get(cat_url, False)

        col1, col2 = st.columns([3, 1])
        with col1:
            new_selection = st.checkbox(
                f"**{cat_name}** ({product_count} products)",
                value=is_selected,
                key=f"cat_checkbox_{i}",
            )
            st.session_state.selected_categories[cat_url] = new_selection

            if new_selection:
                selected_count += 1
                selected_products += product_count

        with col2:
            # Show product preview in expander
            if product_names:
                with st.expander("Preview"):
                    for name in product_names[:5]:
                        st.caption(f"• {name}")
                    if len(product_names) > 5:
                        st.caption(f"... and {len(product_names) - 5} more")

    st.markdown("---")

    # Selection summary
    st.markdown(f"**Selected:** {selected_count} categories, ~{selected_products} products")

    # Extract button
    if selected_count > 0:
        if st.button(
            f"Extract Selected Categories ({selected_products} products)",
            type="primary",
            key="extract_selected_btn"
        ):
            # Get selected URLs
            selected_urls = [
                url for url, selected in st.session_state.selected_categories.items()
                if selected
            ]

            # Store for extraction
            st.session_state.extraction_urls = selected_urls
            st.session_state.extraction_brand = brand_name

            # Submit extraction task
            _submit_extraction_task(selected_urls, brand_name, catalog.get("website_url", ""))
    else:
        st.info("Select at least one category to extract.")


def _submit_extraction_task(collection_urls: list, brand_name: str, website_url: str):
    """Submit the extraction task for selected categories."""
    task_queue = get_task_queue()

    # Build the prompt with specific URLs
    urls_list = "\n".join(f"- {url}" for url in collection_urls)

    prompt = f"""Please extract ALL products from the following categories for {brand_name}:

Website: {website_url}

Categories to extract (EXTRACT ALL PRODUCTS FROM EACH):
{urls_list}

For EACH category URL listed above:
1. Use `extract_gear_list_page(url)` to get ALL products
2. For each product found:
   a. Use `find_similar_gear(name, brand)` to check for duplicates
   b. If new, save with `save_gear_to_graph` including ALL available details
   c. Link to source with `link_extracted_gear_to_source`

IMPORTANT: Extract EVERY product from each category. Do not skip any products.
Do not "save tokens" or abbreviate - extract the complete catalog.

After extraction, report:
- Total products extracted per category
- How many were new vs already in database
- Any errors encountered"""

    description = f"Extracting {len(collection_urls)} categories from {brand_name}"
    task_id = task_queue.submit(prompt, description)

    st.session_state.extraction_task_id = task_id
    st.success(f"Extraction started! Task ID: {task_id[:8]}...")
    st.info("This may take a while. You can switch to other views - extraction runs in background.")
    st.rerun()


def render_active_tasks():
    """Show currently running catalog-related tasks."""
    task_queue = get_task_queue()
    active_tasks = task_queue.get_active_tasks()

    # Filter to catalog-related tasks
    catalog_tasks = [
        t for t in active_tasks
        if "catalog" in t.description.lower()
        or "discovering" in t.description.lower()
        or "extracting" in t.description.lower()
    ]

    if catalog_tasks:
        st.markdown("### Active Tasks")
        for task in catalog_tasks:
            status_icon = "🔄" if task.status == TaskStatus.RUNNING else "⏳"
            duration = f" ({int(task.duration_seconds)}s)" if task.duration_seconds else ""

            with st.container():
                st.markdown(f"{status_icon} **{task.description}**{duration}")
                if task.status == TaskStatus.RUNNING:
                    st.progress(0.5, text="Processing...")

        st.markdown("---")


def render_recent_results():
    """Show recently completed catalog tasks."""
    task_queue = get_task_queue()
    recent = task_queue.get_recent_completed(limit=5)

    # Filter to catalog-related tasks
    catalog_tasks = [
        t for t in recent
        if "catalog" in t.description.lower()
        or "discovering" in t.description.lower()
        or "extracting" in t.description.lower()
    ]

    if catalog_tasks:
        st.markdown("### Recent Results")
        for task in catalog_tasks:
            status = "✅" if task.status == TaskStatus.COMPLETED else "❌"
            with st.expander(f"{status} {task.description}", expanded=False):
                if task.result:
                    st.markdown(task.result)

                    # Try to parse catalog data from result for selection UI
                    if "discovering" in task.description.lower() and task.status == TaskStatus.COMPLETED:
                        _try_parse_catalog_result(task.result)

                if task.error:
                    st.error(task.error)

        st.markdown("---")


def _try_parse_catalog_result(result: str) -> Optional[dict]:
    """Try to parse catalog discovery results and enable selection UI.

    Parses markdown output from discover_manufacturer_catalog tool.
    Expected format:
        # Brand Name Product Catalog

        ### 1. Category Name (N products)
           URL: https://...
           Products: Product1, Product2, ...
    """
    if not result or "categories" not in result.lower():
        return None

    catalog = {
        "brand_name": "Unknown Brand",
        "website_url": "",
        "categories": [],
        "total_categories": 0,
        "total_products_estimated": 0,
    }

    # Extract brand name from header (# Brand Name Product Catalog)
    brand_match = re.search(r'^#\s+(.+?)\s+Product Catalog', result, re.MULTILINE)
    if brand_match:
        catalog["brand_name"] = brand_match.group(1).strip()

    # Extract website URL if present (may have markdown bold **)
    url_match = re.search(r'\*?\*?Website:\*?\*?\s*(https?://[^\s\n]+)', result)
    if url_match:
        catalog["website_url"] = url_match.group(1).strip()

    # Parse categories - look for patterns like "### 1. Category Name (N products)"
    # followed by "URL: https://..."
    category_pattern = re.compile(
        r'###\s*\d+\.\s*(.+?)\s*\((\d+)\s*products?\)',
        re.IGNORECASE
    )
    url_pattern = re.compile(r'URL:\s*(https?://[^\s\n]+)', re.IGNORECASE)

    for match in category_pattern.finditer(result):
        category_name = match.group(1).strip()
        product_count = int(match.group(2))

        # Find the URL after this category header
        remaining = result[match.end():]
        next_category = category_pattern.search(remaining)
        section_end = next_category.start() if next_category else len(remaining)
        section = remaining[:section_end]

        url_match = url_pattern.search(section)
        category_url = url_match.group(1).strip() if url_match else ""

        # Try to extract product names (listed after "Products:" with bullet points)
        product_names = []
        # Look for "Products:" followed by bullet-point list
        products_section_match = re.search(r'Products:\s*\n((?:\s*-\s*.+\n?)+)', section)
        if products_section_match:
            products_text = products_section_match.group(1)
            for line in products_text.split('\n'):
                line = line.strip()
                if line.startswith('-'):
                    name = line.lstrip('- ').strip()
                    if name and not name.startswith('...'):
                        product_names.append(name)

        if category_url:  # Only add categories with valid URLs
            catalog["categories"].append({
                "category_name": category_name,
                "product_count": product_count,
                "url": category_url,
                "product_names": product_names[:10],  # Limit preview
            })
            catalog["total_products_estimated"] += product_count

    catalog["total_categories"] = len(catalog["categories"])

    if catalog["categories"]:
        # Store in session state for Phase 2 UI
        st.session_state.discovered_catalog = catalog
        st.success(f"Parsed {len(catalog['categories'])} categories! Click 'Select Categories' below.")

        # Add a button to proceed to Phase 2
        if st.button("Proceed to Category Selection", type="primary", key="proceed_to_phase2"):
            st.rerun()

        return catalog
    else:
        st.warning("Could not parse category data from results. Check the format.")
        return None


def render_manufacturer_catalog():
    """Render the main manufacturer catalog page."""
    st.header("Manufacturer Catalog Extraction")
    st.caption(
        "Two-phase extraction: First discover the catalog structure, "
        "then select which categories to fully extract."
    )

    # Show active tasks
    render_active_tasks()

    # Check if we have a discovered catalog to show
    if "discovered_catalog" in st.session_state and st.session_state.discovered_catalog:
        # Add reset button
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("Start New Discovery", key="reset_discovery"):
                st.session_state.discovered_catalog = None
                st.session_state.selected_categories = {}
                st.rerun()
        render_catalog_results()
    else:
        render_discovery_phase()

    # Show recent results
    st.markdown("---")
    render_recent_results()

    # Help section
    with st.expander("How Two-Phase Extraction Works"):
        st.markdown("""
### Phase 1: Catalog Discovery
- Maps the manufacturer's website
- Identifies all product category pages
- Counts products in each category (fast, no full extraction)
- Shows you the complete catalog structure

### Phase 2: Category Selection & Extraction
- You select which categories to extract
- System extracts ALL products from selected categories
- No products are skipped or abbreviated
- Full details captured for each product

### Why Two Phases?
Traditional single-phase extraction often skips products because the AI tries to
"be efficient." By separating discovery from extraction, you maintain control over
what gets extracted, and the extraction phase has clear instructions to capture everything.

### Tips
- Start with discovery to see what's available
- Select specific categories you're interested in
- For large catalogs, extract in batches
- Check the Graph Explorer to verify extracted products
""")


def set_discovered_catalog(catalog: dict):
    """Set the discovered catalog data for the selection UI.

    This should be called by the agent after catalog discovery completes.
    """
    st.session_state.discovered_catalog = catalog

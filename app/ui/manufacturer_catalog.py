"""Manufacturer Catalog Discovery UI Component for GearCrew.

Implements a two-phase extraction process:
1. Discovery Phase: Map website and discover all products per category
2. Selection Phase: Select individual products, categories, or all items to extract
"""

import re
import streamlit as st
from urllib.parse import urlparse
from typing import Optional

from app.task_queue import get_task_queue, TaskStatus
from app.tools.browser_scraper import (
    map_website_sync,
    extract_products_sync,
    _is_product_url,
    _is_non_product_category,
)


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


def init_catalog_state():
    """Initialize session state for catalog discovery."""
    if "catalog_data" not in st.session_state:
        st.session_state.catalog_data = None
    if "selected_products" not in st.session_state:
        st.session_state.selected_products = {}  # url -> bool
    if "expanded_categories" not in st.session_state:
        st.session_state.expanded_categories = set()
    if "discovery_in_progress" not in st.session_state:
        st.session_state.discovery_in_progress = False


def render_discovery_phase():
    """Render the catalog discovery form (Phase 1)."""
    st.subheader("Phase 1: Discover Product Catalog")
    st.caption(
        "Enter a manufacturer's website URL to discover their complete product catalog."
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
            key="discover_catalog_btn",
            disabled=st.session_state.discovery_in_progress,
        )

    if discover_btn:
        if not url:
            st.error("Please enter a URL")
            return

        if not is_valid_url(url):
            st.error("Please enter a valid URL (include https://)")
            return

        st.session_state.discovery_in_progress = True
        st.rerun()

    # Handle discovery in progress
    if st.session_state.discovery_in_progress:
        url = st.session_state.get("catalog_discovery_url", "")
        if url:
            _run_discovery(url)


def _run_discovery(url: str):
    """Run the catalog discovery process."""
    with st.spinner(f"Discovering catalog for {get_domain(url)}..."):
        try:
            result = map_website_sync(url, max_pages=50)

            if result.get("error"):
                st.error(f"Discovery failed: {result['error']}")
                st.session_state.discovery_in_progress = False
                return

            # Enhance with full product details for each category
            categories = result.get("categories", [])
            enhanced_categories = []

            progress_bar = st.progress(0, text="Fetching product details...")
            for i, cat in enumerate(categories):
                cat_name = cat.get("category_name", "Unknown")

                # Skip non-product categories (FAQ, Terms, etc.)
                if _is_non_product_category(cat_name):
                    continue

                progress_bar.progress(
                    (i + 1) / len(categories),
                    text=f"Scanning {cat_name}..."
                )

                # Get full product list for this category
                cat_url = cat.get("url", "")
                if cat_url:
                    products_result = extract_products_sync(cat_url)
                    all_products = products_result.get("products", [])
                    # Filter to only actual product URLs
                    products = [
                        p for p in all_products
                        if p.get("url") and _is_product_url(p["url"])
                    ]
                else:
                    products = []

                # Only add categories with actual products
                if products:
                    enhanced_categories.append({
                        "url": cat_url,
                        "category_name": cat_name,
                        "product_count": len(products),
                        "products": products,  # Full product list with name, url, price
                    })

            progress_bar.empty()

            # Store enhanced catalog data
            st.session_state.catalog_data = {
                "brand_name": result.get("brand_name", "Unknown Brand"),
                "website_url": url,
                "categories": enhanced_categories,
                "total_categories": len(enhanced_categories),
                "total_products": sum(c["product_count"] for c in enhanced_categories),
            }

            # Initialize selection state
            st.session_state.selected_products = {}
            st.session_state.expanded_categories = set()
            st.session_state.discovery_in_progress = False

            st.success(f"Discovered {len(enhanced_categories)} categories!")
            st.rerun()

        except Exception as e:
            st.error(f"Discovery failed: {str(e)}")
            st.session_state.discovery_in_progress = False


def render_catalog_results():
    """Render discovered catalog with product selection."""
    catalog = st.session_state.catalog_data
    if not catalog:
        return

    # Header with brand info
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(f"{catalog['brand_name']} Product Catalog")
    with col2:
        if st.button("New Discovery", key="reset_discovery"):
            st.session_state.catalog_data = None
            st.session_state.selected_products = {}
            st.session_state.expanded_categories = set()
            st.rerun()

    # Summary stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Categories", catalog["total_categories"])
    with col2:
        st.metric("Total Products", catalog["total_products"])
    with col3:
        selected_count = sum(1 for v in st.session_state.selected_products.values() if v)
        st.metric("Selected", selected_count)

    st.markdown("---")

    # Selection controls
    st.markdown("### Product Selection")

    # Quick selection buttons
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Select All", key="select_all"):
            for cat in catalog["categories"]:
                for product in cat.get("products", []):
                    if product.get("url"):
                        st.session_state.selected_products[product["url"]] = True
            st.rerun()
    with col2:
        if st.button("Select None", key="select_none"):
            st.session_state.selected_products = {}
            st.rerun()
    with col3:
        if st.button("Expand All", key="expand_all"):
            for cat in catalog["categories"]:
                st.session_state.expanded_categories.add(cat["url"])
            st.rerun()
    with col4:
        if st.button("Collapse All", key="collapse_all"):
            st.session_state.expanded_categories = set()
            st.rerun()

    st.markdown("---")

    # Render categories with products
    for cat_idx, category in enumerate(catalog["categories"]):
        _render_category(category, cat_idx)

    st.markdown("---")

    # Extraction options
    _render_extraction_options(catalog)


def _render_category(category: dict, cat_idx: int):
    """Render a single category with its products."""
    cat_url = category.get("url", "")
    cat_name = category.get("category_name", f"Category {cat_idx + 1}")
    products = category.get("products", [])
    product_count = len(products)

    # Count selected products in this category
    selected_in_cat = sum(
        1 for p in products
        if p.get("url") and st.session_state.selected_products.get(p["url"], False)
    )

    # Category header with expand/collapse and select all
    is_expanded = cat_url in st.session_state.expanded_categories

    col1, col2, col3, col4 = st.columns([0.5, 3, 1, 1])

    with col1:
        expand_icon = "▼" if is_expanded else "▶"
        if st.button(expand_icon, key=f"expand_{cat_idx}", help="Expand/Collapse"):
            if is_expanded:
                st.session_state.expanded_categories.discard(cat_url)
            else:
                st.session_state.expanded_categories.add(cat_url)
            st.rerun()

    with col2:
        st.markdown(f"**{cat_name}** ({product_count} products)")
        if selected_in_cat > 0:
            st.caption(f"{selected_in_cat} selected")

    with col3:
        if st.button("Select All", key=f"select_cat_{cat_idx}"):
            for p in products:
                if p.get("url"):
                    st.session_state.selected_products[p["url"]] = True
            st.rerun()

    with col4:
        if st.button("Clear", key=f"clear_cat_{cat_idx}"):
            for p in products:
                if p.get("url"):
                    st.session_state.selected_products[p["url"]] = False
            st.rerun()

    # Show products if expanded
    if is_expanded and products:
        with st.container():
            # Product grid - 3 columns
            cols = st.columns(3)
            for p_idx, product in enumerate(products):
                col = cols[p_idx % 3]

                product_url = product.get("url", "")
                product_name = product.get("name", "Unknown Product")
                product_price = product.get("price", "")

                with col:
                    is_selected = st.session_state.selected_products.get(product_url, False)

                    # Create a compact product card
                    selected = st.checkbox(
                        product_name[:50] + ("..." if len(product_name) > 50 else ""),
                        value=is_selected,
                        key=f"prod_{cat_idx}_{p_idx}",
                        help=f"{product_name}\n{product_price or 'No price'}\n{product_url}",
                    )

                    if product_url:
                        st.session_state.selected_products[product_url] = selected

                    if product_price:
                        st.caption(product_price)

        st.markdown("")  # Spacing


def _render_extraction_options(catalog: dict):
    """Render extraction options and buttons."""
    st.markdown("### Extraction Options")

    selected_products = [
        url for url, selected in st.session_state.selected_products.items()
        if selected
    ]
    selected_count = len(selected_products)
    total_products = catalog["total_products"]

    if selected_count == 0:
        st.info("Select products above to extract, or use the quick actions below.")
        st.markdown("---")

    # Extraction mode tabs
    tab1, tab2, tab3 = st.tabs([
        f"Selected Products ({selected_count})",
        "By Category",
        f"All Products ({total_products})"
    ])

    with tab1:
        if selected_count > 0:
            st.markdown(f"Extract **{selected_count}** selected products.")

            # Show preview of selected products
            with st.expander("Preview selected products"):
                for cat in catalog["categories"]:
                    cat_selected = [
                        p for p in cat.get("products", [])
                        if p.get("url") and st.session_state.selected_products.get(p["url"], False)
                    ]
                    if cat_selected:
                        st.markdown(f"**{cat['category_name']}** ({len(cat_selected)})")
                        for p in cat_selected[:5]:
                            st.caption(f"  • {p['name']}")
                        if len(cat_selected) > 5:
                            st.caption(f"  ... and {len(cat_selected) - 5} more")

            if st.button(
                f"Extract {selected_count} Selected Products",
                type="primary",
                key="extract_selected",
            ):
                _submit_product_extraction(
                    selected_products,
                    catalog["brand_name"],
                    catalog["website_url"],
                )
        else:
            st.caption("No products selected. Use the checkboxes above to select specific products.")

    with tab2:
        st.markdown("Extract all products from specific categories:")

        for cat_idx, cat in enumerate(catalog["categories"]):
            cat_name = cat.get("category_name", f"Category {cat_idx + 1}")
            cat_count = len(cat.get("products", []))
            cat_url = cat.get("url", "")

            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{cat_name}** ({cat_count} products)")
            with col2:
                if st.button(
                    f"Extract",
                    key=f"extract_cat_{cat_idx}",
                    disabled=cat_count == 0,
                ):
                    product_urls = [
                        p["url"] for p in cat.get("products", [])
                        if p.get("url")
                    ]
                    _submit_product_extraction(
                        product_urls,
                        catalog["brand_name"],
                        catalog["website_url"],
                        category_name=cat_name,
                    )

    with tab3:
        st.markdown(f"Extract all **{total_products}** products from the catalog.")

        if total_products > 50:
            st.warning(
                f"This will extract {total_products} products. "
                "For large catalogs, consider extracting by category instead."
            )

        if st.button(
            f"Extract All {total_products} Products",
            type="primary" if total_products <= 50 else "secondary",
            key="extract_all",
        ):
            all_urls = []
            for cat in catalog["categories"]:
                for p in cat.get("products", []):
                    if p.get("url"):
                        all_urls.append(p["url"])
            _submit_product_extraction(
                all_urls,
                catalog["brand_name"],
                catalog["website_url"],
            )


def _submit_product_extraction(
    product_urls: list,
    brand_name: str,
    website_url: str,
    category_name: str = None,
):
    """Submit extraction task for selected products."""
    if not product_urls:
        st.error("No products to extract")
        return

    task_queue = get_task_queue()

    # Build product list for prompt
    urls_list = "\n".join(f"- {url}" for url in product_urls[:100])
    if len(product_urls) > 100:
        urls_list += f"\n... and {len(product_urls) - 100} more"

    category_info = f" from {category_name}" if category_name else ""

    prompt = f"""Please extract the following {len(product_urls)} products{category_info} for {brand_name}:

Website: {website_url}

Product URLs to extract:
{urls_list}

For EACH product URL:
1. Use `extract_gear_from_page(url)` to get full product details
2. Use `verify_product_brand(product_name, "{brand_name}")` if the brand seems uncertain
3. Use `find_similar_gear(name, brand)` to check for duplicates
4. If new, save with `save_gear_to_graph` including ALL available details:
   - Full product name
   - Brand: {brand_name}
   - Category (backpack, tent, sleeping_bag, etc.)
   - Weight in grams (convert from oz if needed)
   - Price in USD
   - Description
   - Materials and features
5. Link to source with `link_extracted_gear_to_source`

IMPORTANT: Extract EVERY product URL listed. Do not skip any.

After extraction, report:
- Total products extracted
- How many were new vs already in database
- Any errors encountered"""

    desc_suffix = f" ({category_name})" if category_name else ""
    description = f"Extracting {len(product_urls)} products from {brand_name}{desc_suffix}"
    task_id = task_queue.submit(prompt, description)

    st.success(f"Extraction started! Task ID: {task_id[:8]}...")
    st.info("Extraction runs in background. Check the Task Queue for progress.")


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
                if task.error:
                    st.error(task.error)

        st.markdown("---")


def render_manufacturer_catalog():
    """Render the main manufacturer catalog page."""
    init_catalog_state()

    st.header("Manufacturer Catalog Extraction")
    st.caption(
        "Discover a manufacturer's complete product catalog, then select "
        "individual products, categories, or everything to extract."
    )

    # Show active tasks
    render_active_tasks()

    # Check if we have catalog data
    if st.session_state.catalog_data:
        render_catalog_results()
    else:
        render_discovery_phase()

    # Show recent results
    st.markdown("---")
    render_recent_results()

    # Help section
    with st.expander("How it works"):
        st.markdown("""
### Discovery Phase
- Enter a manufacturer's website URL
- The system crawls the site to find all product categories
- Each category is scanned to identify individual products
- You get a complete overview of their catalog

### Selection Phase
- **Individual Products**: Check specific products you want
- **By Category**: Extract all products from specific categories
- **All Products**: Extract the entire catalog

### Extraction
- Each selected product is visited for full details
- Brand verification prevents transcription errors
- Duplicate checking prevents redundant entries
- All data is saved to GearGraph

### Tips
- For large catalogs (100+ products), extract by category
- Use "Expand All" to see all products before selecting
- Check the Graph Explorer after extraction to verify results
""")

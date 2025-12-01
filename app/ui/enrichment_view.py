"""Enrichment Status and Control UI for GearGraph.

Shows data completeness statistics and allows control of the enrichment agent.
"""

import threading
import streamlit as st

from app.db.memgraph import (
    get_enrichment_stats,
    get_items_needing_enrichment,
    PRIORITY_CATEGORIES,
)
from app.enrichment_agent import get_enrichment_agent, EnrichmentStatus


def init_session_state():
    """Initialize session state for enrichment view."""
    if "enrichment_thread" not in st.session_state:
        st.session_state.enrichment_thread = None
    if "enrichment_results" not in st.session_state:
        st.session_state.enrichment_results = []


def run_enrichment_batch(category: str = None):
    """Run enrichment in background thread."""
    agent = get_enrichment_agent()
    results = agent.run_batch(category=category if category != "All Categories" else None)
    st.session_state.enrichment_results = results


def render_enrichment_stats():
    """Render data completeness statistics."""
    stats = get_enrichment_stats()

    st.subheader("Data Completeness")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Items", stats.get("total_items", 0))
    with col2:
        st.metric("Enriched", stats.get("enriched_count", 0))
    with col3:
        remaining = stats.get("total_items", 0) - stats.get("enriched_count", 0)
        st.metric("Needs Enrichment", remaining)

    st.markdown("---")

    # Field completion bars
    st.markdown("**Field Completion:**")

    fields = [
        ("Weight", stats.get("weight_pct", 0)),
        ("Description", stats.get("desc_pct", 0)),
        ("Price", stats.get("price_pct", 0)),
    ]

    for field_name, pct in fields:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.progress(pct / 100, text=f"{field_name}")
        with col2:
            st.markdown(f"**{pct}%**")


def render_enrichment_queue():
    """Render the enrichment queue preview."""
    st.subheader("Enrichment Queue")
    st.caption("Items prioritized by category importance and data completeness")

    # Category filter
    categories = ["All Categories"] + PRIORITY_CATEGORIES
    selected_category = st.selectbox(
        "Filter by category:",
        categories,
        key="enrichment_category_filter",
    )

    cat_filter = None if selected_category == "All Categories" else selected_category

    items = get_items_needing_enrichment(limit=20, category=cat_filter)

    if not items:
        st.success("No items needing enrichment in this category!")
        return

    # Show queue
    for item in items[:10]:
        score = item.get("completeness_score", 0)
        score_pct = int(score * 100)
        name = item.get("name", "Unknown")
        brand = item.get("brand", "Unknown")
        category = item.get("category", "other")

        # Color based on score
        if score_pct < 20:
            color = "red"
        elif score_pct < 40:
            color = "orange"
        else:
            color = "yellow"

        with st.container():
            cols = st.columns([3, 1, 1])
            with cols[0]:
                st.markdown(f"**{brand}** {name}")
                st.caption(f"Category: {category}")
            with cols[1]:
                st.progress(score, text=f"{score_pct}%")
            with cols[2]:
                # Show missing fields
                missing = []
                if not item.get("weight_grams"):
                    missing.append("weight")
                if not item.get("description"):
                    missing.append("desc")
                if not item.get("price_usd"):
                    missing.append("price")
                st.caption(f"Missing: {', '.join(missing[:3])}")

    if len(items) > 10:
        st.caption(f"... and {len(items) - 10} more items")


def render_enrichment_controls():
    """Render enrichment agent controls."""
    st.subheader("Enrichment Controls")

    agent = get_enrichment_agent()
    status = agent.get_status()

    # Status display
    status_icon = {
        "idle": "⏸️",
        "running": "🔄",
        "paused": "⏹️",
        "error": "❌",
    }.get(status["status"], "❓")

    st.markdown(f"**Status:** {status_icon} {status['status'].upper()}")

    if status["current_item"]:
        st.info(f"Currently processing: {status['current_item']}")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Items Processed", status["items_processed"])
    with col2:
        st.metric("Items Enriched", status["items_enriched"])

    if status["last_error"]:
        st.error(f"Last error: {status['last_error']}")

    st.markdown("---")

    # Category selection for batch
    categories = ["All Categories"] + PRIORITY_CATEGORIES
    batch_category = st.selectbox(
        "Category to enrich:",
        categories,
        key="batch_category",
    )

    # Control buttons
    col1, col2 = st.columns(2)

    with col1:
        if status["status"] == "running":
            if st.button("Stop Enrichment", type="secondary"):
                agent.stop()
                st.rerun()
        else:
            if st.button("Run Batch (10 items)", type="primary"):
                with st.spinner("Running enrichment batch..."):
                    run_enrichment_batch(batch_category)
                st.rerun()

    with col2:
        if status["status"] != "running":
            if st.button("Run Single Item"):
                items = get_items_needing_enrichment(
                    limit=1,
                    category=batch_category if batch_category != "All Categories" else None,
                )
                if items:
                    with st.spinner(f"Enriching {items[0].get('name')}..."):
                        result = agent.enrich_single_item(items[0])
                        if result.success:
                            st.success(f"Added: {', '.join(result.fields_added)}")
                        else:
                            st.warning(result.error or "No new data found")
                else:
                    st.info("No items to enrich")


def render_recent_results():
    """Render recent enrichment results."""
    if not st.session_state.enrichment_results:
        return

    st.subheader("Recent Results")

    for result in st.session_state.enrichment_results[-10:]:
        if result.success:
            st.success(
                f"✅ **{result.brand} {result.name}** - "
                f"Added: {', '.join(result.fields_added)}"
            )
        else:
            st.warning(
                f"⚠️ **{result.brand} {result.name}** - {result.error}"
            )


def render_enrichment_view():
    """Render the main enrichment view page."""
    init_session_state()

    st.header("Data Enrichment")
    st.caption("Automatically enrich gear items with missing specifications")

    # Stats section
    render_enrichment_stats()

    st.markdown("---")

    # Two-column layout for queue and controls
    col1, col2 = st.columns([1, 1])

    with col1:
        render_enrichment_queue()

    with col2:
        render_enrichment_controls()

    # Recent results
    st.markdown("---")
    render_recent_results()

    # Help section
    with st.expander("How Enrichment Works"):
        st.markdown("""
### Enrichment Process

1. **Find Items**: The agent finds gear items with low data completeness scores
2. **Priority**: Items are prioritized by category (tents, backpacks first) and completeness
3. **Search**: For each item, the agent searches the web for product specifications
4. **Extract**: Product pages are analyzed to extract missing specs
5. **Update**: New data is added to existing items (never overwrites existing data)

### Category-Specific Data

The agent looks for different specs based on category:
- **Backpacks**: Volume (liters)
- **Sleeping bags**: Temperature rating, fill power
- **Sleeping pads**: R-value
- **Tents**: Capacity, waterproof rating
- **Headlamps**: Lumens, burn time
- **Stoves**: Fuel type, burn time
- **Water filters**: Filter type, flow rate

### Tips

- Start with "Run Single Item" to test
- Use category filter to focus on specific gear types
- The agent respects rate limits (2s between items)
""")

"""Data Fixer UI Component for GearGraph.

A generic system for fixing data quality issues discovered through queries.
Supports different fix strategies for different types of problems.
"""

import streamlit as st
from typing import Optional
from enum import Enum

from app.ui.fix_handlers import (
    fix_assign_brand,
    fix_add_image,
    fix_link_to_gear,
    fix_delete_orphan,
    fix_set_category,
    fix_set_weight,
    fix_set_price,
    fix_merge_duplicates,
)
from app.ui.family_fix_handler import fix_organize_families


class FixType(Enum):
    """Types of fixes available."""
    ASSIGN_BRAND = "assign_brand"
    ADD_IMAGE = "add_image"
    MERGE_DUPLICATES = "merge_duplicates"
    DELETE_ORPHAN = "delete_orphan"
    LINK_TO_FAMILY = "link_to_family"
    LINK_TO_GEAR = "link_to_gear"
    SET_CATEGORY = "set_category"
    SET_WEIGHT = "set_weight"
    SET_PRICE = "set_price"
    ORGANIZE_FAMILIES = "organize_families"


# Map query keys to their fix configurations
FIXABLE_QUERIES = {
    "no_brand": {
        "fix_type": FixType.ASSIGN_BRAND,
        "title": "Assign Brand to Gear Items",
        "description": "These gear items don't have a brand relationship. Assign the correct brand.",
        "node_label": "GearItem",
        "name_field": "name",
    },
    "no_images": {
        "fix_type": FixType.ADD_IMAGE,
        "title": "Add Images to Gear Items",
        "description": "These gear items are missing images. Add image URLs.",
        "node_label": "GearItem",
        "name_field": "name",
    },
    "orphan_families": {
        "fix_type": FixType.LINK_TO_GEAR,
        "title": "Link Product Families to Gear Items",
        "description": "These product families have no gear item variants. Link or delete them.",
        "node_label": "ProductFamily",
        "name_field": "family_name",
    },
    "orphan_insights": {
        "fix_type": FixType.LINK_TO_GEAR,
        "title": "Link Insights to Products",
        "description": "These insights aren't connected to any products. Link or delete them.",
        "node_label": "Insight",
        "name_field": "summary",
    },
    "orphan_glossary": {
        "fix_type": FixType.DELETE_ORPHAN,
        "title": "Review Orphan Glossary Entries",
        "description": "These glossary entries have no connections. Review or delete them.",
        "node_label": "GlossaryTerm",
        "name_field": "term",
    },
    "no_category": {
        "fix_type": FixType.SET_CATEGORY,
        "title": "Set Category for Gear Items",
        "description": "These gear items are missing a category. Assign the correct category.",
        "node_label": "GearItem",
        "name_field": "name",
    },
    "no_weight": {
        "fix_type": FixType.SET_WEIGHT,
        "title": "Set Weight for Gear Items",
        "description": "These gear items are missing weight data. Enter the weight in grams.",
        "node_label": "GearItem",
        "name_field": "name",
    },
    "no_price": {
        "fix_type": FixType.SET_PRICE,
        "title": "Set Price for Gear Items",
        "description": "These gear items are missing price data. Enter the price in USD.",
        "node_label": "GearItem",
        "name_field": "name",
    },
    "duplicates": {
        "fix_type": FixType.MERGE_DUPLICATES,
        "title": "Merge Duplicate Gear Items",
        "description": "These items appear to be duplicates. Select which to keep and merge.",
        "node_label": "GearItem",
        "name_field": "name",
    },
    "brands_no_products": {
        "fix_type": FixType.DELETE_ORPHAN,
        "title": "Review Orphan Brands",
        "description": "These brands have no products. Review or delete them.",
        "node_label": "OutdoorBrand",
        "name_field": "brand",
    },
    "family_candidates": {
        "fix_type": FixType.ORGANIZE_FAMILIES,
        "title": "Organize Product Families",
        "description": "These products may belong to product families. Review and organize them.",
        "node_label": "GearItem",
        "name_field": "brand",
    },
}


# Map fix types to their handler functions
FIX_HANDLERS = {
    FixType.ASSIGN_BRAND: fix_assign_brand,
    FixType.ADD_IMAGE: fix_add_image,
    FixType.LINK_TO_GEAR: fix_link_to_gear,
    FixType.DELETE_ORPHAN: fix_delete_orphan,
    FixType.SET_CATEGORY: fix_set_category,
    FixType.SET_WEIGHT: fix_set_weight,
    FixType.SET_PRICE: fix_set_price,
    FixType.MERGE_DUPLICATES: fix_merge_duplicates,
    FixType.ORGANIZE_FAMILIES: fix_organize_families,
}


def init_fixer_state():
    """Initialize session state for the data fixer."""
    if "fixer_items" not in st.session_state:
        st.session_state.fixer_items = []
    if "fixer_current_index" not in st.session_state:
        st.session_state.fixer_current_index = 0
    if "fixer_query_key" not in st.session_state:
        st.session_state.fixer_query_key = None
    if "fixer_fixed_count" not in st.session_state:
        st.session_state.fixer_fixed_count = 0
    if "fixer_skipped_count" not in st.session_state:
        st.session_state.fixer_skipped_count = 0


def is_query_fixable(query_key: str) -> bool:
    """Check if a query has an associated fix action."""
    return query_key in FIXABLE_QUERIES


def get_fix_config(query_key: str) -> Optional[dict]:
    """Get the fix configuration for a query."""
    return FIXABLE_QUERIES.get(query_key)


def render_fix_button(query_key: str, results: list) -> bool:
    """Render a 'Fix These' button if the query is fixable. Returns True if clicked."""
    if not is_query_fixable(query_key) or not results:
        return False

    if st.button(f"Fix These ({len(results)} items)", type="primary"):
        st.session_state.fixer_items = results
        st.session_state.fixer_current_index = 0
        st.session_state.fixer_query_key = query_key
        st.session_state.fixer_fixed_count = 0
        st.session_state.fixer_skipped_count = 0
        return True

    return False


def render_data_fixer():
    """Render the data fixer interface."""
    init_fixer_state()

    items = st.session_state.fixer_items
    current_idx = st.session_state.fixer_current_index
    query_key = st.session_state.fixer_query_key

    if not items or not query_key:
        st.info("No items to fix. Run a query and click 'Fix These' to start.")
        return

    config = get_fix_config(query_key)
    if not config:
        st.error(f"Unknown fix type for query: {query_key}")
        return

    # Header
    st.header(config["title"])
    st.caption(config["description"])

    # Progress
    total = len(items)
    fixed = st.session_state.fixer_fixed_count
    skipped = st.session_state.fixer_skipped_count

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Progress", f"{current_idx + 1} / {total}")
    col2.metric("Fixed", fixed)
    col3.metric("Skipped", skipped)
    col4.metric("Remaining", total - current_idx)

    st.progress((current_idx) / total)

    # Check if done
    if current_idx >= total:
        st.success(f"All done! Fixed {fixed} items, skipped {skipped}.")
        if st.button("Start Over"):
            st.session_state.fixer_items = []
            st.session_state.fixer_current_index = 0
            st.rerun()
        return

    st.divider()

    # Current item
    item = items[current_idx]

    # Get the appropriate handler
    handler = FIX_HANDLERS.get(config["fix_type"])
    if not handler:
        st.error(f"No handler for fix type: {config['fix_type']}")
        return

    # Run the handler
    result = handler(item, config)

    if result is True:
        st.session_state.fixer_fixed_count += 1
        st.session_state.fixer_current_index += 1
        st.rerun()
    elif result == "skip":
        st.session_state.fixer_skipped_count += 1
        st.session_state.fixer_current_index += 1
        st.rerun()

    # Navigation
    st.divider()
    col1, col2, col3 = st.columns(3)

    with col1:
        if current_idx > 0:
            if st.button("← Previous"):
                st.session_state.fixer_current_index -= 1
                st.rerun()

    with col2:
        if st.button("Exit Fixer"):
            st.session_state.fixer_items = []
            st.session_state.fixer_current_index = 0
            st.rerun()

    with col3:
        if current_idx < total - 1:
            if st.button("Next →"):
                st.session_state.fixer_current_index += 1
                st.rerun()

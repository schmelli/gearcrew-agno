"""Fix handler for organizing products into families."""

import streamlit as st
from typing import Optional

from app.tools.product_family_detector import (
    detect_product_families,
    create_product_family,
    extract_base_name,
    ProductGroup,
)


def fix_organize_families(item: dict, config: dict) -> Optional[bool]:
    """Handle organizing products into families.

    This handler works differently from others - it processes by brand,
    showing all detected family candidates for that brand.

    Args:
        item: Dict containing brand and sample_products from the query
        config: Fix configuration

    Returns:
        True if changes were made, "skip" to skip, None to stay on current item
    """
    brand = item.get("brand", "Unknown")

    # Initialize session state for this brand
    state_key = f"family_fix_{brand}"
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            "families_created": 0,
            "selected_products": {},
            "custom_family_name": "",
        }

    state = st.session_state[state_key]

    st.markdown(f"### {brand}")
    st.caption(f"Organizing products into families for {brand}")

    # Detect family candidates for this brand
    families = detect_product_families(brand=brand, min_products=2)

    if not families:
        st.info(f"No family candidates detected for {brand}.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Skip Brand", key=f"skip_{brand}"):
                return "skip"
        return None

    # Show family candidates
    st.markdown(f"**{len(families)} potential families detected:**")

    for idx, family in enumerate(families):
        _render_family_card(family, idx, brand, state)

    st.divider()

    # Summary and actions
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Skip Brand", key=f"skip_brand_{brand}"):
            return "skip"

    with col2:
        if state["families_created"] > 0:
            st.success(f"Created {state['families_created']} families")

    with col3:
        if st.button("Done with Brand", key=f"done_{brand}", type="primary"):
            if state["families_created"] > 0:
                # Clear state and move to next
                del st.session_state[state_key]
                return True
            else:
                return "skip"

    return None


def _render_family_card(family: ProductGroup, idx: int, brand: str, state: dict):
    """Render a single family candidate card with actions."""
    card_key = f"family_{brand}_{idx}"

    with st.expander(
        f"{family.family_name} ({family.product_count} products) "
        f"- Confidence: {family.confidence:.0%}",
        expanded=(idx == 0),
    ):
        # Show products in this family
        st.markdown("**Products:**")

        # Create columns for product selection
        cols = st.columns([3, 1, 1, 1])
        cols[0].markdown("**Name**")
        cols[1].markdown("**Variant**")
        cols[2].markdown("**Category**")
        cols[3].markdown("**Include**")

        selected_ids = []
        for pidx, product in enumerate(family.products):
            cols = st.columns([3, 1, 1, 1])
            cols[0].write(product["name"])
            cols[1].write(product["variant"])
            cols[2].write(product.get("category") or "-")

            include = cols[3].checkbox(
                "Include",
                value=True,
                key=f"{card_key}_prod_{pidx}",
                label_visibility="collapsed",
            )
            if include:
                selected_ids.append(product["node_id"])

        st.markdown("---")

        # Family name customization
        col1, col2 = st.columns([2, 1])

        with col1:
            custom_name = st.text_input(
                "Family Name",
                value=family.family_name,
                key=f"{card_key}_name",
            )

        with col2:
            st.caption(f"Pattern: {family.pattern_type}")

        # Category selection
        categories = list(set(
            p.get("category") for p in family.products
            if p.get("category")
        ))
        category = None
        if categories:
            category = st.selectbox(
                "Family Category",
                options=[""] + categories,
                key=f"{card_key}_category",
            )

        # Create family button
        if st.button(
            f"Create '{custom_name}' Family",
            key=f"{card_key}_create",
            type="primary",
            disabled=len(selected_ids) < 2,
        ):
            success = create_product_family(
                family_name=custom_name,
                brand=brand,
                product_node_ids=selected_ids,
                category=category or None,
            )

            if success:
                st.success(f"Created family '{custom_name}' with {len(selected_ids)} products!")
                state["families_created"] += 1
                st.rerun()
            else:
                st.error("Failed to create family. Check logs for details.")

        if len(selected_ids) < 2:
            st.caption("Select at least 2 products to create a family")


def render_family_organizer_standalone():
    """Render a standalone family organizer view (not in the fixer flow)."""
    st.header("Product Family Organizer")
    st.caption("Detect and organize products into families")

    # Get summary stats
    from app.tools.product_family_detector import get_family_summary_stats
    stats = get_family_summary_stats()

    # Show stats
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Existing Families", stats["existing_families"])
    col2.metric("Products in Families", stats["products_in_families"])
    col3.metric("Standalone Products", stats["standalone_products"])
    col4.metric("Family Candidates", stats["detected_family_candidates"])

    st.divider()

    # Brand filter
    from app.tools.product_family_detector import get_family_candidates_by_brand
    candidates_by_brand = get_family_candidates_by_brand()

    if not candidates_by_brand:
        st.info("No family candidates detected. All products may already be organized.")
        return

    brand_options = list(candidates_by_brand.keys())
    selected_brand = st.selectbox(
        "Select Brand to Organize",
        options=brand_options,
        format_func=lambda x: f"{x} ({len(candidates_by_brand[x])} families)",
    )

    if selected_brand:
        st.markdown(f"### {selected_brand}")

        families = candidates_by_brand[selected_brand]

        # Initialize state for this view
        if "organizer_state" not in st.session_state:
            st.session_state.organizer_state = {}

        for idx, family in enumerate(families):
            _render_family_card(
                family, idx, selected_brand,
                st.session_state.organizer_state,
            )

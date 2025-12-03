"""Fix handlers for the Data Fixer.

Each handler implements the logic for fixing a specific type of data quality issue.
"""

import streamlit as st
from typing import Optional

from app.db.memgraph import execute_and_fetch, execute_cypher


# Standard gear categories
GEAR_CATEGORIES = [
    "backpack", "tent", "sleeping_bag", "sleeping_pad", "stove",
    "water_filter", "headlamp", "jacket", "pants", "boots",
    "trekking_poles", "cookware", "shelter", "quilt", "bivy",
    "rain_gear", "base_layer", "mid_layer", "insulation",
    "gloves", "hat", "socks", "gaiters", "food_storage",
    "navigation", "first_aid", "repair_kit", "hygiene",
    "electronics", "accessories", "other"
]


def get_all_brands() -> list[str]:
    """Get list of all brand names for selection."""
    query = """
    MATCH (b:OutdoorBrand)
    RETURN b.name as name
    ORDER BY b.name
    """
    results = execute_and_fetch(query)
    return [b["name"] for b in results if b.get("name")]


def search_gear_items(search_term: str, limit: int = 10) -> list[dict]:
    """Search for gear items by name."""
    query = """
    MATCH (g:GearItem)
    WHERE toLower(g.name) CONTAINS toLower($search)
    RETURN g.name as name, g.brand as brand, g.category as category, id(g) as node_id
    ORDER BY g.name
    LIMIT $limit
    """
    return execute_and_fetch(query, {"search": search_term, "limit": limit})


def infer_brand_from_name(name: str) -> Optional[str]:
    """Try to infer brand from product name using known patterns."""
    name_lower = name.lower()
    # Common brand patterns - format: (pattern, brand_name)
    patterns = [
        ("zpacks", "Zpacks"), ("gossamer", "Gossamer Gear"), ("big agnes", "Big Agnes"),
        ("nemo", "NEMO"), ("thermarest", "Therm-a-Rest"), ("therm-a-rest", "Therm-a-Rest"),
        ("msr", "MSR"), ("jetboil", "Jetboil"), ("osprey", "Osprey"), ("gregory", "Gregory"),
        ("deuter", "Deuter"), ("hilleberg", "Hilleberg"), ("tarptent", "Tarptent"),
        ("durston", "Durston Gear"), ("enlightened equipment", "Enlightened Equipment"),
        ("katabatic", "Katabatic Gear"), ("nunatak", "Nunatak"),
        ("western mountaineering", "Western Mountaineering"), ("patagonia", "Patagonia"),
        ("arc'teryx", "Arc'teryx"), ("arcteryx", "Arc'teryx"), ("rab", "Rab"),
        ("montbell", "Montbell"), ("sea to summit", "Sea to Summit"),
        ("black diamond", "Black Diamond"), ("petzl", "Petzl"), ("altra", "Altra"),
        ("salomon", "Salomon"), ("la sportiva", "La Sportiva"), ("lowa", "Lowa"),
        ("sawyer", "Sawyer"), ("katadyn", "Katadyn"), ("platypus", "Platypus"),
        ("hyperlite", "Hyperlite Mountain Gear"), ("hmg", "Hyperlite Mountain Gear"),
        ("ula", "ULA Equipment"), ("granite gear", "Granite Gear"),
        ("six moon", "Six Moon Designs"), ("naturehike", "Naturehike"),
        ("3f ul", "3F UL Gear"), ("lanshan", "3F UL Gear"), ("decathlon", "Decathlon"),
        ("forclaz", "Decathlon"), ("quechua", "Decathlon"), ("rei", "REI"),
        ("kelty", "Kelty"), ("marmot", "Marmot"), ("mountain hardwear", "Mountain Hardwear"),
        ("sierra designs", "Sierra Designs"), ("feathered friends", "Feathered Friends"),
        ("outdoor research", "Outdoor Research"), ("seek outside", "Seek Outside"),
        ("kifaru", "Kifaru"), ("mystery ranch", "Mystery Ranch"), ("exped", "Exped"),
        ("klymit", "Klymit"), ("nitecore", "Nitecore"), ("fenix", "Fenix"),
        ("toaks", "TOAKS"), ("evernew", "Evernew"), ("snow peak", "Snow Peak"),
        ("trangia", "Trangia"), ("primus", "Primus"), ("soto", "SOTO"),
        ("fire-maple", "Fire-Maple"), ("campingmoon", "Campingmoon"),
        ("ursack", "Ursack"), ("bearvault", "BearVault"), ("cnoc", "CNOC"),
    ]
    for pattern, brand in patterns:
        if pattern in name_lower:
            return brand
    return None


def fix_assign_brand(item: dict, config: dict) -> bool:
    """Handle assigning a brand to an item."""
    name = item.get(config["name_field"], "Unknown")
    current_brand = item.get("brand_text") or item.get("brand", "")

    st.markdown(f"### {name}")
    if current_brand:
        st.caption(f"Current brand text: {current_brand}")

    # Try to infer brand
    inferred = infer_brand_from_name(name)
    if inferred:
        st.info(f"Suggested brand: **{inferred}**")

    # Brand selection
    brands = get_all_brands()
    col1, col2 = st.columns([3, 1])

    with col1:
        if inferred and inferred not in brands:
            brands = [inferred] + brands

        selected_brand = st.selectbox(
            "Select brand:",
            ["-- Select --"] + brands,
            key=f"brand_select_{st.session_state.fixer_current_index}",
            index=1 if inferred and inferred in brands else 0,
        )

    with col2:
        new_brand = st.text_input(
            "Or create new:",
            key=f"new_brand_{st.session_state.fixer_current_index}",
        )

    brand_to_use = new_brand.strip() if new_brand.strip() else (
        selected_brand if selected_brand != "-- Select --" else None
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Apply Fix", type="primary", disabled=not brand_to_use):
            query = """
            MATCH (g:GearItem {name: $name})
            MERGE (b:OutdoorBrand {name: $brand})
            MERGE (b)-[:MANUFACTURES_ITEM]->(g)
            SET g.brand = $brand
            RETURN g.name
            """
            if execute_cypher(query, {"name": name, "brand": brand_to_use}):
                st.success(f"Linked {name} to {brand_to_use}")
                return True
            else:
                st.error("Failed to apply fix")

    with col2:
        if st.button("Skip"):
            return "skip"

    with col3:
        if st.button("Delete Item", type="secondary"):
            key = f"confirm_delete_{st.session_state.fixer_current_index}"
            if st.session_state.get(key):
                query = "MATCH (g:GearItem {name: $name}) DETACH DELETE g"
                if execute_cypher(query, {"name": name}):
                    st.success(f"Deleted {name}")
                    return True
            else:
                st.session_state[key] = True
                st.warning("Click again to confirm deletion")

    return False


def fix_add_image(item: dict, config: dict) -> bool:
    """Handle adding an image URL to an item."""
    name = item.get(config["name_field"], "Unknown")
    brand = item.get("brand", "")

    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    image_url = st.text_input(
        "Image URL:",
        key=f"image_url_{st.session_state.fixer_current_index}",
        placeholder="https://example.com/image.jpg",
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Apply Fix", type="primary", disabled=not image_url):
            query = """
            MATCH (g:GearItem {name: $name})
            SET g.imageUrl = $url
            RETURN g.name
            """
            if execute_cypher(query, {"name": name, "url": image_url}):
                st.success(f"Added image to {name}")
                return True
            else:
                st.error("Failed to apply fix")

    with col2:
        if st.button("Skip"):
            return "skip"

    with col3:
        if st.button("Delete Item", type="secondary"):
            key = f"confirm_delete_{st.session_state.fixer_current_index}"
            if st.session_state.get(key):
                query = "MATCH (g:GearItem {name: $name}) DETACH DELETE g"
                if execute_cypher(query, {"name": name}):
                    st.success(f"Deleted {name}")
                    return True
            else:
                st.session_state[key] = True
                st.warning("Click again to confirm deletion")

    return False


def fix_link_to_gear(item: dict, config: dict) -> bool:
    """Handle linking a node to gear items (for product families, insights)."""
    name = item.get(config["name_field"], "Unknown")
    node_label = config["node_label"]
    brand = item.get("brand", "")

    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    selected_brand = None
    if node_label == "ProductFamily":
        inferred = infer_brand_from_name(name)
        if inferred:
            st.info(f"Suggested brand: **{inferred}**")

        brands = get_all_brands()
        selected_brand = st.selectbox(
            "Assign brand:",
            ["-- No change --"] + ([inferred] if inferred else []) + brands,
            key=f"pf_brand_{st.session_state.fixer_current_index}",
        )

    search = st.text_input(
        "Search gear items to link:",
        value=name.split()[0] if name else "",
        key=f"gear_search_{st.session_state.fixer_current_index}",
    )

    selected_items = []
    if search:
        matches = search_gear_items(search)
        if matches:
            st.write(f"Found {len(matches)} matching gear items:")
            for i, match in enumerate(matches):
                if st.checkbox(
                    f"{match['name']} ({match.get('brand', 'No brand')})",
                    key=f"link_gear_{st.session_state.fixer_current_index}_{i}",
                ):
                    selected_items.append(match)
        else:
            st.info("No matching gear items found")

    col1, col2, col3 = st.columns(3)

    with col1:
        can_apply = bool(selected_items) or (
            node_label == "ProductFamily" and
            selected_brand and selected_brand != "-- No change --"
        )
        if st.button("Apply Fix", type="primary", disabled=not can_apply):
            success = True

            for gear in selected_items:
                if node_label == "ProductFamily":
                    query = """
                    MATCH (pf:ProductFamily {name: $pf_name})
                    MATCH (g:GearItem {name: $gear_name})
                    MERGE (pf)-[:HAS_VARIANT]->(g)
                    RETURN pf.name
                    """
                elif node_label == "Insight":
                    query = """
                    MATCH (i:Insight {summary: $pf_name})
                    MATCH (g:GearItem {name: $gear_name})
                    MERGE (g)-[:HAS_TIP]->(i)
                    RETURN i.summary
                    """
                else:
                    continue

                if not execute_cypher(query, {"pf_name": name, "gear_name": gear["name"]}):
                    success = False

            if node_label == "ProductFamily" and selected_brand and selected_brand != "-- No change --":
                query = """
                MATCH (pf:ProductFamily {name: $name})
                MERGE (b:OutdoorBrand {name: $brand})
                MERGE (pf)-[:PRODUCED_BY]->(b)
                SET pf.brand = $brand
                RETURN pf.name
                """
                if not execute_cypher(query, {"name": name, "brand": selected_brand}):
                    success = False

            if success:
                st.success(f"Fixed {name}")
                return True
            else:
                st.error("Some fixes failed")

    with col2:
        if st.button("Skip"):
            return "skip"

    with col3:
        if st.button("Delete", type="secondary"):
            key = f"confirm_delete_{st.session_state.fixer_current_index}"
            if st.session_state.get(key):
                if node_label == "Insight":
                    query = "MATCH (n:Insight {summary: $name}) DETACH DELETE n"
                else:
                    query = f"MATCH (n:{node_label} {{name: $name}}) DETACH DELETE n"
                if execute_cypher(query, {"name": name}):
                    st.success(f"Deleted {name}")
                    return True
            else:
                st.session_state[key] = True
                st.warning("Click again to confirm deletion")

    return False


def fix_delete_orphan(item: dict, config: dict) -> bool:
    """Handle reviewing and potentially deleting orphan nodes."""
    name = item.get(config["name_field"], "Unknown")
    node_label = config["node_label"]

    st.markdown(f"### {name}")

    for key, value in item.items():
        if key != config["name_field"] and value and key not in ["node_id"]:
            st.caption(f"{key}: {value}")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Keep (Skip)", type="primary"):
            return "skip"

    with col2:
        if st.button("Delete", type="secondary"):
            key = f"confirm_delete_{st.session_state.fixer_current_index}"
            if st.session_state.get(key):
                if node_label == "GlossaryTerm":
                    query = "MATCH (n:GlossaryTerm {name: $name}) DETACH DELETE n"
                elif node_label == "OutdoorBrand":
                    query = "MATCH (n:OutdoorBrand {name: $name}) DETACH DELETE n"
                else:
                    query = f"MATCH (n:{node_label} {{name: $name}}) DETACH DELETE n"

                if execute_cypher(query, {"name": name}):
                    st.success(f"Deleted {name}")
                    return True
            else:
                st.session_state[key] = True
                st.warning("Click again to confirm deletion")

    return False


def fix_set_category(item: dict, config: dict) -> bool:
    """Handle setting category for an item."""
    name = item.get(config["name_field"], "Unknown")
    brand = item.get("brand", "")

    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    selected_category = st.selectbox(
        "Select category:",
        ["-- Select --"] + GEAR_CATEGORIES,
        key=f"category_select_{st.session_state.fixer_current_index}",
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Apply Fix", type="primary", disabled=selected_category == "-- Select --"):
            query = """
            MATCH (g:GearItem {name: $name})
            SET g.category = $category
            RETURN g.name
            """
            if execute_cypher(query, {"name": name, "category": selected_category}):
                st.success(f"Set category of {name} to {selected_category}")
                return True
            else:
                st.error("Failed to apply fix")

    with col2:
        if st.button("Skip"):
            return "skip"

    return False


def fix_set_weight(item: dict, config: dict) -> bool:
    """Handle setting weight for an item."""
    name = item.get(config["name_field"], "Unknown")
    brand = item.get("brand", "")

    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    weight = st.number_input(
        "Weight (grams):",
        min_value=0,
        max_value=50000,
        value=0,
        key=f"weight_{st.session_state.fixer_current_index}",
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Apply Fix", type="primary", disabled=weight == 0):
            query = """
            MATCH (g:GearItem {name: $name})
            SET g.weight_grams = $weight
            RETURN g.name
            """
            if execute_cypher(query, {"name": name, "weight": weight}):
                st.success(f"Set weight of {name} to {weight}g")
                return True
            else:
                st.error("Failed to apply fix")

    with col2:
        if st.button("Skip"):
            return "skip"

    return False


def fix_set_price(item: dict, config: dict) -> bool:
    """Handle setting price for an item."""
    name = item.get(config["name_field"], "Unknown")
    brand = item.get("brand", "")

    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    price = st.number_input(
        "Price (USD):",
        min_value=0.0,
        max_value=10000.0,
        value=0.0,
        step=0.01,
        key=f"price_{st.session_state.fixer_current_index}",
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Apply Fix", type="primary", disabled=price == 0):
            query = """
            MATCH (g:GearItem {name: $name})
            SET g.price_usd = $price
            RETURN g.name
            """
            if execute_cypher(query, {"name": name, "price": price}):
                st.success(f"Set price of {name} to ${price:.2f}")
                return True
            else:
                st.error("Failed to apply fix")

    with col2:
        if st.button("Skip"):
            return "skip"

    return False

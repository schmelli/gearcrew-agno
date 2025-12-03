"""Fix handlers for the Data Fixer."""

import streamlit as st
from typing import Optional

from app.db.memgraph import execute_and_fetch, execute_cypher
from app.tools.web_scraper import search_images, search_product_weights


# Standard gear categories
GEAR_CATEGORIES = [
    "backpack", "tent", "sleeping_bag", "sleeping_pad", "stove", "water_filter",
    "headlamp", "jacket", "pants", "boots", "trekking_poles", "cookware", "shelter",
    "quilt", "bivy", "rain_gear", "base_layer", "mid_layer", "insulation", "gloves",
    "hat", "socks", "gaiters", "food_storage", "navigation", "first_aid", "repair_kit",
    "hygiene", "electronics", "accessories", "other"
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


def strip_brand_from_name(name: str, brand: str) -> str:
    """Remove brand name from product name (e.g., 'Gregory Maya 20' -> 'Maya 20')."""
    if not brand or not name:
        return name
    name_lower, brand_lower = name.lower(), brand.lower()
    # Check brand and common variations (Arc'teryx vs Arcteryx, Therm-a-Rest vs Thermarest)
    for variant in [brand_lower, brand_lower.replace("'", ""), brand_lower.replace("-", " ")]:
        if name_lower.startswith(variant):
            stripped = name[len(variant):].lstrip()
            return stripped if stripped else name
    return name


def fix_assign_brand(item: dict, config: dict) -> bool:
    """Handle assigning a brand to an item."""
    name = item.get(config["name_field"], "Unknown")
    current_brand = item.get("brand_text") or item.get("brand", "")

    st.markdown(f"### {name}")
    if current_brand:
        st.caption(f"Current brand text: {current_brand}")

    # Try to infer brand
    inferred = infer_brand_from_name(name)

    # Brand selection
    brands = get_all_brands()

    # Build options list and find default index
    if inferred and inferred not in brands:
        options = [inferred] + brands
    else:
        options = brands

    # Calculate default index: if inferred brand exists, pre-select it
    default_index = 0  # "-- Select --"
    if inferred:
        try:
            default_index = options.index(inferred) + 1  # +1 for "-- Select --"
        except ValueError:
            default_index = 1 if inferred in options else 0

    col1, col2 = st.columns([3, 1])

    with col1:
        selected_brand = st.selectbox(
            "Select brand:",
            ["-- Select --"] + options,
            key=f"brand_select_{st.session_state.fixer_current_index}",
            index=default_index,
        )

    with col2:
        new_brand = st.text_input(
            "Or create new:",
            key=f"new_brand_{st.session_state.fixer_current_index}",
        )

    brand_to_use = new_brand.strip() if new_brand.strip() else (
        selected_brand if selected_brand != "-- Select --" else None
    )

    # Show preview of cleaned product name
    if brand_to_use:
        cleaned_name = strip_brand_from_name(name, brand_to_use)
        if cleaned_name != name:
            st.info(f"Product name will be updated: **{name}** → **{cleaned_name}**")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Apply Fix", type="primary", disabled=not brand_to_use):
            # Clean the product name by removing brand prefix
            cleaned_name = strip_brand_from_name(name, brand_to_use)

            query = """
            MATCH (g:GearItem {name: $old_name})
            MERGE (b:OutdoorBrand {name: $brand})
            MERGE (b)-[:MANUFACTURES_ITEM]->(g)
            SET g.brand = $brand, g.name = $new_name
            RETURN g.name
            """
            params = {"old_name": name, "brand": brand_to_use, "new_name": cleaned_name}
            if execute_cypher(query, params):
                if cleaned_name != name:
                    st.success(f"Linked '{cleaned_name}' to {brand_to_use}")
                else:
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
    """Handle adding an image URL to an item with Google image search."""
    name, brand = item.get(config["name_field"], "Unknown"), item.get("brand", "")
    idx = st.session_state.fixer_current_index
    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    search_query = f"{brand} {name}".strip() if brand else name
    ik, mk = f"search_images_{idx}", f"manual_url_{idx}"

    if ik not in st.session_state:
        with st.spinner("Searching for images..."):
            st.session_state[ik] = search_images(search_query, num_results=5)

    def _cleanup():
        st.session_state.pop(ik, None)
        st.session_state.pop(mk, None)

    images = st.session_state.get(ik, [])
    if images:
        st.write("**Click an image to apply:**")
        cols = st.columns(5)
        for i, img in enumerate(images):
            with cols[i]:
                st.image(img["imageUrl"], use_container_width=True)
                src = img.get("source", "")
                st.caption(src[:20] + "..." if len(src) > 20 else src)
                if st.button("Apply", key=f"select_img_{idx}_{i}", type="primary"):
                    url = img["imageUrl"]
                    if execute_cypher("MATCH (g:GearItem {name: $name}) SET g.imageUrl = $url RETURN g",
                                      {"name": name, "url": url}):
                        _cleanup()
                        st.success(f"Added image to {name}")
                        return True
                    st.error("Failed")
    else:
        st.warning("No images found. Enter URL manually below.")

    # Manual entry section
    st.divider()
    st.write("**Or enter manually:**")
    manual_url = st.text_input("Image URL:", key=mk, label_visibility="collapsed")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Apply URL", type="primary", disabled=not manual_url.strip()):
            if execute_cypher("MATCH (g:GearItem {name: $name}) SET g.imageUrl = $url RETURN g",
                              {"name": name, "url": manual_url.strip()}):
                _cleanup()
                st.success(f"Added image to {name}")
                return True
            st.error("Failed")
    with c2:
        new_q = st.text_input("Search:", value=search_query, key=f"search_query_{idx}", label_visibility="collapsed")
    with c3:
        if st.button("Re-search", key=f"research_{idx}"):
            with st.spinner("Searching..."):
                st.session_state[ik] = search_images(new_q, num_results=5)
            st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Skip"):
            _cleanup()
            return "skip"
    with c2:
        if st.button("Delete Item", type="secondary"):
            dk = f"confirm_delete_{idx}"
            if st.session_state.get(dk):
                if execute_cypher("MATCH (g:GearItem {name: $name}) DETACH DELETE g", {"name": name}):
                    _cleanup()
                    st.success(f"Deleted {name}")
                    return True
            else:
                st.session_state[dk] = True
                st.warning("Click again to confirm")
    return False


def fix_link_to_gear(item: dict, config: dict) -> bool:
    """Handle linking a node to gear items (for product families, insights)."""
    name, node_label = item.get(config["name_field"], "Unknown"), config["node_label"]
    idx = st.session_state.fixer_current_index
    st.markdown(f"### {name}")
    if item.get("brand"):
        st.caption(f"Brand: {item['brand']}")

    selected_brand = None
    if node_label == "ProductFamily":
        inferred = infer_brand_from_name(name)
        brands = get_all_brands()
        opts = ["-- No change --"] + ([inferred] if inferred and inferred not in brands else []) + brands
        def_idx = opts.index(inferred) if inferred and inferred in opts else 0
        selected_brand = st.selectbox("Assign brand:", opts, index=def_idx, key=f"pf_brand_{idx}")

    search = st.text_input("Search gear items:", value=name.split()[0] if name else "", key=f"gear_search_{idx}")
    selected_items = []
    if search:
        matches = search_gear_items(search)
        if matches:
            for i, m in enumerate(matches):
                if st.checkbox(f"{m['name']} ({m.get('brand', 'No brand')})", key=f"link_gear_{idx}_{i}"):
                    selected_items.append(m)
        else:
            st.info("No matching gear items")

    c1, c2, c3 = st.columns(3)
    can_apply = bool(selected_items) or (node_label == "ProductFamily" and selected_brand and selected_brand != "-- No change --")
    with c1:
        if st.button("Apply Fix", type="primary", disabled=not can_apply):
            ok = True
            for g in selected_items:
                q = ("MATCH (pf:ProductFamily {name: $pf}) MATCH (g:GearItem {name: $g}) MERGE (pf)-[:HAS_VARIANT]->(g)"
                     if node_label == "ProductFamily" else
                     "MATCH (i:Insight {summary: $pf}) MATCH (g:GearItem {name: $g}) MERGE (g)-[:HAS_TIP]->(i)")
                if not execute_cypher(q, {"pf": name, "g": g["name"]}):
                    ok = False
            if node_label == "ProductFamily" and selected_brand and selected_brand != "-- No change --":
                q = "MATCH (pf:ProductFamily {name: $n}) MERGE (b:OutdoorBrand {name: $b}) MERGE (pf)-[:PRODUCED_BY]->(b) SET pf.brand = $b"
                if not execute_cypher(q, {"n": name, "b": selected_brand}):
                    ok = False
            if ok:
                st.success(f"Fixed {name}")
                return True
            st.error("Some fixes failed")
    with c2:
        if st.button("Skip"):
            return "skip"
    with c3:
        if st.button("Delete", type="secondary"):
            dk = f"confirm_delete_{idx}"
            if st.session_state.get(dk):
                q = f"MATCH (n:Insight {{summary: $name}}) DETACH DELETE n" if node_label == "Insight" else f"MATCH (n:{node_label} {{name: $name}}) DETACH DELETE n"
                if execute_cypher(q, {"name": name}):
                    st.success(f"Deleted {name}")
                    return True
            else:
                st.session_state[dk] = True
                st.warning("Click again to confirm")
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
    """Handle setting weight for an item with online weight search."""
    name, brand = item.get(config["name_field"], "Unknown"), item.get("brand", "")
    idx = st.session_state.fixer_current_index
    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")

    wk, wik = f"weight_sources_{idx}", f"weight_input_{idx}"
    if wk not in st.session_state:
        with st.spinner("Searching for weight..."):
            st.session_state[wk] = search_product_weights(name, brand, num_sources=4)

    def _cleanup():
        st.session_state.pop(wk, None)
        st.session_state.pop(wik, None)

    sources = st.session_state.get(wk, [])
    if sources:
        st.write("**Select a weight to apply:**")
        for i, src in enumerate(sources):
            c1, c2 = st.columns([1, 4])
            with c1:
                if st.button("Apply", key=f"sel_wt_{idx}_{i}", type="primary"):
                    wt = src["weight_grams"]
                    if execute_cypher("MATCH (g:GearItem {name: $name}) SET g.weight_grams = $wt RETURN g",
                                      {"name": name, "wt": wt}):
                        _cleanup()
                        st.success(f"Set weight to {wt}g")
                        return True
                    st.error("Failed")
            with c2:
                st.markdown(f"**{src['weight_grams']}g** ({src['original_text']}) - [{src['source']}]({src['url']})")
    else:
        st.warning("No weight sources found. Enter manually below.")

    # Manual entry section
    st.divider()
    st.write("**Or enter manually:**")
    if wik not in st.session_state:
        st.session_state[wik] = 0
    weight = st.number_input("Weight (grams):", min_value=0, max_value=50000, key=wik)

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Apply Manual", type="primary", disabled=weight == 0):
            if execute_cypher("MATCH (g:GearItem {name: $name}) SET g.weight_grams = $wt RETURN g",
                              {"name": name, "wt": weight}):
                _cleanup()
                st.success(f"Set weight to {weight}g")
                return True
            st.error("Failed")
    with c2:
        new_q = st.text_input("Search:", value=f"{brand} {name}".strip(), key=f"wt_query_{idx}", label_visibility="collapsed")
    with c3:
        if st.button("Re-search", key=f"wt_research_{idx}"):
            with st.spinner("Searching..."):
                st.session_state[wk] = search_product_weights(new_q, "", num_sources=4)
                st.session_state[wik] = 0
            st.rerun()

    st.divider()
    if st.button("Skip"):
        _cleanup()
        return "skip"
    return False


def fix_set_price(item: dict, config: dict) -> bool:
    """Handle setting price for an item."""
    name, brand = item.get(config["name_field"], "Unknown"), item.get("brand", "")
    st.markdown(f"### {name}")
    if brand:
        st.caption(f"Brand: {brand}")
    price = st.number_input("Price (USD):", min_value=0.0, max_value=10000.0, value=0.0,
                            step=0.01, key=f"price_{st.session_state.fixer_current_index}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Apply Fix", type="primary", disabled=price == 0):
            q = "MATCH (g:GearItem {name: $name}) SET g.price_usd = $price RETURN g.name"
            if execute_cypher(q, {"name": name, "price": price}):
                st.success(f"Set price of {name} to ${price:.2f}")
                return True
            st.error("Failed to apply fix")
    with col2:
        if st.button("Skip"):
            return "skip"
    return False

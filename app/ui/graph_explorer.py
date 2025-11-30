"""Graph Explorer UI Component for GearGraph.

Provides a Streamlit interface for exploring the Memgraph database.
"""

import streamlit as st
import pandas as pd

from app.db.memgraph import (
    get_memgraph,
    execute_and_fetch,
    get_graph_stats,
)


def node_to_dict(node) -> dict:
    """Convert a gqlalchemy Node to a dictionary."""
    if hasattr(node, "_properties"):
        return dict(node._properties)
    elif hasattr(node, "__dict__"):
        return {k: v for k, v in node.__dict__.items() if not k.startswith("_")}
    elif hasattr(node, "items"):
        return dict(node)
    return {"value": str(node)}


def get_label_icon(label: str) -> str:
    """Get an icon for a node label."""
    icons = {
        "GearItem": "[G]",
        "ProductFamily": "[F]",
        "OutdoorBrand": "[B]",
        "Insight": "[I]",
        "Source": "[S]",
    }
    return icons.get(label, "[?]")


def search_nodes(search_term: str, label: str = None, limit: int = 20) -> list:
    """Search for nodes by name or other properties."""
    if label:
        query = f"""
        MATCH (n:{label})
        WHERE toLower(n.name) CONTAINS toLower($search)
           OR toLower(toString(n.brand)) CONTAINS toLower($search)
        RETURN n, labels(n) as labels
        LIMIT {limit}
        """
    else:
        query = f"""
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($search)
           OR toLower(toString(n.brand)) CONTAINS toLower($search)
        RETURN n, labels(n) as labels
        LIMIT {limit}
        """
    return execute_and_fetch(query, {"search": search_term})


def get_recent_items(label: str = "GearItem", limit: int = 10) -> list:
    """Get recently added items of a specific label."""
    query = f"""
    MATCH (n:{label})
    RETURN n, labels(n) as labels, id(n) as node_id
    ORDER BY n.createdAt DESC, n.name
    LIMIT {limit}
    """
    return execute_and_fetch(query)


def get_brands() -> list:
    """Get all outdoor brands with product counts."""
    query = """
    MATCH (b:OutdoorBrand)
    WITH b,
         size([(b)-[:MANUFACTURES]->(p) | p]) +
         size([(b)-[:MANUFACTURES_ITEM]->(p) | p]) +
         size([(p)-[:PRODUCED_BY]->(b) | p]) as product_count
    RETURN b.name as name, id(b) as node_id, product_count
    ORDER BY product_count DESC, b.name
    """
    return execute_and_fetch(query)


def get_insights(limit: int = 20) -> list:
    """Get insights from the graph."""
    query = f"""
    MATCH (i:Insight)
    OPTIONAL MATCH (p)-[:HAS_TIP]->(i)
    RETURN i.summary as summary, i.content as content,
           i.category as category, p.name as related_product,
           id(i) as node_id
    LIMIT {limit}
    """
    return execute_and_fetch(query)


def execute_custom_query(query: str) -> list:
    """Execute a custom Cypher query (read-only)."""
    query_upper = query.upper().strip()
    forbidden = ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP"]

    if any(kw in query_upper for kw in forbidden):
        st.error("Only read queries (MATCH, RETURN) are allowed in the explorer.")
        return []

    return execute_and_fetch(query)


def render_overview_tab():
    """Render the overview/statistics tab."""
    st.subheader("Graph Statistics")

    stats = get_graph_stats()

    if not stats.get("total_nodes"):
        st.warning("Could not load statistics. Check database connection.")
        return

    # Summary metrics
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Nodes", stats.get("total_nodes", 0))
    with col2:
        st.metric("Total Relationships", stats.get("total_rels", 0))

    st.divider()

    # Node counts by label
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Nodes by Type")
        node_counts = stats.get("node_counts", {})
        if node_counts:
            df = pd.DataFrame(
                [{"Label": k, "Count": v} for k, v in node_counts.items()]
            )
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.info("No nodes found")

    with col2:
        st.subheader("Relationships by Type")
        rel_counts = stats.get("rel_counts", {})
        if rel_counts:
            df = pd.DataFrame(
                [{"Type": k, "Count": v} for k, v in rel_counts.items()]
            )
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.info("No relationships found")

    # Recent items
    st.divider()
    st.subheader("Recent Gear Items")
    recent = get_recent_items("GearItem", 10)

    if recent:
        for item in recent:
            node_obj = item.get("n")
            if not node_obj:
                continue
            node = node_to_dict(node_obj)
            name = node.get("name", "Unknown")
            brand = node.get("brand", "")
            weight = node.get("weight_grams", "")

            with st.expander(f"{name} ({brand})" if brand else name):
                cols = st.columns(3)
                if weight:
                    cols[0].write(f"**Weight:** {weight}g")
                if node.get("productUrl"):
                    cols[1].write(f"[Product Page]({node.get('productUrl')})")
                if node.get("imageUrl"):
                    cols[2].image(node.get("imageUrl"), width=100)
                st.json(node)
    else:
        st.info("No gear items found")


def render_search_tab():
    """Render the search tab."""
    st.subheader("Search Graph")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_term = st.text_input("Search for products, brands, or keywords:")
    with col2:
        label_filter = st.selectbox(
            "Filter by type:",
            ["All", "GearItem", "ProductFamily", "OutdoorBrand", "Insight"],
        )

    if search_term:
        label = None if label_filter == "All" else label_filter
        results = search_nodes(search_term, label)

        if results:
            st.write(f"Found {len(results)} results:")

            for item in results:
                node_obj = item.get("n")
                if not node_obj:
                    continue
                node = node_to_dict(node_obj)
                labels = item.get("labels", [])
                name = node.get("name", "Unknown")
                label_str = labels[0] if labels else "Node"
                icon = get_label_icon(label_str)

                with st.expander(f"{icon} {name} ({label_str})"):
                    st.json(node)
        else:
            st.info("No results found")


def render_brands_tab():
    """Render the brands exploration tab."""
    st.subheader("Outdoor Brands")

    brands = get_brands()

    if brands:
        cols_per_row = 3
        for i in range(0, len(brands), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, col in enumerate(cols):
                if i + j < len(brands):
                    brand = brands[i + j]
                    with col:
                        st.markdown(f"### {brand['name']}")
                        st.caption(f"{brand['product_count']} products")

                        if st.button(
                            f"View {brand['name']}", key=f"brand_{brand['node_id']}"
                        ):
                            st.session_state["selected_brand"] = brand["name"]

        # Show products for selected brand
        if "selected_brand" in st.session_state:
            st.divider()
            st.subheader(f"Products by {st.session_state['selected_brand']}")

            query = """
            MATCH (b:OutdoorBrand {name: $brand})
            OPTIONAL MATCH (b)-[:MANUFACTURES]->(pf:ProductFamily)
            OPTIONAL MATCH (b)-[:MANUFACTURES_ITEM]->(gi:GearItem)
            OPTIONAL MATCH (pf2:ProductFamily)-[:PRODUCED_BY]->(b)
            WITH b, collect(DISTINCT pf) + collect(DISTINCT gi) + collect(DISTINCT pf2) as products
            UNWIND products as p
            RETURN DISTINCT p, labels(p) as labels
            ORDER BY p.name
            """
            products = execute_and_fetch(
                query, {"brand": st.session_state["selected_brand"]}
            )

            if products:
                for product in products:
                    node_obj = product.get("p")
                    if not node_obj:
                        continue
                    node = node_to_dict(node_obj)
                    labels = product.get("labels", [])
                    with st.expander(
                        f"{node.get('name', 'Unknown')} ({labels[0] if labels else 'Product'})"
                    ):
                        st.json(node)
            else:
                st.info("No products linked to this brand yet.")
    else:
        st.info("No brands found in the graph")


def render_insights_tab():
    """Render the insights exploration tab."""
    st.subheader("Gear Insights")

    insights = get_insights(30)

    if insights:
        categories = {}
        for insight in insights:
            cat = insight.get("category", "General") or "General"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(insight)

        for category, cat_insights in categories.items():
            st.markdown(f"### {category}")

            for insight in cat_insights:
                product = insight.get("related_product", "")
                summary = insight.get("summary", "No summary")

                with st.expander(f"{summary} - {product}" if product else summary):
                    st.write(insight.get("content", "No content"))
                    if product:
                        st.caption(f"Related to: {product}")
    else:
        st.info("No insights found in the graph")


def render_data_health_tab():
    """Render the data health/quality tab."""
    st.subheader("Data Health Report")

    # Get total counts
    result = execute_and_fetch("MATCH (g:GearItem) RETURN count(g) as total")
    total_items = result[0]["total"] if result else 0

    result = execute_and_fetch("MATCH (p:ProductFamily) RETURN count(p) as total")
    total_families = result[0]["total"] if result else 0

    # Items without brand relationships
    result = execute_and_fetch("""
        MATCH (g:GearItem)
        WHERE NOT (g)-[:PRODUCED_BY]->(:OutdoorBrand)
          AND NOT (g)<-[:MANUFACTURES_ITEM]-(:OutdoorBrand)
        RETURN count(g) as orphan_count
    """)
    items_no_brand = result[0]["orphan_count"] if result else 0

    # Items without weight
    result = execute_and_fetch("""
        MATCH (g:GearItem)
        WHERE g.weight_grams IS NULL
        RETURN count(g) as missing_weight
    """)
    items_no_weight = result[0]["missing_weight"] if result else 0

    # Orphaned insights
    result = execute_and_fetch("""
        MATCH (i:Insight)
        WHERE NOT ()-[:HAS_TIP]->(i)
        RETURN count(i) as orphan_count
    """)
    orphan_insights = result[0]["orphan_count"] if result else 0

    # Calculate percentages
    brand_coverage = (
        ((total_items - items_no_brand) / total_items * 100) if total_items > 0 else 0
    )
    weight_coverage = (
        ((total_items - items_no_weight) / total_items * 100) if total_items > 0 else 0
    )

    # Health Score
    health_score = (brand_coverage + weight_coverage) / 2
    st.markdown("### Overall Health Score")

    if health_score >= 80:
        st.success(f"Health Score: {health_score:.1f}%")
    elif health_score >= 50:
        st.warning(f"Health Score: {health_score:.1f}%")
    else:
        st.error(f"Health Score: {health_score:.1f}%")

    st.divider()

    # Issues
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Critical Issues")
        if items_no_brand > 0:
            st.error(f"[!] {items_no_brand} GearItems without brand relationship")
        else:
            st.success("[OK] All GearItems have brand relationships")

    with col2:
        st.metric("Brand Coverage", f"{brand_coverage:.1f}%")
        st.metric("Weight Coverage", f"{weight_coverage:.1f}%")

    st.divider()

    if items_no_weight > 0:
        st.warning(f"[!] {items_no_weight} GearItems missing weight_grams")

    if orphan_insights > 0:
        st.warning(f"[!] {orphan_insights} orphaned Insights (not connected)")


def render_query_tab():
    """Render the custom query tab."""
    st.subheader("Custom Cypher Query")

    st.warning("Only read-only queries (MATCH, RETURN) are allowed.")

    preset = st.selectbox(
        "Preset queries:",
        [
            "-- Select a preset --",
            "Get all brands with product counts",
            "Find items missing weight data",
            "Find items with images",
            "Get all insights for a product",
        ],
    )

    preset_queries = {
        "Get all brands with product counts": """
MATCH (b:OutdoorBrand)
OPTIONAL MATCH (b)-[:MANUFACTURES_ITEM]->(p)
RETURN b.name as brand, count(p) as products
ORDER BY products DESC
LIMIT 20
""",
        "Find items missing weight data": """
MATCH (g:GearItem)
WHERE g.weight_grams IS NULL
RETURN g.name as name, g.brand as brand
LIMIT 20
""",
        "Find items with images": """
MATCH (g:GearItem)
WHERE g.imageUrl IS NOT NULL
RETURN g.name as name, g.brand as brand, g.imageUrl as image
LIMIT 20
""",
        "Get all insights for a product": """
MATCH (p)-[:HAS_TIP]->(i:Insight)
RETURN p.name as product, i.summary as insight, i.content as detail
LIMIT 30
""",
    }

    query = preset_queries.get(preset, "") if preset != "-- Select a preset --" else ""

    query = st.text_area(
        "Cypher Query:",
        value=query,
        height=150,
        placeholder="MATCH (n) RETURN n LIMIT 10",
    )

    if st.button("Execute Query", type="primary"):
        if query.strip():
            results = execute_custom_query(query)

            if results:
                st.success(f"Found {len(results)} results")
                try:
                    flat_results = []
                    for row in results:
                        flat_row = {}
                        for k, v in row.items():
                            if hasattr(v, "__iter__") and not isinstance(v, (str, dict)):
                                flat_row[k] = str(v)
                            elif isinstance(v, dict):
                                flat_row[k] = str(dict(v))
                            else:
                                flat_row[k] = v
                        flat_results.append(flat_row)
                    df = pd.DataFrame(flat_results)
                    st.dataframe(df, width="stretch")
                except Exception:
                    for row in results:
                        st.json(dict(row) if hasattr(row, "items") else str(row))
            else:
                st.info("Query returned no results")


def render_graph_explorer():
    """Main function to render the Graph Explorer UI."""
    st.header("GearGraph Explorer")

    db = get_memgraph()
    if db is None:
        st.error("Memgraph connection not available. Check your configuration.")
        return

    # Tabs for different exploration modes
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["Overview", "Search", "Brands", "Insights", "Data Health", "Custom Query"]
    )

    with tab1:
        render_overview_tab()
    with tab2:
        render_search_tab()
    with tab3:
        render_brands_tab()
    with tab4:
        render_insights_tab()
    with tab5:
        render_data_health_tab()
    with tab6:
        render_query_tab()

"""Firebase Sync UI Component for GearGraph.

Provides a Streamlit interface for syncing GearGraph data to Firebase
gearBase collection via the GearGraph Sync API.
"""

import json
import os
import streamlit as st

from app.tools.firebase_sync import (
    export_full_gearbase,
    export_brands_for_firebase,
    export_products_for_firebase,
    export_deleted_items,
    clear_deleted_items,
)
from app.tools.geargraph_sync_client import (
    GearGraphSyncClient,
    SyncResponse,
    get_saved_sync_token,
    save_sync_token,
    clear_sync_token,
    sync_to_firebase,
    slugify,
)


def init_sync_state():
    """Initialize session state for the sync view."""
    if "sync_export_data" not in st.session_state:
        st.session_state.sync_export_data = None
    if "sync_api_response" not in st.session_state:
        st.session_state.sync_api_response = None
    if "sync_api_url" not in st.session_state:
        st.session_state.sync_api_url = os.getenv(
            "GEARGRAPH_SYNC_API_URL",
            "https://geargraph.gearshack.app/api/sync/changes"
        )


def render_firebase_sync_view():
    """Render the Firebase sync interface."""
    init_sync_state()

    st.header("Firebase gearBase Sync")
    st.caption(
        "Sync GearGraph data to Firebase for fast autocomplete in the GearShack app"
    )

    # Tabs for different operations
    tab_api_sync, tab_export, tab_preview, tab_upload, tab_settings = st.tabs([
        "Sync API",
        "Manual Export",
        "Preview JSON",
        "Upload to Firebase",
        "Settings",
    ])

    with tab_api_sync:
        render_api_sync_tab()

    with tab_export:
        render_export_tab()

    with tab_preview:
        render_preview_tab()

    with tab_upload:
        render_upload_tab()

    with tab_settings:
        render_settings_tab()


def render_api_sync_tab():
    """Render the API sync tab - the primary sync method."""
    st.subheader("GearGraph Sync API")
    st.caption("Pull data from GearGraph server and push to Firebase")

    # Check for API key
    api_key = os.getenv("GEARGRAPH_API_KEY")
    if not api_key:
        st.error(
            "GEARGRAPH_API_KEY not set. Please add it to your .env file."
        )
        st.code("GEARGRAPH_API_KEY=your_api_key_here", language="bash")
        return

    st.success("API key configured")

    # Show current sync status
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Sync Status")
        saved_token = get_saved_sync_token()

        if saved_token:
            st.info(f"Last sync token: `{saved_token[:20]}...`")
            st.caption("Next sync will be incremental (only changes)")
        else:
            st.warning("No sync token saved - next sync will be full")

    with col2:
        st.markdown("### Actions")

        if st.button("Fetch from API", type="primary", use_container_width=True):
            _fetch_from_api(api_key, incremental=bool(saved_token))

        if st.button("Force Full Sync", use_container_width=True):
            clear_sync_token()
            _fetch_from_api(api_key, incremental=False)

        if saved_token and st.button("Clear Sync Token", use_container_width=True):
            clear_sync_token()
            st.success("Sync token cleared - next sync will be full")
            st.rerun()

    # Show fetched data
    if st.session_state.sync_api_response:
        st.markdown("---")
        _render_api_response()


def _fetch_from_api(api_key: str, incremental: bool = True):
    """Fetch data from the GearGraph Sync API."""
    try:
        client = GearGraphSyncClient(api_key=api_key)

        since = get_saved_sync_token() if incremental else None
        sync_type = "incremental" if since else "full"

        with st.spinner(f"Fetching {sync_type} sync from GearGraph API..."):
            response = client.fetch_changes(since=since)

        st.session_state.sync_api_response = response
        st.success(
            f"Fetched {response.total_brands} brands, "
            f"{response.total_products} products"
        )

    except ValueError as e:
        st.error(f"API Error: {e}")
    except Exception as e:
        st.error(f"Failed to fetch: {e}")


def _render_api_response():
    """Render the API response data."""
    response: SyncResponse = st.session_state.sync_api_response

    st.markdown("### Fetched Data")

    # Summary stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Brands Added", len(response.brands_added))
    with col2:
        st.metric("Brands Updated", len(response.brands_updated))
    with col3:
        st.metric("Products Added", len(response.products_added))
    with col4:
        st.metric("Products Updated", len(response.products_updated))

    if response.total_deleted > 0:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Brands Deleted", len(response.brands_deleted))
        with col2:
            st.metric("Products Deleted", len(response.products_deleted))

    st.caption(f"Sync type: {'Full' if response.full_sync else 'Incremental'}")
    st.caption(f"Next sync token: `{response.next_sync_token[:30]}...`")

    # Browse data
    with st.expander("Browse Brands", expanded=False):
        all_brands = response.brands_added + response.brands_updated
        if all_brands:
            for brand in all_brands[:20]:
                st.markdown(f"**{brand.name}** ({brand.product_count} products)")
                if brand.website:
                    st.caption(f"  {brand.website}")
            if len(all_brands) > 20:
                st.caption(f"... and {len(all_brands) - 20} more")
        else:
            st.caption("No brands in this sync")

    with st.expander("Browse Products", expanded=False):
        all_products = response.products_added + response.products_updated
        if all_products:
            # Group by brand
            by_brand = {}
            for p in all_products:
                if p.brand_name not in by_brand:
                    by_brand[p.brand_name] = []
                by_brand[p.brand_name].append(p)

            for brand_name, products in sorted(by_brand.items())[:10]:
                st.markdown(f"**{brand_name}** ({len(products)} products)")
                for p in products[:5]:
                    st.caption(f"  - {p.name} ({p.category or 'no category'})")
                if len(products) > 5:
                    st.caption(f"  ... and {len(products) - 5} more")

            if len(by_brand) > 10:
                st.caption(f"... and {len(by_brand) - 10} more brands")
        else:
            st.caption("No products in this sync")

    # Push to Firebase button
    st.markdown("---")
    st.markdown("### Push to Firebase")

    service_account_path = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT",
        "firebase-service-account.json"
    )

    if not os.path.exists(service_account_path):
        st.warning(
            f"Firebase service account not found at `{service_account_path}`. "
            "Add the service account JSON to enable uploads."
        )
        return

    st.success("Firebase credentials found")

    col1, col2 = st.columns(2)
    with col1:
        save_token = st.checkbox("Save sync token after upload", value=True)
    with col2:
        pass  # Reserved for future options

    if st.button(
        f"Push {response.total_brands} brands & {response.total_products} products to Firebase",
        type="primary",
        use_container_width=True,
    ):
        with st.spinner("Uploading to Firebase..."):
            try:
                stats = sync_to_firebase(response, service_account_path)

                st.success("Upload complete!")
                st.write(f"- Brands written: {stats['brands_written']}")
                st.write(f"- Products written: {stats['products_written']}")
                st.write(f"- Items deleted: {stats['items_deleted']}")

                if save_token and response.next_sync_token:
                    save_sync_token(response.next_sync_token)
                    st.info("Sync token saved for next incremental sync")

            except Exception as e:
                st.error(f"Upload failed: {e}")


def render_export_tab():
    """Render the manual data export tab."""
    st.subheader("Manual Export from GearGraph")
    st.caption("Export directly from local Memgraph database")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Quick Stats")

        try:
            brands = export_brands_for_firebase()
            products_by_brand = export_products_for_firebase()
            deleted = export_deleted_items()

            total_products = sum(len(prods) for prods in products_by_brand.values())
            total_variants = sum(
                sum(len(p.get("variants", [])) for p in prods)
                for prods in products_by_brand.values()
            )

            st.metric("Brands", len(brands))
            st.metric("Products", total_products)
            st.metric("Variants", total_variants)
            st.metric("Pending Deletions", len(deleted["brands"]) + len(deleted["products"]))

        except Exception as e:
            st.error(f"Failed to get stats: {e}")

    with col2:
        st.markdown("### Export Actions")

        if st.button("Generate Full Export", type="primary", use_container_width=True):
            with st.spinner("Exporting data from GearGraph..."):
                try:
                    export_data = export_full_gearbase()
                    st.session_state.sync_export_data = export_data
                    st.success(
                        f"Export complete: {export_data['metadata']['brand_count']} brands, "
                        f"{export_data['metadata']['product_count']} products"
                    )
                except Exception as e:
                    st.error(f"Export failed: {e}")

        st.markdown("---")

        if st.session_state.sync_export_data:
            json_str = json.dumps(st.session_state.sync_export_data, indent=2)

            st.download_button(
                "Download JSON",
                data=json_str,
                file_name="gearbase_export.json",
                mime="application/json",
                use_container_width=True,
            )


def render_preview_tab():
    """Render the JSON preview tab."""
    st.subheader("JSON Preview")

    if not st.session_state.sync_export_data:
        st.info("Generate a manual export first to preview the JSON data.")
        return

    data = st.session_state.sync_export_data

    # Show metadata
    st.markdown("### Export Metadata")
    metadata = data.get("metadata", {})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Brands", metadata.get("brand_count", 0))
    col2.metric("Products", metadata.get("product_count", 0))
    col3.metric("Deleted Brands", metadata.get("deleted_brand_count", 0))
    col4.metric("Deleted Products", metadata.get("deleted_product_count", 0))

    st.caption(f"Exported at: {metadata.get('exported_at', 'Unknown')}")

    # Brand selector
    st.markdown("### Browse Data")

    brands_data = data.get("brands", {})
    brand_slugs = list(brands_data.keys())

    if not brand_slugs:
        st.warning("No brands in export data.")
        return

    selected_brand = st.selectbox(
        "Select Brand",
        brand_slugs,
        format_func=lambda x: brands_data[x].get("brand_name", x),
    )

    if selected_brand:
        brand = brands_data[selected_brand]

        with st.expander("Brand Details", expanded=True):
            st.json({
                "slug": selected_brand,
                "brand_name": brand.get("brand_name"),
                "brand_aliases": brand.get("brand_aliases"),
                "brand_logo": brand.get("brand_logo"),
                "brand_url": brand.get("brand_url"),
            })

        products = brand.get("products", {})
        st.markdown(f"**Products ({len(products)})**")

        if products:
            product_slugs = list(products.keys())
            selected_product = st.selectbox(
                "Select Product",
                product_slugs,
                format_func=lambda x: products[x].get("product_name", x),
            )

            if selected_product:
                product = products[selected_product]

                with st.expander("Product Details", expanded=True):
                    product_display = {k: v for k, v in product.items() if k != "variants"}
                    st.json(product_display)

                variants = product.get("variants", [])
                if variants:
                    st.markdown(f"**Variants ({len(variants)})**")
                    for variant in variants:
                        with st.expander(variant.get("product_name", "Unknown Variant")):
                            st.json(variant)


def render_upload_tab():
    """Render the Firebase upload tab for manual exports."""
    st.subheader("Upload Manual Export to Firebase")

    if not st.session_state.sync_export_data:
        st.info("Generate a manual export first before uploading to Firebase.")
        st.caption("Or use the 'Sync API' tab for the recommended sync method.")
        return

    data = st.session_state.sync_export_data
    metadata = data.get("metadata", {})

    st.markdown("### Export Summary")
    st.write(f"- **Brands:** {metadata.get('brand_count', 0)}")
    st.write(f"- **Products:** {metadata.get('product_count', 0)}")
    st.write(f"- **Pending Deletions:** {metadata.get('deleted_brand_count', 0) + metadata.get('deleted_product_count', 0)}")

    st.markdown("---")

    service_account_path = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT",
        "firebase-service-account.json"
    )
    has_credentials = os.path.exists(service_account_path)

    if not has_credentials:
        st.warning(
            f"Firebase service account not found at `{service_account_path}`. "
            "Please add the service account JSON file to enable uploads."
        )
        return

    st.success("Firebase credentials found")

    st.markdown("### Upload Options")

    col1, col2 = st.columns(2)
    with col1:
        upload_brands = st.checkbox("Upload Brands", value=True)
        upload_products = st.checkbox("Upload Products", value=True)
    with col2:
        process_deletes = st.checkbox("Process Deletions", value=True)
        clear_after_sync = st.checkbox("Clear deleted items after sync", value=False)

    st.markdown("---")

    if st.button("Upload to Firebase", type="primary", use_container_width=True):
        with st.spinner("Uploading to Firebase..."):
            try:
                stats = _upload_manual_export_to_firebase(
                    data,
                    service_account_path,
                    upload_brands=upload_brands,
                    upload_products=upload_products,
                    process_deletes=process_deletes,
                )

                st.success("Upload complete!")
                st.write(f"- Brands written: {stats.get('brands_written', 0)}")
                st.write(f"- Products written: {stats.get('products_written', 0)}")
                st.write(f"- Items deleted: {stats.get('items_deleted', 0)}")

                if clear_after_sync and stats.get("items_deleted", 0) > 0:
                    cleared = clear_deleted_items()
                    st.info(f"Cleared {cleared} soft-deleted items from GearGraph")

            except Exception as e:
                st.error(f"Upload failed: {e}")


def _upload_manual_export_to_firebase(
    data: dict,
    service_account_path: str,
    upload_brands: bool = True,
    upload_products: bool = True,
    process_deletes: bool = True,
) -> dict:
    """Upload manual export data to Firebase Firestore."""
    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    stats = {"brands_written": 0, "products_written": 0, "items_deleted": 0}

    brands_data = data.get("brands", {})
    deleted = data.get("deleted", {})

    for brand_slug, brand in brands_data.items():
        brand_ref = db.collection("gearBase").document(brand_slug)

        if upload_brands:
            brand_doc = {
                "brand_name": brand.get("brand_name", ""),
                "brand_aliases": brand.get("brand_aliases", []),
                "brand_logo": brand.get("brand_logo", ""),
                "brand_url": brand.get("brand_url", ""),
            }
            brand_ref.set(brand_doc, merge=True)
            stats["brands_written"] += 1

        if upload_products:
            products = brand.get("products", {})
            for product_slug, product in products.items():
                product_ref = brand_ref.collection("products").document(product_slug)
                product_doc = {k: v for k, v in product.items() if k != "variants"}
                product_ref.set(product_doc, merge=True)
                stats["products_written"] += 1

                for variant in product.get("variants", []):
                    variant_slug = variant.get("slug", "unknown")
                    variant_ref = product_ref.collection("variants").document(variant_slug)
                    variant_ref.set(variant, merge=True)

    if process_deletes:
        for brand_slug in deleted.get("brands", []):
            try:
                db.collection("gearBase").document(brand_slug).delete()
                stats["items_deleted"] += 1
            except Exception:
                pass

        for item in deleted.get("products", []):
            try:
                db.collection("gearBase").document(item["brand_slug"]) \
                    .collection("products").document(item["product_slug"]).delete()
                stats["items_deleted"] += 1
            except Exception:
                pass

    return stats


def render_settings_tab():
    """Render the settings tab."""
    st.subheader("Sync Settings")

    # API configuration
    st.markdown("### GearGraph Sync API")

    api_key = os.getenv("GEARGRAPH_API_KEY")
    if api_key:
        st.success("API key configured")
        st.text_input("API Key", value=f"{api_key[:8]}...{api_key[-4:]}", disabled=True)
    else:
        st.warning("GEARGRAPH_API_KEY not set")
        st.code("GEARGRAPH_API_KEY=your_key_here", language="bash")

    api_url = st.text_input(
        "Sync API URL",
        value=st.session_state.sync_api_url,
        help="URL of the GearGraph sync API endpoint"
    )
    if api_url != st.session_state.sync_api_url:
        st.session_state.sync_api_url = api_url
        st.success("API URL updated")

    st.markdown("---")

    # Firebase configuration
    st.markdown("### Firebase Configuration")

    service_account_path = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT",
        "firebase-service-account.json"
    )

    st.text_input(
        "Service Account Path",
        value=service_account_path,
        disabled=True,
        help="Set via FIREBASE_SERVICE_ACCOUNT environment variable"
    )

    if os.path.exists(service_account_path):
        st.success("Service account file found")
        try:
            with open(service_account_path) as f:
                sa_data = json.load(f)
            st.caption(f"Project ID: {sa_data.get('project_id', 'Unknown')}")
        except Exception:
            pass
    else:
        st.warning("Service account file not found")

    st.markdown("---")

    # Sync token management
    st.markdown("### Sync Token")

    saved_token = get_saved_sync_token()
    if saved_token:
        st.info(f"Current token: `{saved_token}`")
        if st.button("Clear Sync Token"):
            clear_sync_token()
            st.success("Token cleared - next sync will be full")
            st.rerun()
    else:
        st.caption("No sync token saved")

    st.markdown("---")

    # Danger zone
    st.markdown("### Danger Zone")
    st.warning("These actions cannot be undone!")

    if st.button("Clear All Soft-Deleted Items from GearGraph", type="secondary"):
        with st.spinner("Clearing soft-deleted items..."):
            try:
                count = clear_deleted_items()
                st.success(f"Permanently deleted {count} items from GearGraph")
            except Exception as e:
                st.error(f"Failed to clear deleted items: {e}")

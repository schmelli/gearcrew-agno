"""Firebase Sync UI Component for GearGraph.

Provides a Streamlit interface for exporting GearGraph data to Firebase
gearBase collection for autocomplete functionality in the GearShack app.
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


def init_sync_state():
    """Initialize session state for the sync view."""
    if "sync_export_data" not in st.session_state:
        st.session_state.sync_export_data = None
    if "sync_api_url" not in st.session_state:
        st.session_state.sync_api_url = os.getenv(
            "GEARBASE_SYNC_API_URL",
            "https://geargraph.gearshack.app/api/sync/gearbase"
        )


def render_firebase_sync_view():
    """Render the Firebase sync interface."""
    init_sync_state()

    st.header("Firebase gearBase Sync")
    st.caption(
        "Export GearGraph data to Firebase for fast autocomplete in the GearShack app"
    )

    # Tabs for different operations
    tab_export, tab_preview, tab_upload, tab_settings = st.tabs([
        "Export Data",
        "Preview JSON",
        "Upload to Firebase",
        "Settings",
    ])

    with tab_export:
        render_export_tab()

    with tab_preview:
        render_preview_tab()

    with tab_upload:
        render_upload_tab()

    with tab_settings:
        render_settings_tab()


def render_export_tab():
    """Render the data export tab."""
    st.subheader("Export from GearGraph")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Quick Stats")

        # Show current counts
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

        if st.button("Fetch from API Endpoint", use_container_width=True):
            api_url = st.session_state.sync_api_url
            with st.spinner(f"Fetching from {api_url}..."):
                try:
                    import httpx
                    response = httpx.get(api_url, timeout=60.0)
                    response.raise_for_status()
                    export_data = response.json()
                    st.session_state.sync_export_data = export_data
                    st.success("Fetched data from API endpoint")
                except Exception as e:
                    st.error(f"Failed to fetch from API: {e}")

        st.markdown("---")

        # Download buttons
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
        st.info("Generate an export first to preview the JSON data.")
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

        # Brand details
        with st.expander("Brand Details", expanded=True):
            st.json({
                "slug": selected_brand,
                "brand_name": brand.get("brand_name"),
                "brand_aliases": brand.get("brand_aliases"),
                "brand_logo": brand.get("brand_logo"),
                "brand_url": brand.get("brand_url"),
            })

        # Products
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
                    # Show product without variants first
                    product_display = {k: v for k, v in product.items() if k != "variants"}
                    st.json(product_display)

                # Show variants if any
                variants = product.get("variants", [])
                if variants:
                    st.markdown(f"**Variants ({len(variants)})**")
                    for variant in variants:
                        with st.expander(variant.get("product_name", "Unknown Variant")):
                            st.json(variant)

    # Show deleted items
    deleted = data.get("deleted", {})
    if deleted.get("brands") or deleted.get("products"):
        st.markdown("### Pending Deletions")

        if deleted.get("brands"):
            st.markdown(f"**Brands to delete ({len(deleted['brands'])})**")
            st.code(", ".join(deleted["brands"]))

        if deleted.get("products"):
            st.markdown(f"**Products to delete ({len(deleted['products'])})**")
            for item in deleted["products"][:10]:  # Show first 10
                st.caption(f"- {item['brand_slug']}/{item['product_slug']}")
            if len(deleted["products"]) > 10:
                st.caption(f"... and {len(deleted['products']) - 10} more")


def render_upload_tab():
    """Render the Firebase upload tab."""
    st.subheader("Upload to Firebase")

    if not st.session_state.sync_export_data:
        st.info("Generate an export first before uploading to Firebase.")
        return

    data = st.session_state.sync_export_data
    metadata = data.get("metadata", {})

    st.markdown("### Export Summary")
    st.write(f"- **Brands:** {metadata.get('brand_count', 0)}")
    st.write(f"- **Products:** {metadata.get('product_count', 0)}")
    st.write(f"- **Pending Deletions:** {metadata.get('deleted_brand_count', 0) + metadata.get('deleted_product_count', 0)}")

    st.markdown("---")

    # Check for Firebase credentials
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
        st.markdown("""
        **To enable Firebase uploads:**
        1. Download your Firebase service account JSON from the Firebase Console
        2. Save it as `firebase-service-account.json` in the project root
        3. Or set `FIREBASE_SERVICE_ACCOUNT` environment variable to the path
        """)
        return

    st.success("Firebase credentials found")

    # Upload options
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
                stats = _upload_to_firebase(
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


def _upload_to_firebase(
    data: dict,
    service_account_path: str,
    upload_brands: bool = True,
    upload_products: bool = True,
    process_deletes: bool = True,
) -> dict:
    """Upload export data to Firebase Firestore.

    Args:
        data: Export data from export_full_gearbase()
        service_account_path: Path to Firebase service account JSON
        upload_brands: Whether to upload brand data
        upload_products: Whether to upload product data
        process_deletes: Whether to process deletions

    Returns:
        Dict with upload statistics
    """
    import firebase_admin
    from firebase_admin import credentials, firestore

    # Initialize Firebase if not already done
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    stats = {"brands_written": 0, "products_written": 0, "items_deleted": 0}

    brands_data = data.get("brands", {})
    deleted = data.get("deleted", {})

    # Upload brands and products
    for brand_slug, brand in brands_data.items():
        brand_ref = db.collection("gearBase").document(brand_slug)

        if upload_brands:
            # Write brand data (excluding products)
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

                # Write product data (excluding variants)
                product_doc = {k: v for k, v in product.items() if k != "variants"}
                product_ref.set(product_doc, merge=True)
                stats["products_written"] += 1

                # Write variants if any
                variants = product.get("variants", [])
                for variant in variants:
                    variant_slug = variant.get("slug", "unknown")
                    variant_ref = product_ref.collection("variants").document(variant_slug)
                    variant_ref.set(variant, merge=True)

    # Process deletions
    if process_deletes:
        # Delete brands
        for brand_slug in deleted.get("brands", []):
            try:
                db.collection("gearBase").document(brand_slug).delete()
                stats["items_deleted"] += 1
            except Exception:
                pass

        # Delete products
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

    # API endpoint configuration
    st.markdown("### API Endpoint")
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

        # Try to read and show project info
        try:
            with open(service_account_path) as f:
                sa_data = json.load(f)
            st.caption(f"Project ID: {sa_data.get('project_id', 'Unknown')}")
        except Exception:
            pass
    else:
        st.warning("Service account file not found")

    st.markdown("---")

    # Danger zone
    st.markdown("### Danger Zone")
    st.warning("These actions cannot be undone!")

    if st.button("Clear All Soft-Deleted Items", type="secondary"):
        with st.spinner("Clearing soft-deleted items..."):
            try:
                count = clear_deleted_items()
                st.success(f"Permanently deleted {count} items from GearGraph")
            except Exception as e:
                st.error(f"Failed to clear deleted items: {e}")

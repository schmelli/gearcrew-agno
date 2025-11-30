"""Archive View UI Component for GearCrew.

Displays previously processed video sources with thumbnails,
titles, and extraction summaries.
"""

import streamlit as st
from datetime import datetime
from typing import Optional

from app.db.memgraph import (
    get_all_video_sources,
    get_gear_from_source,
    check_source_exists,
)


def format_datetime(dt_value) -> str:
    """Format a datetime value for display."""
    if dt_value is None:
        return "Unknown"

    if isinstance(dt_value, str):
        return dt_value

    if hasattr(dt_value, "strftime"):
        return dt_value.strftime("%Y-%m-%d %H:%M")

    return str(dt_value)


def get_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    if not url:
        return None

    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0].split("&")[0]

    if "youtube.com" in url:
        if "watch?v=" in url:
            import re
            match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
            return match.group(1) if match else None
        if "/embed/" in url:
            return url.split("/embed/")[-1].split("?")[0]

    return None


def get_thumbnail_url(source: dict) -> Optional[str]:
    """Get thumbnail URL for a source."""
    if source.get("thumbnail_url"):
        return source["thumbnail_url"]

    video_id = get_youtube_video_id(source.get("url", ""))
    if video_id:
        return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    return None


def render_source_card(source: dict, expanded: bool = False):
    """Render a single source card with thumbnail and info."""
    url = source.get("url", "")
    title = source.get("title", "Unknown Title")
    channel = source.get("channel", "Unknown Channel")
    processed_at = format_datetime(source.get("processed_at"))
    gear_count = source.get("gear_items_found", 0)
    insights_count = source.get("insights_found", 0)
    thumbnail_url = get_thumbnail_url(source)

    with st.container():
        col1, col2 = st.columns([1, 3])

        with col1:
            if thumbnail_url:
                st.image(thumbnail_url, use_container_width=True)
            else:
                st.markdown("**No Thumbnail**")

        with col2:
            st.markdown(f"### {title}")
            st.caption(f"Channel: {channel}")
            st.caption(f"Processed: {processed_at}")

            metric_cols = st.columns(3)
            with metric_cols[0]:
                st.metric("Gear Items", gear_count)
            with metric_cols[1]:
                st.metric("Insights", insights_count)
            with metric_cols[2]:
                st.markdown(f"[Open Source]({url})")

        # Expandable section for full details
        with st.expander("View Extraction Details", expanded=expanded):
            summary = source.get("extraction_summary", "No summary available")
            st.markdown(summary)

            # Show extracted gear items
            gear_items = get_gear_from_source(url)
            if gear_items:
                st.markdown("---")
                st.markdown("#### Extracted Gear Items")
                for item in gear_items:
                    weight_str = ""
                    if item.get("weight_grams"):
                        weight_str = f" ({item['weight_grams']}g)"
                    price_str = ""
                    if item.get("price_usd"):
                        price_str = f" - ${item['price_usd']}"
                    st.markdown(
                        f"- **{item.get('name')}** by {item.get('brand')} "
                        f"[{item.get('category', 'unknown')}]{weight_str}{price_str}"
                    )

        st.markdown("---")


def render_archive_view():
    """Render the main archive view page."""
    st.header("Video Archive")
    st.caption("Previously analyzed videos and their extraction results")

    # Filters
    col1, col2 = st.columns([3, 1])
    with col1:
        search_filter = st.text_input(
            "Search by title or channel",
            placeholder="Enter search term...",
            key="archive_search"
        )
    with col2:
        sort_order = st.selectbox(
            "Sort by",
            ["Most Recent", "Most Gear Items", "Most Insights"],
            key="archive_sort"
        )

    # Fetch sources
    sources = get_all_video_sources(limit=100)

    if not sources:
        st.info(
            "No videos have been analyzed yet. "
            "Go to the Agent Chat and paste a YouTube URL to get started!"
        )
        return

    # Filter sources
    if search_filter:
        search_lower = search_filter.lower()
        sources = [
            s for s in sources
            if search_lower in (s.get("title") or "").lower()
            or search_lower in (s.get("channel") or "").lower()
        ]

    # Sort sources
    if sort_order == "Most Gear Items":
        sources = sorted(
            sources, key=lambda x: x.get("gear_items_found", 0), reverse=True
        )
    elif sort_order == "Most Insights":
        sources = sorted(
            sources, key=lambda x: x.get("insights_found", 0), reverse=True
        )
    # Default is already sorted by most recent from the query

    # Display stats
    st.markdown(f"**{len(sources)} videos in archive**")

    total_gear = sum(s.get("gear_items_found", 0) for s in sources)
    total_insights = sum(s.get("insights_found", 0) for s in sources)

    stats_cols = st.columns(3)
    with stats_cols[0]:
        st.metric("Total Videos", len(sources))
    with stats_cols[1]:
        st.metric("Total Gear Items", total_gear)
    with stats_cols[2]:
        st.metric("Total Insights", total_insights)

    st.markdown("---")

    # Render source cards
    for source in sources:
        render_source_card(source)

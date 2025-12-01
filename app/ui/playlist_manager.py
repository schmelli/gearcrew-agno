"""Playlist Manager UI Component for GearCrew.

Allows users to:
- Load a YouTube playlist
- See processing status for each video
- Process videos one by one with individual buttons
- Add custom context for extraction
- View processed videos with their extraction results
"""

import streamlit as st
from typing import Optional

from app.tools.youtube import get_playlist_videos, get_playlist_info
from app.db.memgraph import check_source_exists, get_gear_from_source
from app.agent import extract_gear_with_context


def get_youtube_thumbnail(video_id: str) -> str:
    """Get YouTube thumbnail URL for a video ID."""
    return f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"


def format_duration(seconds: Optional[int]) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if not seconds:
        return "--:--"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_datetime(dt_value) -> str:
    """Format a datetime value for display."""
    if dt_value is None:
        return "Unknown"
    if isinstance(dt_value, str):
        return dt_value
    if hasattr(dt_value, "strftime"):
        return dt_value.strftime("%Y-%m-%d %H:%M")
    return str(dt_value)


def get_source_data(url: str) -> Optional[dict]:
    """Get source data from database if processed."""
    return check_source_exists(url)


def init_session_state():
    """Initialize session state for playlist manager."""
    if "playlist_videos" not in st.session_state:
        st.session_state.playlist_videos = []
    if "playlist_info" not in st.session_state:
        st.session_state.playlist_info = None
    if "processing_video_id" not in st.session_state:
        st.session_state.processing_video_id = None
    if "extraction_context" not in st.session_state:
        st.session_state.extraction_context = ""
    if "video_contexts" not in st.session_state:
        st.session_state.video_contexts = {}


def load_playlist(playlist_url: str):
    """Load playlist data and check processing status for each video."""
    try:
        with st.spinner("Loading playlist..."):
            info = get_playlist_info(playlist_url)
            videos = get_playlist_videos(playlist_url)

            # Check processing status for each video
            for video in videos:
                source_data = get_source_data(video["url"])
                video["is_processed"] = source_data is not None
                video["source_data"] = source_data

            st.session_state.playlist_info = info
            st.session_state.playlist_videos = videos

            return True
    except Exception as e:
        st.error(f"Failed to load playlist: {str(e)}")
        return False


def render_unprocessed_video(video: dict):
    """Render an unprocessed video with Process button."""
    video_id = video.get("video_id", "")
    title = video.get("title", "Unknown")
    url = video.get("url", "")
    duration = video.get("duration")
    channel = video.get("channel", "Unknown")

    with st.container():
        cols = st.columns([1.5, 4, 1, 1.5])

        # Thumbnail
        with cols[0]:
            if video_id:
                st.image(get_youtube_thumbnail(video_id), width="stretch")

        # Title and channel
        with cols[1]:
            st.markdown(f"**{title}**")
            st.caption(f"{channel} | {format_duration(duration)} | [Open]({url})")

            # Show context note indicator if exists
            if video_id in st.session_state.video_contexts:
                st.caption(f"Note: {st.session_state.video_contexts[video_id][:50]}...")

        # Add Note button
        with cols[2]:
            video_context = st.session_state.video_contexts.get(video_id, "")
            btn_label = "Edit Note" if video_context else "Add Note"
            if st.button(btn_label, key=f"note_{video_id}", type="secondary"):
                st.session_state[f"show_note_{video_id}"] = True

        # Process button
        with cols[3]:
            if st.session_state.processing_video_id == video_id:
                st.info("Processing...")
            else:
                if st.button("Process", key=f"process_{video_id}", type="primary"):
                    st.session_state.processing_video_id = video_id
                    st.rerun()

        # Show note input if expanded
        if st.session_state.get(f"show_note_{video_id}", False):
            new_context = st.text_area(
                "Context note for this video:",
                value=st.session_state.video_contexts.get(video_id, ""),
                key=f"note_input_{video_id}",
                height=80,
                placeholder="E.g., 'This reviews the 2023 version, not the current model'",
            )
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Save Note", key=f"save_note_{video_id}"):
                    st.session_state.video_contexts[video_id] = new_context
                    st.session_state[f"show_note_{video_id}"] = False
                    st.rerun()
            with col_b:
                if st.button("Cancel", key=f"cancel_note_{video_id}"):
                    st.session_state[f"show_note_{video_id}"] = False
                    st.rerun()

        st.markdown("---")


def render_processed_video(video: dict):
    """Render a processed video in archive style with extraction details."""
    video_id = video.get("video_id", "")
    title = video.get("title", "Unknown")
    url = video.get("url", "")
    duration = video.get("duration")
    channel = video.get("channel", "Unknown")
    source_data = video.get("source_data", {}) or {}

    processed_at = format_datetime(source_data.get("processed_at"))
    gear_count = source_data.get("gear_items_found", 0)
    insights_count = source_data.get("insights_found", 0)

    with st.container():
        cols = st.columns([1.5, 4])

        # Thumbnail
        with cols[0]:
            if video_id:
                st.image(get_youtube_thumbnail(video_id), width="stretch")

        # Info
        with cols[1]:
            st.markdown(f"**{title}** ✅")
            st.caption(f"{channel} | {format_duration(duration)} | [Open]({url})")
            st.caption(f"Processed: {processed_at}")

            # Metrics row
            metric_cols = st.columns(3)
            with metric_cols[0]:
                st.metric("Gear Items", gear_count)
            with metric_cols[1]:
                st.metric("Insights", insights_count)

        # Expandable extraction details
        with st.expander("View Extraction Details"):
            summary = source_data.get("extraction_summary", "No summary available")
            st.markdown(summary)

            # Show extracted gear items
            gear_items = get_gear_from_source(url)
            if gear_items:
                st.markdown("---")
                st.markdown("**Extracted Gear Items:**")
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


def process_video(video: dict):
    """Process a single video and show results."""
    import logging
    logger = logging.getLogger(__name__)

    video_id = video.get("video_id", "")
    url = video.get("url", "")
    title = video.get("title", "")

    # Combine global context with video-specific context
    global_context = st.session_state.extraction_context
    video_context = st.session_state.video_contexts.get(video_id, "")
    combined_context = "\n\n".join(filter(None, [global_context, video_context]))

    # Store result in session state so it persists across reruns
    result_key = f"process_result_{video_id}"

    try:
        with st.spinner(f"Processing: {title}..."):
            logger.info(f"Starting extraction for: {title} ({url})")

            result = extract_gear_with_context(
                source_url=url,
                user_context=combined_context,
                video_title=title,
            )

            logger.info(f"Extraction complete. Result length: {len(result) if result else 0}")

            if not result:
                st.warning(f"Extraction returned empty result for: {title}")
                result = "No content extracted from this video."

            # Update video status
            for v in st.session_state.playlist_videos:
                if v.get("video_id") == video_id:
                    v["is_processed"] = True
                    v["source_data"] = get_source_data(url)
                    break

            # Store result in session state
            st.session_state[result_key] = result

            st.success(f"Successfully processed: {title}")

    except Exception as e:
        logger.error(f"Failed to process {title}: {str(e)}", exc_info=True)
        st.error(f"Failed to process {title}: {str(e)}")
        st.session_state[result_key] = f"Error: {str(e)}"

    # Show result (outside the try block so it shows even after errors)
    if result_key in st.session_state:
        with st.expander("View Extraction Result", expanded=True):
            st.markdown(st.session_state[result_key])

    # Clear processing state
    st.session_state.processing_video_id = None


def render_playlist_manager():
    """Render the main playlist manager view."""
    init_session_state()

    st.header("Playlist Manager")
    st.caption("Load a YouTube playlist and process videos one by one")

    # Playlist URL input
    col1, col2 = st.columns([4, 1])
    with col1:
        playlist_url = st.text_input(
            "YouTube Playlist URL",
            placeholder="https://www.youtube.com/playlist?list=...",
            key="playlist_url_input",
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        load_clicked = st.button("Load Playlist", type="primary")

    if load_clicked and playlist_url:
        load_playlist(playlist_url)

    # Check if we need to process a video
    if st.session_state.processing_video_id:
        video = next(
            (v for v in st.session_state.playlist_videos
             if v.get("video_id") == st.session_state.processing_video_id),
            None
        )
        if video:
            process_video(video)
            # Don't rerun immediately - let the user see the results
            # The processing_video_id is cleared in process_video()

    # Show playlist info and videos
    if st.session_state.playlist_info:
        info = st.session_state.playlist_info
        videos = st.session_state.playlist_videos

        st.markdown("---")

        # Playlist header
        st.subheader(info.get("title", "Playlist"))
        st.caption(f"Channel: {info.get('channel', 'Unknown')}")

        # Stats
        total = len(videos)
        processed = sum(1 for v in videos if v.get("is_processed"))
        unprocessed = total - processed

        stat_cols = st.columns(3)
        with stat_cols[0]:
            st.metric("Total Videos", total)
        with stat_cols[1]:
            st.metric("Processed", processed)
        with stat_cols[2]:
            st.metric("Remaining", unprocessed)

        st.markdown("---")

        # Global context input
        st.markdown("### Extraction Context")
        st.caption(
            "Add notes that apply to ALL videos during extraction. "
            "You can also add per-video notes using 'Add Note'."
        )
        st.session_state.extraction_context = st.text_area(
            "Global context for all extractions",
            value=st.session_state.extraction_context,
            height=80,
            placeholder="E.g., 'Focus on ultralight gear. Ignore sponsored segments.'",
            key="global_context_input",
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Show processed toggle
        show_processed = st.checkbox("Show processed videos", value=True)

        st.markdown("---")

        # Separate videos into processed and unprocessed
        unprocessed_videos = [v for v in videos if not v.get("is_processed")]
        processed_videos = [v for v in videos if v.get("is_processed")]

        # Render unprocessed videos first
        if unprocessed_videos:
            st.markdown(f"### Unprocessed Videos ({len(unprocessed_videos)})")
            for video in unprocessed_videos:
                render_unprocessed_video(video)

        # Render processed videos if toggle is on
        if show_processed and processed_videos:
            st.markdown(f"### Processed Videos ({len(processed_videos)})")
            for video in processed_videos:
                render_processed_video(video)
        elif not unprocessed_videos and not show_processed:
            st.success("All videos have been processed!")

"""Playlist Manager UI Component for GearCrew.

Allows users to:
- Load a YouTube playlist
- See processing status for each video
- Select videos to process
- Add custom context for extraction
- Process videos one by one with progress tracking
"""

import streamlit as st
from typing import Optional

from app.tools.youtube import get_playlist_videos, get_playlist_info
from app.tools.geargraph import check_video_already_processed
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


def check_processing_status(url: str) -> bool:
    """Check if a video has been processed. Returns True if processed."""
    result = check_video_already_processed(url)
    return "already been processed" in result


def init_session_state():
    """Initialize session state for playlist manager."""
    if "playlist_videos" not in st.session_state:
        st.session_state.playlist_videos = []
    if "playlist_info" not in st.session_state:
        st.session_state.playlist_info = None
    if "selected_videos" not in st.session_state:
        st.session_state.selected_videos = set()
    if "processing_video" not in st.session_state:
        st.session_state.processing_video = None
    if "extraction_context" not in st.session_state:
        st.session_state.extraction_context = ""
    if "extraction_results" not in st.session_state:
        st.session_state.extraction_results = {}
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
                video["is_processed"] = check_processing_status(video["url"])

            st.session_state.playlist_info = info
            st.session_state.playlist_videos = videos
            st.session_state.selected_videos = set()

            return True
    except Exception as e:
        st.error(f"Failed to load playlist: {str(e)}")
        return False


def render_video_card(video: dict, index: int):
    """Render a single video card with selection checkbox."""
    video_id = video.get("video_id", "")
    title = video.get("title", "Unknown")
    url = video.get("url", "")
    duration = video.get("duration")
    channel = video.get("channel", "Unknown")
    is_processed = video.get("is_processed", False)

    # Container for the video card
    with st.container():
        cols = st.columns([0.5, 1.5, 4, 1, 1])

        # Checkbox column
        with cols[0]:
            if is_processed:
                st.markdown("✅")
            else:
                is_selected = st.checkbox(
                    "Select",
                    value=video_id in st.session_state.selected_videos,
                    key=f"select_{video_id}",
                    label_visibility="collapsed",
                )
                if is_selected:
                    st.session_state.selected_videos.add(video_id)
                elif video_id in st.session_state.selected_videos:
                    st.session_state.selected_videos.discard(video_id)

        # Thumbnail column
        with cols[1]:
            if video_id:
                st.image(
                    get_youtube_thumbnail(video_id),
                    use_container_width=True,
                )

        # Title and channel
        with cols[2]:
            status_badge = "**[Processed]**" if is_processed else ""
            st.markdown(f"**{title}** {status_badge}")
            st.caption(f"{channel} | [Open]({url})")

        # Duration
        with cols[3]:
            st.markdown(format_duration(duration))

        # Per-video context button
        with cols[4]:
            if not is_processed:
                video_context = st.session_state.video_contexts.get(video_id, "")
                has_context = bool(video_context)
                btn_label = "Edit Note" if has_context else "Add Note"
                if st.button(btn_label, key=f"ctx_{video_id}", type="secondary"):
                    st.session_state[f"show_context_{video_id}"] = True

        # Show context input if expanded
        if st.session_state.get(f"show_context_{video_id}", False):
            with st.container():
                new_context = st.text_area(
                    f"Context for: {title[:50]}...",
                    value=st.session_state.video_contexts.get(video_id, ""),
                    key=f"context_input_{video_id}",
                    height=80,
                    placeholder="E.g., 'This reviews the 2023 version, not the current model'",
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Save", key=f"save_ctx_{video_id}"):
                        st.session_state.video_contexts[video_id] = new_context
                        st.session_state[f"show_context_{video_id}"] = False
                        st.rerun()
                with col_b:
                    if st.button("Cancel", key=f"cancel_ctx_{video_id}"):
                        st.session_state[f"show_context_{video_id}"] = False
                        st.rerun()


def process_single_video(video: dict, global_context: str = ""):
    """Process a single video with extraction."""
    video_id = video.get("video_id", "")
    url = video.get("url", "")
    title = video.get("title", "")

    # Combine global context with video-specific context
    video_context = st.session_state.video_contexts.get(video_id, "")
    combined_context = "\n\n".join(filter(None, [global_context, video_context]))

    try:
        result = extract_gear_with_context(
            source_url=url,
            user_context=combined_context,
            video_title=title,
        )
        st.session_state.extraction_results[video_id] = {
            "success": True,
            "result": result,
        }
        # Mark as processed in our local state
        for v in st.session_state.playlist_videos:
            if v.get("video_id") == video_id:
                v["is_processed"] = True
                break
        return True
    except Exception as e:
        st.session_state.extraction_results[video_id] = {
            "success": False,
            "error": str(e),
        }
        return False


def render_playlist_manager():
    """Render the main playlist manager view."""
    init_session_state()

    st.header("Playlist Manager")
    st.caption("Load a YouTube playlist, select videos, and extract gear information")

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
        selected = len(st.session_state.selected_videos)

        stat_cols = st.columns(4)
        with stat_cols[0]:
            st.metric("Total Videos", total)
        with stat_cols[1]:
            st.metric("Processed", processed)
        with stat_cols[2]:
            st.metric("Remaining", unprocessed)
        with stat_cols[3]:
            st.metric("Selected", selected)

        st.markdown("---")

        # Global context input
        st.markdown("### Extraction Context")
        st.caption(
            "Add notes that apply to ALL selected videos during extraction. "
            "You can also add per-video notes using the 'Add Note' button."
        )
        st.session_state.extraction_context = st.text_area(
            "Global context for all extractions",
            value=st.session_state.extraction_context,
            height=100,
            placeholder="E.g., 'Focus on ultralight gear mentioned. "
            "Ignore sponsored segments. The creator prefers cottage brands.'",
            key="global_context_input",
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Selection controls
        ctrl_cols = st.columns([1, 1, 1, 3])
        with ctrl_cols[0]:
            if st.button("Select All Unprocessed"):
                for v in videos:
                    if not v.get("is_processed"):
                        st.session_state.selected_videos.add(v.get("video_id"))
                st.rerun()
        with ctrl_cols[1]:
            if st.button("Clear Selection"):
                st.session_state.selected_videos = set()
                st.rerun()
        with ctrl_cols[2]:
            show_processed = st.checkbox("Show processed", value=True)

        st.markdown("---")

        # Video list header
        header_cols = st.columns([0.5, 1.5, 4, 1, 1])
        with header_cols[0]:
            st.markdown("**Select**")
        with header_cols[1]:
            st.markdown("**Thumbnail**")
        with header_cols[2]:
            st.markdown("**Title**")
        with header_cols[3]:
            st.markdown("**Duration**")
        with header_cols[4]:
            st.markdown("**Notes**")

        # Render video list
        for i, video in enumerate(videos):
            if not show_processed and video.get("is_processed"):
                continue
            render_video_card(video, i)

        st.markdown("---")

        # Process selected videos section
        if selected > 0:
            st.markdown("### Process Selected Videos")

            # Get selected video objects
            selected_videos = [
                v for v in videos
                if v.get("video_id") in st.session_state.selected_videos
            ]

            st.info(f"Ready to process {len(selected_videos)} video(s)")

            # Show list of selected
            with st.expander("View selected videos"):
                for v in selected_videos:
                    ctx_note = ""
                    if v.get("video_id") in st.session_state.video_contexts:
                        ctx_note = " (has notes)"
                    st.markdown(f"- {v.get('title')}{ctx_note}")

            # Process button
            if st.button("Start Processing", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, video in enumerate(selected_videos):
                    status_text.markdown(
                        f"Processing **{video.get('title', 'video')}**... "
                        f"({i + 1}/{len(selected_videos)})"
                    )

                    st.session_state.processing_video = video.get("video_id")
                    success = process_single_video(
                        video, st.session_state.extraction_context
                    )

                    progress_bar.progress((i + 1) / len(selected_videos))

                    # Show result
                    result_data = st.session_state.extraction_results.get(
                        video.get("video_id"), {}
                    )
                    if success:
                        with st.expander(
                            f"Results: {video.get('title')}", expanded=False
                        ):
                            st.markdown(result_data.get("result", "No output"))
                    else:
                        st.error(
                            f"Failed: {video.get('title')} - "
                            f"{result_data.get('error', 'Unknown error')}"
                        )

                status_text.markdown("**Processing complete!**")
                st.session_state.processing_video = None
                st.session_state.selected_videos = set()
                st.balloons()

        # Show recent extraction results
        if st.session_state.extraction_results:
            st.markdown("---")
            st.markdown("### Recent Extraction Results")
            for video_id, result_data in st.session_state.extraction_results.items():
                video = next(
                    (v for v in videos if v.get("video_id") == video_id), None
                )
                if video:
                    title = video.get("title", video_id)
                    if result_data.get("success"):
                        with st.expander(f"[Success] {title}"):
                            st.markdown(result_data.get("result", ""))
                    else:
                        with st.expander(f"[Failed] {title}"):
                            st.error(result_data.get("error", "Unknown error"))

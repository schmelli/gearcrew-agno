"""GearCrew Streamlit Dashboard.

Run with: streamlit run streamlit_app.py
"""

import os
import re
import time
from urllib.parse import urlparse, parse_qs

import streamlit as st
from dotenv import load_dotenv

# Import task queue at module level to avoid lazy import issues
from app.task_queue import get_task_queue, TaskStatus

load_dotenv()


def extract_youtube_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None

    # Handle youtu.be short URLs
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0].split("&")[0]

    # Handle standard youtube.com URLs
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc:
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        elif "/embed/" in parsed.path:
            return parsed.path.split("/embed/")[-1].split("?")[0]
        elif "/v/" in parsed.path:
            return parsed.path.split("/v/")[-1].split("?")[0]

    return None


def get_youtube_thumbnail(video_id: str, quality: str = "hq") -> str | None:
    """Get YouTube thumbnail URL for a video ID."""
    if not video_id:
        return None

    quality_map = {
        "max": "maxresdefault",
        "hq": "hqdefault",
        "mq": "mqdefault",
        "sd": "sddefault",
        "default": "default",
    }

    quality_suffix = quality_map.get(quality, "hqdefault")
    return f"https://img.youtube.com/vi/{video_id}/{quality_suffix}.jpg"


def is_youtube_url(text: str) -> str | None:
    """Check if text contains a YouTube URL and return it."""
    youtube_pattern = r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+)'
    match = re.search(youtube_pattern, text)
    return match.group(1) if match else None


def render_youtube_preview(url: str):
    """Render a YouTube video preview card."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return

    thumbnail_url = get_youtube_thumbnail(video_id, "hq")

    with st.container():
        col1, col2 = st.columns([1, 2])

        with col1:
            if thumbnail_url:
                st.image(thumbnail_url)

        with col2:
            st.markdown("**Analyzing YouTube Video**")
            st.caption(f"Video ID: `{video_id}`")
            st.markdown(f"[Open on YouTube]({url})")

            # Show oembed info if available
            try:
                import urllib.request
                import json

                oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
                with urllib.request.urlopen(oembed_url, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    st.markdown(f"**{data.get('title', 'Unknown Title')}**")
                    st.caption(f"Channel: {data.get('author_name', 'Unknown')}")
            except Exception:
                pass  # Silently fail if oembed doesn't work


def render_task_status_sidebar():
    """Render the task queue status in the sidebar."""
    task_queue = get_task_queue()
    active_tasks = task_queue.get_active_tasks()
    recent_completed = task_queue.get_recent_completed(limit=3)

    if active_tasks or recent_completed:
        st.markdown("### Active Tasks")

        # Show active tasks
        for task in active_tasks:
            status_icon = "⏳" if task.status == TaskStatus.PENDING else "🔄"
            duration = ""
            if task.duration_seconds:
                duration = f" ({int(task.duration_seconds)}s)"

            with st.container():
                st.markdown(f"{status_icon} **{task.description}**{duration}")
                if task.status == TaskStatus.RUNNING:
                    st.progress(0.5, text="Processing...")

        # Show recent completed
        if recent_completed:
            with st.expander("Recent Tasks", expanded=False):
                for task in recent_completed:
                    if task.status == TaskStatus.COMPLETED:
                        st.markdown(f"✅ {task.description}")
                    else:
                        st.markdown(f"❌ {task.description}")
                        if task.error:
                            st.caption(f"Error: {task.error[:50]}...")

                if st.button("Clear History", key="clear_task_history"):
                    task_queue.clear_completed()
                    st.rerun()

        st.markdown("---")


def check_and_display_completed_tasks():
    """Check for newly completed tasks and add to chat history."""
    if "processed_task_ids" not in st.session_state:
        st.session_state.processed_task_ids = set()

    task_queue = get_task_queue()
    recent = task_queue.get_recent_completed(limit=10)

    for task in recent:
        if task.id not in st.session_state.processed_task_ids:
            st.session_state.processed_task_ids.add(task.id)

            if task.status == TaskStatus.COMPLETED and task.result:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": task.result,
                    "model": task.model_tier,
                    "task_id": task.id,
                })
            elif task.status == TaskStatus.FAILED:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Error: {task.error}",
                    "task_id": task.id,
                })


st.set_page_config(
    page_title="GearCrew - Outdoor Gear Intelligence",
    layout="wide",
    page_icon="[G]",
)

# Initialize view mode in session state
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "Graph Explorer"

# Sidebar
with st.sidebar:
    st.title("GearCrew")
    st.caption("Outdoor Gear Intelligence Engine")

    st.markdown("---")

    # Task status (shown on all views)
    render_task_status_sidebar()

    st.markdown("### Navigation")
    nav_options = [
        "Graph Explorer",
        "Agent Chat",
        "Playlist Manager",
        "Website Extractor",
        "Data Enrichment",
        "Video Archive",
    ]
    view_mode = st.radio(
        "View:",
        nav_options,
        index=nav_options.index(st.session_state.view_mode)
        if st.session_state.view_mode in nav_options
        else 0,
        key="nav_radio",
    )

    # Update session state when view changes
    if view_mode != st.session_state.view_mode:
        st.session_state.view_mode = view_mode

    st.markdown("---")

    # Connection status
    st.markdown("### Status")
    memgraph_host = os.getenv("MEMGRAPH_HOST", "Not configured")
    st.info(f"Memgraph: {memgraph_host}")

# Auto-refresh when tasks are active
if get_task_queue().get_active_tasks():
    time.sleep(0.5)  # Small delay to prevent hammering
    st.rerun()

# Main content - use session state for view to survive reruns
if st.session_state.view_mode == "Graph Explorer":
    from app.ui.graph_explorer import render_graph_explorer

    render_graph_explorer()

elif st.session_state.view_mode == "Agent Chat":
    st.header("GearCrew Agent Chat")

    st.info(
        "Chat with the GearCrew agent to extract gear information from URLs, "
        "search the knowledge base, or ask questions about outdoor gear. "
        "**Tasks run in the background** - you can switch views while processing!"
    )

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Check for completed background tasks
    check_and_display_completed_tasks()

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            # Check if message contains YouTube URL and show preview
            if message["role"] == "user":
                yt_url = is_youtube_url(message["content"])
                if yt_url:
                    render_youtube_preview(yt_url)
                    st.markdown("---")
            elif message["role"] == "assistant" and "model" in message:
                # Show model tier indicator for assistant messages
                model_tier = message["model"]
                model_icons = {"haiku": "[H]", "sonnet": "[S]", "opus": "[O]"}
                model_names = {
                    "haiku": "Haiku 4.5",
                    "sonnet": "Sonnet 4.5",
                    "opus": "Opus 4.5",
                }
                st.caption(f"{model_icons.get(model_tier, '')} {model_names.get(model_tier, '')}")
            st.markdown(message["content"])

    # Show pending message for active tasks
    task_queue = get_task_queue()
    active_tasks = task_queue.get_active_tasks()
    for task in active_tasks:
        # Check if we already showed the user message for this task
        if f"shown_task_{task.id}" not in st.session_state:
            st.session_state[f"shown_task_{task.id}"] = True
            # The user message was already added when submitted

        with st.chat_message("assistant"):
            status = "🔄 Processing..." if task.status == TaskStatus.RUNNING else "⏳ Queued..."
            duration = f" ({int(task.duration_seconds)}s)" if task.duration_seconds else ""
            st.info(f"{status}{duration}\n\n*You can switch views - this will continue in the background.*")

    # Chat input
    if prompt := st.chat_input("Ask about gear or paste a URL to analyze..."):
        # Add user message immediately
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Determine task description
        yt_url = is_youtube_url(prompt)
        if yt_url:
            video_id = extract_youtube_video_id(yt_url)
            description = f"Analyzing video {video_id or 'unknown'}..."
        elif prompt.startswith("http"):
            description = "Analyzing webpage..."
        else:
            description = prompt[:30] + "..." if len(prompt) > 30 else prompt

        # Submit to background queue
        task_id = task_queue.submit(prompt, description)
        st.session_state[f"shown_task_{task_id}"] = True

        st.rerun()

    # Sidebar actions for chat
    with st.sidebar:
        if st.button("Clear Chat"):
            st.session_state.messages = []
            st.session_state.processed_task_ids = set()
            st.rerun()

elif st.session_state.view_mode == "Playlist Manager":
    from app.ui.playlist_manager import render_playlist_manager

    render_playlist_manager()

elif st.session_state.view_mode == "Website Extractor":
    from app.ui.website_extractor import render_website_extractor

    render_website_extractor()

elif st.session_state.view_mode == "Data Enrichment":
    from app.ui.enrichment_view import render_enrichment_view

    render_enrichment_view()

elif st.session_state.view_mode == "Video Archive":
    from app.ui.archive_view import render_archive_view

    render_archive_view()

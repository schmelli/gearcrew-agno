"""GearCrew Streamlit Dashboard.

Run with: streamlit run streamlit_app.py
"""

import os
import re
from urllib.parse import urlparse, parse_qs

import streamlit as st
from dotenv import load_dotenv

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

st.set_page_config(
    page_title="GearCrew - Outdoor Gear Intelligence",
    layout="wide",
    page_icon="[G]",
)

# Sidebar
with st.sidebar:
    st.title("GearCrew")
    st.caption("Outdoor Gear Intelligence Engine")

    st.markdown("---")

    st.markdown("### Navigation")
    view_mode = st.radio(
        "View:",
        ["Graph Explorer", "Agent Chat"],
        index=0,
    )

    st.markdown("---")

    # Connection status
    st.markdown("### Status")
    memgraph_host = os.getenv("MEMGRAPH_HOST", "Not configured")
    st.info(f"Memgraph: {memgraph_host}")

# Main content
if view_mode == "Graph Explorer":
    from app.ui.graph_explorer import render_graph_explorer

    render_graph_explorer()

elif view_mode == "Agent Chat":
    st.header("GearCrew Agent Chat")

    st.info(
        "Chat with the GearCrew agent to extract gear information from URLs, "
        "search the knowledge base, or ask questions about outdoor gear."
    )

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            # Check if message contains YouTube URL and show preview
            if message["role"] == "user":
                yt_url = is_youtube_url(message["content"])
                if yt_url:
                    render_youtube_preview(yt_url)
                    st.markdown("---")
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask about gear or paste a URL to analyze..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            # Check for YouTube URL and show preview
            yt_url = is_youtube_url(prompt)
            if yt_url:
                render_youtube_preview(yt_url)
                st.markdown("---")
            st.markdown(prompt)

        # Get agent response
        with st.chat_message("assistant"):
            # Show processing indicator with video info if applicable
            if yt_url:
                status_placeholder = st.empty()
                status_placeholder.info("Fetching video transcript and analyzing gear mentions...")

            with st.spinner("Thinking..."):
                try:
                    from app.agent import run_agent_chat

                    response = run_agent_chat(prompt)

                    # Clear the status message
                    if yt_url:
                        status_placeholder.empty()

                    st.markdown(response)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": response}
                    )
                except Exception as e:
                    if yt_url:
                        status_placeholder.empty()
                    error_msg = f"Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_msg}
                    )

    # Sidebar actions
    with st.sidebar:
        if st.button("Clear Chat"):
            st.session_state.messages = []
            st.rerun()

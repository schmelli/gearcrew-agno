"""GearCrew Streamlit Dashboard.

Run with: streamlit run streamlit_app.py
"""

import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

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
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask about gear or paste a URL to analyze..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from app.agent import run_agent_chat

                    response = run_agent_chat(prompt)
                    st.markdown(response)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": response}
                    )
                except Exception as e:
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

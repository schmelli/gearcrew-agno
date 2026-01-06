"""Agent mode UI components for hygiene queue.

Separated from main hygiene_queue.py to keep files under 500 lines.
"""

import streamlit as st

from app.hygiene.checklist import CheckPriority
from app.hygiene.logbook import get_logbook


def render_agent_status(status: dict):
    """Render agent status and statistics."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Status", status["status"].upper())
    with col2:
        st.metric("Items Processed", status["items_processed"])
    with col3:
        st.metric("Issues Found", status["issues_found"])
    with col4:
        st.metric("Fixes Applied", status["fixes_applied"])

    if status.get("queue"):
        queue = status["queue"]
        st.caption(
            f"Queue: {queue.get('pending', 0)} pending | "
            f"By priority: {queue.get('by_priority', {})}"
        )


def render_queue_tab(agent):
    """Render the priority queue view."""
    stats = agent.queue.get_statistics()

    if stats["total_items"] == 0:
        st.info("Queue is empty. Click 'Triage Items' to load items.")
        return

    st.write(f"**Total items:** {stats['total_items']}")
    st.write(f"**Pending:** {stats['pending']}")

    st.subheader("Items by Priority")
    for priority, count in sorted(stats.get("by_priority", {}).items()):
        st.write(f"**{priority}:** {count}")

    st.subheader("Items by Status")
    for status, count in stats.get("by_status", {}).items():
        st.write(f"**{status}:** {count}")


def render_logbook_tab():
    """Render the logbook view."""
    logbook = get_logbook()
    stats = logbook.get_statistics()

    st.write(f"**Total entries:** {stats['total_entries']}")

    col1, col2 = st.columns(2)
    with col1:
        st.write("**By Decision Type:**")
        for decision, count in stats.get("by_decision", {}).items():
            st.write(f"- {decision}: {count}")

    with col2:
        st.write("**By Check:**")
        for check, count in list(stats.get("by_check", {}).items())[:5]:
            st.write(f"- {check}: {count}")

    st.subheader("Recent Entries")
    entries = logbook.entries[-10:]
    for entry in reversed(entries):
        with st.expander(
            f"{entry.decision.value}: {entry.entity_name} ({entry.check_id})"
        ):
            st.write(f"**Entity ID:** {entry.entity_id}")
            st.write(f"**Confidence:** {entry.confidence:.0%}")
            st.write(f"**Reasoning:** {entry.reasoning}")
            if entry.fix_type:
                st.write(f"**Fix:** {entry.fix_type}: `{entry.old_value}` → `{entry.new_value}`")
            st.caption(f"Time: {entry.timestamp}")


def render_pending_review_tab():
    """Render items flagged for human review."""
    logbook = get_logbook()
    pending = logbook.get_pending_reviews()

    if not pending:
        st.success("No items pending review!")
        return

    st.write(f"**{len(pending)} items need review**")

    for entry in pending[:20]:
        # Determine issue type for better labeling
        is_missing_data = entry.check_id in ["missing_provenance", "data_completeness", "orphaned_node"]

        with st.expander(f"{entry.entity_name} - {entry.check_id}"):
            st.write(f"**Entity ID:** {entry.entity_id}")
            st.write(f"**Issue:** {entry.check_id.replace('_', ' ').title()}")
            st.write(f"**Reasoning:** {entry.reasoning}")

            if entry.fix_type:
                st.write("**Suggested Fix:**")
                st.code(f"{entry.old_value} → {entry.new_value}")

            st.divider()

            if is_missing_data:
                # For data quality issues - different actions
                st.caption("This item has data quality issues that need manual attention.")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("📝 Will Fix Later", key=f"defer_{entry.id}"):
                        logbook.mark_reviewed(entry.id, "user", approved=True, notes="Deferred for manual fix")
                        st.info("Marked for later")
                        st.rerun()
                with col2:
                    if st.button("✓ Not an Issue", key=f"dismiss_{entry.id}"):
                        logbook.mark_reviewed(entry.id, "user", approved=False, notes="Dismissed - not an issue")
                        st.success("Dismissed")
                        st.rerun()
                with col3:
                    if st.button("🗑️ Delete Item", key=f"delete_{entry.id}", type="secondary"):
                        st.warning("Delete functionality not yet implemented")
            else:
                # For suggested fixes - approve/reject
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✓ Apply Fix", key=f"approve_log_{entry.id}", type="primary"):
                        logbook.mark_reviewed(entry.id, "user", approved=True)
                        st.success("Fix approved!")
                        st.rerun()
                with col2:
                    if st.button("✗ Reject Fix", key=f"reject_log_{entry.id}"):
                        logbook.mark_reviewed(entry.id, "user", approved=False)
                        st.info("Fix rejected")
                        st.rerun()


def render_processing_controls(agent, batch_size: int):
    """Render the processing control buttons."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("Triage Items"):
            with st.spinner("Triaging items from database..."):
                result = agent.triage_all_items(limit=100)

            if result.get("error"):
                st.error(f"Triage failed: {result['error']}")
            elif result.get("triaged", 0) > 0:
                st.success(f"Triaged {result['triaged']} items from {result.get('total', 0)} loaded")
                if result.get("by_priority"):
                    st.caption(f"By priority: {result['by_priority']}")
                st.rerun()
            else:
                st.warning(f"No items found to triage. Loaded {result.get('total', 0)} items from DB.")

    with col2:
        priority = st.selectbox(
            "Priority",
            ["P1", "P2", "P3", "P4", "P5"],
            format_func=lambda x: {
                "P1": "P1 - Instant",
                "P2": "P2 - Quick",
                "P3": "P3 - Context",
                "P4": "P4 - Research",
                "P5": "P5 - Deep",
            }[x]
        )

    with col3:
        if st.button("Process Priority"):
            priority_map = {
                "P1": CheckPriority.P1_INSTANT,
                "P2": CheckPriority.P2_QUICK,
                "P3": CheckPriority.P3_CONTEXT,
                "P4": CheckPriority.P4_RESEARCH,
                "P5": CheckPriority.P5_DEEP,
            }
            with st.spinner(f"Processing {priority}..."):
                results = agent.process_priority_level(
                    priority_map[priority],
                    batch_size=batch_size
                )
            st.success(f"Processed {len(results)} items")
            st.rerun()

    with col4:
        if st.button("Process Batch"):
            with st.spinner("Processing batch..."):
                progress = st.progress(0)
                status_text = st.empty()
                processed = 0
                last_event = None
                for event in agent.process_batch_streaming(batch_size):
                    last_event = event
                    if event["event"] == "processing":
                        processed += 1
                        progress.progress(min(processed / batch_size, 1.0))
                        status_text.text(event.get("detail", ""))
                    elif event["event"] == "progress":
                        status_text.text(event.get("detail", ""))
                progress.progress(1.0)
                status_text.empty()

            if processed > 0:
                st.success(f"Processed {processed} items!")
                st.rerun()
            else:
                st.warning("No items to process. Click 'Triage Items' first to load items into the queue.")

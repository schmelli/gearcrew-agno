"""Hygiene Approval Queue UI for GearGraph.

Displays hygiene issues that require human approval and allows users to
approve, reject, or modify suggested fixes. Supports both legacy scanner
mode and new LLM-based agent mode.
"""

import streamlit as st
from datetime import datetime

from app.hygiene.scanner import run_hygiene_scan
from app.hygiene.auto_fixer import AutoFixer
from app.hygiene.metrics import get_metrics_collector
from app.hygiene.issues import RiskLevel, ApprovalStatus, HygieneIssue


def render_hygiene_queue():
    """Render the hygiene approval queue UI."""
    st.header("Data Hygiene Queue")
    st.caption("Review and approve data quality fixes")

    # Initialize session state
    if "hygiene_issues" not in st.session_state:
        st.session_state.hygiene_issues = []
    if "hygiene_scan_time" not in st.session_state:
        st.session_state.hygiene_scan_time = None
    if "auto_fixer" not in st.session_state:
        st.session_state.auto_fixer = AutoFixer()

    # Mode toggle
    col1, col2 = st.columns([1, 3])
    with col1:
        agent_mode = st.toggle(
            "Agent Mode",
            value=st.session_state.get("agent_mode", False),
            help="Use LLM-based intelligent evaluation instead of rule-based scanning"
        )
        st.session_state.agent_mode = agent_mode

    if agent_mode:
        _render_agent_mode()
    else:
        _render_scanner_mode()


def _render_scanner_mode():
    """Render the legacy scanner-based UI."""
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

    with col1:
        enable_web_validation = st.checkbox(
            "Web validation",
            value=False,
            help="Use web search to verify brands/products"
        )

    with col2:
        if st.button("Run Hygiene Scan", type="primary"):
            with st.spinner("Scanning database for issues..."):
                result = run_hygiene_scan(enable_web_validation=enable_web_validation)
                st.session_state.hygiene_issues = result.get("issues", [])
                st.session_state.hygiene_scan_time = datetime.now()
                get_metrics_collector().record_scan(result)

            st.success(f"Found {result['total_issues']} issues")
            st.rerun()

    with col3:
        if st.session_state.hygiene_scan_time:
            st.caption(f"Last: {st.session_state.hygiene_scan_time.strftime('%H:%M')}")

    with col4:
        if st.button("Auto-Fix Low-Risk"):
            _auto_fix_low_risk()

    if st.session_state.hygiene_issues:
        _render_summary(st.session_state.hygiene_issues)
        st.divider()
        _render_issue_list(st.session_state.hygiene_issues)
    else:
        st.info("No issues in queue. Run a scan to detect issues.")


def _auto_fix_low_risk():
    """Auto-fix low risk issues."""
    fixer = st.session_state.auto_fixer
    auto_fixable = [i for i in st.session_state.hygiene_issues if i.can_auto_fix]

    if not auto_fixable:
        st.info("No auto-fixable issues found")
        return

    with st.spinner(f"Applying {len(auto_fixable)} auto-fixes..."):
        results = fixer.apply_auto_fixes(auto_fixable)
        successful = sum(1 for r in results if r.success)
        fixed_ids = {r.issue.id for r in results if r.success}
        st.session_state.hygiene_issues = [
            i for i in st.session_state.hygiene_issues if i.id not in fixed_ids
        ]

    st.success(f"Applied {successful}/{len(auto_fixable)} auto-fixes")
    st.rerun()


def _render_agent_mode():
    """Render the LLM agent-based UI."""
    from app.hygiene.hygiene_agent import (
        HygieneAgent,
        reset_hygiene_agent,
    )
    from app.hygiene.logbook import reset_logbook
    from app.hygiene.priority_queue import reset_queue
    from app.ui.hygiene_agent_ui import (
        render_agent_status,
        render_queue_tab,
        render_logbook_tab,
        render_pending_review_tab,
        render_processing_controls,
    )

    if "hygiene_agent" not in st.session_state:
        st.session_state.hygiene_agent = None

    st.subheader("Intelligent Hygiene Agent")
    st.caption("Uses LLM judgment for context-aware data quality evaluation")

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        model = st.selectbox("Model", ["sonnet", "haiku", "opus"])

    with col2:
        batch_size = st.number_input("Batch Size", min_value=1, max_value=50, value=10)

    with col3:
        if st.button("Initialize Agent", type="primary"):
            with st.spinner("Initializing agent..."):
                # Reset global singletons to ensure fresh instances
                reset_hygiene_agent()
                reset_logbook()
                reset_queue()
                # Create new agent
                st.session_state.hygiene_agent = HygieneAgent(model=model)
            st.success("Agent initialized!")

    if st.session_state.hygiene_agent is None:
        st.info("Click 'Initialize Agent' to start.")
        return

    agent = st.session_state.hygiene_agent
    st.divider()

    render_agent_status(agent.get_status())
    st.divider()
    render_processing_controls(agent, batch_size)
    st.divider()

    tab1, tab2, tab3 = st.tabs(["Queue", "Logbook", "Pending Review"])
    with tab1:
        render_queue_tab(agent)
    with tab2:
        render_logbook_tab()
    with tab3:
        render_pending_review_tab()


def _render_summary(issues: list[HygieneIssue]):
    """Render summary statistics."""
    low = sum(1 for i in issues if i.risk_level == RiskLevel.LOW)
    medium = sum(1 for i in issues if i.risk_level == RiskLevel.MEDIUM)
    high = sum(1 for i in issues if i.risk_level == RiskLevel.HIGH)
    auto_fixable = sum(1 for i in issues if i.can_auto_fix)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Issues", len(issues))
    with col2:
        st.metric("Low Risk", low)
    with col3:
        st.metric("Medium Risk", medium)
    with col4:
        st.metric("High Risk", high)

    if auto_fixable > 0:
        st.info(f"{auto_fixable} issues can be auto-fixed.")


def _render_issue_list(issues: list[HygieneIssue]):
    """Render the list of issues."""
    col1, col2 = st.columns(2)

    with col1:
        risk_filter = st.selectbox(
            "Filter by Risk", ["All", "High", "Medium", "Low"], key="risk_filter"
        )
    with col2:
        type_filter = st.selectbox(
            "Filter by Type",
            ["All"] + list(set(i.issue_type.value for i in issues)),
            key="type_filter"
        )

    filtered = issues
    if risk_filter != "All":
        filtered = [i for i in filtered if i.risk_level.value == risk_filter.lower()]
    if type_filter != "All":
        filtered = [i for i in filtered if i.issue_type.value == type_filter]

    st.caption(f"Showing {len(filtered)} of {len(issues)} issues")

    for idx, issue in enumerate(filtered[:50]):
        _render_issue_card(issue, idx)


def _render_issue_card(issue: HygieneIssue, idx: int):
    """Render a single issue card."""
    colors = {RiskLevel.LOW: "green", RiskLevel.MEDIUM: "orange", RiskLevel.HIGH: "red"}
    color = colors.get(issue.risk_level, "gray")

    with st.expander(
        f":{color}[{issue.risk_level.value.upper()}] "
        f"{issue.issue_type.value}: {issue.description[:50]}...",
        expanded=False
    ):
        col1, col2 = st.columns([3, 1])

        with col1:
            st.write(f"**Description:** {issue.description}")
            st.write(f"**Entity:** {issue.entity_type} (ID: {issue.entity_id})")
            st.write(f"**Confidence:** {issue.confidence:.0%}")

        with col2:
            st.write(f"**Risk:** {issue.risk_level.value}")
            st.write(f"**Auto-fix:** {'Yes' if issue.can_auto_fix else 'No'}")

        fix = issue.suggested_fix
        st.write(f"**Fix:** {fix.fix_type.value}")
        if fix.old_value:
            st.write(f"**Current:** `{fix.old_value}`")
        if fix.new_value:
            st.write(f"**New:** `{fix.new_value}`")

        st.divider()
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Approve", key=f"approve_{issue.id}_{idx}", type="primary"):
                _apply_fix(issue)
        with col2:
            if st.button("Reject", key=f"reject_{issue.id}_{idx}"):
                _reject_fix(issue)
        with col3:
            if st.button("Skip", key=f"skip_{issue.id}_{idx}"):
                _skip_fix(issue)


def _apply_fix(issue: HygieneIssue):
    """Apply an approved fix."""
    result = st.session_state.auto_fixer.apply_fix(issue, force=True)
    if result.success:
        st.success(result.message)
        st.session_state.hygiene_issues = [
            i for i in st.session_state.hygiene_issues if i.id != issue.id
        ]
        st.rerun()
    else:
        st.error(result.message)


def _reject_fix(issue: HygieneIssue):
    """Reject a suggested fix."""
    issue.status = ApprovalStatus.REJECTED
    st.session_state.hygiene_issues = [
        i for i in st.session_state.hygiene_issues if i.id != issue.id
    ]
    st.info("Fix rejected")
    st.rerun()


def _skip_fix(issue: HygieneIssue):
    """Skip an issue."""
    issue.status = ApprovalStatus.IGNORED
    st.info("Issue skipped")


def render_hygiene_dashboard():
    """Render the hygiene metrics dashboard."""
    st.header("Data Hygiene Dashboard")
    st.caption("Monitor data quality and hygiene progress")

    summary = get_metrics_collector().get_summary()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Issues", summary["total_issues"])
    with col2:
        st.metric("Pending Approval", summary["pending_approval"])
    with col3:
        st.metric("Total Fixes Applied", summary["total_fixes_applied"])
    with col4:
        st.metric("Patterns Learned", summary["patterns_learned"])

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Fix Statistics")
        st.write(f"**Auto-Fix Rate:** {summary['auto_fix_rate']:.0%}")
        st.write(f"**Approval Rate:** {summary['approval_rate']:.0%}")
    with col2:
        st.subheader("Issues by Risk Level")
        for risk, count in summary["issues_by_risk"].items():
            st.write(f"**{risk.capitalize()}:** {count}")

    st.divider()
    st.subheader("Data Quality Metrics")
    dq = summary["data_quality"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Avg Completeness", dq["avg_completeness"])
    with col2:
        st.metric("Provenance Coverage", dq["provenance_coverage"])
    with col3:
        st.metric("Est. Duplicates", dq["estimated_duplicates"])
    with col4:
        st.metric("Orphaned Nodes", dq["orphaned_nodes"])

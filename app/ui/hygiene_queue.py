"""Hygiene Approval Queue UI for GearGraph.

Displays hygiene issues that require human approval and allows users to
approve, reject, or modify suggested fixes.
"""

import streamlit as st
from datetime import datetime

from app.hygiene.scanner import HygieneScanner, run_hygiene_scan
from app.hygiene.auto_fixer import AutoFixer, FixResult
from app.hygiene.metrics import get_metrics_collector
from app.hygiene.issues import (
    IssueType,
    RiskLevel,
    ApprovalStatus,
    HygieneIssue,
)


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

    # Scan controls
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        if st.button("Run Hygiene Scan", type="primary"):
            with st.spinner("Scanning database for issues..."):
                result = run_hygiene_scan()
                st.session_state.hygiene_issues = result.get("issues", [])
                st.session_state.hygiene_scan_time = datetime.now()

                # Update metrics
                metrics = get_metrics_collector()
                metrics.record_scan(result)

            st.success(f"Found {result['total_issues']} issues")
            st.rerun()

    with col2:
        if st.session_state.hygiene_scan_time:
            st.caption(f"Last scan: {st.session_state.hygiene_scan_time.strftime('%H:%M:%S')}")

    with col3:
        auto_fix_btn = st.button("Auto-Fix Low-Risk")

    # Auto-fix low-risk issues
    if auto_fix_btn and st.session_state.hygiene_issues:
        fixer = st.session_state.auto_fixer
        auto_fixable = [i for i in st.session_state.hygiene_issues if i.can_auto_fix]

        if auto_fixable:
            with st.spinner(f"Applying {len(auto_fixable)} auto-fixes..."):
                results = fixer.apply_auto_fixes(auto_fixable)
                successful = sum(1 for r in results if r.success)

                # Remove fixed issues from list
                fixed_ids = {r.issue.id for r in results if r.success}
                st.session_state.hygiene_issues = [
                    i for i in st.session_state.hygiene_issues
                    if i.id not in fixed_ids
                ]

            st.success(f"Applied {successful}/{len(auto_fixable)} auto-fixes")
            st.rerun()
        else:
            st.info("No auto-fixable issues found")

    # Display summary
    if st.session_state.hygiene_issues:
        _render_summary(st.session_state.hygiene_issues)
        st.divider()
        _render_issue_list(st.session_state.hygiene_issues)
    else:
        st.info("No issues in queue. Run a scan to detect issues.")


def _render_summary(issues: list[HygieneIssue]):
    """Render summary statistics.

    Args:
        issues: List of hygiene issues
    """
    # Count by risk level
    low = sum(1 for i in issues if i.risk_level == RiskLevel.LOW)
    medium = sum(1 for i in issues if i.risk_level == RiskLevel.MEDIUM)
    high = sum(1 for i in issues if i.risk_level == RiskLevel.HIGH)

    # Count auto-fixable
    auto_fixable = sum(1 for i in issues if i.can_auto_fix)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Issues", len(issues))
    with col2:
        st.metric("Low Risk", low, help="Can be auto-fixed")
    with col3:
        st.metric("Medium Risk", medium, help="Auto-fix with logging")
    with col4:
        st.metric("High Risk", high, help="Requires approval")

    # Auto-fixable indicator
    if auto_fixable > 0:
        st.info(f"{auto_fixable} issues can be auto-fixed. Click 'Auto-Fix Low-Risk' to apply.")


def _render_issue_list(issues: list[HygieneIssue]):
    """Render the list of issues.

    Args:
        issues: List of hygiene issues
    """
    # Filter controls
    col1, col2 = st.columns(2)

    with col1:
        risk_filter = st.selectbox(
            "Filter by Risk Level",
            ["All", "High", "Medium", "Low"],
            key="risk_filter"
        )

    with col2:
        type_filter = st.selectbox(
            "Filter by Issue Type",
            ["All"] + list(set(i.issue_type.value for i in issues)),
            key="type_filter"
        )

    # Apply filters
    filtered = issues
    if risk_filter != "All":
        filtered = [i for i in filtered if i.risk_level.value == risk_filter.lower()]
    if type_filter != "All":
        filtered = [i for i in filtered if i.issue_type.value == type_filter]

    st.caption(f"Showing {len(filtered)} of {len(issues)} issues")

    # Render each issue
    for idx, issue in enumerate(filtered[:50]):  # Limit to 50 for performance
        _render_issue_card(issue, idx)


def _render_issue_card(issue: HygieneIssue, idx: int):
    """Render a single issue card.

    Args:
        issue: The hygiene issue
        idx: Index for unique keys
    """
    # Determine color based on risk
    risk_colors = {
        RiskLevel.LOW: "green",
        RiskLevel.MEDIUM: "orange",
        RiskLevel.HIGH: "red",
    }
    color = risk_colors.get(issue.risk_level, "gray")

    with st.expander(
        f":{color}[{issue.risk_level.value.upper()}] "
        f"{issue.issue_type.value}: {issue.description[:60]}...",
        expanded=False
    ):
        # Issue details
        col1, col2 = st.columns([3, 1])

        with col1:
            st.write(f"**Description:** {issue.description}")
            st.write(f"**Entity:** {issue.entity_type} (ID: {issue.entity_id})")
            st.write(f"**Confidence:** {issue.confidence:.0%}")

            if issue.source_channel:
                st.write(f"**Source:** {issue.source_channel}")

        with col2:
            st.write(f"**Risk:** {issue.risk_level.value}")
            st.write(f"**Auto-fix:** {'Yes' if issue.can_auto_fix else 'No'}")

        # Suggested fix
        st.subheader("Suggested Fix")
        fix = issue.suggested_fix

        st.write(f"**Action:** {fix.fix_type.value}")
        if fix.target_field:
            st.write(f"**Field:** {fix.target_field}")
        if fix.old_value is not None:
            st.write(f"**Current Value:** `{fix.old_value}`")
        if fix.new_value is not None:
            st.write(f"**New Value:** `{fix.new_value}`")
        if fix.merge_target_id:
            st.write(f"**Merge Into:** ID {fix.merge_target_id}")

        st.caption(f"Reasoning: {fix.reasoning}")

        # Action buttons
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
    """Apply an approved fix.

    Args:
        issue: The issue to fix
    """
    fixer = st.session_state.auto_fixer
    result = fixer.apply_fix(issue, force=True)

    if result.success:
        st.success(result.message)

        # Remove from list
        st.session_state.hygiene_issues = [
            i for i in st.session_state.hygiene_issues
            if i.id != issue.id
        ]

        # Update metrics
        metrics = get_metrics_collector()
        metrics.record_fix(result)

        st.rerun()
    else:
        st.error(result.message)


def _reject_fix(issue: HygieneIssue):
    """Reject a suggested fix.

    Args:
        issue: The issue to reject
    """
    issue.status = ApprovalStatus.REJECTED

    # Remove from list
    st.session_state.hygiene_issues = [
        i for i in st.session_state.hygiene_issues
        if i.id != issue.id
    ]

    # Update metrics
    metrics = get_metrics_collector()
    metrics.record_rejection()

    st.info("Fix rejected")
    st.rerun()


def _skip_fix(issue: HygieneIssue):
    """Skip an issue (keep for later).

    Args:
        issue: The issue to skip
    """
    issue.status = ApprovalStatus.IGNORED
    st.info("Issue skipped - will remain in queue")


def render_hygiene_dashboard():
    """Render the hygiene metrics dashboard."""
    st.header("Data Hygiene Dashboard")
    st.caption("Monitor data quality and hygiene progress")

    metrics = get_metrics_collector()
    summary = metrics.get_summary()

    # Key metrics
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

    # Fix rates
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Fix Statistics")
        st.write(f"**Auto-Fix Rate:** {summary['auto_fix_rate']:.0%}")
        st.write(f"**Approval Rate:** {summary['approval_rate']:.0%}")
        st.write(f"**Rejection Rate:** {summary['rejection_rate']:.0%}")

    with col2:
        st.subheader("Issues by Risk Level")
        for risk, count in summary["issues_by_risk"].items():
            st.write(f"**{risk.capitalize()}:** {count}")

    st.divider()

    # Data quality
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

    # Copyright status
    st.subheader("Copyright Status")
    cp = summary["copyright"]

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Flagged Descriptions", cp["flagged"])
    with col2:
        st.metric("Rewritten", cp["rewritten"])

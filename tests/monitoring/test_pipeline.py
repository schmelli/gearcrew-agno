"""Integration tests for monitoring pipeline."""

import tempfile
from unittest.mock import Mock, patch

import pytest

from app.monitoring.pipeline import PlaylistMonitor
from app.monitoring.tracker import VideoTracker


@pytest.fixture
def mock_playlist_videos():
    """Mock playlist videos."""
    return [
        {
            "video_id": "vid1",
            "title": "Backpacking Gear Review 2024",
            "url": "https://youtube.com/watch?v=vid1",
            "duration": 600,
            "channel": "TestChannel",
        },
        {
            "video_id": "vid2",
            "title": "My Ultralight Setup",
            "url": "https://youtube.com/watch?v=vid2",
            "duration": 450,
            "channel": "TestChannel",
        },
    ]


@pytest.fixture
def mock_playlist_info():
    """Mock playlist info."""
    return {
        "playlist_id": "PLtest123",
        "title": "Test Playlist",
        "channel": "TestChannel",
        "video_count": 2,
    }


@patch("app.monitoring.pipeline.get_playlist_info")
@patch("app.monitoring.pipeline.get_playlist_videos")
def test_check_and_process_dry_run(
    mock_get_videos,
    mock_get_info,
    mock_playlist_videos,
    mock_playlist_info,
):
    """Test dry run mode doesn't process videos."""
    mock_get_info.return_value = mock_playlist_info
    mock_get_videos.return_value = mock_playlist_videos

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")
        monitor = PlaylistMonitor(
            playlist_url="https://youtube.com/playlist?list=test",
            tracker=tracker,
            notifier=None,  # No email in tests
        )

        stats = monitor.check_and_process(dry_run=True)

        assert stats["new_videos"] == 2
        assert stats["processed"] == 0
        assert stats["failed"] == 0
        # Videos should NOT be marked as processed in dry run
        assert not tracker.is_processed("vid1")
        assert not tracker.is_processed("vid2")


@patch("app.monitoring.pipeline.get_playlist_info")
@patch("app.monitoring.pipeline.get_playlist_videos")
def test_no_new_videos(
    mock_get_videos,
    mock_get_info,
    mock_playlist_videos,
    mock_playlist_info,
):
    """Test behavior when no new videos are found."""
    mock_get_info.return_value = mock_playlist_info
    mock_get_videos.return_value = mock_playlist_videos

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")

        # Mark all videos as processed
        for video in mock_playlist_videos:
            tracker.mark_processed(video["video_id"])

        monitor = PlaylistMonitor(
            playlist_url="https://youtube.com/playlist?list=test",
            tracker=tracker,
            notifier=None,
        )

        stats = monitor.check_and_process()

        assert stats["new_videos"] == 0
        assert stats["processed"] == 0
        assert stats["failed"] == 0


@patch("app.monitoring.pipeline.get_playlist_info")
@patch("app.monitoring.pipeline.get_playlist_videos")
@patch("app.monitoring.pipeline.run_agent_chat")
def test_successful_processing(
    mock_agent,
    mock_get_videos,
    mock_get_info,
    mock_playlist_videos,
    mock_playlist_info,
):
    """Test successful video processing."""
    mock_get_info.return_value = mock_playlist_info
    mock_get_videos.return_value = [mock_playlist_videos[0]]  # Just one video

    # Mock agent response with gear items
    mock_agent.return_value = """
    I found the following gear items:
    - Osprey Atmos 65L backpack
    - Big Agnes Copper Spur tent
    - Western Mountaineering sleeping bag

    The reviewer recommends using trekking poles for stability.
    Important tip: Keep your pack weight under 20 lbs.
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")
        monitor = PlaylistMonitor(
            playlist_url="https://youtube.com/playlist?list=test",
            tracker=tracker,
            notifier=None,
        )

        stats = monitor.check_and_process()

        assert stats["new_videos"] == 1
        assert stats["processed"] == 1
        assert stats["failed"] == 0
        assert stats["gear_extracted"] > 0

        # Video should be marked as processed
        assert tracker.is_processed("vid1")


@patch("app.monitoring.pipeline.get_playlist_info")
@patch("app.monitoring.pipeline.get_playlist_videos")
@patch("app.monitoring.pipeline.run_agent_chat")
def test_processing_failure(
    mock_agent,
    mock_get_videos,
    mock_get_info,
    mock_playlist_videos,
    mock_playlist_info,
):
    """Test handling of processing failures."""
    mock_get_info.return_value = mock_playlist_info
    mock_get_videos.return_value = [mock_playlist_videos[0]]

    # Mock agent raises exception
    mock_agent.side_effect = Exception("API error")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")
        monitor = PlaylistMonitor(
            playlist_url="https://youtube.com/playlist?list=test",
            tracker=tracker,
            notifier=None,
        )

        stats = monitor.check_and_process()

        assert stats["new_videos"] == 1
        assert stats["processed"] == 0
        assert stats["failed"] == 1

        # Failed video should NOT be marked as processed
        assert not tracker.is_processed("vid1")

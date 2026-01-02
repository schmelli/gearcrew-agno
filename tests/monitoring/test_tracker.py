"""Unit tests for video tracker."""

import json
import tempfile
from pathlib import Path

import pytest

from app.monitoring.tracker import VideoTracker


def test_tracker_initialization():
    """Test tracker initialization with empty state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")
        assert len(tracker.processed_videos) == 0
        assert tracker.last_check is None


def test_tracker_persistence():
    """Test tracker saves and loads state correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tracking_file = f"{tmpdir}/test.json"

        # Create tracker and mark videos as processed
        tracker1 = VideoTracker(tracking_file=tracking_file)
        tracker1.mark_processed("video1")
        tracker1.mark_processed("video2")

        # Create new tracker instance - should load saved state
        tracker2 = VideoTracker(tracking_file=tracking_file)
        assert "video1" in tracker2.processed_videos
        assert "video2" in tracker2.processed_videos
        assert len(tracker2.processed_videos) == 2


def test_is_processed():
    """Test checking if video is processed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")
        tracker.mark_processed("video1")

        assert tracker.is_processed("video1")
        assert not tracker.is_processed("video2")


def test_get_new_videos():
    """Test filtering new videos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = VideoTracker(tracking_file=f"{tmpdir}/test.json")
        tracker.mark_processed("video1")

        all_videos = [
            {"video_id": "video1", "title": "Video 1"},
            {"video_id": "video2", "title": "Video 2"},
            {"video_id": "video3", "title": "Video 3"},
        ]

        new_videos = tracker.get_new_videos(all_videos)

        assert len(new_videos) == 2
        assert new_videos[0]["video_id"] == "video2"
        assert new_videos[1]["video_id"] == "video3"


def test_get_stats():
    """Test getting tracker statistics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tracking_file = f"{tmpdir}/test.json"
        tracker = VideoTracker(tracking_file=tracking_file)
        tracker.mark_processed("video1")
        tracker.mark_processed("video2")

        # Reload to get updated last_check from file
        tracker = VideoTracker(tracking_file=tracking_file)
        stats = tracker.get_stats()

        assert stats["total_processed"] == 2
        assert stats["last_check"] is not None


def test_mark_processed_creates_file():
    """Test that marking processed creates the tracking file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tracking_file = Path(tmpdir) / "test.json"
        tracker = VideoTracker(tracking_file=str(tracking_file))

        assert not tracking_file.exists()

        tracker.mark_processed("video1")

        assert tracking_file.exists()

        # Verify file contents
        with open(tracking_file) as f:
            data = json.load(f)
            assert "video1" in data["video_ids"]
            assert data["total_processed"] == 1

#!/usr/bin/env python3
"""Sync tracking file with videos already in the database.

This script queries the database for all processed videos and updates
the tracking file so the monitoring system doesn't reprocess them.
"""

from dotenv import load_dotenv
from app.db.memgraph import get_all_video_sources
from app.monitoring.tracker import VideoTracker
from app.tools.youtube import extract_video_id

load_dotenv()


def sync_tracking():
    """Sync tracking file from database."""
    print("🔍 Querying database for processed videos...")

    # Get all video sources from database (no limit)
    sources = get_all_video_sources(limit=10000)

    if not sources:
        print("❌ No videos found in database")
        return

    print(f"📊 Found {len(sources)} videos in database")

    # Extract video IDs
    video_ids = []
    for source in sources:
        url = source.get("url", "")
        video_id = extract_video_id(url)
        if video_id:
            video_ids.append(video_id)
            print(f"  ✓ {source.get('title', 'Unknown')[:60]}... ({video_id})")
        else:
            print(f"  ⚠️  Could not extract ID from: {url}")

    print(f"\n📝 Extracted {len(video_ids)} valid video IDs")

    # Update tracking file
    tracker = VideoTracker()
    print(f"📂 Current tracking file has {len(tracker.processed_videos)} videos")

    # Add all video IDs
    for video_id in video_ids:
        tracker.mark_processed(video_id)

    print(f"✅ Updated tracking file with {len(tracker.processed_videos)} total videos")
    print(f"📁 Tracking file: data/processed_videos.json")


if __name__ == "__main__":
    sync_tracking()

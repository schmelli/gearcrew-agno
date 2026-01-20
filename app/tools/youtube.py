"""YouTube transcript and playlist extraction tools."""

import os
import re
import requests
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi
from yt_dlp import YoutubeDL

# YouTube Data API v3 base URL
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extract YouTube video ID from URL or return as-is if already an ID.

    Args:
        url_or_id: YouTube URL or video ID

    Returns:
        Video ID or None if extraction failed
    """
    if len(url_or_id) == 11 and not url_or_id.startswith("http"):
        return url_or_id

    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    return None


def get_youtube_transcript(url_or_id: str, languages: list[str] = None) -> str:
    """Fetch transcript from a YouTube video.

    Args:
        url_or_id: YouTube video URL or ID
        languages: Preferred languages (default: ['en'])

    Returns:
        Full transcript text

    Raises:
        ValueError: If video ID cannot be extracted or transcript unavailable
    """
    if languages is None:
        languages = ["en"]

    video_id = extract_video_id(url_or_id)
    if not video_id:
        raise ValueError(f"Could not extract video ID from: {url_or_id}")

    try:
        ytt = YouTubeTranscriptApi()

        # Try to fetch transcript with preferred languages
        try:
            transcript_data = ytt.fetch(video_id, languages=languages)
        except Exception:
            # Fall back to any available transcript
            transcript_data = ytt.fetch(video_id)

        # Extract text from transcript snippets
        full_text = " ".join(
            snippet.text for snippet in transcript_data
        )
        return full_text

    except Exception as e:
        error_msg = str(e).lower()
        if "disabled" in error_msg:
            raise ValueError(f"Transcripts are disabled for video: {video_id}")
        elif "unavailable" in error_msg or "not found" in error_msg:
            raise ValueError(f"Video unavailable or no transcript: {video_id}")
        else:
            raise ValueError(f"Error fetching transcript for {video_id}: {str(e)}")


def extract_playlist_id(url: str) -> Optional[str]:
    """Extract YouTube playlist ID from URL.

    Args:
        url: YouTube playlist URL

    Returns:
        Playlist ID or None if extraction failed
    """
    patterns = [
        r"[?&]list=([a-zA-Z0-9_-]+)",
        r"youtube\.com\/playlist\?list=([a-zA-Z0-9_-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def get_playlist_videos(playlist_url: str) -> list[dict]:
    """Fetch list of videos from a YouTube playlist.

    Args:
        playlist_url: YouTube playlist URL

    Returns:
        List of video info dicts with keys: video_id, title, url, duration, channel

    Raises:
        ValueError: If playlist cannot be fetched
    """
    playlist_id = extract_playlist_id(playlist_url)
    if not playlist_id:
        raise ValueError(f"Could not extract playlist ID from: {playlist_url}")

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)

            if not info or "entries" not in info:
                raise ValueError(f"Could not fetch playlist: {playlist_url}")

            videos = []
            for entry in info["entries"]:
                if entry is None:
                    continue

                video_id = entry.get("id", "")
                videos.append({
                    "video_id": video_id,
                    "title": entry.get("title", "Unknown"),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "duration": entry.get("duration"),
                    "channel": entry.get("channel") or entry.get("uploader", "Unknown"),
                })

            return videos

    except Exception as e:
        raise ValueError(f"Error fetching playlist {playlist_url}: {str(e)}")


def get_playlist_info(playlist_url: str) -> dict:
    """Get playlist metadata (title, channel, video count).

    Args:
        playlist_url: YouTube playlist URL

    Returns:
        Dict with playlist_id, title, channel, video_count
    """
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)

            return {
                "playlist_id": info.get("id", ""),
                "title": info.get("title", "Unknown Playlist"),
                "channel": info.get("channel") or info.get("uploader", "Unknown"),
                "video_count": len(info.get("entries", [])),
            }

    except Exception as e:
        raise ValueError(f"Error fetching playlist info: {str(e)}")


def get_video_details_api(video_id: str, api_key: str) -> dict:
    """Fetch video details using YouTube Data API v3.

    This is the PREFERRED method as it's reliable and doesn't get blocked.
    Requires a YouTube Data API key (free tier: 10,000 units/day).

    Args:
        video_id: YouTube video ID (11 characters)
        api_key: YouTube Data API key

    Returns:
        Dict with video details including description

    Raises:
        ValueError: If API call fails
    """
    url = f"{YOUTUBE_API_BASE}/videos"
    params = {
        "part": "snippet,contentDetails,statistics",
        "id": video_id,
        "key": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            raise ValueError(f"Video not found: {video_id}")

        item = data["items"][0]
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        statistics = item.get("statistics", {})

        # Parse duration from ISO 8601 format (PT1H2M3S)
        duration_iso = content_details.get("duration", "")
        duration_seconds = _parse_iso_duration(duration_iso)

        # Parse upload date
        published_at = snippet.get("publishedAt", "")
        upload_date = published_at[:10].replace("-", "") if published_at else None

        return {
            "video_id": video_id,
            "title": snippet.get("title", "Unknown"),
            "description": snippet.get("description", ""),
            "channel": snippet.get("channelTitle", "Unknown"),
            "duration": duration_seconds,
            "upload_date": upload_date,
            "view_count": int(statistics.get("viewCount", 0)) if statistics.get("viewCount") else None,
            "like_count": int(statistics.get("likeCount", 0)) if statistics.get("likeCount") else None,
            "tags": snippet.get("tags", []),
        }

    except requests.exceptions.RequestException as e:
        raise ValueError(f"YouTube API request failed: {str(e)}")
    except (KeyError, ValueError) as e:
        raise ValueError(f"Failed to parse YouTube API response: {str(e)}")


def _parse_iso_duration(duration: str) -> Optional[int]:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds.

    Args:
        duration: ISO 8601 duration string

    Returns:
        Duration in seconds, or None if parsing fails
    """
    if not duration:
        return None

    # Remove PT prefix
    duration = duration.replace("PT", "")

    total_seconds = 0
    # Parse hours
    if "H" in duration:
        hours, duration = duration.split("H")
        total_seconds += int(hours) * 3600
    # Parse minutes
    if "M" in duration:
        minutes, duration = duration.split("M")
        total_seconds += int(minutes) * 60
    # Parse seconds
    if "S" in duration:
        seconds = duration.replace("S", "")
        total_seconds += int(seconds)

    return total_seconds if total_seconds > 0 else None


def get_video_details(url_or_id: str) -> dict:
    """Fetch full video details including description.

    PRIORITY ORDER:
    1. YouTube Data API (reliable, no bot detection)
    2. yt-dlp fallback (may get blocked by YouTube)

    This is CRITICAL for gear extraction because:
    - Video descriptions often contain complete gear lists with links
    - Affiliate links reveal exact product names and brands
    - Timestamps in descriptions help locate gear mentions

    Args:
        url_or_id: YouTube video URL or ID

    Returns:
        Dict with: video_id, title, description, channel, duration,
                   upload_date, view_count, like_count, tags

    Raises:
        ValueError: If video cannot be fetched
    """
    video_id = extract_video_id(url_or_id)
    if not video_id:
        raise ValueError(f"Could not extract video ID from: {url_or_id}")

    # Try YouTube Data API first (preferred - reliable and no bot detection)
    api_key = os.getenv("YOUTUBE_API_KEY")
    if api_key:
        try:
            return get_video_details_api(video_id, api_key)
        except ValueError as e:
            # Log but continue to fallback
            print(f"  ⚠️ YouTube API failed, trying yt-dlp: {e}")

    # Fallback to yt-dlp (may get blocked by YouTube)
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Don't use extract_flat - we want FULL metadata including description
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

            return {
                "video_id": video_id,
                "title": info.get("title", "Unknown"),
                "description": info.get("description", ""),
                "channel": info.get("channel") or info.get("uploader", "Unknown"),
                "duration": info.get("duration"),
                "upload_date": info.get("upload_date"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "tags": info.get("tags", []),
            }

    except Exception as e:
        raise ValueError(f"Error fetching video details for {video_id}: {str(e)}")

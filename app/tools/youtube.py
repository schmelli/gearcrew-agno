"""YouTube transcript and playlist extraction tools."""

import re
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi
from yt_dlp import YoutubeDL


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


def get_video_details(url_or_id: str) -> dict:
    """Fetch full video details including description.

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

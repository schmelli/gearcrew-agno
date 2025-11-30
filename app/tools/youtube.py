"""YouTube transcript extraction tool."""

import re
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)


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
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None
        for lang in languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except NoTranscriptFound:
                continue

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(languages)
            except NoTranscriptFound:
                available = list(transcript_list)
                if available:
                    transcript = available[0]
                else:
                    raise ValueError(f"No transcripts available for video: {video_id}")

        transcript_data = transcript.fetch()
        full_text = " ".join(entry["text"] for entry in transcript_data)
        return full_text

    except TranscriptsDisabled:
        raise ValueError(f"Transcripts are disabled for video: {video_id}")
    except VideoUnavailable:
        raise ValueError(f"Video unavailable: {video_id}")
    except Exception as e:
        raise ValueError(f"Error fetching transcript: {str(e)}")

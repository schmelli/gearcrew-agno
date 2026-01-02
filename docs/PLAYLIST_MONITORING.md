# YouTube Playlist Monitoring

Automated system to monitor a YouTube playlist and extract gear information from new videos.

## Features

- 🔍 **Automatic Detection**: Monitors playlist every 6 hours for new videos
- 🤖 **AI Extraction**: Uses the GearCrew agent to extract gear info and insights
- 📧 **Email Notifications**: Sends detailed reports for each processed video
- 📊 **Progress Tracking**: Maintains state to avoid reprocessing videos
- ☁️ **GitHub Actions**: Runs automatically in the cloud

## Setup

### 1. Configure GitHub Secrets

Add the following secrets to your GitHub repository (Settings → Secrets and variables → Actions):

#### Required Secrets

**Playlist Configuration:**
- `PLAYLIST_URL`: Your YouTube playlist URL
  - Example: `https://www.youtube.com/playlist?list=PLy6TtegcnZj84nCIzqtZcWlNHD6sQAJqj`

**AI API Keys** (at least one required):
- `OPENAI_API_KEY`: OpenAI API key
- `ANTHROPIC_API_KEY`: Anthropic API key
- `DEEPSEEK_API_KEY`: DeepSeek API key

**Email Notifications:**
- `SENDER_EMAIL`: Email address to send from (e.g., your Gmail address)
- `SENDER_PASSWORD`: Email password or app-specific password
  - For Gmail: Create an [App Password](https://support.google.com/accounts/answer/185833)
- `RECIPIENT_EMAIL`: Email address to receive notifications
- `SMTP_SERVER`: SMTP server address (default: `smtp.gmail.com`)
- `SMTP_PORT`: SMTP port (default: `587`)

**Database Configuration:**
- `NEO4J_URI`: Neo4j database URI
- `NEO4J_USERNAME`: Neo4j username
- `NEO4J_PASSWORD`: Neo4j password

#### Optional Secrets

- `FIREBASE_CREDENTIALS`: Firebase service account JSON (if using Firebase)
- `FIRECRAWL_API_KEY`: Firecrawl API key (for web scraping fallback)
- `LANGWATCH_API_KEY`: LangWatch API key (for monitoring)

### 2. Gmail App Password Setup

If using Gmail for notifications:

1. Go to your [Google Account](https://myaccount.google.com/)
2. Navigate to Security → 2-Step Verification
3. Scroll down to "App passwords"
4. Create a new app password for "Mail"
5. Use this password as `SENDER_PASSWORD`

### 3. Enable GitHub Actions

The workflow is located at `.github/workflows/monitor-playlist.yml`

- Runs automatically every 6 hours
- Can be manually triggered from the Actions tab

## Manual Usage

You can also run the monitoring locally:

```bash
# Set environment variables in .env file
export PLAYLIST_URL="https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID"
export SENDER_EMAIL="your-email@gmail.com"
export SENDER_PASSWORD="your-app-password"
export RECIPIENT_EMAIL="recipient@example.com"
# ... other required vars

# Run monitoring
uv run python monitor_playlist.py

# Dry run (check for new videos without processing)
uv run python monitor_playlist.py --dry-run
```

## How It Works

1. **Playlist Check**: Fetches all videos from the playlist using yt-dlp
2. **New Video Detection**: Compares against `data/processed_videos.json` to find new videos
3. **Processing**: For each new video:
   - Extracts transcript using youtube-transcript-api
   - Runs GearCrew agent to extract gear information
   - Saves data to GearGraph database
   - Sends email notification with results
4. **Tracking**: Updates `processed_videos.json` with processed video IDs
5. **Summary**: Sends summary email with overall statistics

## Email Notifications

You'll receive two types of emails:

### Individual Video Notifications

Sent for each processed video:

```
✅ Gear Extraction: Video Title

📹 Video: Video Title
🔗 URL: https://youtube.com/watch?v=...

🎒 Gear Items Extracted (5):
  • Osprey Atmos 65L Backpack
  • Big Agnes Copper Spur HV UL2 Tent
  • ...

💡 Key Insights (3):
  • Recommends using trekking poles for stability
  • Pack weight kept under 20 lbs for comfort
  • ...
```

### Summary Reports

Sent after each monitoring run:

```
📊 Playlist Monitoring Summary

📋 Playlist: Best Backpacking Gear 2024

📊 Summary:
  • New videos found: 3
  • Successfully processed: 3
  • Failed: 0
  • Total gear items extracted: 15
```

## Monitoring Schedule

The workflow runs:
- **Every 6 hours**: `0 */6 * * *` (midnight, 6am, noon, 6pm UTC)
- **On-demand**: Can be manually triggered from GitHub Actions tab

You can adjust the schedule by editing `.github/workflows/monitor-playlist.yml`:

```yaml
on:
  schedule:
    - cron: '0 */6 * * *'  # Change this cron expression
```

## Troubleshooting

### No emails received

1. Check GitHub Actions logs for errors
2. Verify email credentials are correct
3. Check spam folder
4. Ensure Gmail "Less secure app access" is enabled (if using Gmail without app password)

### Videos not being processed

1. Check that `PLAYLIST_URL` secret is set correctly
2. Verify API keys are valid and have quota remaining
3. Check GitHub Actions logs for error messages
4. Ensure video has transcripts available

### Tracking file conflicts

If you get git conflicts on `data/processed_videos.json`:

```bash
# Keep the version with more processed videos
git checkout --theirs data/processed_videos.json
git add data/processed_videos.json
```

## File Structure

```
app/monitoring/
├── __init__.py
├── tracker.py      # Video tracking system
├── notifier.py     # Email notification system
└── pipeline.py     # Main monitoring pipeline

data/
└── processed_videos.json  # Tracking file (committed to git)

.github/workflows/
└── monitor-playlist.yml   # GitHub Actions workflow

monitor_playlist.py        # CLI script
```

## Development

To test the monitoring system locally:

```bash
# Install dependencies
uv sync

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# Dry run
uv run python monitor_playlist.py --dry-run

# Process new videos
uv run python monitor_playlist.py
```

## Cost Considerations

- **GitHub Actions**: Free tier includes 2,000 minutes/month
- **AI APIs**: Costs vary by provider and usage
- **Email**: Free with Gmail (standard limits apply)

Each monitoring run typically uses:
- ~5-10 minutes of GitHub Actions time
- ~$0.01-0.10 in AI API costs per video (depending on length)

## Privacy & Security

- Video tracking data is committed to the repository
- All sensitive credentials are stored as GitHub Secrets
- Email notifications are only sent to configured recipient
- No video content is stored, only metadata and extracted information

"""YouTube API client for listing channel uploads."""

import os
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube"]


def get_authenticated_service(credentials_path: str, token_path: str):
    """Authenticate with YouTube Data API v3 via OAuth2.

    On first run, opens a browser for user consent.
    Subsequent runs use the cached refresh token.
    """
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired OAuth2 token")
            creds.refresh(Request())
        else:
            log.info("No valid token found — launching browser for OAuth2 consent")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def get_recent_uploads(
    youtube, channel_id: str, since_date: date, tz: ZoneInfo
) -> list[dict]:
    """Fetch uploads from a channel since a given date.

    Returns a list of dicts with keys: video_id, title, published_date, url.
    The published_date is converted to the given timezone.
    """
    # Get the channel's "uploads" playlist ID
    ch_response = (
        youtube.channels().list(part="contentDetails", id=channel_id).execute()
    )
    if not ch_response.get("items"):
        log.error(f"Channel {channel_id} not found or has no content")
        return []

    uploads_playlist = ch_response["items"][0]["contentDetails"]["relatedPlaylists"][
        "uploads"
    ]
    log.debug(f"Uploads playlist: {uploads_playlist}")

    videos = []
    next_page = None

    while True:
        response = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_playlist,
                maxResults=50,
                pageToken=next_page,
            )
            .execute()
        )

        for item in response.get("items", []):
            published_str = item["snippet"]["publishedAt"]
            published_utc = datetime.fromisoformat(
                published_str.replace("Z", "+00:00")
            )
            published_local = published_utc.astimezone(tz)
            pub_date = published_local.date()

            if pub_date < since_date:
                # Playlist is reverse-chronological, so we can stop early
                return videos

            video_id = item["snippet"]["resourceId"]["videoId"]
            videos.append(
                {
                    "video_id": video_id,
                    "title": item["snippet"]["title"],
                    "published_date": pub_date,
                    "url": f"https://youtu.be/{video_id}",
                }
            )

        next_page = response.get("nextPageToken")
        if not next_page:
            break

    return videos

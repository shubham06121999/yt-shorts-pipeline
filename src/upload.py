"""
Uploads the finished video to YouTube as a Short via the YouTube Data API v3.

Requires a Google Cloud OAuth "Desktop app" client secret JSON (see README.md
for how to create one) and the google-auth-oauthlib / google-api-python-client
packages. The first run opens a browser for consent; after that, the token is
cached to YOUTUBE_TOKEN_FILE and reused.

NOTE: YouTube Data API has a default daily quota of 10,000 units, and a
single video upload costs 1,600 units - so by default you get ~6 uploads/day
across your whole project before you'd need to request a quota increase.
"""
import os
from typing import List, Optional

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_credentials(client_secret_path: str, token_path: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: List[str],
    privacy_status: str = "private",
    category_id: str = "27",
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
    made_for_kids: bool = False,
) -> str:
    """Uploads video_path to YouTube. Returns the resulting video ID."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    client_secret_path = client_secret_path or os.environ.get(
        "YOUTUBE_CLIENT_SECRET", "client_secret.json"
    )
    token_path = token_path or os.environ.get("YOUTUBE_TOKEN_FILE", "token.json")

    if not os.path.exists(client_secret_path):
        raise FileNotFoundError(
            f"OAuth client secret not found at '{client_secret_path}'. "
            "See README.md 'YouTube API setup' for how to create one, "
            "or run with --no-upload to skip this step."
        )

    creds = _get_credentials(client_secret_path, token_path)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[upload] {int(status.progress() * 100)}% uploaded")

    video_id = response["id"]
    print(f"[upload] Done: https://youtube.com/shorts/{video_id}")
    return video_id


if __name__ == "__main__":
    import sys

    upload_video(
        video_path=sys.argv[1],
        title="Test upload from pipeline",
        description="Automated test upload.",
        tags=["test"],
        privacy_status="private",
    )

"""Real YouTube Data API v3 upload via OAuth 2.0.

Not used by default (YOUTUBE_UPLOAD_PROVIDER=mock). This class can be
imported and instantiated without credentials set - they're only
required the moment upload_video() actually runs, mirroring
ClaudeAiProvider's lazy-credential pattern. See
scripts/youtube_oauth_setup.py for how to obtain a refresh token.
"""

from .base import UploadResult, YoutubeUploadProvider
from .scopes import ALL_SCOPES


class RealYoutubeUploadProvider(YoutubeUploadProvider):
    name = "youtube"

    def __init__(self, client_id: str | None, client_secret: str | None, refresh_token: str | None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._client = None

    def _get_client(self):
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise RuntimeError(
                "RealYoutubeUploadProvider requires YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
                "and YOUTUBE_REFRESH_TOKEN. Run scripts/youtube_oauth_setup.py to obtain a "
                "refresh token, or set YOUTUBE_UPLOAD_PROVIDER=mock to test without real credentials."
            )
        if self._client is None:
            from google.oauth2.credentials import Credentials  # lazy: not a hard dependency for mock-only runs
            from googleapiclient.discovery import build

            credentials = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=ALL_SCOPES,  # the refresh token must have been granted both scopes at consent time
            )
            self._client = build("youtube", "v3", credentials=credentials)
        return self._client

    def upload_video(
        self,
        video_path: str,
        thumbnail_path: str | None,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        privacy_status: str,
        target_playlist_id: str | None = None,
    ) -> UploadResult:
        from googleapiclient.http import MediaFileUpload

        client = self._get_client()

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {"privacyStatus": privacy_status},
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        response = client.videos().insert(part="snippet,status", body=body, media_body=media).execute()
        video_id = response["id"]

        if thumbnail_path:
            client.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()

        added_to_playlist = False
        if target_playlist_id:
            client.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": target_playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            added_to_playlist = True

        return UploadResult(
            video_id=video_id,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
            added_to_playlist=added_to_playlist,
        )

"""OAuth scopes shared by upload (Phase 5) and analytics (Phase 6). Kept in
one place so scripts/youtube_oauth_setup.py, RealYoutubeUploadProvider, and
RealYoutubeAnalyticsProvider always request/expect the same grant - a
refresh token issued for a narrower scope set silently fails for calls
outside it, so scope drift here is a real footgun to avoid."""

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"

ALL_SCOPES = [UPLOAD_SCOPE, ANALYTICS_READONLY_SCOPE]

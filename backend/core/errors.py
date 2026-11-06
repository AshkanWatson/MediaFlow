"""Typed errors with stable machine codes and user-friendly messages."""
from __future__ import annotations


class MediaFlowError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500
    default_message = "Something went wrong."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class InvalidURL(MediaFlowError):
    code, http_status = "INVALID_URL", 400
    default_message = "That doesn't look like a valid public http(s) URL."


class InvalidRequest(MediaFlowError):
    code, http_status = "INVALID_REQUEST", 400
    default_message = "The request is invalid."


class BlockedHost(MediaFlowError):
    code, http_status = "BLOCKED_HOST", 400
    default_message = "This address is not allowed (private, local or reserved network)."


class UnsupportedURL(MediaFlowError):
    code, http_status = "UNSUPPORTED_URL", 422
    default_message = "This link is not supported."


class AuthRequired(MediaFlowError):
    code, http_status = "AUTH_REQUIRED", 403
    default_message = (
        "This content requires signing in or is private. MediaFlow only "
        "handles publicly accessible content."
    )


class RestrictedContent(MediaFlowError):
    code, http_status = "RESTRICTED_CONTENT", 403
    default_message = "This content is restricted (DRM, geo-blocked, age-gated or protected)."


class PreviewOnly(MediaFlowError):
    code, http_status = "PREVIEW_ONLY", 409
    default_message = (
        "Only a (possibly watermarked) preview is publicly available. "
        "Set accept_preview=true to download the preview."
    )


class MediaNotFound(MediaFlowError):
    code, http_status = "MEDIA_NOT_FOUND", 404
    default_message = "The media could not be found (removed or unavailable)."


class TooLarge(MediaFlowError):
    code, http_status = "TOO_LARGE", 413
    default_message = "The file exceeds the maximum allowed size."


class DownloadTimeout(MediaFlowError):
    code, http_status = "TIMEOUT", 504
    default_message = "The operation took too long and was stopped."


class RateLimited(MediaFlowError):
    code, http_status = "RATE_LIMITED", 429
    default_message = "Too many requests. Please slow down."


class Busy(MediaFlowError):
    code, http_status = "BUSY", 429
    default_message = "The server is busy. Try again shortly."


class UpstreamError(MediaFlowError):
    code, http_status = "UPSTREAM_ERROR", 502
    default_message = "The source site returned an error or could not be reached."


class InvalidMedia(MediaFlowError):
    code, http_status = "INVALID_MEDIA", 422
    default_message = "The downloaded file is not a valid or allowed media file."


class ProcessingFailed(MediaFlowError):
    code, http_status = "PROCESSING_FAILED", 500
    default_message = "Processing the media failed."


class JobNotFound(MediaFlowError):
    code, http_status = "JOB_NOT_FOUND", 404
    default_message = "Job not found or expired."


class JobCancelled(MediaFlowError):
    code, http_status = "CANCELLED", 409
    default_message = "The job was cancelled."


class Unauthorized(MediaFlowError):
    code, http_status = "UNAUTHORIZED", 401
    default_message = "Missing or invalid API key."

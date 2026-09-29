"""Domain errors mapped to RFC 7807 problem+json responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    title = "Bad request"

    def __init__(self, detail: str | None = None, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    title = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"
    title = "Validation failed"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    title = "Authentication required"


class PermissionDenied(AppError):
    status_code = 403
    code = "forbidden"
    title = "Permission denied"


class InvalidTransition(AppError):
    status_code = 409
    code = "invalid_transition"
    title = "Invalid workflow transition"


class ApprovalRequired(AppError):
    status_code = 409
    code = "approval_required"
    title = "Human approval required"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Too many requests"


class UnsafeContent(AppError):
    status_code = 422
    code = "unsafe_content"
    title = "Content rejected by security checks"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"
    title = "Upstream service error"

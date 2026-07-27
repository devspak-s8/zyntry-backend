from __future__ import annotations

from fastapi import HTTPException, status


class ZyntraError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or "internal_error"


class NotFoundError(ZyntraError):
    code = "not_found"


class ValidationError(ZyntraError):
    code = "validation_error"


class ConflictError(ZyntraError):
    code = "conflict"


class UnauthorizedError(ZyntraError):
    code = "unauthorized"


class ForbiddenError(ZyntraError):
    code = "forbidden"


class RateLimitError(ZyntraError):
    code = "rate_limited"


def http_exception_from_error(error: ZyntraError) -> HTTPException:
    status_map = {
        "not_found": status.HTTP_404_NOT_FOUND,
        "validation_error": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "conflict": status.HTTP_409_CONFLICT,
        "unauthorized": status.HTTP_401_UNAUTHORIZED,
        "forbidden": status.HTTP_403_FORBIDDEN,
        "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    }
    return HTTPException(
        status_code=status_map.get(error.code, status.HTTP_500_INTERNAL_SERVER_ERROR),
        detail={"code": error.code, "message": error.message},
    )

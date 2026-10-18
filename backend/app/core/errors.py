from __future__ import annotations

from fastapi import HTTPException, status


class APIError(HTTPException):
    def __init__(self, status_code: int, detail: str, code: str = "error"):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def not_found(what: str = "Resource") -> APIError:
    return APIError(status.HTTP_404_NOT_FOUND, f"{what} not found.", "not_found")


def bad_request(detail: str) -> APIError:
    return APIError(status.HTTP_400_BAD_REQUEST, detail, "bad_request")


def forbidden(detail: str = "You do not have permission to perform this action.") -> APIError:
    return APIError(status.HTTP_403_FORBIDDEN, detail, "forbidden")


def conflict(detail: str) -> APIError:
    return APIError(status.HTTP_409_CONFLICT, detail, "conflict")

from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, status: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(status_code=status, detail={"code": code, "message": message, "details": details})


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, "not_found", f"{what} not found")


def forbidden(msg: str = "You do not have access to this resource") -> AppError:
    return AppError(403, "forbidden", msg)


def bad_request(msg: str, details=None) -> AppError:
    return AppError(400, "bad_request", msg, details)


def conflict(msg: str) -> AppError:
    return AppError(409, "conflict", msg)

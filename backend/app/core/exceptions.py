from fastapi import HTTPException, status


class DeplotError(Exception):
    def __init__(self, message: str, code: str = "DEPLOT_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(DeplotError):
    pass


class ValidationError(DeplotError):
    pass


class ExternalServiceError(DeplotError):
    pass


def to_http_exception(exc: DeplotError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(exc, NotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ExternalServiceError):
        status_code = status.HTTP_502_BAD_GATEWAY
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )

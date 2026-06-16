import hmac

from fastapi import Header, HTTPException, status

from api.config import settings


async def exigir_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY nao configurada no servidor.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key invalida ou ausente.",
        )

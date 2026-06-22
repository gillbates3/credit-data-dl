from pydantic import BaseModel, Field


class CadastroTickerRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    deep: bool = False
    data_corte_deep: str | None = None


class ProcessoCriadoResponse(BaseModel):
    process_id: str

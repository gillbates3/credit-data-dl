from pydantic import BaseModel, Field


class IngestTickerRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    deep: bool = False
    data_corte_deep: str | None = None


class JobCriadoResponse(BaseModel):
    job_id: str

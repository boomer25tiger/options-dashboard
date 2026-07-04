"""Pydantic request models for the API. Responses are plain dicts from services."""
import datetime as dt
from typing import List, Optional

from pydantic import BaseModel, Field


class StrategyLeg(BaseModel):
    option_type: str = Field(description="'call', 'put', or 'stock'")
    quantity: int = Field(description="signed: positive long, negative short")
    strike: Optional[float] = None
    expiration: Optional[dt.date] = None
    sigma: Optional[float] = Field(
        default=None, description="IV; if omitted it is filled from the live chain")
    entry_price: Optional[float] = Field(
        default=None, description="per-share basis; defaults to theoretical value")
    multiplier: Optional[int] = Field(
        default=None, description="defaults to 100 for options, 1 for stock")


class StrategyRequest(BaseModel):
    ticker: str
    legs: List[StrategyLeg]
    iv_source: str = "auto"
    dividend_yield: Optional[float] = None

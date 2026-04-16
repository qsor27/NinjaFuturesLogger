from typing import Literal

from models.base import StrictModel

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
FieldType = Literal["text", "number", "dropdown", "date", "boolean"]


class SourceMapping(StrictModel):
    continuous: str | None = None
    contract_template: str | None = None


class InstrumentSources(StrictModel):
    yfinance: SourceMapping
    stooq: SourceMapping


class InstrumentSession(StrictModel):
    timezone: str
    open: str
    close: str
    daily_break_start: str
    daily_break_end: str


class InstrumentConfig(StrictModel):
    display_name: str
    multiplier: float
    tick_size: float
    sources: InstrumentSources
    session: InstrumentSession
    commission_per_contract: float = 0.0


class ChartDefaults(StrictModel):
    default_timeframe: Timeframe
    volume_visible_default: bool
    display_timezone: str | None = None


class CustomFieldDefinition(StrictModel):
    field_id: int
    name: str
    field_type: FieldType
    is_active: bool
    display_order: int
    created_at: int


class CustomFieldOption(StrictModel):
    option_id: int
    field_id: int
    value: str
    display_order: int


class CustomFieldOptionInput(StrictModel):
    value: str
    display_order: int = 0

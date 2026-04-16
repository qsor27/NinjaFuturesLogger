import pytest
from pydantic import ValidationError

from models.settings import (
    ChartDefaults,
    CustomFieldDefinition,
    CustomFieldOption,
    InstrumentConfig,
    InstrumentSession,
    InstrumentSources,
    SourceMapping,
)


def test_source_mapping_round_trip():
    m = SourceMapping(continuous="ES=F", contract_template=None)
    assert m.continuous == "ES=F"
    assert m.contract_template is None
    assert SourceMapping(**m.model_dump()) == m


def test_source_mapping_both_fields_optional():
    m = SourceMapping()
    assert m.continuous is None
    assert m.contract_template is None


def test_instrument_sources_requires_both_providers():
    with pytest.raises(ValidationError):
        InstrumentSources()


def test_instrument_session_all_fields_strings():
    s = InstrumentSession(
        timezone="America/Chicago",
        open="17:00",
        close="16:00",
        daily_break_start="16:00",
        daily_break_end="17:00",
    )
    assert s.timezone == "America/Chicago"


def test_instrument_config_full_round_trip():
    raw = {
        "display_name": "E-mini S&P 500",
        "multiplier": 50.0,
        "tick_size": 0.25,
        "sources": {
            "yfinance": {"continuous": "ES=F", "contract_template": None},
            "stooq": {"continuous": "es.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    cfg = InstrumentConfig(**raw)
    assert cfg.multiplier == 50.0
    assert cfg.sources.yfinance.continuous == "ES=F"
    assert cfg.session.timezone == "America/Chicago"
    assert cfg.model_dump()["sources"]["stooq"]["continuous"] == "es.f"


def test_instrument_config_extra_forbidden():
    with pytest.raises(ValidationError):
        InstrumentConfig(
            display_name="x",
            multiplier=1.0,
            tick_size=0.25,
            sources=InstrumentSources(
                yfinance=SourceMapping(),
                stooq=SourceMapping(),
            ),
            session=InstrumentSession(
                timezone="UTC",
                open="00:00",
                close="00:00",
                daily_break_start="",
                daily_break_end="",
            ),
            extra_field="nope",
        )


def test_chart_defaults_timeframe_literal():
    cd = ChartDefaults(default_timeframe="5m", volume_visible_default=True, display_timezone=None)
    assert cd.default_timeframe == "5m"
    with pytest.raises(ValidationError):
        ChartDefaults(default_timeframe="2m", volume_visible_default=True, display_timezone=None)


def test_custom_field_definition_field_type_literal():
    for ft in ("text", "number", "dropdown", "date", "boolean"):
        CustomFieldDefinition(
            field_id=1,
            name="x",
            field_type=ft,
            is_active=True,
            display_order=0,
            created_at=0,
        )
    with pytest.raises(ValidationError):
        CustomFieldDefinition(
            field_id=1,
            name="x",
            field_type="bogus",
            is_active=True,
            display_order=0,
            created_at=0,
        )


def test_custom_field_option_round_trip():
    o = CustomFieldOption(option_id=1, field_id=2, value="Breakout", display_order=0)
    assert o.value == "Breakout"


def test_instrument_config_commission_defaults_to_zero():
    raw = {
        "display_name": "E-mini Nasdaq-100",
        "multiplier": 20.0,
        "tick_size": 0.25,
        "sources": {
            "yfinance": {"continuous": "NQ=F", "contract_template": None},
            "stooq": {"continuous": "nq.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    cfg = InstrumentConfig(**raw)
    assert cfg.commission_per_contract == 0.0


def test_instrument_config_commission_round_trips():
    raw = {
        "display_name": "Micro E-mini Nasdaq-100",
        "multiplier": 2.0,
        "tick_size": 0.25,
        "commission_per_contract": 1.08,
        "sources": {
            "yfinance": {"continuous": "MNQ=F", "contract_template": None},
            "stooq": {"continuous": "mnq.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    cfg = InstrumentConfig(**raw)
    assert cfg.commission_per_contract == 1.08
    assert cfg.model_dump()["commission_per_contract"] == 1.08

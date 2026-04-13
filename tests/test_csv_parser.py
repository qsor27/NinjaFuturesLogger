from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.csv_parser import ParseError, parse_execution_row

TRADER_TZ = ZoneInfo("America/Chicago")
IMPORTED_AT = 1_700_000_000
SRC = "NinjaTrader_Executions_20260413.csv"


def _parse(line: str):
    return parse_execution_row(
        line,
        source_filename=SRC,
        trader_tz=TRADER_TZ,
        imported_at=IMPORTED_AT,
    )


def test_parse_basic_buy_row():
    line = (
        "MNQ,Buy,3,4237.75,1/15/2025 2:45:30 PM,abc123,Entry,3 L,"
        "12345,Manual Entry,$5.00,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.instrument == "MNQ"
    assert e.original_action == "Buy"
    assert e.side == "Buy"
    assert e.quantity == 3
    assert e.price == 4237.75
    assert e.nt_execution_id == "abc123"
    assert e.entry_exit == "Entry"
    assert e.position_after == "3 L"
    assert e.source_order_id == "12345"
    assert e.commission == 5.0
    assert e.account == "Sim101"
    assert e.source_filename == SRC
    assert e.imported_at == IMPORTED_AT
    expected = int(datetime(2025, 1, 15, 14, 45, 30, tzinfo=TRADER_TZ).timestamp())
    assert e.timestamp == expected


def test_parse_normalizes_buy_to_cover_to_buy_side():
    line = (
        "ES,BuyToCover,2,5000.25,2/3/2025 9:00:00 AM,xid,Exit,-,"
        "9,Exit,$0.50,1,Sim101,Apex Trader Funding ,Valid"
    )
    e = _parse(line)
    assert e.original_action == "BuyToCover"
    assert e.side == "Buy"
    assert e.position_after == "-"


def test_parse_normalizes_sell_short_to_sell_side():
    line = (
        "CL,SellShort,1,72.34,3/10/2025 11:30:15 AM,xid,Entry,1 S,"
        "7,Short,$1.00,1,APEX-1,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.original_action == "SellShort"
    assert e.side == "Sell"


def test_parse_handles_rfc4180_quoted_field_with_comma():
    line = (
        "MNQ,Buy,1,4100.00,5/5/2025 10:00:00 AM,qid,Entry,1 L,"
        '1,"Name, with comma",$0.00,1,Sim101,Apex Trader Funding ,'
    )
    e = _parse(line)
    assert e.quantity == 1


def test_parse_rejects_wrong_column_count():
    line = "MNQ,Buy,3,4237.75,1/15/2025 2:45:30 PM"
    with pytest.raises(ParseError, match="15 columns"):
        _parse(line)


def test_parse_rejects_unknown_action():
    line = (
        "MNQ,Teleport,1,4000,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="action"):
        _parse(line)


def test_parse_rejects_bad_quantity():
    line = (
        "MNQ,Buy,abc,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="quantity"):
        _parse(line)


def test_parse_rejects_zero_quantity():
    line = (
        "MNQ,Buy,0,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="quantity"):
        _parse(line)


def test_parse_rejects_bad_price():
    line = (
        "MNQ,Buy,1,notaprice,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="price"):
        _parse(line)


def test_parse_rejects_bad_time():
    line = "MNQ,Buy,1,4237.75,yesterday,id,Entry,1 L," "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    with pytest.raises(ParseError, match="time"):
        _parse(line)


def test_parse_rejects_bad_entry_exit():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Maybe,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="E/X"):
        _parse(line)


def test_parse_rejects_empty_execution_id():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="execution id"):
        _parse(line)


def test_parse_rejects_empty_account():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L," "1,n,$0.00,1,,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="account"):
        _parse(line)


def test_parse_commission_with_no_dollar_prefix_still_accepted():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,2.50,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.commission == 2.50


def test_parse_empty_commission_becomes_zero():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L," "1,n,,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.commission == 0.0


def test_parse_empty_position_after_becomes_none():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.position_after is None


def test_parse_dash_position_after_is_preserved_verbatim():
    line = (
        "MNQ,Sell,1,4237.75,1/15/2025 2:45:30 PM,id,Exit,-,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.position_after == "-"

from services.instruments import base_symbol, get_multiplier


def test_get_multiplier_known_symbols():
    assert get_multiplier("MNQ") == 2.0
    assert get_multiplier("ES") == 50.0
    assert get_multiplier("NQ") == 20.0
    assert get_multiplier("MES") == 5.0
    assert get_multiplier("CL") == 1000.0
    assert get_multiplier("GC") == 100.0


def test_get_multiplier_handles_contract_suffix():
    assert get_multiplier("MNQ SEP25") == 2.0
    assert get_multiplier("ES DEC25") == 50.0


def test_get_multiplier_unknown_symbol_returns_one():
    assert get_multiplier("ZZZZ") == 1.0


def test_base_symbol_strips_suffix():
    assert base_symbol("MNQ SEP25") == "MNQ"
    assert base_symbol("ES DEC25") == "ES"
    assert base_symbol("MNQ") == "MNQ"


def test_source_symbol_renders_contract_template_for_yfinance(tmp_path):
    import json

    from services.instruments import set_registry_path, source_symbol

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {
                            "continuous": "MNQ=F",
                            "contract_template": "{ROOT}{M}{YY}.CME",
                        },
                        "stooq": {
                            "continuous": "mnq.f",
                            "contract_template": None,
                        },
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)
    assert source_symbol("MNQ JUN26", "yfinance") == "MNQM26.CME"
    assert source_symbol("MNQ", "yfinance") == "MNQ=F"
    assert source_symbol("MNQ JUN26", "stooq") is None
    assert source_symbol("MNQ", "stooq") == "mnq.f"


def test_source_symbol_all_month_codes(tmp_path):
    import json

    from services.instruments import set_registry_path, source_symbol

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "NQ": {
                    "display_name": "E-mini Nasdaq-100",
                    "multiplier": 20.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {
                            "continuous": "NQ=F",
                            "contract_template": "{ROOT}{M}{YY}.CME",
                        },
                        "stooq": {
                            "continuous": "nq.f",
                            "contract_template": None,
                        },
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)

    pairs = {
        "JAN": "F",
        "FEB": "G",
        "MAR": "H",
        "APR": "J",
        "MAY": "K",
        "JUN": "M",
        "JUL": "N",
        "AUG": "Q",
        "SEP": "U",
        "OCT": "V",
        "NOV": "X",
        "DEC": "Z",
    }
    for word, code in pairs.items():
        assert source_symbol(f"NQ {word}26", "yfinance") == f"NQ{code}26.CME"

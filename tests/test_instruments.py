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

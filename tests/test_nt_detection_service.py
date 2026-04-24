from services.nt_detection import DetectionResult, detect_ninjatrader


def test_not_found_when_documents_has_no_nt_folder(tmp_path):
    result = detect_ninjatrader(documents_override=tmp_path)
    assert isinstance(result, DetectionResult)
    assert result.found is False
    assert result.indicators_path is None


def test_found_when_indicators_dir_exists(tmp_path):
    indicators = tmp_path / "NinjaTrader 8" / "bin" / "Custom" / "Indicators"
    indicators.mkdir(parents=True)
    result = detect_ninjatrader(documents_override=tmp_path)
    assert result.found is True
    assert result.indicators_path == indicators


def test_not_found_when_nt_folder_exists_but_indicators_dir_does_not(tmp_path):
    (tmp_path / "NinjaTrader 8").mkdir()
    result = detect_ninjatrader(documents_override=tmp_path)
    assert result.found is False
    assert result.indicators_path is None

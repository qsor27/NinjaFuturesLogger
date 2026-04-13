import json

from logging_config import configure_logging, get_logger


def test_log_line_is_json_with_component(capsys):
    configure_logging(level="INFO")
    log = get_logger("http")
    log.info("hello world", extra={"path": "/healthz"})
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["component"] == "http"
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["path"] == "/healthz"

from services.version import get_version


def test_get_version_defaults_to_unknown(monkeypatch):
    monkeypatch.delenv("FTL_GIT_SHA", raising=False)
    monkeypatch.delenv("FTL_BUILT_AT", raising=False)
    monkeypatch.delenv("FTL_IMAGE_TAG", raising=False)
    v = get_version()
    assert v == {
        "git_sha": "unknown",
        "built_at": "unknown",
        "image_tag": "unknown",
    }


def test_get_version_reads_env(monkeypatch):
    monkeypatch.setenv("FTL_GIT_SHA", "abc1234")
    monkeypatch.setenv("FTL_BUILT_AT", "2026-04-23T12:00:00Z")
    monkeypatch.setenv("FTL_IMAGE_TAG", "v1.5.0")
    v = get_version()
    assert v == {
        "git_sha": "abc1234",
        "built_at": "2026-04-23T12:00:00Z",
        "image_tag": "v1.5.0",
    }

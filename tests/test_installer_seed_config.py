"""Pin the installer-seeded app.json against load_config.

windows/installer/pages.pas::SeedAppJsonIfMissing writes this JSON verbatim
on first install (data dir and port substituted from the wizard). Config is
a StrictModel (extra="forbid", strict) — any drift between what pages.pas
writes and what Config accepts is a first-run crash on a clean Windows
install. If you edit the seeded JSON in pages.pas, update SEED_TEMPLATE to
match, and vice versa (the second test cross-checks the static lines).

Future work (out of scope here): move the seed to a shared
app.json.template consumed by both the installer and this test.
"""

from pathlib import Path

from config import load_config

# Mirrors pages.pas SeedAppJsonIfMissing (Lines.Add calls) line for line.
# {dir} is the forward-slash data dir; {port} is the wizard's chosen port.
SEED_TEMPLATE = """\
{{
  "data_dir": "{dir}",
  "db_path": "{dir}/app.db",
  "inbox_dir": "{dir}/inbox",
  "archive_dir": "{dir}/archive",
  "log_dir": "{dir}/logs",
  "session": {{
    "exchange_timezone": "America/Chicago",
    "trade_date_rollover": "17:00",
    "archive_job_time": "18:00",
    "source_timezone": "America/Chicago"
  }},
  "thread_pool": {{ "max_workers": 4 }},
  "scheduler": {{ "heartbeat_seconds": 60 }},
  "theme": "dark",
  "windows": {{ "port": {port} }}
}}
"""

# Static fragments of the seeded JSON exactly as they appear inside the
# Lines.Add('...') calls in pages.pas — substring-checked against the
# Pascal source so the fixture can't silently diverge from the installer.
STATIC_FRAGMENTS = [
    '"exchange_timezone": "America/Chicago"',
    '"trade_date_rollover": "17:00"',
    '"archive_job_time": "18:00"',
    '"source_timezone": "America/Chicago"',
    '"thread_pool": { "max_workers": 4 }',
    '"scheduler": { "heartbeat_seconds": 60 }',
    '"theme": "dark"',
]

PAGES_PAS = Path(__file__).resolve().parents[1] / "windows" / "installer" / "pages.pas"


def test_installer_seed_config_loads(tmp_path: Path):
    data_dir = str(tmp_path).replace("\\", "/")  # pages.pas writes forward slashes
    path = tmp_path / "app.json"
    path.write_text(SEED_TEMPLATE.format(dir=data_dir, port=8003), encoding="utf-8")

    cfg = load_config(path)  # StrictModel: raises on any unknown/renamed field

    assert cfg.data_dir == data_dir
    assert cfg.session.exchange_timezone == "America/Chicago"
    assert cfg.session.source_timezone == "America/Chicago"
    assert cfg.thread_pool.max_workers == 4
    assert cfg.scheduler.heartbeat_seconds == 60
    assert cfg.theme == "dark"
    assert cfg.windows.port == 8003


def test_seed_template_static_lines_match_pages_pas():
    pascal = PAGES_PAS.read_text(encoding="utf-8")
    # Render the template so its escaped {{ }} become literal braces —
    # the raw string would never contain '"thread_pool": { ... }'.
    rendered = SEED_TEMPLATE.format(dir="D:/data", port=8003)
    for fragment in STATIC_FRAGMENTS:
        assert fragment in pascal, (
            f"pages.pas no longer writes {fragment!r} — "
            "update SEED_TEMPLATE/STATIC_FRAGMENTS to match SeedAppJsonIfMissing"
        )
        assert fragment in rendered, (
            f"SEED_TEMPLATE dropped {fragment!r} — resync with pages.pas"
        )

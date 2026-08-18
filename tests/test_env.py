"""Regression tests for the .env loader.

This is the exact mechanism that broke the AI toggle when the Streamlit process
was launched via `sh -c` (no ~/.zshrc), so its contract is pinned here: load
values, skip comments/blanks, strip quotes, and NEVER override a real env var.
"""
import os

from studio.env import load_dotenv

_KEY = "STUDIO_ENV_TEST_KEY"
_QUOTED = "STUDIO_ENV_TEST_QUOTED"


def test_loads_values_and_strips_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv(_KEY, raising=False)
    monkeypatch.delenv(_QUOTED, raising=False)
    (tmp_path / ".env").write_text(
        f"# a comment\n\n{_KEY}=hello\n{_QUOTED}=\"quoted value\"\n"
    )
    applied = load_dotenv(tmp_path)
    assert os.environ[_KEY] == "hello"
    assert os.environ[_QUOTED] == "quoted value"   # surrounding quotes stripped
    assert applied == {_KEY: "hello", _QUOTED: "quoted value"}
    # cleanup (load_dotenv writes os.environ directly, outside monkeypatch)
    os.environ.pop(_KEY, None)
    os.environ.pop(_QUOTED, None)


def test_existing_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(_KEY, "from-shell")
    (tmp_path / ".env").write_text(f"{_KEY}=from-file\n")
    load_dotenv(tmp_path)
    assert os.environ[_KEY] == "from-shell"   # file must not override a real var


def test_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path) == {}

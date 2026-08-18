"""AI description helpers — provider gating, sparseness, prompt building, and
the DuckDuckGo snippet parser. No network is touched (the LLM call itself is
integration-tested manually)."""
from catbuilder.describer import (
    ai_configured,
    _is_sparse,
    _build_prompt,
    _SnippetParser,
)
from catbuilder.models import MerchantData


def test_ai_configured_with_cloud_key(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "some-key")
    assert ai_configured() is True


def test_ai_configured_with_explicit_local_base(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434/v1")
    assert ai_configured() is True


def test_ai_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    assert ai_configured() is False


def test_is_sparse():
    assert _is_sparse("", []) is True
    assert _is_sparse("x" * 40, []) is False        # useful bio
    assert _is_sparse("", ["Item A", "Item B"]) is False  # enough listings


def test_build_prompt_includes_all_context():
    m = MerchantData(handle="foo", display_name="Foo Co", category="Autos",
                     profile_url="https://www.carousell.sg/u/foo/")
    prompt = _build_prompt(m, ["Brake pads", "Alloy wheels"], "extra web context")
    for needle in ("@foo", "Foo Co", "Autos", "Brake pads", "extra web context"):
        assert needle in prompt


def test_snippet_parser_extracts_result_snippets():
    html = (
        '<div class="result__snippet">First snippet</div>'
        '<span class="other">ignored</span>'
        '<div class="result__body">Second snippet</div>'
    )
    p = _SnippetParser()
    p.feed(html)
    assert p.snippets == ["First snippet", "Second snippet"]

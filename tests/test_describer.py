"""AI description helpers - provider gating, sparseness, prompt building, and
the DuckDuckGo snippet parser. No network is touched (the LLM call itself is
integration-tested manually)."""
from catbuilder.describer import (
    ai_configured,
    _is_sparse,
    _build_prompt,
    _SnippetParser,
    _grounding_tokens,
    _is_grounded,
)
from catbuilder.models import MerchantData

# The real hallucination that shipped for @81.aircon - an image caption of a
# random photo instead of a description of the aircon business. Kept as a
# regression fixture so the guardrail can never let it through again.
_HALLUCINATION = (
    "A woman with dark hair pulled back leans toward the viewer with a lively, "
    "mid-speech expression, her mouth open in a candid, easy laugh. She is dressed "
    "in a solid black one-shoulder top, accessorized with large hoop earrings and a "
    "delicate silver necklace. A dark flat-screen television is mounted on a plain "
    "beige wall behind her."
)
_AIRCON_BIO = ("Assistance available for aircon setup and related concerns. "
               "Includes complimentary site checks and old unit removal.")


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


def test_grounding_tokens_from_name_and_bio():
    m = MerchantData(handle="81.aircon", display_name="81.Aircon", category="Services")
    tokens = _grounding_tokens(m, _AIRCON_BIO, [])
    assert "aircon" in tokens          # from the name / handle
    assert "setup" in tokens           # distinctive bio word
    assert "services" not in tokens     # generic → stop-worded out
    assert "81" not in tokens           # pure numbers dropped


def test_guardrail_rejects_the_81aircon_hallucination():
    m = MerchantData(handle="81.aircon", display_name="81.Aircon", category="Services")
    tokens = _grounding_tokens(m, _AIRCON_BIO, [])
    # the shipped hallucination mentions none of the merchant's words → rejected
    assert _is_grounded(_HALLUCINATION, tokens) is False


def test_guardrail_accepts_a_real_description():
    m = MerchantData(handle="81.aircon", display_name="81.Aircon", category="Services")
    tokens = _grounding_tokens(m, _AIRCON_BIO, [])
    good = ("81.Aircon offers aircon setup, servicing, and old-unit removal with "
            "complimentary site checks - message them to book.")
    assert _is_grounded(good, tokens) is True


def test_guardrail_does_not_over_reject_when_nothing_to_check():
    assert _is_grounded("anything at all", set()) is True


def test_snippet_parser_extracts_result_snippets():
    html = (
        '<div class="result__snippet">First snippet</div>'
        '<span class="other">ignored</span>'
        '<div class="result__body">Second snippet</div>'
    )
    p = _SnippetParser()
    p.feed(html)
    assert p.snippets == ["First snippet", "Second snippet"]

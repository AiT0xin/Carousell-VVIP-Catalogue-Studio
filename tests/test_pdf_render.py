"""Text sanitizer for the PDF renderer — LLM descriptions use smart punctuation
(non-breaking hyphens, em-dashes, smart quotes) and the occasional emoji, none of
which the embedded fonts have glyphs for; unsanitized they render as tofu boxes."""
from catbuilder.pdf_render import _ascii


def test_maps_dashes_and_quotes():
    assert _ascii("air‑conditioner") == "air-conditioner"          # non-breaking hyphen
    assert _ascii("old‑unit — removal") == "old-unit - removal"  # em dash
    assert _ascii("it’s the “best”") == 'it\'s the "best"'   # smart quotes


def test_maps_special_spaces():
    assert _ascii("a b c") == "a b c"


def test_drops_emoji_and_symbols():
    assert _ascii("great service ✅") == "great service "


def test_leaves_plain_ascii_untouched():
    s = "HDB/BTO aircon servicing from $65 - book now."
    assert _ascii(s) == s


def test_no_non_ascii_survives():
    out = _ascii("HDB‑BTO service—with 24’s ✅ care")
    assert all(ord(c) < 128 for c in out)

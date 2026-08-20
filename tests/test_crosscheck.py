"""Cross-check core — fuzzy VVIP matching and the summary tally.

The network-bound run_crosscheck() (which drives PDF extraction) is exercised
manually; here we pin the pure logic it depends on."""
from studio.crosscheck import _match_vvip, crosscheck_summary
from studio.state import StudioSession, MerchantRecord, CC_KEEP, CC_REMOVE, CC_ADD


def test_exact_match():
    ok, matched = _match_vvip("acmemotors", {"acmemotors"})
    assert ok and matched == "acmemotors"


def test_prefix_fuzzy_match():
    # master stores the stem "acmebrand"; catalogue shows "acmebrandsg"
    ok, matched = _match_vvip("acmebrandsg", {"acmebrand"})
    assert ok and matched == "acmebrand"


def test_no_fuzzy_for_short_handles():
    # both under the 5-char floor → no fuzzy match even if related
    ok, _ = _match_vvip("abcd", {"abc"})
    assert not ok


def test_no_match():
    ok, matched = _match_vvip("foobar", {"bazqux"})
    assert not ok and matched == ""


def test_summary_counts():
    s = StudioSession()
    s.n_vvip_total = 3
    s.merchants = [
        MerchantRecord(handle="a", in_catalogue=True, is_vvip=True, cc_status=CC_KEEP),
        MerchantRecord(handle="b", in_catalogue=True, is_vvip=False, cc_status=CC_REMOVE),
        MerchantRecord(handle="c", in_catalogue=False, is_vvip=True, cc_status=CC_ADD),
    ]
    assert crosscheck_summary(s) == {
        "in_catalogue": 2, "vvip_total": 3, "keep": 1, "remove": 1, "add": 1,
    }

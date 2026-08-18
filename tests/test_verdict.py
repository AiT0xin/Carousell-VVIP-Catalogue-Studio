"""QR verdict logic — turns (extraction + live-verify + master) into a reason
code. This is the heart of Feature 2, so every branch is pinned here."""
from qrcheck.models import ExtractedRow, VerifyResult, QRClass, ReasonCode
from qrcheck.verdict import decide, _similar, _in_master


def _row(printed=None, url="https://caro.sl/x", qr_class=QRClass.SHORTLINK):
    return ExtractedRow(page=1, printed_handle=printed, decoded_url=url,
                        decoded_handle=None, qr_class=qr_class)


def _live(handle):
    return VerifyResult(resolves_to_handle=handle, is_live_profile=True,
                        qr_status="live", final_url=f"https://www.carousell.sg/u/{handle}/")


def test_decode_fail_when_no_qr():
    r = decide(ExtractedRow(1, "foo", None, None, QRClass.MERCHANT), None, None, set())
    assert r.reason_code is ReasonCode.DECODE_FAIL


def test_pass_when_match_and_in_master():
    r = decide(_row("foo"), _live("foo"), None, {"foo"})
    assert r.reason_code is ReasonCode.PASS
    assert r.match_status == "match"


def test_pass_when_match_and_no_master():
    # empty master set → nothing to check against, still a pass
    r = decide(_row("foo"), _live("foo"), None, set())
    assert r.reason_code is ReasonCode.PASS


def test_not_in_master_when_match_but_absent():
    r = decide(_row("foo"), _live("foo"), None, {"bar"})
    assert r.reason_code is ReasonCode.NOT_IN_MASTER


def test_dead_link():
    r = decide(_row("foo"), VerifyResult(is_live_profile=False, qr_status="dead"), None, set())
    assert r.reason_code is ReasonCode.DEAD_LINK


def test_renamed_handle_blank_shell():
    r = decide(_row("foo"), VerifyResult(is_live_profile=False, qr_status="blank-shell"),
               None, set())
    assert r.reason_code is ReasonCode.RENAMED_HANDLE


def test_mismatch_when_printed_is_a_different_live_store():
    r = decide(_row("foo"), _live("bar"), _live("foo"), set())
    assert r.reason_code is ReasonCode.MISMATCH


def test_handle_typo_when_printed_dead_and_near_spelling():
    # printed slug is not live; QR lands on a near-spelling → typo, QR is right
    r = decide(_row("carshopp"), _live("carshoppp"), None, set())
    assert r.reason_code is ReasonCode.HANDLE_TYPO


def test_cta_ok():
    r = decide(ExtractedRow(1, None, "https://wa.me/123", None, QRClass.CTA),
               None, None, set())
    assert r.reason_code is ReasonCode.CTA_OK


def test_similar_helper():
    assert _similar("", "x") == 0.0
    assert _similar("abc", "abc") == 1.0
    assert _similar("carshopp", "carshoppp") >= 0.72


def test_in_master_helper():
    assert _in_master("foo", set()) == "—"      # em dash when no master
    assert _in_master("", {"x"}) == "No"
    assert _in_master("Foo", {"foo"}) == "Yes"        # normalizes before lookup

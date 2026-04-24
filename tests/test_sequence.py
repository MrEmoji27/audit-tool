"""Tests for detect_sequence_gaps — sequence detection and gap reporting."""
import pytest

from audit import detect_sequence_gaps


# ─── helpers ────────────────────────────────────────────────────────────────


def _single(names: list[str]) -> dict | None:
    """Return the first (dominant) pattern dict or None."""
    results = detect_sequence_gaps(names)
    return results[0] if results else None


def _all(names: list[str]) -> list[dict]:
    return detect_sequence_gaps(names)


# ─── basic detection ─────────────────────────────────────────────────────────


def test_simple_sequence_no_gaps():
    pat = _single(["C01", "C02", "C03", "C04", "C05"])
    assert pat is not None
    assert pat["missing_names"] == []
    assert pat["matched_count"] == 5
    assert pat["range"] == (1, 5)


def test_simple_sequence_with_gaps():
    pat = _single(["C01", "C02", "C04", "C05"])
    assert pat is not None
    assert "C03" in pat["missing_names"]
    assert pat["matched_count"] == 4


def test_empty_list_returns_empty():
    assert _all([]) == []


def test_single_name_returns_empty():
    assert _all(["C01"]) == []


def test_two_names_below_min_threshold_returns_empty():
    # _SEQ_MIN_MEMBERS = 3; two entries is not enough
    assert _all(["C01", "C02"]) == []


def test_three_names_meet_minimum():
    pat = _single(["C01", "C02", "C03"])
    assert pat is not None


def test_no_digit_names_returns_empty():
    assert _all(["foo", "bar", "baz"]) == []


# ─── mixed padding ───────────────────────────────────────────────────────────


def test_merges_padded_and_unpadded_same_bucket():
    """C01, C7, C08, C09 must all land in one bucket (prefix='C')."""
    pat = _single(["C01", "C05", "C7", "C08", "C09"])
    assert pat is not None
    assert pat["matched_count"] == 5
    assert pat["range"] == (1, 9)
    # Missing: 2, 3, 4, 6
    assert sorted(pat["missing_nums"]) == [2, 3, 4, 6]


def test_zero_padding_applied_to_missing_when_present():
    """Missing names should be zero-padded if any existing folder uses leading zeros."""
    pat = _single(["C01", "C02", "C04"])
    assert pat is not None
    assert "C03" in pat["missing_names"]


def test_no_padding_when_none_use_leading_zero():
    pat = _single(["C1", "C2", "C4", "C5", "C6"])
    assert pat is not None
    assert "C3" in pat["missing_names"]
    assert "C03" not in pat["missing_names"]


# ─── titles with digits (the main bug) ───────────────────────────────────────


def test_title_with_year_does_not_fragment():
    """C10-NLP-2024 should be prefix='C', num=10, NOT prefix='C10-NLP-', num=2024."""
    names = [f"C{i}-PROJECT-2024" for i in range(1, 11)]  # C1 through C10
    pat = _single(names)
    assert pat is not None
    assert pat["matched_count"] == 10
    assert pat["range"] == (1, 10)
    assert pat["missing_names"] == []


def test_title_with_descriptive_suffix_groups_together():
    """C1-SMART COMMENT and C7 should be in the same bucket."""
    names = [
        "C1-SMART COMMENT CLASSIFICATION",
        "C2-NLP",
        "C3-WEB APP",
        "C5-CHATBOT",
        "C7",
        "C8-AUTH",
    ]
    pat = _single(names)
    assert pat is not None
    assert pat["matched_count"] == 6
    assert pat["missing_nums"] == [4, 6]


def test_real_cse_cohort_pattern():
    """Simulate a realistic D:/CSE-C folder set (the original bug report)."""
    names = [
        "C1-SMART COMMENT CLASSIFICATION",
        "C2-CHATBOT",
        "C3-SPEECH",
        "C4-OCR",
        "C5-NLP",
        "C6-FACE",
        "C7",
        "C08",
        "C09",
        "C10-VISION-2024",
        "C11-AUTH",
        "C13-API",
        "C14-WEB",
        "C15-ML",
        "C17-EAILS",
    ]
    pat = _single(names)
    assert pat is not None
    assert pat["matched_count"] == 15
    assert pat["range"] == (1, 17)
    assert set(pat["missing_nums"]) == {12, 16}


# ─── multiple independent patterns ───────────────────────────────────────────


def test_two_cohorts_reported_separately():
    """A01-A03 and C01-C03 must each be reported as a separate pattern."""
    names = ["A01", "A02", "A03", "C01", "C02", "C03"]
    patterns = _all(names)
    assert len(patterns) == 2
    prefixes = {p["prefix"] for p in patterns}
    assert "A" in prefixes
    assert "C" in prefixes


def test_other_names_on_first_pattern_only():
    """Non-matching names appear in other_names of the first (dominant) pattern."""
    names = ["C01", "C02", "C03", "RANDOM_PROJECT", "README"]
    patterns = _all(names)
    assert len(patterns) >= 1
    # RANDOM_PROJECT and README don't match the seq regex's digit requirement for a group;
    # they should appear in other_names
    other = patterns[0].get("other_names", [])
    assert "RANDOM_PROJECT" in other or "README" in other


# ─── case and whitespace normalization ───────────────────────────────────────


def test_prefix_whitespace_variation_merges():
    """'A1', 'A2 ', 'A3' (trailing space on second folder) must land in one bucket."""
    names = ["A1", "A2 ", "A3"]
    pat = _single(names)
    assert pat is not None
    assert pat["matched_count"] == 3


def test_prefix_case_variation_merges():
    """'a1', 'A2', 'A3' must merge (prefix normalized case-insensitively)."""
    names = ["a1", "A2", "A3"]
    pat = _single(names)
    assert pat is not None
    assert pat["matched_count"] == 3


# ─── edge cases ───────────────────────────────────────────────────────────────


def test_all_numbers_returns_sequence():
    pat = _single(["1", "2", "3", "5"])
    assert pat is not None
    assert 4 in pat["missing_nums"]


def test_large_gap_reported_correctly():
    pat = _single(["A01", "A02", "A03", "A10", "A11", "A12"])
    assert pat is not None
    assert sorted(pat["missing_nums"]) == [4, 5, 6, 7, 8, 9]


def test_sequence_complete_empty_missing():
    pat = _single(["T1", "T2", "T3", "T4"])
    assert pat is not None
    assert pat["missing_names"] == []
    assert pat["missing_nums"] == []

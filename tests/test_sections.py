"""Tier 4 tests: heading classification and the heading stack."""

from __future__ import annotations

from special_export_mcp.wikitext.sections import (
    HeadingStack,
    classify_heading,
    clean_heading_text,
    update_literal_state,
)


def test_classify_level_two_heading() -> None:
    assert classify_heading("== Engine choices ==") == (2, "Engine choices")


def test_classify_tight_spacing_variant() -> None:
    assert classify_heading("==Engine choices==") == (2, "Engine choices")


def test_classify_level_three_with_loose_spacing() -> None:
    assert classify_heading("=== Golf and Jetta ===") == (3, "Golf and Jetta")


def test_classify_level_one_is_accepted() -> None:
    assert classify_heading("= Title =") == (1, "Title")


def test_classify_level_six() -> None:
    assert classify_heading("====== deep ======") == (6, "deep")


def test_non_heading_line_returns_none() -> None:
    assert classify_heading("Not a heading") is None
    assert classify_heading("| a cell") is None


def test_mismatched_equals_count_folds_the_extra_into_the_text() -> None:
    # Real MediaWiki takes the heading level as min(leading, trailing) '='
    # count and keeps any leftover on the longer side as literal text.
    # The regex's own backtracking on \1 produces the same result here.
    assert classify_heading("== mismatched =") == (1, "= mismatched")


def test_heading_text_is_cleaned_through_tier_3() -> None:
    text = clean_heading_text("[[Volkswagen Bora|Bora]]/Jetta Mk4")
    assert text == "Bora/Jetta Mk4"


def test_heading_text_strips_span_anchors_and_italics() -> None:
    raw = "<span class=\"anchor\" id=\"Mk1\"></span>First generation (''Typ'' 1U; 1996)"
    assert clean_heading_text(raw) == "First generation (Typ 1U; 1996)"


def test_stack_pops_entries_at_or_above_the_new_level() -> None:
    stack = HeadingStack()
    stack.push(2, "A")
    stack.push(3, "B")
    stack.push(3, "C")  # sibling: pops B (level >= 3), pushes C
    assert stack.snapshot() == ["A", "C"]


def test_stack_deeper_heading_extends_the_path() -> None:
    stack = HeadingStack()
    stack.push(2, "Engine choices")
    stack.push(3, "Golf and Jetta")
    assert stack.snapshot() == ["Engine choices", "Golf and Jetta"]


def test_stack_shallower_heading_pops_back_up() -> None:
    stack = HeadingStack()
    stack.push(2, "A")
    stack.push(3, "B")
    stack.push(2, "C")  # pops both A and B (both >= 2), pushes C
    assert stack.snapshot() == ["C"]


def test_stack_empty_snapshot_before_any_heading() -> None:
    assert HeadingStack().snapshot() == []


def test_join_uses_the_arrow_separator() -> None:
    assert HeadingStack.join(["A", "B"]) == "A > B"
    assert HeadingStack.join([]) == ""


def test_literal_state_toggles_on_nowiki_open_and_close() -> None:
    state = False
    state = update_literal_state("<nowiki>", state)
    assert state is True
    state = update_literal_state("== not a heading here ==", state)
    assert state is True
    state = update_literal_state("</nowiki>", state)
    assert state is False


def test_literal_state_toggles_on_pre_open_and_close() -> None:
    state = update_literal_state("<pre>", False)
    assert state is True
    state = update_literal_state("</pre>", state)
    assert state is False


def test_literal_state_unaffected_by_unrelated_lines() -> None:
    assert update_literal_state("just text", False) is False
    assert update_literal_state("just text", True) is True

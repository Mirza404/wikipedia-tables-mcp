"""Tier 3 tests: string-in / string-out cell cleaning."""

from __future__ import annotations

from wikipedia_tables_mcp.wikitext.inline import clean_cell


def _clean(raw: str) -> str:
    text, _ = clean_cell(raw)
    return text


def test_piped_wikilink_keeps_the_display_text() -> None:
    assert _clean("[[Straight-four engine|I4]] 16V") == "I4 16V"


def test_piped_wikilink_with_a_section_fragment_in_the_target() -> None:
    assert (
        _clean("[[List of discontinued Volkswagen Group petrol engines#AGN|AGN/BAF]]") == "AGN/BAF"
    )


def test_unpiped_wikilink_keeps_the_whole_target() -> None:
    assert _clean("[[VR6 engine]]") == "VR6 engine"


def test_unpiped_wikilink_drops_the_fragment() -> None:
    assert _clean("[[Foo#Bar]]") == "Foo"


def test_wikilink_inline_with_surrounding_text() -> None:
    assert _clean("1.8 [[Turbocharger|T]]") == "1.8 T"


def test_file_link_is_dropped_entirely() -> None:
    assert _clean("[[File:x.jpg|thumb|caption]]") == ""


def test_category_link_is_dropped_entirely() -> None:
    assert _clean("[[Category:X]]") == ""


def test_image_and_media_namespaces_are_dropped_case_insensitively() -> None:
    assert _clean("[[image:x.jpg|thumb]]") == ""
    assert _clean("[[Media:x.ogg]]") == ""


def test_external_link_with_text() -> None:
    assert _clean("[http://example.com read more]") == "read more"


def test_external_link_without_text_keeps_the_bare_url() -> None:
    assert _clean("[http://example.com]") == "http://example.com"


def test_ref_pair_is_dropped_keeping_the_rest() -> None:
    assert _clean("text<ref>footnote</ref> more") == "text more"


def test_ref_with_attributes_is_dropped() -> None:
    assert _clean('text<ref name="x">footnote</ref> more') == "text more"


def test_self_closing_ref_is_dropped() -> None:
    assert _clean('text<ref name="x"/> more') == "text more"


def test_html_comment_is_dropped_including_multiline() -> None:
    assert _clean("a<!-- comment\nspanning lines -->b") == "ab"


def test_nowiki_keeps_inner_text_literal() -> None:
    assert _clean("<nowiki>[[not a link]]</nowiki>") == "[[not a link]]"


def test_bold_and_italic_keep_inner_text() -> None:
    assert _clean("'''bold''' and ''italic''") == "bold and italic"


def test_br_becomes_a_space() -> None:
    assert _clean("a<br>b") == "a b"
    assert _clean("a<br/>b") == "a b"
    assert _clean("a<br />b") == "a b"


def test_bare_tags_are_stripped_keeping_content() -> None:
    assert _clean("<small>x</small>") == "x"
    assert _clean("<sup>2</sup>") == "2"
    assert _clean('<span style="color:red">x</span>') == "x"


def test_nbsp_entity_becomes_a_normal_space() -> None:
    assert _clean("a&nbsp;b") == "a b"


def test_other_html_entities_are_decoded() -> None:
    assert _clean("a&ndash;b") == "a–b"
    assert _clean("a&amp;b") == "a&b"


def test_reference_markers_are_stripped() -> None:
    assert _clean("value[1]") == "value"
    assert _clean("value[a]") == "value"
    assert _clean("value[note 3]") == "value"
    assert _clean("value[citation needed]") == "value"


def test_whitespace_runs_collapse_to_one_space() -> None:
    assert _clean("a    b\n\nc") == "a b c"


def test_leading_and_trailing_whitespace_is_stripped() -> None:
    assert _clean("   a b   ") == "a b"


def test_template_and_wikilink_together() -> None:
    assert _clean("{{convert|55|kW|PS hp|0|abbr=on}} at 5,500 rpm") == "55 kW at 5,500 rpm"


def test_template_output_is_itself_wikilink_resolved() -> None:
    # Templates resolve before wikilinks (spec 003 section 1): a template
    # whose own output contains raw [[...]] markup must still have that
    # markup resolved afterward, not left as literal brackets.
    assert _clean("{{sortname|[[John Smith]]|}}") == "John Smith"


def test_comment_removed_before_ref_so_a_commented_out_ref_leaves_nothing() -> None:
    assert _clean("a<!-- <ref>x</ref> -->b") == "ab"

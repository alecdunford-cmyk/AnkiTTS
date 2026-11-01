from __future__ import annotations

from speech_text import (
    SPEECH_TEXT_VERSION,
    base_language,
    describe_unusual_characters,
    prepare_for_speech,
)


# Every string below is invented for these tests.


def check_slash_between_english_alternatives():
    for text, expected in (
        ("sb/sth", "sb, or sth"),
        ("to hold sb / sth", "to hold sb, or sth"),
        ("to hold sb /sth", "to hold sb, or sth"),
        ("his/her", "his, or her"),
        ("his/her/their", "his, or her, or their"),
        ("a quiet/loud room", "a quiet, or loud room"),
        ("a quiet / loud room.", "a quiet, or loud room."),
    ):
        assert prepare_for_speech(text, "en") == expected, text


def check_slash_between_french_alternatives():
    for text, expected in (
        ("il/elle", "il, ou elle"),
        ("il / elle", "il, ou elle"),
        ("un/une", "un, ou une"),
        ("le/l'", "le, ou l'"),
        ("l'/la maison", "l', ou la maison"),
        ("se lever / se coucher", "se lever, ou se coucher"),
        ("mon/ma/mes", "mon, ou ma, ou mes"),
        ("beau/belle", "beau, ou belle"),
    ):
        assert prepare_for_speech(text, "fr") == expected, text


def check_slash_wording_follows_the_segment_language():
    assert prepare_for_speech("rouge/vert", "fr") == "rouge, ou vert"
    assert prepare_for_speech("rouge/vert", "en") == "rouge, or vert"
    assert prepare_for_speech("rouge/vert", "fr-FR") == "rouge, ou vert"
    assert prepare_for_speech("red/green", "EN_us") == "red, or green"


def check_slash_that_is_not_an_alternative_is_left_alone():
    for text in (
        "3/4 full",
        "on 12/05/2026",
        "see http://example.invalid/page",
        "60 km/h",
        "10 m/s",
        "n/a",
        "A/C",
        "a // b",
    ):
        assert prepare_for_speech(text, "en") == text, text


def check_and_or_forms():
    assert prepare_for_speech("tea and/or coffee", "en") == "tea and or coffee"
    assert prepare_for_speech("thé et/ou café", "fr") == "thé et ou café"


def check_other_languages_keep_their_slash():
    assert prepare_for_speech("これ/それ", "ja") == "これ/それ"
    assert prepare_for_speech("un/une", "ja") == "un/une"
    assert prepare_for_speech("un/une", "") == "un/une"
    assert prepare_for_speech("un/une", None) == "un/une"


def check_bare_or_in_a_gloss_gets_a_comma():
    for text, language, expected in (
        ("rouge ou bleu", "fr", "rouge, ou bleu"),
        ("rouge ou bleu ou vert", "fr", "rouge, ou bleu, ou vert"),
        ("se lever tôt ou tard", "fr", "se lever tôt, ou tard"),
        ("red or blue", "en", "red, or blue"),
        ("to rush or hurry", "en", "to rush, or hurry"),
        ("to rush or hurry (informal)", "en", "to rush, or hurry (informal)"),
    ):
        assert prepare_for_speech(text, language) == expected, text


def check_existing_comma_before_or_is_kept_once():
    assert prepare_for_speech("rouge, ou bleu", "fr") == "rouge, ou bleu"
    assert prepare_for_speech("red, or blue", "en") == "red, or blue"
    assert prepare_for_speech("run; or flee", "en") == "run; or flee"
    assert prepare_for_speech("two: or three", "en") == "two: or three"
    assert prepare_for_speech("il/elle, ou on", "fr") == "il, ou elle, ou on"


def check_or_is_not_touched_in_example_sentences():
    for text, language in (
        ("Veux-tu du thé ou du café ?", "fr"),
        ("Il viendra lundi ou mardi.", "fr"),
        ("Do you want tea or coffee?", "en"),
        ("She will call today or tomorrow.", "en"),
        ("Il viendra lundi ou mardi. Je ne sais pas.", "fr"),
        ("Is it tea or coffee? Nobody knows", "en"),
        ("He said \"yes or no.\"", "en"),
        ("(Do you want tea or coffee?)", "en"),
    ):
        assert prepare_for_speech(text, language) == text, text


def check_or_is_not_touched_in_long_segments():
    twelve = "one two three four five six seven eight nine ten eleven or"
    thirteen_before = "one two three four five six seven eight nine ten eleven twelve or last"

    assert len(f"{twelve} x".split()) == 13

    assert prepare_for_speech(
        "one two three four five six seven eight nine ten eleven or x", "en"
    ) == "one two three four five six seven eight nine ten eleven or x"
    assert prepare_for_speech(thirteen_before, "en") == thirteen_before

    # Exactly twelve words is still a gloss.
    assert (
        prepare_for_speech("a b c d e f g h i j or k", "en")
        == "a b c d e f g h i j, or k"
    )
    assert len("a b c d e f g h i j or k".split()) == 12


def check_slash_is_rewritten_even_in_a_sentence():
    # The comma rule for bare or/ou is for glosses only; a slash never is.
    assert (
        prepare_for_speech("Il aime le thé/café.", "fr")
        == "Il aime le thé, ou café."
    )
    assert (
        prepare_for_speech("She said he/she was late.", "en")
        == "She said he, or she was late."
    )


def check_symbols_become_pauses_or_are_dropped():
    for text, expected in (
        ("chat → cat", "chat, cat"),
        ("chat→cat", "chat, cat"),
        ("a = b", "a, b"),
        ("quick ≈ fast", "quick fast"),
        ("quick≈fast", "quick fast"),
        ("run [verb] fast", "run fast"),
        ("run {noun} fast", "run fast"),
        ("[verb] run", "run"),
        ("run [verb]", "run"),
        ("run (informal) fast", "run (informal) fast"),
        ("run [a] and {b} fast", "run and fast"),
    ):
        assert prepare_for_speech(text, "en") == expected, text

    # Symbols are language independent.
    assert prepare_for_speech("これ → それ", "ja") == "これ, それ"
    assert prepare_for_speech("chat → [m] cat", "fr") == "chat, cat"


def check_parentheses_are_kept():
    assert (
        prepare_for_speech("faire (quelque chose) = agir", "fr")
        == "faire (quelque chose), agir"
    )


def check_doubled_punctuation_is_collapsed():
    for text, expected in (
        ("A, → B", "A, B"),
        ("A → , B", "A, B"),
        ("A; → B", "A; B"),
        ("A → → B", "A, B"),
        ("A = = B", "A, B"),
        ("a →. b", "a. b"),
        ("→ B", "B"),
        ("= B", "B"),
        ("A →", "A,"),
    ):
        assert prepare_for_speech(text, "en") == expected, text

    # An alternative next to existing punctuation never doubles the comma.
    assert prepare_for_speech("il/elle → on", "fr") == "il, ou elle, on"


def check_nothing_else_is_changed():
    for text, language in (
        ("Le vieux phare brille.", "fr"),
        ("  padded  text ", "en"),
        ("two  spaces", "en"),
        ("A well-known rule (see p. 3): yes!", "en"),
        ("« Bonjour », dit-il.", "fr"),
        ("Voilà : c'est fini ; vraiment ?", "fr"),
        ("wait... what", "en"),
        ("", "en"),
        ("plain", "fr"),
    ):
        assert prepare_for_speech(text, language) == text, repr(text)


def check_no_terminal_punctuation_is_added():
    for text, language in (
        ("a paper lantern", "en"),
        ("une petite barque", "fr"),
        ("rouge ou bleu", "fr"),
        ("sb/sth", "en"),
    ):
        spoken = prepare_for_speech(text, language)

        assert not spoken.rstrip().endswith((".", "!", "?")), spoken


def check_preparation_is_idempotent():
    for text, language in (
        ("il/elle ou on", "fr"),
        ("to hold sb/sth or sth else", "en"),
        ("chat → [m] cat ≈ tiger", "en"),
        ("A, → B = C", "en"),
        ("Do you want tea or coffee?", "en"),
    ):
        once = prepare_for_speech(text, language)

        assert prepare_for_speech(once, language) == once, text


def check_base_language():
    assert base_language("en") == "en"
    assert base_language("FR-ca") == "fr"
    assert base_language("en_US") == "en"
    assert base_language("") == ""
    assert base_language(None) == ""


def check_unusual_characters_are_counted_and_named():
    assert describe_unusual_characters("Le vieux phare brille.") == (0, "")
    assert describe_unusual_characters("« Voilà, c'est l'été (déjà) ? »") == (0, "")
    assert describe_unusual_characters("これは日本語です。") == (0, "")
    assert describe_unusual_characters("a/b → c [x] 3 + 4 = 7") == (
        6,
        "+/=[]→",
    )
    assert describe_unusual_characters("100% ≈ all & more @ home") == (
        4,
        "%&@≈",
    )

    count, characters = describe_unusual_characters("jaune/bleu → vert")

    # Characters only: no letter of the text appears in the description.
    assert (count, characters) == (2, "/→")


def check_version_is_a_nonempty_string():
    assert isinstance(SPEECH_TEXT_VERSION, str) and SPEECH_TEXT_VERSION


def run():
    checks = [
        check_slash_between_english_alternatives,
        check_slash_between_french_alternatives,
        check_slash_wording_follows_the_segment_language,
        check_slash_that_is_not_an_alternative_is_left_alone,
        check_and_or_forms,
        check_other_languages_keep_their_slash,
        check_bare_or_in_a_gloss_gets_a_comma,
        check_existing_comma_before_or_is_kept_once,
        check_or_is_not_touched_in_example_sentences,
        check_or_is_not_touched_in_long_segments,
        check_slash_is_rewritten_even_in_a_sentence,
        check_symbols_become_pauses_or_are_dropped,
        check_parentheses_are_kept,
        check_doubled_punctuation_is_collapsed,
        check_nothing_else_is_changed,
        check_no_terminal_punctuation_is_added,
        check_preparation_is_idempotent,
        check_base_language,
        check_unusual_characters_are_counted_and_named,
        check_version_is_a_nonempty_string,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")

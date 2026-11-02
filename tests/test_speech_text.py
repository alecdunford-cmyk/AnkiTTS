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
        "n/a",
        "A/C",
        "see // there",
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

    assert len(f"{twelve} xylophone".split()) == 13

    assert prepare_for_speech(
        "one two three four five six seven eight nine ten eleven or xylophone", "en"
    ) == "one two three four five six seven eight nine ten eleven or xylophone"
    assert prepare_for_speech(thirteen_before, "en") == thirteen_before

    # Exactly twelve words is still a gloss.
    assert (
        prepare_for_speech("aa bb cc dd ee ff gg hh ii jj or kk", "en")
        == "aa bb cc dd ee ff gg hh ii jj, or kk"
    )
    assert len("aa bb cc dd ee ff gg hh ii jj or kk".split()) == 12


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


def check_arrows_become_pauses_and_approx_is_dropped():
    for text, expected in (
        ("chat → cat", "chat, cat"),
        ("chat→cat", "chat, cat"),
        ("quick ≈ fast", "quick fast"),
        ("quick≈fast", "quick fast"),
    ):
        assert prepare_for_speech(text, "en") == expected, text

    # Arrows are language independent.
    assert prepare_for_speech("これ → それ", "ja") == "これ, それ"


def check_equals_and_plus_are_spoken_between_pauses():
    for text, language, expected in (
        ("cat = dog", "en", "cat, equals, dog"),
        ("cat=dog", "en", "cat, equals, dog"),
        ("old + new", "en", "old, plus, new"),
        ("chat = félin", "fr", "chat, égale, félin"),
        ("de + le = du", "fr", "de, plus, le, égale, du"),
        ("2+2 = 4", "en", "2, plus, 2, equals, 4"),
        ("+5 degrees", "en", "plus 5 degrees"),
    ):
        assert prepare_for_speech(text, language) == expected, text

    # Other languages keep "=" as a plain pause and leave "+" alone.
    assert prepare_for_speech("これ = それ", "ja") == "これ, それ"
    assert prepare_for_speech("これ + それ", "ja") == "これ + それ"


def check_plus_that_is_not_an_operator_is_left_alone():
    assert prepare_for_speech("C++ code", "en") == "C++ code"
    assert prepare_for_speech("a B+ grade", "en") == "a B+ grade"
    assert prepare_for_speech("C++ code", "fr") == "C++ code"


def check_a_grammar_rule_line_is_readable():
    # Invented analogue of a dictionary note on elision and contraction.
    assert prepare_for_speech(
        "Devant une voyelle ou un h muet = l' ; de + le = du ; à + les = aux.",
        "fr",
    ) == (
        "Devant une voyelle ou un ache muet, égale, l' ; de, plus, le, égale, "
        "du ; à, plus, les, égale, aux."
    )


def check_bracketed_labels_are_spoken():
    for text, language, expected in (
        ("run [verb] fast", "en", "run, verb, fast"),
        ("run {noun} fast", "en", "run, noun, fast"),
        ("[verb] run", "en", "verb, run"),
        ("run [verb]", "en", "run, verb"),
        ("[quelqu'un]", "fr", "quelqu'un"),
        ("voir [quelqu'un] partir", "fr", "voir, quelqu'un, partir"),
        ("sparkle → shine [verb] ≈ glitter", "en", "sparkle, shine, verb, glitter"),
        ("run (informal) fast", "en", "run (informal) fast"),
    ):
        assert prepare_for_speech(text, language) == expected, text


def check_parentheses_are_kept():
    assert (
        prepare_for_speech("faire (quelque chose) = agir", "fr")
        == "faire (quelque chose), égale, agir"
    )


def check_doubled_punctuation_is_collapsed():
    for text, expected in (
        ("cat, → dog", "cat, dog"),
        ("cat → , dog", "cat, dog"),
        ("cat; → dog", "cat; dog"),
        ("cat → → dog", "cat, dog"),
        ("cat →. dog", "cat. dog"),
        ("→ dog", "dog"),
        ("= dog", "equals, dog"),
        ("cat →", "cat"),
        ("cat = ", "cat, equals"),
    ):
        assert prepare_for_speech(text, "en") == expected, text

    # An alternative next to existing punctuation never doubles the comma.
    assert prepare_for_speech("il/elle → on", "fr") == "il, ou elle, on"


def check_currency_signs_are_spoken():
    for text, language, expected in (
        ("It costs €20", "en", "It costs 20 euros"),
        ("It costs 20€", "en", "It costs 20 euros"),
        ("It costs € 20", "en", "It costs 20 euros"),
        ("a €1 coin", "en", "a 1 euro coin"),
        ("$2.50/day", "en", "2.50 dollars per day"),
        ("£5", "en", "5 pounds"),
        ("Ça coûte 20 €", "fr", "Ça coûte vingt euros"),
        ("Ça coûte €20", "fr", "Ça coûte vingt euros"),
        ("1 €", "fr", "un euro"),
        ("2,50 €", "fr", "deux virgule cinquante euros"),
        ("12 €/mois", "fr", "douze euros par mois"),
        ("£5", "fr", "cinq livres sterling"),
    ):
        assert prepare_for_speech(text, language) == expected, text


def check_unit_abbreviations_are_spoken_in_english():
    for text, expected in (
        ("5 km and 3 cm", "5 kilometers and 3 centimeters"),
        ("1 km", "1 kilometer"),
        ("20km", "20 kilometers"),
        ("0.5 kg", "0.5 kilograms"),
        ("250 ml", "250 milliliters"),
        ("a 60 km/h limit", "a 60 kilometers per hour limit"),
        ("10 m/s", "10 meters per second"),
        ("a 6 m 2 room", "a 6 square meters room"),
        ("a 6 m² room", "a 6 square meters room"),
        ("3 h 15 min", "3 hours 15 minutes"),
        ("wait 5 s", "wait 5 seconds"),
        ("50 %", "50 percent"),
        ("20 °C and 5°F", "20 degrees Celsius and 5 degrees Fahrenheit"),
        ("1 °C", "1 degree Celsius"),
    ):
        assert prepare_for_speech(text, "en") == expected, text


def check_unit_abbreviations_are_spoken_in_french():
    for text, expected in (
        ("5 km et 3 cm", "cinq kilomètres et trois centimètres"),
        ("1 km", "un kilomètre"),
        ("1,5 kg", "un virgule cinq kilogramme"),
        ("0,05 l", "zéro virgule zéro cinq litre"),
        ("une pièce de 6 m 2", "une pièce de six mètres carrés"),
        ("12 m²", "douze mètres carrés"),
        ("2 m3", "deux mètres cubes"),
        ("14 h 30", "quatorze heures trente"),
        ("90 km/h", "quatre-vingt-dix kilomètres par heure"),
        ("20 °C", "vingt degrés Celsius"),
        ("50 %", "cinquante pour cent"),
        ("1 000 km", "mille kilomètres"),
    ):
        assert prepare_for_speech(text, "fr") == expected, text


def check_bare_unambiguous_units_are_spoken_but_single_letters_are_not():
    assert prepare_for_speech("km", "en") == "kilometers"
    assert prepare_for_speech("cm", "en") == "centimeters"
    assert prepare_for_speech("km", "fr") == "kilomètres"
    assert prepare_for_speech("cm", "fr") == "centimètres"
    assert prepare_for_speech("km, cm, mm", "en") == (
        "kilometers, centimeters, millimeters"
    )

    # Without a number a lone m, g, l, s or h is a letter, not a unit.
    assert prepare_for_speech("the letter m", "en") == "the letter em"
    assert prepare_for_speech("un g muet", "fr") == "un gé muet"


def check_units_are_not_invented_in_other_words():
    for text, language in (
        ("the 1990s", "en"),
        ("in her 20s", "en"),
        ("5 minutes", "en"),
        ("Ce soir", "fr"),
        ("H2O", "en"),
    ):
        assert prepare_for_speech(text, language) == text, text

    # Whole words after a number: only the number is spelled (French).
    assert prepare_for_speech("3 mois", "fr") == "trois mois"
    assert prepare_for_speech("2 heures", "fr") == "deux heures"
    assert prepare_for_speech("le 5 mars", "fr") == "le cinq mars"


def check_french_numbers_are_spelled_out():
    for text, expected in (
        ("0", "zéro"),
        ("7", "sept"),
        ("16", "seize"),
        ("21", "vingt et un"),
        ("22", "vingt-deux"),
        ("71", "soixante et onze"),
        ("72", "soixante-douze"),
        ("80", "quatre-vingts"),
        ("81", "quatre-vingt-un"),
        ("91", "quatre-vingt-onze"),
        ("99", "quatre-vingt-dix-neuf"),
        ("100", "cent"),
        ("101", "cent un"),
        ("200", "deux cents"),
        ("280", "deux cent quatre-vingts"),
        ("1000", "mille"),
        ("1998", "mille neuf cent quatre-vingt-dix-huit"),
        ("2024", "deux mille vingt-quatre"),
        ("80 000", "quatre-vingt mille"),
        ("200 000", "deux cent mille"),
        ("1 000 000", "un million"),
        ("3,5", "trois virgule cinq"),
        ("0,05", "zéro virgule zéro cinq"),
    ):
        assert prepare_for_speech(text, "fr") == expected, text

    # English numerals are left to the engine.
    assert prepare_for_speech("1998 and 21", "en") == "1998 and 21"

    # Codes, leading zeros and digits glued to letters are not numerals.
    for text in ("007", "H2O", "A4", "3D"):
        assert prepare_for_speech(text, "fr") == text, text


def check_french_ordinals_are_spoken():
    for text, expected in (
        ("les romanciers du 20e siècle", "les romanciers du vingtième siècle"),
        ("les romanciers du 20 e siècle", "les romanciers du vingtième siècle"),
        ("le 20ème siècle", "le vingtième siècle"),
        ("le 1er mai", "le premier mai"),
        ("la 1re fois", "la première fois"),
        ("la 1ère fois", "la première fois"),
        ("2e, 3e, 4e, 5e", "deuxième, troisième, quatrième, cinquième"),
        ("9e et 11e", "neuvième et onzième"),
        ("21e", "vingt et unième"),
        ("80e", "quatre-vingtième"),
        ("100e", "centième"),
        ("au XXe siècle", "au vingtième siècle"),
        ("le XIXe siècle", "le dix-neuvième siècle"),
        ("le Ier siècle", "le premier siècle"),
    ):
        assert prepare_for_speech(text, "fr") == expected, text

    # French words that look like Roman numerals stay words.
    for text in ("la Vie est belle", "la Cie du Nord", "Le chat", "Mixe"):
        assert prepare_for_speech(text, "fr") == text, text


def check_lone_letters_are_spelled():
    for text, language, expected in (
        ("un h muet", "fr", "un ache muet"),
        ("vitamine C", "fr", "vitamine cé"),
        ("la lettre w", "fr", "la lettre double vé"),
        ("plan B", "en", "plan bee"),
        ("the letter h", "en", "the letter aitch"),
        ("Option B.", "en", "Option bee."),
    ):
        assert prepare_for_speech(text, language) == expected, text

    # Letters that are words stay words; elisions and abbreviations stay.
    for text, language in (
        ("il a dit y", "fr"),
        ("A paper lantern", "en"),
        ("I think so", "en"),
        ("c'est d' abord", "fr"),
        ("a-t-il fini", "fr"),
        ("T-shirt", "en"),
        ("e.g. this", "en"),
        ("see p. 3", "en"),
        ("C++ code", "en"),
    ):
        assert prepare_for_speech(text, language) == text, text


def check_section_letters_are_spoken_with_a_pause():
    for text, language, expected in (
        ("a) le chat", "fr", "a, le chat"),
        ("b) le chien", "fr", "bé, le chien"),
        ("(c) le chien", "fr", "cé, le chien"),
        ("y) le chien", "fr", "i grec, le chien"),
        ("a) the cat", "en", "ay, the cat"),
        ("(b) the dog", "en", "bee, the dog"),
        ("I) the end", "en", "eye, the end"),
    ):
        assert prepare_for_speech(text, language) == expected, text

    # A plural or feminine marker is not a section letter.
    for text, language in (
        ("friend(s)", "en"),
        ("ami(e)", "fr"),
    ):
        assert prepare_for_speech(text, language) == text, text


def check_multiplication_sign():
    assert prepare_for_speech("2 x 3", "fr") == "deux fois trois"
    assert prepare_for_speech("2 × 3", "en") == "2 times 3"
    assert prepare_for_speech("an x ray", "en") == "an ex ray"


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
        ("cat, → dog = bird", "en"),
        ("Do you want tea or coffee?", "en"),
        ("It costs €20 for 5 km", "en"),
        ("Ça coûte 20 € pour 5 km au 20e siècle", "fr"),
        ("un h muet = d' ; de + le = du", "fr"),
        ("une pièce de 6 m 2 et 3,5 kg", "fr"),
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
        check_arrows_become_pauses_and_approx_is_dropped,
        check_equals_and_plus_are_spoken_between_pauses,
        check_plus_that_is_not_an_operator_is_left_alone,
        check_a_grammar_rule_line_is_readable,
        check_bracketed_labels_are_spoken,
        check_currency_signs_are_spoken,
        check_unit_abbreviations_are_spoken_in_english,
        check_unit_abbreviations_are_spoken_in_french,
        check_bare_unambiguous_units_are_spoken_but_single_letters_are_not,
        check_units_are_not_invented_in_other_words,
        check_french_numbers_are_spelled_out,
        check_french_ordinals_are_spoken,
        check_lone_letters_are_spelled,
        check_section_letters_are_spoken_with_a_pause,
        check_multiplication_sign,
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

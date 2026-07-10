from lingua import Language, LanguageDetectorBuilder


detector = (
    LanguageDetectorBuilder
    .from_languages(
        Language.FRENCH,
        Language.ENGLISH,
        Language.JAPANESE,
    )
    .build()
)


def detect_language(text):
    result = detector.detect_language_of(text)

    if result == Language.FRENCH:
        return "fr"

    if result == Language.ENGLISH:
        return "en"

    if result == Language.JAPANESE:
        return "ja"

    return None


def detect_with_confidence(text):
    confidence = detector.compute_language_confidence_values(text)

    if not confidence:
        return None, 0

    best = confidence[0]

    language_map = {
        Language.FRENCH: "fr",
        Language.ENGLISH: "en",
        Language.JAPANESE: "ja",
    }

    return (
        language_map.get(best.language),
        best.value
    )
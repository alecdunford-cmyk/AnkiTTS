from detector import detect_language


def parse_text(text):
    lines = text.splitlines()

    chunks = []

    for line in lines:
        line = line.strip()

        if not line:
            continue

        language = detect_language(line)

        chunks.append(
            {
                "language": language,
                "text": line
            }
        )

    return chunks
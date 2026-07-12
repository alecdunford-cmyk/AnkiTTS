def create_note_job(
    front,
    back,
    front_language=None,
    generate_front=True,
    generate_back=True,
):
    return {
        "front": front,
        "back": back,
        "front_language": front_language,
        "generate_front": generate_front,
        "generate_back": generate_back,
    }
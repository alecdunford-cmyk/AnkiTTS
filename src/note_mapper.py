def create_note_job(
    front,
    back,
    front_language=None,
):
    return {
        "front": front,
        "back": back,
        "front_language": front_language,
    }
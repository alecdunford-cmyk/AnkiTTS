from parser import parse_text


sample = """
aborder

to approach

J'ai abordé le problème.

I approached the problem.
"""


chunks = parse_text(sample)


for chunk in chunks:
    print(
        chunk["language"],
        "→",
        chunk["text"]
    )
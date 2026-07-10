from parser import parse_text


sample = """
rundown, spiel; Ex. faire un topo sur (give a rundown on), c'est toujours le même topo (it's always the same old story), Tu vois un peu le topo? (Get the picture?)
"""


chunks = parse_text(sample)


for chunk in chunks:
    print(
        chunk["language"],
        "→",
        chunk["text"]
    )
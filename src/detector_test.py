from detector import detect_language


examples = [
    "Bonjour, comment allez-vous ?",
    "I am studying French.",
    "私は日本語を勉強しています。",
]


for example in examples:
    print(example)
    print("→", detect_language(example))
    print()
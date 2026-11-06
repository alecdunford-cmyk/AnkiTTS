# AnkiTTS — Claude Code project memory

AnkiTTS is a local Anki add-on that generates multilingual TTS audio
(Microsoft Edge Neural voices) for Anki cards. It is a companion to RCE (a
separate C# repository) but must remain fully usable on its own — the
generic field-mapping/synthesis path is the core product, and RCE support is
additive, never a replacement for it.

## Quick facts

- Language: Python 3.13.
- Layout: `src/` (core logic), `addon/` (Anki add-on entry point and
  settings dialog), `tests/`, `docs/`, `validation_deck/`.
- Run tests: `python tests/run_tests.py`. This requires `edge_tts`, `anki`,
  and the add-on's other dependencies installed in the active Python
  environment — without them, imports fail before any test body runs.
- The RCE↔AnkiTTS contract boundary lives in `src/rce_contract.py`. RCE owns
  linguistic/editorial content, article/scope selection, and card creation.
  AnkiTTS owns speech-profile/voice resolution, synthesis, caching, trimming/
  stitching, and audio publication into Anki. Do not blur this boundary.
- Requirements for the accepted ordinary path: Anki 26.x, Python 3.13+,
  FFmpeg, Microsoft Edge Neural TTS. Since ruling CA-38 (2026-11-06, reversing
  CA-3) the default provider chain is Edge alone; Kyutai Pocket TTS (local,
  separate engine venv) and Fish Audio stay wired and configured but off, so the
  ordinary path needs nothing more. No other TTS provider (e.g. ElevenLabs)
  belongs in the default configuration. Design and rulings:
  `docs/DESIGN-providers.md`; speech plan v2 and role voices are its section 18.
- The live add-on reads Anki's add-on config (`addon/config.json` overlaid by
  `addon/meta.json["config"]`), not `settings.json`.
- Keep Alec's personal `settings.json` untouched and unstaged unless he
  explicitly asks for a settings change.
- Before proposing any source edit, inspect the actual current repository
  bytes and tests — do not reconstruct file contents from prose memory or
  older chat context.

## Session guidance

At the start of any substantial task, state the recommended effort
level (Low / Medium / High / Extra) for that specific task, with one
line of reasoning — e.g. "well-specified implementation against an
already-agreed design → Medium-High" vs. "genuinely open-ended
debugging with an unclear root cause → Extra/xhigh". Alec relies on
this recommendation and does not want to have to ask for it.

If a task represents a genuinely new, independent line of work
unrelated to what's already been done in this session (check
CLAUDE.md's linked docs and recent commits if unsure), say so
explicitly and suggest whether it warrants a fresh session rather than
continuing in this one.

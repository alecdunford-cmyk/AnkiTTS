# Changelog

All notable changes since the v1.0.0 release. Dates are commit dates.
Versions are tagged by the maintainer; everything below "Unreleased" is not yet
in a tagged release.

## Unreleased

### Language to Edge's multilingual voices (2026-11-06)

Rulings CA-55 (Alec) and CA-56 to CA-60, `docs/DESIGN-providers.md`, section 18:

- **Short French and English segments are no longer read in the wrong language.**
  Edge's multilingual voices pick a language from the text, so a headword, a
  label or a word spelled alike in both languages came out English. The Edge
  endpoint takes no language in SSML (a `<lang>` element returns no audio; a
  top-level `xml:lang` changes the sound the same for any locale), so a segment
  of one to four words is now spoken after a short sentence in its language,
  and the sentence is cut off again using the word offsets Edge returns.
- Only on multilingual voices, and only for French and English. Longer text,
  monolingual voices and Japanese are unchanged. If the cut cannot be made the
  segment is generated as before.
- **Every Edge clip regenerates once** (`edge_language_version`), so the audio
  already cached with the wrong reading refills. If the French slots on the
  Speech Plans tab still name Denise and Henri (an earlier choice saved in the
  dialog), they keep speaking as those voices do; pick the multilingual voices
  there to use this.

### Speech plan v2, role voices, earcons, proportional pauses (2026-11-06)

Rulings CA-41 (Alec) and CA-42 to CA-53, `docs/DESIGN-providers.md`, section 18:

- **Edge is the default provider** (Alec's CA-38). The default chain is `edge`;
  Pocket and Fish stay wired and configured but off. A saved configuration that
  holds the old default order moves on load, and nothing is written until the
  settings are saved.
- **Speech plan schema version 2**, parsed beside version 1: roles, voice roles,
  pause kinds, earcons, pairs, a preset and a tempo profile.
- **Role voices** (CA-41): one content and one label voice per language, with
  Alec's four defaults, each switchable on the new Speech Plans tab. Changing one
  regenerates that role's audio only.
- **Tempo profiles and proportional pauses:** a pause is computed at stitch time
  from the length of the speech it follows, clamped by the plan's tempo profile.
- **Earcons:** three short default tones generated once into `user_files`, each
  replaceable, placed where the plan says.
- **Version 1 plans and plain notes are unchanged by the schema**: for a given
  provider and voice, their cache keys and track names are byte for byte what
  they were. They keep their speech profile voices until RCE emits version 2.
  The move to Edge is a provider change, so a card regenerated now is Edge audio
  in those voices, generated once if Edge has not made it before. Audio already
  in Anki stays until its card is regenerated.
- **The Speech Profiles voice lists offer every Edge voice**, the language's own
  first. A multilingual voice from another locale can now serve a language, so
  version 1 cards can use a CA-41 voice before RCE emits version 2. Choosing a
  new voice regenerates the cards that use it, as any voice change does.

### Speech providers (2026-11-01)

- **Provider seam.** Synthesis goes through a `Provider` interface
  (`src/providers/`) and a registry. `generator.create_audio` walks a
  configurable fallback chain: for each provider, its cache, else its synthesis.
  Design: `docs/DESIGN-providers.md` (rulings CA-3 to CA-13 and later).
- **Kyutai Pocket TTS** (6-layer `french` / `english`) is the primary provider
  for French and English, cloned from reference clips configured by path. It
  runs in a separate worker process from its own Python 3.12 environment,
  speaking JSON lines over stdin/stdout. The worker starts on demand, is reused
  across a batch and stops when idle.
- **Fish Audio** (`s2.1-pro`) is the second provider. Voice ids come from
  settings and the key from `FISH_API_KEY`.
- **Microsoft Edge** is the last-resort fallback, with behaviour unchanged.
- Default chain `pocket, fish, edge`. Unconfigured providers are skipped, so
  installs without Pocket or Fish keep using Edge.
- Rate is applied with ffmpeg `atempo` (0.5–2.0×) for providers without native
  rate. Pitch and volume remain Edge-only.
- **Cache:** the generic key now includes the producing provider's identity,
  and the structured key adds the reference-clip hash or voice id for non-Edge
  providers. Structured track filenames hash each segment's provider identity.
  Existing caches refill once.
- **Settings:** new `provider_chain` and `providers` keys, merged over defaults
  on load, so older configurations migrate without edits. The Settings dialog
  has a minimal Providers tab.

### Audio defects (2026-11-01)

- **Cut-off endings fixed.** The stitcher trimmed trailing silence at
  -45 dBFS, only 9 dB under the average level of Pocket's English voice, and
  clipped the last syllable. It now trims at -60 dBFS and keeps a 50 ms margin
  (`docs/audio-tail-diagnosis-20261101.md`). Pauses between segments can be up
  to 50 ms longer than before.
- **Speech text preparation** (`src/speech_text.py`), applied to the text every
  provider receives: a slash between alternatives is spoken as ", or" (English)
  or ", ou" (French); a bare "or"/"ou" in a short sentence-less gloss gets a
  comma; "→" becomes a pause and "≈" is dropped (the first version also
  dropped `[...]` labels and made "=" a pause; see "round 2" below).
  Example sentences are left alone.
- **Cache:** every provider identity now carries `speech_text_version`, so
  cached audio and published track names change once. The key is made from the
  original text, never the prepared text.
- **Log:** per segment, a count of unusual characters and their set (never the
  text).
- Design and rulings CA-21 to CA-28: `docs/DESIGN-providers.md`, section 15.

### Loudness normalisation (2026-11-01)

Rulings CA-35 to CA-41, `docs/DESIGN-providers.md`, section 17:

- **Every provider's clip is normalised to -16 LUFS before it is cached**
  (Pocket, Fish and Edge), so a card mixing English and French no longer has
  a level step (the English clone was about 12 dB quieter). Where reaching the
  target would pass -1.5 dBTP, a limiter holds the peaks (at most 12 dB of it);
  such a clip may end up 1 to 2 LU short. It never clips. Very short clips are
  measured looped; silence is left alone.
- `loudness_version` is in every provider identity, so cached audio and track
  names refill once more.
- **MP3 quality:** clips and stitched tracks are now encoded at 96 kbit/s. The
  old default (about 32 kbit/s) was poor for the English voice and made a
  stitched track overshoot to full scale.
- **Trim threshold -60 to -50 dBFS** (the normalised tails are louder).
- Fish audio is now always re-encoded (it was renamed into the cache at tempo 1).

### Speech text, round 2 (2026-11-01)

From listening to the first corrected card (`speech_text_version` 2, rules and
rulings CA-29 to CA-33 in `docs/DESIGN-providers.md`, section 15):

- **Spoken, no longer dropped or garbled:** currency signs (`€20` is "20
  euros"), unit abbreviations in English and French (`km`, `cm`, `m²`, `km/h`,
  `°C`, `%`, `h`, `min`, ...), bracketed `[...]` labels, `=` ("equals" /
  "égale") and `+` ("plus"), each between two pauses, `×`, and lone letters
  such as `h` ("ache" / "aitch"). Section letters `a)` and `(b)` are spoken.
- **French numerals** are spelled out ("1 250" is "mille deux cent
  cinquante") and **French ordinals** are spoken ("20 e siècle", "XXe siècle"
  is "vingtième siècle"; "1er" is "premier").
- `[...]` labels, previously dropped, are now spoken, in the flow of the sentence
  with no pause (supersedes part of CA-21; CA-29, CA-34). `speech_text_version` 3.
- Hyphenated units before a noun ("a 3-km/3-hour walk") are expanded and singular.
- Parked: a different voice for headings/notes and spoken section numbers
  (needs RCE to mark segments and a profile-aware provider identity).

### Repairs (2026-11-01)

- edge-tts 7.2.8 → **7.3.1**. 7.2.8 failed the Edge handshake with HTTP 403.
- `addon/libs` rebuilt for Python 3.13 from the new pin file
  `addon/requirements-libs.txt`. The vendored copy now imports `edge_tts` on its
  own (the `attr` package was missing).
- Logging: a rotating log at `addon/user_files/logs/ankitts.log`.
- The add-on runs the repository's `src` when loaded from the checkout, so a
  stale `addon/src` mirror is never used.
- Documented that the live add-on's settings are Anki's add-on config. Added
  `read_addon_config` / `SettingsManager.load_addon_config` for development runs.
- `deploy.bat` rewritten. It refreshes `addon/src` and rebuilds `addon/libs`,
  and no longer copies a missing `config.json`.
- The test runner prints correctly on a cp1252 Windows console.

### Structured RCE audio (2026-07-23 to 2026-08-03)

- Strict parser for RCE speech plans (`schemaVersion` 1) and the structured
  RCE job contract (`b2d97d6`, `cf28306`).
- Structured speech resolution: profiles, logical voice-profile aliases, and
  rate composition (`6334936`).
- Structured RCE audio engine with exact pauses, transactional publication and
  a provider-aware cache (`9558150`), integrated with the Anki browser and
  editor (`98cea1b`).
- Edge synthesis retries `NoAudioReceived` with bounded backoff (`fafe221`).
- Automated RCE audio processing through `rce-audio::*` tags (`a552ac0`).
- Up to three missing structured segments synthesised in parallel (`bc67b88`).
- RCE polling suspended and resumed across profile and collection transitions
  (`149a9b0`, `79a5f5f`).
- Interrupted RCE audio generation recovered after a restart (`c6aefce`).

### Project

- Session guidance added to `CLAUDE.md` (`e4576ae`).

## 1.0.0 (2026-07-14)

Initial stable release (`c532ba0`): Edge Neural voices, automatic language
detection, speech profiles, field mappings, browser batch generation, audio
cache, validation deck and regression tests.

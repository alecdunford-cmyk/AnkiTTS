# Changelog

All notable changes since the v1.0.0 release. Dates are commit dates.
Versions are tagged by the maintainer; everything below "Unreleased" is not yet
in a tagged release.

## Unreleased

### English was spoken by a German voice: a withdrawn Edge voice is replaced (2026-11-13)

Ruling CA-95 (Alec, 2026-11-13) and CA-96 to CA-102,
`docs/DESIGN-providers.md`, section 18:

- **The cause.** Edge withdrew `de-DE-SeraphinaMultilingualNeural`, the English
  content voice (CA-41), and answers a request naming it, with no error, in
  `de-DE-TanjaNeural`, a German voice that is not multilingual, reading English as
  German. French and every label were unaffected (their voices still exist). Nothing
  in AnkiTTS changed the request.
- **The fix.** A withdrawn Edge voice (`settings.WITHDRAWN_EDGE_VOICES`) is replaced
  wherever it is stored (voices, speech profiles, role-voice slots) when the settings
  load; nothing is written back. Seraphina's replacement, and the new English content
  default, is `en-US-AvaMultilingualNeural`; it can be changed in **Tools > AnkiTTS
  Settings...**.
- **The log names the voice.** Each "synthesized" line now says which voice the
  segment asked for.
- **What refills.** The voice is in every cache key, so only English content clips,
  the English "or," clip and the tracks holding them are made again; French clips and
  labels are reused. No version moved. A published card is not picked up again by
  itself: select the cards in the Browse window and use **Notes > Generate AnkiTTS
  Audio for Selected Notes** (no re-export from RCE is needed).

### "or" after a main translation, symbols reach the voice, an ffmpeg timeout (2026-11-12)

Ruling CA-90 (Alec, 2026-11-12) and CA-91 to CA-94,
`docs/DESIGN-providers.md`, section 18:

- **"or" / "ou" after a gloss and an idiom heading.** An alternative whose previous
  spoken segment is a `gloss` (a sense's main translation) or an `idiomHead`, of the
  same node and language, is now preceded by "or," / "ou," like one after a
  translation or an example line. Every other condition is unchanged; a `gloss`
  segment itself never takes the word.
- **Symbols reach the voice.** Proven for 17 signs in English and French at the
  provider and at Edge's library. Fixed: a sign's word glued to the word or number
  beside it (`%50`, `word€`), `n°` read as degrees, and a letter touching `&` spelled
  out (`R&D`). A currency or degree sign touching a letter (`n°`, `M€`) is left as
  written.
- **ffmpeg runs are bounded.** Every ffmpeg run under `src/providers` is ended after
  120 seconds (`FFMPEG_TIMEOUT_SECONDS`) and reaped; in a batch run that note fails
  alone (not published, audited silent, left pending without `immediate`) and the run
  goes on. The stitch's own ffmpeg runs (pydub, `src/stitcher.py`) are not bounded yet.
- **What refills.** `speech_text_version` 4 → 5: every segment's audio refills once,
  the next time its card is generated. No other version moved.

### Anki no longer freezes while audio is generated (2026-11-10)

Ruling CA-81 (Alec, 2026-11-09 and 2026-11-10) and CA-82 to CA-89,
`docs/DESIGN-providers.md`, section 18. With the add-on enabled Anki went Not
Responding for the length of a batch and again at every start:

- **The run no longer holds Anki's main thread.** The notes are read and the
  jobs built on the main thread, synthesis, stitching and copying run on a
  background thread, and the fields are written and the result shown back on the
  main thread. This applies to the automation (the poll, **Tools > Generate
  Pending RCE Audio**) and to **Generate AnkiTTS Audio for Selected Notes**. One run
  at a time; closing the profile stops a run between notes; a run is never written
  into a different collection.
- **The audio audit cannot block.** An unattended run shows no box: it logs the
  audit's line, records its counts in the outcome, and shows a notice (Anki's
  tooltip, 20 seconds, once per run). A run started by hand shows the one result
  box, with the audit in it.
- **Start-up.** The resume of pending audio is scheduled three seconds after the
  collection opens and a failure in it is logged, not raised. Pending audio is still
  generated at start-up, in the background.
- **An empty plan never clears audio.** A side whose plan has no spoken segment keeps
  the audio its field holds; the audit still counts it. A side with a new track
  replaces its field as before; the generic path (plain notes) still clears an empty
  track.
- **The log says where a run is** (`Audio run: note i of N done.`), counts only.
- **What refills.** Nothing: no cache or track version moved.

### Three earcons, the "or" after an example, the audio audit (2026-11-09)

Ruling CA-71 (Alec, 2026-11-09) and CA-72 to CA-80,
`docs/DESIGN-providers.md`, section 18:

- **Three new earcons, each played before what it marks.** `sectionNumber` (a
  numbered section), `sectionLetter` (a lettered sub-section) and `idiomHeading`
  (an idiom block's heading inside a sense) are accepted in a plan's
  `earconBefore` only; in `earconAfter` they are a validation error. The old
  three (`sectionBoundary`, `answerStart`, `directionFlip`) are still accepted
  in both places. Default tones are generated into `user_files/earcons` and can
  be replaced by a file in the earcons map; the dialog's earcon list has a row
  for each.
- **"or" / "ou" after an example line.** An alternative that continues an
  example's source or target line (not only a translation) is preceded by the
  content voice saying "ou" after a French line and "or" after an English one,
  with a short pause each side.
- **Audio audit.** Every run now reports, as counts and note ids and never card
  text: silent sides (speech in the plan, no audio), empty sides (a plan with
  nothing to speak) and rejected plans. Quiet (`0 silent sides`) when clean; a
  banner and a warning box when not; a warning for an unattended run.
- **What refills.** Nothing: no cache version moved. A track changes only if it
  now has an "or" or one of the new earcons.

### Tags, "or" between alternatives, "[somebody]'s" (2026-11-07)

Ruling CA-61 (Alec; parts 4, 7 and 9) and CA-62 to CA-70,
`docs/DESIGN-providers.md`, section 18:

- **A tag is spoken close to the word it qualifies.** Speech plan v2 accepts an
  optional `attachedTo` (the `segmentId` of the segment a tag or label
  qualifies; version 1 plans reject it). The pause on the side of the tag that
  faces its owner is a new tempo-profile field, `tightPauseMs` (120 ms, in the
  Speech Plans table as "Tag / or pause (ms)"), whatever the plan says there.
  Nothing else about the pauses changes.
- **"or" between the translation alternatives of an example.** An alternative
  that follows a translation or an alternative of the same example and
  language is preceded by the content voice saying "or" ("ou" for French), with
  a short pause each side in place of the pause the plan would have put there.
  The word is one cached clip per language and voice. A sense's gloss list is
  untouched.
- **`[somebody]'s` is spoken `somebody's`** (and `[x]-like`, `l'[objet]`): a
  bracket that touches a letter, an apostrophe or a joining hyphen keeps no
  space on that side. Contractions and possessives were never spelled as
  letters.
- **What refills.** `speech_text_version` is now `"4"`, so every segment's audio
  regenerates once on the next run. Every version 2 track is rebuilt once from
  the cached audio (`stitch_version` `"2"`). Tags are attached only when a plan
  carries `attachedTo`, which RCE's next card stage is to emit; an "or" is
  spoken wherever a plan already has an `alternative` after a `translation` or
  `alternative` of the same `contentNodeId` and language.

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

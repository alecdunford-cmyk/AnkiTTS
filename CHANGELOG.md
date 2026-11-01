# Changelog

All notable changes since the v1.0.0 release. Dates are commit dates.
Versions are tagged by the maintainer; everything below "Unreleased" is not yet
in a tagged release.

## Unreleased

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

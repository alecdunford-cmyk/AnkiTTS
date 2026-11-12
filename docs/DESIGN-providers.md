# AnkiTTS synthesis providers: design

Status: accepted design, built in stages B–H on 2026-11-01. This document is
the durable home of the card-and-audio rulings CA-3 onward. CA-1 and CA-2 are
in `D:\RCE-Project-Archive\Session-Handoffs\AnkiTTS-Card-Audio-Bakeoff-Plan-20261029.md`.
The audio-defect fixes of the same day (ruling CA-21 and CA-22 to CA-28: the
trim margin and speech-text preparation) are in section 15, loudness in section
17, and speech plan v2 with role voices (CA-41, CA-42 onward) in section 18.

## 1. Why

Up to v1.0.0 and the structured-RCE commits, `generator.create_audio` called
`edge_tts` directly. No other engine could plug in, and the generic path's
cache key did not record which engine made a file. Ruling CA-3 made Kyutai
Pocket TTS the primary engine, Fish Audio the second provider and Edge the
last resort. This design is the seam that made that possible. **CA-38 (Alec,
2026-11-06) reversed the order:** Edge is primary and the other two stay wired
but off, which the seam made a change of one default (sections 3 and 18). This
section and the ones after it describe the seam and hold for any order.

The RCE↔AnkiTTS boundary (`src/rce_contract.py`) does not move. RCE still
says *what* is spoken: text, language, voice profile id, speaking-rate
multiplier and pauses. AnkiTTS still decides *how*: provider, voice, cache,
trimming, stitching and publication. Provider choice is an AnkiTTS setting,
never part of the speech plan.

## 2. The Provider interface

`src/providers/base.py`:

```python
@dataclass(frozen=True)
class Capabilities:
    languages: frozenset[str] | None  # AnkiTTS profile languages; None = any
    native_rate: bool                 # False: rate applied by ffmpeg atempo
    volume: bool                      # False: volume ignored
    pitch: bool                       # False: pitch ignored
    local: bool                       # runs on this machine
    max_parallel: int                 # concurrent synthesize() calls it serves

@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str

class ProviderError(RuntimeError): ...          # synthesis failed
class ProviderUnavailable(ProviderError): ...   # not configured / not reachable

class Provider(ABC):
    provider_id: str                  # registry id: "pocket", "fish", "edge"

    def identity(self, language) -> dict[str, str]: ...
    def capabilities(self) -> Capabilities: ...
    def voices(self, language) -> list[str]: ...
    def health(self, language=None) -> HealthStatus: ...
    def cache_fields(self, language, profile) -> dict: ...
    def synthesize(self, text, language, profile, output_path) -> None: ...
    def close(self) -> None: ...
```

- `identity(language)` returns at least `provider`, `provider_model` and
  `provider_version`, plus whatever else selects the voice: `reference_sha256`
  (Pocket) or `reference_id` (Fish), and `speech_text_version` (every
  provider, section 15). It feeds the cache key and the track
  filename. It must be cheap, because it is computed before every cache lookup.
  Pocket reads its version from the engine venv's `dist-info` and hashes the
  clip once per (path, size, mtime), so it never starts the worker.
- `cache_fields(language, profile)` returns the `voice`, `rate`, `volume` and
  `pitch` values that change this provider's audio. A field the provider
  ignores is `None`, so changing an ignored Edge pitch does not invalidate
  Pocket's cache.
- `synthesize(text, language, profile, output_path)` writes a non-empty MP3 at
  `output_path`, or raises `ProviderError` and leaves nothing behind. `profile`
  is the existing `settings.SpeechProfile` (language, voice, rate, volume,
  pitch). On the structured path `profile.rate` is already composed with the
  plan's `speakingRate` (`compose_edge_rate`).
- `health(language)` is cheap and makes no paid call. It checks the
  configuration (paths exist, key present, reference set for that language).
  It also reports a recent start or synthesis failure (a 60 s cool-down), so
  a dead provider is not retried for every segment of a batch.
- `voices(language)`: Edge lists its neural voices; Pocket and Fish return
  the one cloned voice configured for that language (or none).

`src/providers/registry.py` maps ids to classes and resolves the chain:

```python
PROVIDER_CLASSES = {"pocket": PocketProvider, "fish": FishProvider, "edge": EdgeProvider}
get_provider(provider_id, settings) -> Provider    # cached per (id, config)
resolve_chain(settings) -> list[Provider]          # settings.provider_chain
set_override_chain(providers | None)               # tests only
close_all()
```

Instances are cached per id and per provider config (sorted JSON), so a
batch reuses one Pocket worker, and a settings change builds a new one and
closes the old.

### The thin `create_audio`

`generator.create_audio(text, language, profile, cache_path_for, settings=None, chain=None)`
walks the chain and returns `SynthesisResult(path, identity, provider_id, generated)`:

```
for provider in chain:
    if language not in provider.capabilities().languages: record "unsupported"; continue
    identity = provider.identity(language)
    path     = cache_path_for(identity, provider.cache_fields(language, profile))
    if path is a non-empty file: return (path, identity, cached)
    health = provider.health(language)
    if not health.ok: record health.detail; continue
    try: provider.synthesize(text, language, profile, path)
    except Exception as e: delete path; record e; continue
    if path is a non-empty file: return (path, identity, generated)
raise SynthesisFailed(every provider's reason)
```

`card_processor` and `structured_audio` call only this. Neither imports a
provider or `edge_tts`. Before this work `card_processor` imported
`generator.create_audio` and `structured_audio` imported `create_audio` and
`get_edge_provider_identity`. Only `generator.py` and `voice_manager.py`
imported `edge_tts`.

## 3. Fallback

- Settings key `provider_chain`, default `["edge"]` since CA-38 (Alec,
  2026-11-06), which reversed CA-3: Edge is primary, and Pocket and Fish stay
  wired and configured but off. It was `["pocket", "fish", "edge"]`; a config
  saved with that value moves on load (section 18, CA-45). The text below still
  holds for any chain that lists them.
- A provider that cannot serve the language, fails health or fails synthesis
  hands the segment to the next one, and the reason is logged.
- **Cache precedence (CA-6):** for each provider in order, its cached file is
  used if present; otherwise it synthesises. The cache of a later provider is
  consulted only after the earlier provider has failed for that segment. Once
  Pocket recovers, Pocket audio is made again rather than serving Edge
  stand-ins forever. The cost is one health check per uncached segment.
- The cache key records the provider that produced the file, because the key
  is computed from that provider's identity.
- On the structured path one card may mix providers (for example a Japanese
  segment on Edge). The track filename hashes each segment's identity (CA-11).
- If every provider fails, `SynthesisFailed` lists every reason. The generic
  path counts the chunk as skipped, as it did for Edge's no-audio. The
  structured path raises `StructuredAudioProcessingError` and publishes nothing.

## 4. Cache keys

| Path | Key (SHA-256 of sorted-key JSON) |
|---|---|
| Generic (before) | text, language, voice, rate, volume, pitch |
| Generic (now) | the above with voice/rate/volume/pitch from `cache_fields`, **plus every identity field** |
| Structured (before) | provider, provider_model, provider_version, text, language, profile_key, voice, rate, volume, pitch |
| Structured (now) | the same keys, plus any extra identity fields (`reference_sha256`, `reference_id`), each only when present |

The structured key keeps its exact shape for Edge: no extra fields and the
same names. Old Edge structured entries still match while the edge-tts version
is unchanged. The edge-tts bump to 7.3.1 changes `provider_version`, and the
generic key gains fields, so both caches refill once after this release. No
cached file is deleted. `Clear audio cache` in the settings dialog still
removes everything.

Since the audio-defect fixes (section 15) every provider identity also carries
`speech_text_version`, so the Edge structured key gains that one field too and
every cache entry and track filename changes once more (one refill, accepted
in CA-21's brief). The text in the key is always the **original** text; the
prepared text is never keyed.

Loudness normalisation (section 17) adds one more identity field on every
provider, `loudness_version`, with the same effect: one refill, no file deleted.

## 5. Rate, pitch and volume

| | Edge | Pocket | Fish |
|---|---|---|---|
| Rate | native (`+N%`) | ffmpeg `atempo` after synthesis | ffmpeg `atempo` after synthesis |
| Volume | native | **ignored** | **ignored** |
| Pitch | native | **ignored** | **ignored** |

- Rate is carried as the Edge-format string it already is (`+10%`). The
  structured path has already composed the profile rate with the plan's
  `speakingRate` multiplier (`compose_edge_rate`). A provider without native
  rate turns it back into a multiplier (`parse_edge_rate_multiplier`) and
  applies `atempo` while encoding the MP3. The multiplier is bounded to
  **0.5–2.0**: values outside are clamped and logged. At exactly 1.0 no
  filter is applied.
- Volume and pitch are Edge concepts. Pocket and Fish ignore them, leave them
  out of their cache keys (CA-10) and log once per provider instance when a
  non-default value is ignored. **Loudness is normalised per
  segment at encode time, for every provider (section 17, CA-35).** An earlier
  version of this document said the stitcher already did this. It did not (it
  trims and joins only), and Pocket's English clone measured about 12 dB
  quieter than its French clone, so a mixed card had a level step. That is
  now true: each clip is brought to -16 LUFS before it is cached, and the
  stitcher still trims and joins only.

## 6. Pocket TTS worker

Pocket TTS needs torch, which cannot be installed into Anki's bundled Python
(3.13.13, embedded, no pip). It therefore runs as a separate process from its
own venv.

- Engine venv: `C:\AnkiTTS-engine-env`, Python 3.12, `torch==2.15.0` (CPU
  wheel) and `pocket-tts==4.0.1`, the versions rated in Round 1b (CA-9).
  Nothing else is installed into it. Models come from the Hugging Face cache
  (`kyutai/pocket-tts`; the 6-layer `french` and `english` configs).
- Worker script: `src/providers/pocket_worker.py`. It uses only the standard
  library plus `pocket_tts`, `torch` and `numpy` (pocket-tts dependencies) and
  never imports add-on code. It is launched as
  `<engine python> -I -u pocket_worker.py`, with no console window
  (`CREATE_NO_WINDOW`).
- Launched on demand by the first Pocket synthesis. It is reused across
  segments, notes and batches, and closed after `idle_shutdown_seconds`
  (default 300) without requests (CA-13), when the add-on's settings change,
  or at interpreter exit. Requests are serialised by a lock: `max_parallel = 1`.
- It holds one language model at a time. A request for the other language
  unloads the first. It caches the voice state per (language, reference path,
  reference sha256), so the clip is encoded once per model load.

### Protocol (CA-5): JSON lines over stdin/stdout

One UTF-8 JSON object per line in each direction, strictly request→response,
with `id` echoed. stdout carries only protocol lines. Everything else
(warnings, progress, tracebacks) goes to stderr, which the add-on drains into
its log.

| op | request fields | response fields (besides `id`, `ok`) |
|---|---|---|
| `hello` | `protocol` (1) | `protocol`, `worker_version`, `pocket_tts_version`, `torch_version`, `python` |
| `synthesize` | `model` (`french`/`english`), `reference` (path), `reference_sha256`, `text`, `output` (WAV path) | `sample_rate`, `audio_seconds`, `load_seconds` (0 if loaded), `voice_seconds` (0 if cached), `synth_seconds` |
| `shutdown` | — | — (then exits 0) |

Failure: `{"id": n, "ok": false, "error": "<ExceptionType>: <message>"}`. The
worker keeps running after a failed request. A malformed line gets an error
response with `id: null`. If the hash of the clip on disk does not match
`reference_sha256`, the worker refuses, so a swapped clip cannot pass under a
stale cache key. The add-on side times out on start (`start_timeout_seconds`,
default 180) and per request (`request_timeout_seconds`, default 300). On
timeout it kills the process and raises `ProviderError`.

The add-on converts the WAV to the MP3 cache file with ffmpeg (through pydub,
with `atempo` when needed) and deletes the WAV.

## 7. Fish provider

- `POST https://api.fish.audio/v1/tts`, header `model: s2.1-pro` (setting),
  JSON body `{"text", "reference_id", "format": "mp3"}`, timeout 60 s, standard
  library `urllib` only.
- The key is read from `FISH_API_KEY`: the process environment first, then
  the Windows User-scope variable (`HKCU\Environment`), because Anki is often
  started before a newly set user variable reaches its environment. The key is
  never logged, printed or written to settings.
- `reference_ids` per language come from settings and default to empty
  (CA-12). With no id for a language, health fails and the chain moves on.
- Identity: `provider` `fish-audio`, `provider_model` (the model setting),
  `provider_version` `v1` (the API path; Fish exposes no engine version) and
  `reference_id`.
- Paid: about $15 per million UTF-8 bytes for s2.1-pro (Round 1b). AnkiTTS
  does not meter. As second in the chain it is called only when Pocket fails.

## 8. Edge provider

The previous `generator` code moved unchanged into `src/providers/edge.py`:
the `NoAudioReceived` retry (1, 2, 4 s), `get_edge_provider_identity()` and
`generate_audio`. `generator.get_edge_provider_identity` stays as a
compatibility name. Identity is `edge-tts` / `edge-neural-voices` /
`<edge_tts version>`. `get_edge_provider_identity()` is unchanged; the provider's
`identity()` adds `speech_text_version` (section 15) and `loudness_version`
(section 17) to it. Edge writes its MP3 itself, so after a successful
synthesis the file is decoded, normalised and re-encoded in place
(`providers.audio.normalise_mp3_in_place`); a failure there is a provider error
and nothing is cached.
Health is configuration-only (always ok). Edge failures surface during
synthesis.

## 9. Settings schema and migration

The live add-on reads **Anki's add-on config**, not `settings.json`
(CA-4): `mw.addonManager.getConfig(...)`, which is `addon/config.json`
(defaults) overlaid by `addon/meta.json["config"]` (what the dialog saved).
`settings.json` at the repo root is a developer file read only by
`SettingsManager` (dev scripts). The inventory's guess that the add-on reads
`addon/settings.json` was wrong. New keys (the chain's default has since
become `["edge"]`, and section 18 adds more):

```json
"provider_chain": ["pocket", "fish", "edge"],
"providers": {
  "pocket": {
    "engine_python": "C:\\AnkiTTS-engine-env\\Scripts\\python.exe",
    "models": {"fr": "french", "en": "english"},
    "reference_clips": {
      "fr": "D:\\RCE-Project-Archive\\Milestones\\Card-Audio\\reference\\alec-fr-lively-15s.wav",
      "en": "D:\\RCE-Project-Archive\\Milestones\\Card-Audio\\reference\\alec-en-lively-15s.wav"
    },
    "start_timeout_seconds": 180,
    "request_timeout_seconds": 300,
    "idle_shutdown_seconds": 300
  },
  "fish": {
    "model": "s2.1-pro",
    "reference_ids": {"fr": "", "en": ""},
    "timeout_seconds": 60
  },
  "edge": {}
}
```

- **Migration on load:** `AppSettings.from_dict` fills any missing key from
  the defaults above, per provider and per field, so a config written before
  this change loads with the full chain. Every legacy key stays readable: the
  four field-name keys, `voice_mode`, top-level `voices`/`rate`/`volume`/`pitch`.
  Nothing is rewritten until the user presses Save in the dialog.
- Unknown ids in `provider_chain` are dropped with a log warning on load.
  An empty chain becomes `["edge"]`. `validate()` (used by Save) rejects them.
- `addon/config.json` gains the same keys, so Anki's merge shows them to a
  fresh install.
- Alec's working-copy `settings.json` is never written by any of this.
- The dialog gets a minimal **Providers** tab: chain order, engine Python
  path, the two clip paths, the Fish model and the two Fish reference ids.
  It has no key field.

## 10. Reference-clip rule

The canonical clips (CA-3 part 3) live in
`D:\RCE-Project-Archive\Milestones\Card-Audio\reference\` and are referenced
by absolute path from settings. They are never copied into the repository,
the add-on folder or the cache, and never committed. `.gitignore` already
excludes `*.wav` and `*.mp3`. The clip's SHA-256 is part of the Pocket
identity, so re-recording a clip invalidates exactly the audio cloned from it.

| Language | File | sha256 |
|---|---|---|
| fr | alec-fr-lively-15s.wav | a236fd4c2b1203935faefd02b43c64c80f36a190da0ae6b5c8431e7a36ed2cc3 |
| en | alec-en-lively-15s.wav | 78d9791177e90e5f237a1b3de860aa19e103d2f25c2416114bc7640bf692137e |

## 11. What each provider supports

| | Pocket | Fish | Edge |
|---|---|---|---|
| Languages | fr, en (6-layer `french`, `english`); a language needs a model **and** a clip | any language with a `reference_id` set (fr, en today) | any with an Edge voice (fr, en, ja) |
| Voice | clone of the configured clip | the configured Fish voice model | the profile's Edge voice |
| Rate / volume / pitch | atempo / no / no | atempo / no / no | yes / yes / yes |
| Runs | local CPU, separate process | network, paid | network, free |
| Parallel | 1 | 3 | 3 |
| Japanese | no → falls through | only if a ja id is set | yes |

A missing clip makes Pocket unhealthy for that language. It never falls
back to a stock Pocket voice (CA-8).

## 12. Logging

`src/ankitts_log.py` provides a rotating log (1 MB × 5) at
`<add-on folder>/user_files/logs/ankitts.log`. Anki keeps `user_files` across
add-on updates. Providers log starts, health failures, fallbacks, timings and
RTF. They never log text longer than 80 characters, and never keys.

## 13. Test plan

Unit tests (always run, no network, no engine):
- the registry resolves the chain from settings, drops unknown ids and caches instances;
- fallback: first provider unhealthy, raising, or unsupported language → the
  next one produces the audio, and the cache key carries the producer's identity;
- cache precedence (CA-6);
- generic cache key includes identity, structured key unchanged for Edge;
- settings migration: legacy config gets the defaults; partial provider config
  is merged; unknown chain ids dropped; round trip through `asdict`;
- rate: atempo multiplier and bounds; volume and pitch excluded from Pocket/Fish keys;
- Pocket worker protocol against a fake worker script (any Python), including
  error responses, timeouts and the reference hash refusal;
- Fish request construction against a fake opener (no network);
- existing Edge retry tests moved to `providers.edge`.

Integration tests (`tests/integration_providers.py`, run on demand with
`python tests/integration_providers.py [pocket|fish|fallback|all]`; not part
of `run_tests.py` because they need the engine venv, the network or a paid key):
- E: chain `[pocket]`, one invented French and one invented English sentence
  through `generator.create_audio`; non-empty MP3; identity in the key; prints
  durations and RTF;
- F: chain `[fish]` if `FISH_API_KEY` is set; one sentence per language,
  under 500 UTF-8 bytes each, counts printed; otherwise recorded as skipped;
- G: chain `[pocket, fish, edge]` with a wrong engine path in a temporary
  settings object; asserts fish or edge produced the audio and the key says so.

## 14. Rulings

### Ruling CA-3 (Alec, 2026-11-01), verbatim

1. Engine: Kyutai Pocket TTS, 6-layer models, is AnkiTTS's primary provider for French and English,
   cloned from Alec's lively reference clips. Fish Audio s2.1-pro is a second provider. edge-tts
   (7.3.1 or newer) is the last-resort fallback. Basis: Round 1b unblinded
   (AnkiTTS-Bakeoff-Round1b-Unblinded-20261030.md): all lively candidates 4.4-4.8, Pocket English
   5.0/5.0, French 4.3/4.5, differences within noise; the 24-layer French model adds nothing worth
   2x memory and 1.8x time.
2. Round 2 (Qwen3-TTS) is cancelled; Qwen3-TTS goes to the parked-ideas register with the trigger
   "if Pocket's French ever disappoints on real cards".
3. Canonical reference clips: round1b\ref\alec-fr-lively-15s.wav and alec-en-lively-15s.wav, copied
   to D:\RCE-Project-Archive\Milestones\Card-Audio\reference\, referenced by path from AnkiTTS
   settings, never committed to git.
4. Fish account: Alec deletes the two Round 1 (flat) voice models; the two lively models stay for
   the second provider.

### Session rulings (the implementing session, 2026-11-01; option taken, then not taken)

- **CA-4 Live settings location.** The live add-on keeps Anki's add-on config
  (`config.json` + `meta.json["config"]`) as its settings store. Dev and
  integration runs read the same store through
  `SettingsManager.load_addon_config()`. `settings.json` stays a dev-only file
  and is not touched. *Not taken:* pointing the add-on at the repo
  `settings.json`. That would orphan the live field mapping (`expression` /
  `definition`) Alec saved through the dialog, and make the dialog write his
  personal file.
- **CA-5 Worker transport.** JSON lines over stdin/stdout. *Not taken:* a
  localhost HTTP endpoint (port choice, a firewall prompt, a server to keep
  alive, and nothing gained for one client).
- **CA-6 Cache precedence under fallback.** Per provider in chain order: its
  cache, else its synthesis. *Not taken:* "first cached file anywhere in the
  chain", which would keep serving fallback audio after the primary recovers.
- **CA-7 Ids.** Settings use `pocket`, `fish` and `edge`. Identities use
  `pocket-tts`, `fish-audio` and `edge-tts` (unchanged for Edge). *Not taken:*
  renaming the Edge identity.
- **CA-8 Missing clip.** Pocket is unavailable for that language, and the
  chain falls through. *Not taken:* a stock Pocket voice, which would silently
  change the voice.
- **CA-9 Engine versions.** `pocket-tts==4.0.1` and `torch==2.15.0` (CPU
  index), the rated versions. *Not taken:* newest, which might not sound the
  same as what Alec rated.
- **CA-10 Ignored parameters.** Volume and pitch are ignored by Pocket and
  Fish and left out of their cache keys. Rate is applied by atempo, bounded
  to 0.5–2.0 and clamped. *Not taken:* rejecting non-default volume/pitch
  (it would break Alec's existing Edge profiles under the new chain).
- **CA-11 Track filenames.** The structured track filename hashes each
  segment's provider identity. Existing published filenames change once.
  *Not taken:* one identity per track (it cannot describe a mixed track).
- **CA-12 Fish reference ids.** They default to empty in code and in
  `config.json`. Alec sets his two lively model ids in the dialog. The
  integration test reads them from the bake-off file. *Not taken:*
  committing Alec's private voice-model ids to a public repository.
- **CA-13 Worker lifetime.** Idle shutdown after 300 s by default. *Not
  taken:* keeping the worker for the whole Anki session (about 1.2 GB on an
  8 GB machine).

Later rulings made during the build:

- **CA-14 Repository src first.** When the add-on is loaded from the
  repository checkout (the `addons21\AnkiTTS` junction), it runs
  `C:\AnkiTTS\src` directly. It falls back to `addon\src` only in a packaged
  copy. *Not taken:* keeping `addon\src` first. That mirror was a hand-made
  copy, and after this change it would have kept Anki on the old Edge-only
  code until someone refreshed it.
- **CA-15 Edge pin and libs.** edge-tts is pinned at 7.3.1 in the new
  `addon/requirements-libs.txt`. `addon/libs` was rebuilt from it with Python
  3.13, and the old folder was moved to `AnkiTTS_backup\libs-edge-tts-7.2.8-20261101`.
  `.venv313` was upgraded in place. *Not taken:* also upgrading `.venv` (3.14,
  unused by tests or the add-on), and pinning every transitive version (pip
  resolves them; the resolved set is in the session summary).
- **CA-16 deploy.bat repaired, not deleted.** It now mirrors `src` into
  `addon\src` and rebuilds `addon\libs`. *Not taken:* deleting it, because a
  packaged copy still needs the mirror and the libs rebuild is a real step.
- **CA-17 README rewritten clean.** The stored README carried literal
  markdown escapes (`\#`, `\-`), so it rendered as backslashes. The rewrite
  keeps every section and updates features, requirements and setup. *Not
  taken:* editing only the provider lines inside the escaped text.
- **CA-18 CLAUDE.md requirements line updated to CA-3.** The line "no other
  provider belongs in the default configuration" contradicted CA-3. It now
  states the CA-3 chain and keeps the exclusion for providers outside it.
  *Not taken:* leaving project memory contradicting Alec's ruling.
- **CA-19 Generic-path error semantics kept.** A chunk is skipped only when
  every provider that tried answered "no audio". Any real error (for example
  HTTP 403) still surfaces, as Edge errors did before. *Not taken:* skipping
  on any failure, which would hide outages as silent cards.
- **CA-20 Integration tests are a separate script**
  (`tests/integration_providers.py`), not part of `run_tests.py`. They need
  the engine venv, the network and a paid key, and the regression suite must
  stay offline and free. *Not taken:* auto-skipping checks inside the suite.

Rulings CA-21 (Alec) and CA-22 to CA-28 (the implementing session), made while
fixing the first real card's audio defects, are in section 15.

## 15. Speech text preparation and the tail trim

Alec's first real card with the Pocket voices showed three audio defects. This
section is their fix: a trim that no longer clips the last syllable, and one
preparation step that turns dictionary notation into words and pauses before
any provider is called. The measurements behind the trim are in
`docs/audio-tail-diagnosis-20261101.md`.

### Ruling CA-21 (Alec, 2026-11-01), verbatim

```
Context: the provider seam is built (AnkiTTS-Providers-Design-Summary-20261101.md, HEAD f59fd90,
145/145). Alec's first real card with the Pocket voices showed three audio defects.
1. English (and possibly French) audio is cut off abruptly on the last syllable of a sentence or
phrase. This is fixed on the AnkiTTS side (trim margin, tail padding, or final punctuation
handed to the engine), whichever the diagnosis shows.
2. A slash between alternatives in dictionary text is never spoken as a slash: before synthesis
it becomes " or " in English and " ou " in French, by segment language, for every provider.
3. The alternative is punctuated so the engine pauses and stresses it naturally: "X, ou Y" /
"X, or Y" (comma before, nothing after). Segments are not split at "or"/"ou". The same
treatment applies to a spelled-out "or"/"ou" only in short, sentence-less segments (a gloss
list), never inside an example sentence; the clean fix (RCE marking alternatives in the
speech plan) is parked until sem-2b closes.
```

### The cut-off ending (defect 1): diagnosis and trim

Three suspects were tested on 12 invented phrases through the real Pocket
worker (half with a final full stop, half without), keeping the worker WAV, the
MP3 and the stitched track:

| Suspect | Verdict | Evidence |
|---|---|---|
| (a) `trim_trailing_silence` at -45 dBFS biting the final consonant | **Real, mostly English** | Pocket's English clone speaks at a mean -36.7 dBFS, so -45 dBFS is only 9 dB below the average. The trim removed 108 ms of audible content on average (max 230 ms) from English clips, and every English track ended at -35 to -44 dBFS. French (mean -24.9 dBFS): 23 ms on average (max 40 ms). |
| (b) the engine stopping early without terminal punctuation | Ruled out | Pocket already appends a full stop itself (`append_terminal_punctuation` defaults to true and neither language config changes it). Clips with and without a stop have the same length and tail shape. |
| (c) atempo or the MP3 encode | Ruled out | Tempo is 1, so no filter runs. WAV and MP3 have identical length in all 12 cases. |

The fix, in `stitcher.trim_trailing_silence`, used by both stitchers:

- `SILENCE_THRESHOLD_DB` moves from -45 to **-60 dBFS**, which is where the
  sound really ends (Pocket's own tail sits at -80 to -84 dBFS, an Edge clip's at
  digital silence).
- `TRIM_SAFETY_MARGIN_MS = 50`: after the detected end of the sound, 50 ms of
  the original audio is kept (never more than the clip has). It covers the 10 ms
  window granularity and the MP3 smoothing of the threshold crossing.
- Replayed on the 12 clips: nothing audible is lost in either language, and the
  extra silence kept is a constant 50 ms.

Consequence for pauses: a segment's audio now ends up to 50 ms later than
before, so each authoritative `pause_after` (structured path) and each
text-derived pause (generic path) is followed by, at most, 50 ms more of decay
or silence. RCE's pause values are unchanged and still applied exactly; the
audible gap between two segments is up to 50 ms longer.

**Amended by CA-37 (same day, after loudness normalisation):** the trim
threshold is now **-50 dBFS**, because normalised audio is up to 22 dB louder
and its -80 dBFS tail rose to within 1.5 dB of -60. The 50 ms margin is
unchanged. Section 17 has the replay.

Regression tests: `tests/test_stitcher.py`, including a fake-worker clip whose
last 60 ms is a soft final syllable (about -38 dBFS RMS in the normalised clip)
that the stitched track must keep, and a tail 38 dB under the program level
that it must remove.

### `prepare_for_speech(text, language)` (defects 2 and 3)

`src/speech_text.py`. Called once in `generator.create_audio` on the text handed
to every provider, so it applies on the generic and the structured paths alike.
`language` is the segment's profile language (`fr`, `en-US` and `FR_ca` all
resolve to their base language). A provider receives the prepared text; the
cache key uses the **original** text plus `speech_text_version` (below), so the
plan text stays the authority.

| # | Rule | Examples (invented) |
|---|---|---|
| 1 | A slash between word alternatives, spaced or not, becomes `, or ` (English) / `, ou ` (French): comma before, nothing after. Three alternatives chain. Other languages keep their slash. | `sb/sth` → `sb, or sth`; `il / elle` → `il, ou elle`; `mon/ma/mes` → `mon, ou ma, ou mes`; `le/l'` → `le, ou l'` |
| 1a | `and/or` and `et/ou` become `and or` and `et ou` (no comma). | `tea and/or coffee` → `tea and or coffee` |
| 1b | Not alternatives, left alone: digit/digit (`3/4`, `12/05/2026`), tokens containing `://`, two bare single letters (`n/a`, `A/C`). `km/h` and `m/s` are units (rule 7). | |
| 2 | In a sentence-less segment of at most 12 words (a gloss list), a bare ` or ` / ` ou ` gets a comma before it, unless a comma, `;` or `:` already precedes it (or the word before it is `and`/`et`). A segment with a sentence end anywhere in it, or longer than 12 words, is left alone. Segments are never split. | `rouge ou bleu` → `rouge, ou bleu`; `Veux-tu du thé ou du café ?` unchanged |
| 3 | No terminal full stop is added: the engine does it (diagnosis, suspect b). | |
| 4 | `→` becomes a comma (a short pause) and `≈` is dropped, in any language. Bracketed `[...]` and `{...}` labels are **spoken in the flow of the sentence**, with no pause (CA-29, CA-34). A bracket that touches a letter, an apostrophe or a hyphen joining two parts of a word keeps no space on that side, so it is part of that word (CA-61 (9), version 4). Parentheses are kept. | `chat → cat` → `chat, cat`; `faire [quelque chose] à [quelqu'un]` → `faire quelque chose à quelqu'un`; `[somebody]'s` → `somebody's`; `[x]-like` → `x-like`; `l'[objet]` → `l'objet` |
| 5 | `=` and a `+` between words or numbers are spoken between two pauses, English and French only: `, equals, ` / `, égale, ` and `, plus, `. `×` and a spaced `x` between numbers are `times` / `fois` (no pauses). A leading sign (`+5`) is `plus 5`. `C++` and `B+` are left alone. In other languages `=` stays a plain comma and `+` is untouched (CA-29). | `de + le = du` → `de, plus, le, égale, du`; `2 x 3` → `deux fois trois` |
| 6 | Currency signs `€ $ £ ¥` before or after a number become the currency word, singular for 1; `€20/month` gives `20 euros per month` (`par` in French). English and French. | `€20` → `20 euros`; `2,50 €` → `deux virgule cinquante euros` |
| 7 | Unit abbreviations after a number become words, singular or plural by the number (English: anything but 1 is plural; French: 2 and above). Unambiguous units also expand with no number (`km`, `cm`, `mm`, `kg`, `mg`, `ml`, `cl`, `dl`, `kW`, `Hz`, ...), in the plural. Ambiguous single letters (`m g l s h`) need a number. `s` and `ms` need a space after the number (`the 1990s` is a decade). `m²` / `m2` / `m 2` after a number is square metres and `m³` cubic (CA-30). `%` is `percent` / `pour cent`; `°C`, `°F` and `°` are degrees. `km/h` and `m/s` are `per hour` / `per second` (`par heure`, `par seconde`). Before a noun, English `3-km` is singular (`3-kilometer`), and a slash after a unit followed by a number is a slash between alternatives (`3-km/3-hour walk` → `3-kilometer, or 3-hour walk`, CA-34). | `20 km` → `20 kilometers`; `6 m 2` → `six mètres carrés`; `14 h 30` → `quatorze heures trente`; `20 °C` → `vingt degrés Celsius` |
| 8 | French only: numerals are spelled out (up to 10^12; the cardinal is masculine, so `1 pièce` is `un pièce`). A decimal comma reads `virgule`; a space-separated group of three digits is a thousands group (`1 000` is `mille`). Leading zeros (`007`), codes (`H2O`, `A4`, `3D`) and anything over 10^12 are left as written. English numerals are left to the engine. | `1998` → `mille neuf cent quatre-vingt-dix-huit` |
| 9 | French ordinals: `20e`, `20 e`, `20ème`, `1er`, `1re`, `1ère` are spoken as ordinals (`vingtième`, `premier`, `première`; `21e` is `vingt et unième`). A Roman numeral with an ordinal suffix is only trusted before `siècle`, `millénaire`, `arrondissement`, `dynastie`, `république` or `empire` (`XXe siècle`); `Vie` and `Cie` are words. English ordinals are left to the engine. | `du 20 e siècle` → `du vingtième siècle` |
| 10 | A lone letter (English and French) is spoken by its name: `h` is `ache` / `aitch`. Not spelled: the letters that are words (`a i` English; `a y o` French), a letter touching an apostrophe, hyphen, slash or `+` (`d'`, `T-shirt`, `C++`), `e.g.`, `p. 3`, and `(s)` / `(e)` after a word. `a)`, `b)` and `(c)` are section letters and are always spoken (including `a`, `i`), followed by a comma. | `un h muet` → `un ache muet`; `b) le chien` → `bé, le chien` |

Doubled punctuation left by these rewrites is collapsed (`A, → B` → `A, B`;
`a →. b` → `a. b`), leading commas are stripped, and whitespace is normalised,
only when a rule changed the text; untouched text is returned as it is. The
function is idempotent.

If preparation leaves nothing speakable (a segment that is only `≈`, an arrow or
a comma), the original text is spoken and a warning is logged (CA-26).

### Cache identity: `speech_text_version`

`speech_text.SPEECH_TEXT_VERSION` (currently `"4"`; rules 5 to 10 came with version 2, the no-pause labels and hyphenated units with version 3, the attached brackets of rule 4 with version 4) is a field of the identity
of **every** provider (`EdgeProvider`, `PocketProvider`, `FishProvider`). Bump
it whenever a rule changes what is spoken. Because the identity feeds the
generic key, the structured key and the structured track filename, everything
refills once after this release. Regenerating a card after the change is
enough to pick up the new audio; no cache needs to be cleared by hand.

### Logging

Per `create_audio` call (each segment, cached or not), if the **original** text
holds characters outside letters, digits, spaces and ordinary punctuation
(`. , ; : ! ? ' " ( ) - – — …`, curly quotes, `« »`, and CJK punctuation), the
log has one line with their count and the set of those characters, never the
text. A second line gives the length before and after preparation when the text
changed. The next real batch therefore shows what else the dictionary sends.
Slashes and the symbols rule 4 handles count too, so the log also shows how
often each is hit.

### Rulings made while fixing the defects (the implementing session)

Option taken, then option not taken.

- **CA-22 Trim at -60 dBFS with a 50 ms margin** (threshold amended to -50 by CA-37). *Not taken:* the managing
  chat's likely margin-only fix (keep -45 dBFS, add 80-150 ms). On the data that
  would still cut up to 80 ms of English at +150 ms, and it needs +250 ms to
  lose nothing, adding 100 to 240 ms of dead air to every clip and to every
  authoritative pause. Also: the brief assumed Pocket's WAV ends with almost no
  silence; it ends with 110 to 530 ms.
- **CA-23 No terminal full stop is added.** *Not taken:* appending `.` in
  AnkiTTS. Pocket already does it, and the data shows no early stop.
- **CA-24 Slash rewriting is limited to real alternatives** (rows 1a and 1b
  above), and only for `en` and `fr`. *Not taken:* rewriting every slash,
  which would turn `3/4` into `3, or 4` and break dates and units.
- **CA-25 The gloss rule is stricter than "no terminal punctuation":** a
  sentence end anywhere inside the segment also disables it, and it never puts a
  comma after `;` / `:` or inside `and or` / `et ou`. *Not taken:* checking only
  the end of the segment, which would comma an `or` in `Il est parti. Elle ou lui`.
- **CA-26 Nothing speakable falls back to the original text** with a warning.
  *Not taken:* skipping the segment, which on the structured path aborts the
  whole card for a segment of only symbols.
- **CA-27 `speech_text_version` lives in each provider's `identity()`**, not
  added centrally in `create_audio`. `get_edge_provider_identity()` stays the
  engine-level identity (edge-tts version). A future provider must add the
  field itself. *Not taken:* injecting it centrally in `create_audio`, which
  would cover a forgetful new provider but leave `identity()` short of the full
  record of what produced a file.
- **CA-28 The unusual-character log** counts on the original text, per
  `create_audio` call, and only when the count is above zero. *Not taken:* a
  zero-count line per segment, which would fill the rotating log with noise.

### Rulings made while extending the rules (the implementing session, same day)

Alec listened to the first corrected card and reported: `€20` read as `twenty`
with a cut-off ending; `km` and `cm` read oddly; `h` and `=` not spoken and no
pauses at `+` and `=`; `20 e` and `6 m 2` garbled; `[quelqu'un]` not spoken;
numbers, symbols and unit abbreviations garbled in French as well. He also
asked for a different voice on notes, headings and labels, and for section
numbers and letters to be spoken. Rules 4 to 10 are the answer to the first
group; the voice question is parked (section 16).

- **CA-29 Bracketed labels are spoken, and `=` and `+` are words.** This
  supersedes CA-21's implied drop of `[...]` labels and the plain-comma `=`.
  Labels are read between commas so they sound set apart; `=` is `equals` /
  `égale`, `+` is `plus`, each with a pause either side. *Not taken:* a pause
  without a word (the original rule), which is what Alec heard and could not
  follow.
- **CA-34 Labels are read with no pause; hyphenated units are singular.** Alec
  listened to CA-29's output: the comma pauses around `[quelque chose]`,
  `[quelqu'un]`, `[someone]`, `[something]` and similar tags broke the sentence,
  so a label is now just its words in the flow (the brackets disappear). Also
  `a 3-km/3-hour walk` was not expanded because a unit was not recognised after
  a hyphen or before a slash; `3-km` is now `3-kilometer` (English attributive
  units are singular) and the slash after it is rewritten as an alternative.
  *Not taken:* keeping a short pause for labels, which is what he heard.
- **CA-30 `m²`, `m2` and `m 2` after a number are square metres** (`mètres
  carrés`), cubic for `3`. Alec's note said `6 m 2` "should read as 6 mètres 2";
  the only reading of that notation that is correct French is `six mètres
  carrés`, so that is what is spoken. *Not taken:* the literal `six mètres
  deux`. Risk: `5 m 2 fois` would also be read as an area. Overrule here if
  the literal reading is wanted.
- **CA-31 French numerals are spelled by AnkiTTS, with no new dependency.** A
  small cardinal/ordinal converter lives in `speech_text.py` (masculine forms,
  classic hyphenation, `quatre-vingts` only when nothing follows). *Not taken:*
  `num2words`, which would be one more package in the vendored libs for a few
  dozen lines of rules. English numerals are left to the engine: the English
  voice reads digits correctly and only the sign, unit or ordinal was wrong.
- **CA-32 Ambiguity is resolved toward leaving text alone.** Roman numerals
  only before an ordinal noun; `s` / `ms` only after a space; `m g l h` only
  after a number; lone letters that are words are not spelled; numbers that
  look like codes or exceed 10^12 are untouched. Known gaps: a run of
  three-digit groups (`99 100 101`) reads as one thousands-grouped number and is
  then left as written; dates (`20/03/2024`) and ranges (`10-20`) are not
  rewritten; `1 pièce` takes the masculine `un`.
- **CA-33 Section letters `a)` / `(b)` are always spoken**, with a trailing
  comma, so a listener hears where a section starts. Whether a heading or
  section marker is in the segment text at all is RCE's decision (below).

Rulings CA-35 to CA-41 are in section 17, CA-42 onward in section 18.

## 16. Parked

- **Qwen3-TTS** (0.6B / 1.7B). Trigger: "if Pocket's French ever disappoints
  on real cards" (CA-3 part 2). It would be a fourth provider behind the same
  interface, in its own venv.
- **`Playback Plan`** is still required on RCE notes and still not consumed
  (inventory). It is unchanged here.
- **RCE marks alternatives in the speech plan** (trigger: sem-2b closed). The
  clean fix for defects 2 and 3: RCE would say which words are alternatives
  and the slash and bare-`or` heuristics in `speech_text.py` could go.
- **Per-segment loudness normalisation** is built (section 17), no longer
  parked.
- **Peaky English clips stay 1 to 2 LU under the target.** Pocket's English
  voice has peaks 19 to 22 dB over its loudness; the limiter's 12 dB cap
  (CA-36) leaves the peakiest takes at -17 to -18 LUFS. Trigger: Alec hears a
  level step in a mixed card, or crunch or pumping on English, either of which
  points at the limiter. Options then: a lower common target (about -18 LUFS
  makes every clip linear), or a gentler dynamics stage than a limiter.
- **A different voice for notes, headings and labels, and spoken section
  numbers** (Alec, 2026-11-01). **Superseded by speech plan v2 (section 18):**
  the plan carries `voiceRole` and `role`, and section numbers are their own
  segments. It takes effect when RCE emits version 2 (card-4). The original
  note, for the record: not built, because both halves need RCE:
  - *Who speaks what* is RCE's content. The speech plan already carries
    `voiceProfileId` per segment, and AnkiTTS already resolves a direct
    profile key or a logical alias to a profile. So RCE would emit, for
    heading/note/label segments, a profile id such as `french-heading` /
    `english-heading`, and AnkiTTS would add those aliases and profiles.
  - *Today the voice is per language, not per profile.* Pocket chooses its
    reference clip from `reference_clips[language]`, and
    `provider.identity(language)` and the cache key know nothing of the
    profile. A second voice per language therefore needs a profile-aware
    identity on all three providers (a cache-key change, like
    `speech_text_version`), a `reference_clips` entry per profile with the
    language clip as fallback, and a Settings field for it.
  - *Section numbers and letters* are only spoken if they are in the segment
    text. If RCE sends `b)` or `2.` inside the text, rule 10 and the French
    numerals speak them. If it sends them as markup or metadata, RCE would
    have to put them in the text or in their own segment.
  - Trigger: RCE confirms which segments are headings/notes and which profile
    ids it will send (with sem-2b, alongside "RCE marks alternatives").
  - A short wording for RCE: "For heading, note and label segments, set
    `voiceProfileId` to `<language>-heading`; include the section marker (`a)`,
    `2.`) in the segment text."

## 17. Loudness normalisation

### Ruling CA-35 (Alec, 2026-11-01, 20:13, "All A"), verbatim

```
1. Per-segment loudness normalisation is built now: every provider's clip is normalised to one
   target (-16 LUFS, the bake-off's setting) at encode, before caching, with a version in the
   cache identity so audio refills once.
2. Working rhythm: Alec studies on the current build for several days and keeps a running list
   of what sounds wrong, reads wrong or looks wrong; then one batched fix session. That list
   also seeds the card-design doc (bridge step 3).
3. CA-30 stands: "6 m 2" after a number is read as square metres.
```

### How it works (`providers/audio.py`)

Every clip a provider produces is normalised before it is cached:

1. **Measure** integrated loudness and true peak with ffmpeg's `loudnorm` in
   analysis mode (I=-16, TP=-1.5, LRA=11, the bake-off's settings), after any
   `atempo`.
2. **Gain.** The gain is `-16 - measured`, bounded to +-30 dB. If it keeps the
   true peak under -1.5 dBTP it is applied as a plain `volume` filter (linear,
   exact).
3. **Limiter, only when the gain would pass -1.5 dBTP.** Pocket's voices have
   peaks 19 to 22 dB above their loudness; the room between -16 LUFS and
   -1.5 dBTP is 14.5 dB, so about half the Pocket clips need it. An `alimiter`
   (5 ms attack, 50 ms release, latency compensated) holds the sample peak at
   -3 dBFS, and the gain is **calibrated closed-loop** (up to 3 measurements of
   the limited audio) until the output is within 0.3 LU of -16, never letting
   the limiter cut peaks by more than **12 dB**. Beyond that the clip stays
   quieter than the target and is reported as `at_limit`.
4. **Encode** as 96 kbit/s MP3 (CA-38), written to a temporary file and moved
   into place.

A clip under 400 ms has no integrated loudness (BS.1770 needs a 400 ms block),
so it is measured looped to 2 s. Silence (under -69 LUFS) is encoded unchanged.
Each normalisation is logged as one line: input and output LUFS and dBTP, the
gain, and whether the limiter or its cap applied. Never any text.

`loudness_version` (`"1"`, `providers.audio.LOUDNESS_VERSION`) is in every
provider identity, the same pattern as `speech_text_version` (CA-27), so cached
audio and track names refill once. Bump it whenever a constant in
`providers/audio.py` changes what is cached.

Where each provider passes through it:

| Provider | Path |
|---|---|
| Pocket | worker WAV, then `encode_mp3` (always) |
| Fish | the API's MP3 is written raw, then `encode_mp3` (always; it used to be renamed straight into the cache at tempo 1) |
| Edge | `edge-tts` writes an MP3; `normalise_mp3_in_place` decodes, normalises and re-encodes it |

### Rulings (the implementing session)

Option taken, then option not taken.

- **CA-36 Measure with `loudnorm`, apply an explicit gain, and limit only when
  needed.** The brief asked for `loudnorm` two-pass in linear mode. On the real
  clips that is not linear: with `linear=true` and the measured values,
  `loudnorm` silently fell back to its *dynamic* mode on four of six Pocket
  clips, and stayed linear (capped by true peak) on the other two at -19.9 and
  -18.1 LUFS, so the English-French step would have stayed at 2 to 4 LU. The
  explicit gain is deterministic, never clips, and lands on the target.
  *Not taken:* `loudnorm` doing the whole job (inconsistent between clips);
  linear gain only (English near -23 and French near -20 LUFS, the 12 dB step
  reduced only to about 3 LU). The limiter cap is 12 dB: at 10 dB the peakiest
  take stopped at -17.6, at 12 dB at -16.4, at 14 dB at -16.2 (the last 2 dB
  buys 0.2 LU at the price of heavier limiting).
- **CA-37 The trim threshold moves from -60 to -50 dBFS** (amends CA-22; the
  50 ms margin stays). Normalisation raises Pocket's -80 dBFS tail by the clip's
  gain, up to +22 dB: English tails measured -58.5 to -66 dBFS afterwards, one
  of six (in one run) no longer trimmed at all, two within 3 dB of the threshold. Replayed
  on 14 normalised clips at -60, -55, -50, -45 and -40: the loudest 10 ms
  window the trim removes is -59.4 dBFS at -55 and -50, -58.9 at -45 (about
  40 dB under the speech), and -55.5 only at -40. -50 leaves 8 dB above the highest tail
  floor and 18 dB under a soft word ending. *Not taken:* keeping -60 (brittle,
  and already failing on one clip); a per-clip threshold from the applied gain
  (the cached MP3 does not carry it).
- **CA-38 Clips and stitched tracks are encoded at 96 kbit/s.** Measured by the
  signal-to-distortion ratio of the decoded MP3 against the same audio before
  encoding (dB, higher is better), on two Pocket clips and the two Edge clips
  (Edge is a second MP3 generation):

  | Bitrate | Pocket EN | Pocket FR | Edge EN | Edge FR |
  |---|---|---|---|---|
  | old default (about 32k) | 6.4 | 15.6 | 13.9 | 17.0 |
  | 48k | 9.8 | 18.5 | 18.7 | 19.8 |
  | 64k | 17.4 | 22.7 | 22.5 | 23.0 |
  | **96k** | **24.1** | **25.5** | **25.8** | **25.5** |
  | 128k | 25.6 | 25.9 | 26.0 | 25.9 |

  The curve is steep to 96k and flat after (within 1.5 dB of 128k). The old
  default was poor, worst on the quiet English clone. The stitched track had
  the same default; a mixed track encoded at about 32 kbit/s overshot the
  clips' -3 dBFS peaks to a decoded **-0.02 dBFS** (full scale, clipping), and
  at 96k its peak is -2.7 dBFS (-1.9 dBTP). Both stitchers now export at 96k
  (`stitcher.TRACK_MP3_BITRATE`). *Not taken:* 64k (cheaper, 2.5 to 6.7 dB worse);
  128k (no gain by the numbers). Files are about 3 times larger than before,
  12 KB per second of audio.
- **CA-39 There is no single place every provider's audio passes**, contrary to
  the brief: Edge never used `encode_mp3`, and Fish renamed its MP3 into the
  cache at tempo 1. Normalisation is therefore one function in
  `providers/audio.py` (`encode_mp3` and `normalise_mp3_in_place`) that all
  three providers call. A failure to normalise is a provider error and the
  file is not cached. *Not taken:* caching the unnormalised clip on failure,
  which would put quiet audio under an identity that promises -16 LUFS.
- **CA-40 Short clips are measured looped; silence is left alone.** *Not
  taken:* padding with silence, which smears a 200 ms tone by about 3 LU, and
  skipping short clips.
- **CA-41 The acceptance criteria are met for the clips, and met only barely
  for a mixed track.** Details below. Peaky English takes stop short of -16
  (the 12 dB cap), which can leave a segment-to-segment step of 1.9 to 2.2 LU
  next to a French clip (three runs of the harness: 1.87, 2.15 and 2.04 LU).
  *Not taken:* a lower target for English only (CA-35 asks for one target),
  or a cap above 12 dB (heavier limiting for tenths of a LU). See Parked.

### Acceptance (real Pocket worker, 6 invented phrases per language, 2 through Edge)

Run `loudness\acceptance.py` (outside the repository; output kept with it).
Final run, every figure measured on the cached MP3:

- **Clips:** 14 of 14 within +-1 LU of -16 LUFS or at their stated limiter cap:
  12 within +-1 LU (-16.4 to -16.8) and 2 at the 12 dB cap (-17.0 and -17.9);
  **no clipping** (decoded sample peaks -2.3 to
  -3.6 dBFS; true peaks -0.8 to -3.6 dBTP, within 0.7 dB of the -1.5 target at
  worst, from MP3 overshoot).
- **Mixed-language track** (Pocket EN/FR alternating, then Edge): per-segment
  loudness -15.8 to -17.9 LUFS; largest step 2.04 LU.
- **Tail noise floor** after normalisation (last 100 ms of each Pocket clip):
  -59.7 to -76.3 dBFS on 11 clips, against a -50 dBFS threshold; the one clip above it
  (`en-4`, a sentence with no final punctuation) is already above it before
  normalisation (the engine ended on the voiced syllable, raw -47.9 dBFS).
- **Cost:** 180 to 700 ms per clip (linear 180 to 200 ms; limited clips need up
  to three measurement passes), against about 1 to 3.5 s of synthesis.

### Tests

`tests/test_loudness.py` (12 checks): a -30 dBFS tone and the fake Pocket
worker's `QUIET30` clip come out within 1 LU of -16; a loud clip is turned
down; a 200 ms clip is normalised (measured looped) and not clipped; a peaky
clip uses the limiter and stays under -0.5 dBFS; an unreachable target is
reported as `at_limit` and still does not clip; silence is left alone; tempo
and normalisation combine; an existing MP3 is normalised in place; the Edge
provider normalises what Edge wrote and caches nothing on failure. Identity
tests for the three providers and the fakes carry `loudness_version`; the Fish
test now supplies real MP3 bytes.

## 18. Speech plan v2

Schema version 2 of the speech plan: RCE names roles, and AnkiTTS maps them to
voices, sounds and timings from its own settings. Design note:
`D:\RCE-Project-Archive\Session-Handoffs\AnkiTTS-SpeechPlan-v2-Design-20261106.md`.
What is built: its section 2 (the plan) and section 4 (what AnkiTTS resolves).
Its section 3 (what RCE emits) is RCE's stage, card-4; the fixture here follows
it.

**Two sets of ruling numbers.** Alec's rulings in the card-and-audio plan
(`AnkiTTS-Card-Audio-Bakeoff-Plan-20261029.md`) and this document's session
rulings in section 17 both use CA-36 to CA-41, and they are different rulings.
So in this section "CA-37", "CA-38", "CA-40" and "CA-41" mean Alec's, in that
plan file, unless marked "section 17". Session rulings continue from CA-42.

### Ruling CA-41 (Alec, 2026-11-06), verbatim

```
Basis: Stage 2 unblinded (AnkiTTS-VoiceSelection-Stage2-Unblinded-20261106.md) and Alec's addendum
("My favorite voices were actually the female voices, so I'd rather hear the females speak the
content and the males speak the labels"), which amends CA-40 (2): content voices are female,
label voices male.
1. French: content fr-FR-VivienneMultilingualNeural; label en-US-BrianMultilingualNeural.
   English: content de-DE-SeraphinaMultilingualNeural (chosen over the tied Vivienne so that each
   language has its own voice and the language switch is audible); label en-US-AndrewNeural.
2. These four are the DEFAULTS. The settings panel exposes all four slots (content and label per
   language), each switchable to any Edge voice from the live catalogue, or to another enabled
   provider's voice, for real-study dissatisfaction or simply a change. A changed voice regenerates
   that role's audio on the next run (the cache identity changes); nothing else refills.
3. Normalisation finding carried forward: the bake-off's loudnorm fell back to dynamic mode on most
   Edge files and plausibly caused the Stage 1 "crunchiness" notes; AnkiTTS's own normalisation
   (explicit gain plus bounded limiter, CA-35) is unaffected and stays.
```

### The plan

One JSON string per side field, as for version 1. `src/speech_plan.py` parses
both versions; version 1 goes through exactly the path it always did.

Plan fields: `schemaVersion` (2), `side`, `preset` (`{id, version}`,
informational), `tempoProfile` (a name), `segments`. All required.

Segment fields:

| Field | Required | Values |
|---|---|---|
| the twelve version 1 fields | yes | as version 1 (P3: v2 removes none) |
| `role` | yes | `headword`, `sectionNumber`, `label`, `gloss`, `idiomHead`, `exampleSource`, `exampleTarget`, `translation`, `cue`, `alternative`, `other` |
| `voiceRole` | yes | `content`, `label` |
| `pauseBefore`, `pauseAfter` | no | `{kind: "none"}`, `{kind: "fixed", milliseconds}`, `{kind: "proportional", scale}`, `{kind: "boundary"}` |
| `earconBefore` | no | `sectionBoundary`, `answerStart`, `directionFlip`, and, since CA-71, `sectionNumber`, `sectionLetter`, `idiomHeading` |
| `earconAfter` | no | `sectionBoundary`, `answerStart`, `directionFlip` only: a CA-71 kind after a segment is a validation error |
| `pair` | no | `{id, position}`; `position` is `source` or `target` |
| `spoken` | no | `true` (default), `false` |
| `attachedTo` | no | a `segmentId` of the same plan, not the segment's own (CA-61 (7)); version 2 only |

Validation is as strict as version 1: an unknown key is an error, including a
key that does not belong to a pause's kind, and `null` is not "absent". An
`attachedTo` that is not a nonempty string, names the segment itself, or names
no segment of the plan (before or after it) is an error, and a version 1 plan
that carries one fails as any unknown field does. A pause
that is present replaces its version 1 millisecond field, which is otherwise
ignored but still required; a pause that is absent uses it.

### Field mapping: the design note's names and the code's

JSON keys in a plan are spelled as the note spells them. Settings and code:

| Design note | Code | Why it differs |
|---|---|---|
| `voices` (per language, content and label) | settings key `role_voices` | `voices` is already the legacy per-language key, still read |
| `<provider+voice>` | `{"provider": ..., "voice": ...}` | a structured slot |
| `tempoProfiles` | settings key `tempo_profiles`; its fields keep the note's names (`rate`, `pauseFactor`, `minPauseMs`, `maxPauseMs`, `boundaryPauseMs`, `tightPauseMs`) | settings keys are snake_case |
| `earcons` | settings key `earcons` | same |
| `voiceRole`, `tempoProfile`, `pauseBefore` and the rest | `voice_role`, `tempo_profile`, `pause_before` on the parsed dataclasses | Python attributes |
| "section pause" | `boundaryPauseMs`, "Section pause (ms)" in the dialog | same thing |
| "tight pause" | `tightPauseMs`, "Tag / or pause (ms)" in the dialog; `tight_pause_ms` on `TempoProfile` | CA-62 |
| `attachedTo` | `attached_to` on the parsed segment; the resolver adds `attached_side` and `connective` | CA-61 (4), (7) |
| v1 `pauseBeforeMilliseconds`, ... | unchanged, `pause_before_milliseconds` | as before |

### What AnkiTTS resolves

**Voices (`role_voices`).** A segment's language and voice role choose a slot.
Defaults are CA-41's. The slot's provider is tried first, then the rest of
`provider_chain` in order, so a label voice can stay on Edge while content is
on another provider. The language is the segment's, not the voice's locale.
A language with no slot (Japanese) uses its speech profile's voice.

**Tempo (`tempo_profiles`).** The plan's name, or `default` if the name is
unknown. Table as in the note, editable in the dialog.

**Pauses**, at stitch time (P4), in `stitcher.resolve_pause_milliseconds`:

| Kind | Length |
|---|---|
| `none` | 0 |
| `fixed` | the plan's milliseconds, exactly |
| `boundary` | the profile's `boundaryPauseMs` |
| `proportional` | `clamp(scale x pauseFactor x speech, minPauseMs, maxPauseMs)`, where speech is this segment's own audio after the tail trim |

Two things reshape these pauses for a segment that is part of a tag or an
alternative; both are in "Tags and alternatives" below.

**Earcons (`earcons`).** Role to file path; blank is the default tone, generated
once into `<add-on>/user_files/earcons/` by `src/earcons.py`:

| Role | Tone | Length |
|---|---|---|
| `sectionBoundary` | soft tick, 1320 Hz, decaying | 120 ms |
| `answerStart` | rising, 523 to 784 Hz | 220 ms |
| `directionFlip` | steady, 392 Hz | 180 ms |
| `sectionNumber` | falling two-note step, 880 then 587 Hz (A5, D5), 110 ms each | 220 ms |
| `sectionLetter` | rising two-note step, 784 then 1046 Hz (G5, C6), 65 ms each | 130 ms |
| `idiomHeading` | low falling glide, 440 to 330 Hz (A4 to E4) | 240 ms |

The first three are the original sounds (CA-37 (4)); RCE stops emitting them in
card-8 but a plan that still does must not fail. The last three are CA-71 (1)
and are played *before* the thing they mark, never after (see "Earcons, the
connective after an example, the audio audit" below).

All -20 LUFS, measured looped because they are shorter than a BS.1770 block
(section 17, its CA-40). A replacement file is used as it is; it is not
normalised.

**Layout of one segment:** pause before, earcon before, 120 ms, speech, 120 ms,
earcon after, pause after. An alternative that takes an "or" starts with the
"or" block instead of its pause before (below). A segment with `spoken: false` contributes nothing:
no audio, no pause, no earcon, no part in the track's identity.

### Cache identity (P5)

| Change | Segment audio | Track |
|---|---|---|
| Text, language, role, voice role, resolved voice | regenerates | new name |
| Effective rate (including a tempo profile's `rate`) | regenerates | new name |
| Pause kind, or a tempo profile's pause numbers | reused | new name |
| Earcon use, or an earcon file's contents | reused | new name |
| Tempo profile's name, if the rate is the same | reused | new name only if its pause numbers differ |

A version 2 segment's key adds `role`, `voice_role`, `resolved_voice`
(`<provider identity>/<voice>`, or `own-voice` for Pocket and Fish) and
`role_voice_version` (`"1"`, `structured_audio.ROLE_VOICE_VERSION`). A version 2
track's identity adds `stitch_version` (`"2"`, CA-68), the tempo's pause numbers
(`tight_pause_ms` among them), the sha256 of each earcon it uses, and each
segment's role, voice role, slot provider, pause kinds and earcon names, its
attached side when it has one, and the identity, text, voice and rate of the
"or" clip spoken before it when it has one. **A version 1 plan gets none of this**:
its keys and track names are pinned against values recorded before version 2
existed (`tests/test_speech_plan_v2_e2e.py`).

### Settings and migration

New keys, all merged over the defaults on load, so an older config loads with
nothing to do and nothing is written until Save in the dialog:

```json
"provider_chain": ["edge"],
"role_voices": {
  "fr": {"content": {"provider": "edge", "voice": "fr-FR-VivienneMultilingualNeural"},
         "label":   {"provider": "edge", "voice": "en-US-BrianMultilingualNeural"}},
  "en": {"content": {"provider": "edge", "voice": "de-DE-SeraphinaMultilingualNeural"},
         "label":   {"provider": "edge", "voice": "en-US-AndrewNeural"}}
},
"tempo_profiles": {"default": {"rate": 1.0, "pauseFactor": 0.35, "minPauseMs": 250, "maxPauseMs": 1200, "boundaryPauseMs": 700, "tightPauseMs": 120}},
"earcons": {"sectionBoundary": "", "answerStart": "", "directionFlip": "", "sectionNumber": "", "sectionLetter": "", "idiomHeading": ""}
```

The dialog's **Speech Plans** tab has the four slots (the shared voice picker
over the whole live catalogue, the four defaults always offered, even with no
network), the tempo table and the earcon paths. `settings_version` is written
only by the dialog's Save (CA-45).

The **Speech Profiles** tab's voice lists used to show only the language's own
locale. They now start with those and go on to every other voice (Alec,
2026-11-06), so Seraphina (de-DE) can serve the English profile and version 1
cards can use a CA-41 voice before card-4. This does not undo CA-42: a version 1
key changes only if the user chooses a different voice, and each language then
has one voice, with no label voice.

### Language to the engine (CA-55, CA-56)

Edge's multilingual voices choose the language of what they read from its text.
A bare headword, a short label, or a word spelled alike in both languages is
read as English, although the plan tags it `fr`. The cause, as the RCE chat
found it: `edge-tts` writes `xml:lang='en-US'` into every request
(`edge_tts.communicate.mkssml`) and escapes the text, so the plan's language
never reaches the voice. CA-54 (in the plan file, not copied here) is the rule
for RCE's planner, which already complied.

**Ruling CA-55 (Alec, 2026-11-06, evening, relayed from the RCE chat), verbatim:**

```
Context: first listening of card-4 output with the CA-41 multilingual voices: headwords, short labels
and words spelled alike in both languages are read as English although the plan tags every one fr.
Cause (RCE chat): multilingual Edge voices detect the language from the text; edge-tts hard-codes
xml:lang en-US and escapes the text, so the plan's language never reaches the voice. Monolingual fr
voices read everything correctly. CA-54's premise (that RCE tagged the language wrong) was the card
chat's error; CA-54 (1) stands as the rule for RCE's planner, which already complied.
1. Keep the multilingual voices. AnkiTTS sends each segment's language to Edge as SSML: a
   `<lang xml:lang="...">` element inside `<voice>`, the plan's language mapped to fr-FR / en-US
   (and ja-JP for the existing profile).
2. One probe call first proves the Edge endpoint honours `<lang>` on a multilingual voice; the
   fallback is the top-level `xml:lang` set per segment instead of the hard-coded en-US.
3. The language, as sent, joins the cache key (a version bump so the wrongly spoken audio refills).
4. One AnkiTTS stage, Sonnet 5 high.
5. Noted for a later RCE card stage: a bracketed placeholder inside an example is voiced as a label;
   the headword's inflection marker on the own-page back is spoken.
```

**The probe (2026-11-06)** found neither route in items 1 and 2 works. With
`fr-FR-VivienneMultilingualNeural`, a `<lang xml:lang='fr-FR'>` element returns
no audio at all (`NoAudioReceived`), whether it wraps the text inside
`<prosody>`, sits outside it, or stands alone in `<voice>`. The top-level
`xml:lang` is accepted and changes the audio, but by the same amount and in the
same way for `fr-FR`, `de-DE` and `en-GB`: over seven words spelled alike in both
languages, none moved toward the voice's own French reading under any of the
three locales (mean cepstral-distance margin -10.5 against -10.5 as before; a
French reading would have moved it by about 19). `edge-tts` has no raw-SSML
entry point either; the only seam is replacing the module-level `mkssml`.

**What is sent instead (CA-56).** A short segment is spoken after a short
sentence that is unmistakably in its language, and the sentence is cut off
again. The request is the library's own SSML, unchanged; only the text differs:

```
fr  segment text "important"  ->  Écoutez bien le mot suivant : important
en  segment text "table"      ->  Listen carefully to the following word: table
```

`Communicate(..., boundary="WordBoundary")` returns the start of every word in
100 ns ticks. The carrier's words come first and are counted, so the segment's
first word begins at the next event's offset. The audio is cut `0.02 s` before
it into 24 kHz PCM (lossless) and goes through the same one loudness
normalisation and MP3 encode as any Edge clip. Punctuation and dashes are not
words and do not produce events; the carrier's last word is checked against its
event before the offset is trusted.

| | |
|---|---|
| Applies when | the voice's name contains `Multilingual`, the segment's primary language subtag is `fr` or `en` (`fr`, `fr-FR`, `en_US` all work), and the text has 1 to 4 words (tokens containing a letter or digit) |
| Does not apply | monolingual voices (they read their own language whatever the text), `ja`, an unknown or missing language, longer text (recognised correctly on its own, and a carrier would only change its first intonation) |
| Both paths | the generic path (language from detection) and the structured path (the plan's `language`) both reach `EdgeProvider.synthesize` with the language; nothing else changed |
| Fallback | offsets that do not look like the carrier followed by a word, or a cut that fails: the segment is generated without a carrier, a warning is logged (never the text) |
| Retry | the same as without a carrier: `NoAudioReceived` is retried 1, 2 and 4 s, then reported |
| Rate, volume, pitch | unchanged; they apply to carrier and text together, and the offsets are measured, not assumed |
| Cache | `edge_language_version` `"1"` in the Edge provider's identity (`providers.edge.EDGE_LANGUAGE_VERSION`) |

Acceptance, through the real service with the CA-41 voices, on the version 2
fixture plus two extra segments ("important" in the content voice and "Voir
aussi" in the label voice): 26 Edge syntheses, 12 with a carrier (8 French, 4
English), none fell back. The 8 French carrier segments' margin (distance to the
voice's English-carrier reading minus distance to its French-carrier reading;
positive is French) went from a mean of 3.7 without the carrier to 16.0 with it,
against a separation between the two references of 17.2; "important" went from
-12.2 to +23.6. This measure cannot hear, and the "after" clips are the same
method as one of the references, so the "before" column is the independent
evidence. The ear decided: Alec listened to the probe files (2026-11-06) and
judged the carrier-and-cut readings "great".

**Note on saved settings.** `addon/meta.json` holds what the settings dialog
saved. If the French content and label slots there name a monolingual voice
(Denise, Henri), the carrier is not used for them, by design, and the voice
speaks as that voice does. The CA-41 defaults are multilingual.

### Tags and alternatives (CA-61, 2026-11-07)

**Ruling CA-61 (Alec, 2026-11-07, 07:25-09:03, the card review of 16 French Deep
Study rows), verbatim, from `AnkiTTS-Card-Audio-Bakeoff-Plan-20261029.md`.** This
stage implements parts 4, 7 and 9. Parts 1 to 3, 5, 6, 8 and 10 are RCE's (its
planner and card stage) and are copied here as context only.

```
Alec's design decisions, each stated on a card he reviewed against the GUI; the fidelity defects he
found are listed separately in RCE-CardStage-List-20261107.md.
1. Deep Study and Deep Recall fronts carry the headword alone (plus the part of speech where the
   entry has one); everything else -- sense label, section letters, sub-labels, glosses, examples --
   is on the back in dictionary order. These are listening decks, not recall tests.
2. The inflection marker ("circonspect, e") is never spoken, on any card. Display unchanged.
3. Cross-references ("voir ...", "Voir : ...") are never spoken, in any preset. Display unchanged.
4. Between the translation alternatives of an EXAMPLE (the dictionary's "|"), the content voice
   says ", or, " (", ou, " on a French-side translation), as a connective with a small pause each
   side. A sense's gloss alternatives keep their small pauses with no "or".
5. A bracketed PLACEHOLDER inside an example ([quelque chose], [quelqu'un], [somebody], [oneself])
   is part of the sentence: content voice, read in the flow, brackets silent. A bracketed
   ANNOTATION inside an example ([sujet : ...], [+ ...], a domain or register tag) is a label:
   label voice, with its pauses, and typeset in the label font on the card.
6. Object tags "[+ x]" are spoken "objet : x" on a French entry and "object: x" on an English one,
   so that sujet-tags, objet-tags and the « near-synonyms » are audibly distinct. Display keeps "+".
7. Pauses follow the dictionary's tree. Every tag or label is attached to the element it qualifies,
   whichever side it is printed on; the pause is tight between a tag and its owner and a boundary
   at the owner's edge. Inside a sense the pause is graded by depth: longer after the sense-level
   label (e.g. /Militaire/) than after a sub-label (e.g. [+ recrues]), longer still between senses,
   before an idiom block, and between a sense's translations and its examples. The lengths are
   AnkiTTS's tempo table; the kinds are the plan's.
8. The section earcon sounds only where a numbered or lettered section begins, immediately before
   the section number or letter is spoken; a Sense card, which contains no section change, has no
   section earcon.
9. A "[somebody]'s" is spoken "somebody's" and displayed without a space.
10. The engine finds and fixes the fidelity defects itself from the seed entries (terrain, prise,
    jeter, clair, engager, rapporter, circonspect), as in CA-36, with the GUI PDFs as the reference.
```

**What AnkiTTS does with it (this stage).**

| Part | Done by | What |
|---|---|---|
| 9 | `speech_text.prepare_for_speech` (rule 4) | A bracket touching a letter, an apostrophe (`'` or `’`) or a hyphen that joins two parts of a word keeps no space on that side. `[somebody]'s` is `somebody's`, `[x]-like` is `x-like`, `l'[objet]` is `l'objet`, `[quelque chose]s` is `quelque choses`. A bracket followed or preceded by a space is read as before. The clitics `'s 'd 'll 're 've 'm n't` after a word were already never a lone letter (the lone-letter rule skips a letter touching an apostrophe); a test now pins it, with either apostrophe and with the word coming from a bracket. The display is RCE's. |
| 7 | `speech_plan` (`attachedTo`), `structured_processor` (the side), `stitcher` (the pause) | A tag names its owner. If the tag comes before its owner in the plan, the pause **after** the tag is the tight pause; if it comes after, the pause **before** the tag is. That side is the tempo profile's `tightPauseMs`, fixed, whatever the plan says there. Nothing else changes: the owner's own pauses, and the tag's pause on its outer side, are the plan's. |
| 4 | `structured_processor` (who takes an "or"), `structured_audio` (the clip), `stitcher` (the layout) | An alternative that directly follows, among the spoken segments, a translation or an alternative of the same `contentNodeId` in the same base language is preceded by the content voice saying `or,` (English) or `ou,` (French). |
| 7 (lengths) | `tempo_profiles` | The pause lengths are the tempo table below; the pause kinds stay the plan's. |

**The "or" (part 4), exactly.** The condition, in order: the segment's role is
`alternative`; the previous *spoken* segment's role is `translation`,
`alternative`, `exampleSource` or `exampleTarget` (the last two since review
batch 2, CA-76: an alternative that continues an example line); both have the
same nonempty `contentNodeId`; both have the same
base language (`fr-FR` and `fr` are one), which is `en` or `fr`; the segment's
`repetitionNumber` is 1. A role `gloss` never takes it, so a sense's gloss list
keeps its small pauses. The word is `speech_text.ALTERNATIVE_WORDS` plus a comma:
`or,` / `ou,`. It is a segment of its own, synthesised through the ordinary
chain in the content voice of the alternative's language, at the speech
profile's rate times the tempo profile's rate (the alternative's own
`speakingRate` does not apply), with the role `connective` in its cache
identity. So there is **one clip per language, content voice and effective
rate**, found in the cache by every alternative that needs it, on this card and
on any other. On a multilingual voice a one-word text is a carrier-sentence
case (CA-57), so `ou,` is spoken as French. The plan's text is untouched.

Layout: *tight pause, the clip, tight pause*, then the alternative's own earcon
and speech. The block **replaces** the pause after the previous segment and the
pause before the alternative (CA-63). Timeline kinds: `connective_pause_before`,
`connective`, `connective_pause_after`.

**The tempo table, with the new column.** The dialog's **Speech Plans** tab has
the same columns; the new one is "Tag / or pause (ms)".

| Profile | `rate` | `pauseFactor` | `minPauseMs` | `maxPauseMs` | `boundaryPauseMs` | `tightPauseMs` |
|---|---|---|---|---|---|---|
| default | 1.00 | 0.35 | 250 | 1200 | 700 | 120 |
| deep-entry-study | 1.00 | 0.35 | 250 | 1200 | 900 | 120 |
| deep-recall | 0.95 | 0.45 | 300 | 1500 | 900 | 120 |
| sense-map | 1.00 | 0.30 | 200 | 1000 | 600 | 120 |
| translation-group | 1.00 | 0.30 | 200 | 1000 | 600 | 120 |
| example | 1.00 | 0.30 | 200 | 1000 | 600 | 120 |
| sentence | 1.00 | 0.30 | 200 | 1000 | 600 | 120 |

A saved table without the column resolves it from the default row, so no saved
config needs migrating. `tightPauseMs` is a whole number of milliseconds, zero or
more; zero makes the tag's side and the "or"'s two sides gaps of nothing. It
changes the track and never a segment's audio.

**What refills.**

| Version | Now | Effect |
|---|---|---|
| `speech_text_version` | `"4"` | every segment's audio, on the generic and the structured path and for every provider, refills once (it is in each provider's identity). Only text with a bracket touching a word is spoken differently; the key moves for all text. |
| `stitch_version` | `"2"` | every version 2 track is rebuilt from the cached audio once (and the tempo identity gains `tight_pause_ms`). No audio is synthesised for it, except the new "or" clips. |

Version 1 plans, keys and track names are untouched (the pinned names in
`tests/test_speech_plan_v2_e2e.py` still hold); a plan without `attachedTo` and
without alternatives is stitched exactly as before.

**What RCE must emit for the tags to be heard** (the next card stage; an "or" is already spoken for any plan of the shape below): `attachedTo`
on a tag, with `{"kind": "none"}` as the *owner's* pause on the tag's side when
the tag follows its owner (otherwise the owner's own pause after adds to the
tight one), and `role: "alternative"` with the **same `contentNodeId` as the
translation it follows** for each of an example's `|` alternatives, in the
alternative's language, each with repetition number 1. See CA-64 and CA-66.

### Rulings (the implementing session, 2026-11-06)

Option taken, then option not taken.

- **CA-42 Version 1 plans and the generic path keep their speech profile's
  voice.** The brief says a segment without `voiceRole` "is content", and also
  that version 1 stays byte-identical on its cache keys (P1, P3). Both cannot
  hold if "content" means the content slot: the voice is in the key. So such a
  segment is content in meaning only and resolves as it always did. **The
  consequence Alec will notice:** until card-4 emits version 2, real RCE cards
  and plain notes speak in Denise and Jenny (his saved speech profiles), on Edge,
  not in the CA-41 voices. *Not taken:* sending them
  through the content slot, which would refill every version 1 card and change
  plain notes' voices, against P1 and P3.
- **CA-43 `role` is in the segment key as well as `voice_role`.** The brief
  names voice role and resolved voice; P5 also names role. P5 is the design, so
  it is followed: the same text as a `gloss` and as a `translation` is
  synthesised twice. *Not taken:* voice role only, which would share that audio
  but would need the design changed.
- **CA-44 A tempo profile's `rate` is a synthesis input.** P5 says tempo is
  stitch-time and never in a segment's key; section 4 of the same note says a
  provider with native rate uses it and one without gets `atempo` after
  synthesis, "as today". They conflict for `rate` alone. Taken: the rate
  multiplies `speakingRate` and the result goes to the provider, so Edge speaks
  it natively and the *effective* rate is in the key, as every rate already is.
  The profile's name and pause numbers are not, so two profiles at the same rate
  share audio. *Not taken:* `atempo` at stitch time for every provider, which is
  P5's letter but processes Edge's audio for no reason and reports pauses from a
  different duration.
- **CA-45 The saved chain migrates.** `addon/meta.json` holds the whole dialog
  config, including `["pocket", "fish", "edge"]`, and overlays `config.json`, so
  changing the default alone would change nothing for Alec, who is to "set
  nothing". On load, a config with exactly the old default and no
  `settings_version` becomes `["edge"]`; nothing is written. Save writes
  `settings_version: 2`, so choosing that order again afterwards sticks, and any
  other saved order is respected. The marker is not in `config.json`, or Anki's
  overlay would make every old config look current. *Not taken:* editing
  `meta.json` (Anki's file, and it would not help anyone else); asking Alec to
  change the order by hand.
- **CA-46 A slot on Pocket or Fish names the provider only.** Both take their
  voice from their own settings per language, and this stage leaves them
  untouched, so content and label on Pocket are the same clone (split in the
  cache by voice role). If the chain falls through to Edge, Edge speaks the
  role's CA-41 default. A slot on a provider not in the chain is not honoured:
  the chain is used and a warning logged; the dialog marks it "(not enabled)".
  *Not taken:* a per-role clip or Fish id, a change to both providers that
  nothing needs while both are off (CA-38 (2), CA-40 (3)).
- **CA-47 Strict version 2.** `role`, `voiceRole`, `preset` and `tempoProfile`
  are required; so are all twelve version 1 fields; a pause object has exactly
  its kind's fields; `null` is not "absent". *Not taken:* defaulting a missing
  `voiceRole` to content in version 2, which would hide an RCE serialiser defect
  as the wrong voice on a card. RCE's serialiser must omit absent fields.
- **CA-48 A proportional pause measures the speech after the tail trim.** Edge
  clips end in about 800 ms of silence, which would otherwise add about 280 ms
  to every pause and make the numbers mean something other than "what was just
  said". `fixed` and `boundary` are not clamped. *Not taken:* the file's length.
- **CA-49 An earcon stays 120 ms from its speech; the plan's pauses go outside
  it.** So a section reads: previous speech, boundary pause, tick, 120 ms, new
  speech. The 120 ms is a constant (`stitcher.EARCON_GAP_MS`, covered by
  `stitch_version`), to be tuned by ear with the rest. *Not taken:* no gap (a
  tone running into a word); a setting (a number nobody has asked to change).
- **CA-50 Default earcons are computed with the standard library and calibrated
  with ffmpeg**, stored as WAV. Nothing new for Anki's bundled Python to load,
  and the brief's stop does not arise. A named file that has gone missing falls
  back to the default with a warning (a moved sound should not stop a card); the
  dialog refuses to save a path that does not exist. *Not taken:* numpy (not in
  the vendored libs); MP3 defaults (an extra generation, and encoder padding
  around a 120 ms tone).
- **CA-51 The brief's "one refill" has nothing to refill.** Version 2 keys are
  new, and version 1's must not move, so the identity change itself refills
  nothing. The version fields exist so that a later change can refill once, as
  `speech_text_version` and `loudness_version` did. Separately, CA-38's move to
  Edge means a card regenerated now gets Edge audio: its key differs because the
  provider does, as it always has. *Not taken:* bumping a version on version 1
  keys.
- **CA-52 These rulings are in this section.** The brief says section 15, whose
  last ruling is CA-34; CA-35 to CA-41 went to section 17. Section 15 points
  here. *Not taken:* splitting one design between two sections.
- **CA-53 `CLAUDE.md`'s provider line is updated to CA-38**, as CA-18 did for
  CA-3. *Not taken:* leaving project memory contradicting Alec's ruling.

Rulings for the language stage (2026-11-06, evening). CA-54 and CA-55 are Alec's
and live in the plan file (CA-55 is quoted above).

- **CA-56 The language reaches the voice as a carrier sentence, not as SSML.**
  CA-55 items 1 and 2 are exhausted by their own probe (above), and the ruling's
  premise that the endpoint takes a language does not hold. After the probe the
  files with the carrier cut were played to Alec, who answered: "1&2, 7&8, 11&12
  indeed sound the same. 5 and 9 sound great. I still don't like Denise's voice
  in 3". Files 5 and 9 were the carrier-and-cut sample, so the implementing
  session read this as the choice of that route; Alec did not name it, and a
  different decision from him replaces this ruling. *Not taken:* building the top-level `xml:lang` because the endpoint
  accepts it (it does nothing for the defect); French monolingual voices for the
  French slots (Alec rejected Denise's sound, and it would reverse CA-41).
- **CA-57 A carrier is added only for a multilingual voice, French or English,
  and one to four words.** Where the voice is monolingual it already reads its
  own language; a longer segment is recognised on its own, and a carrier would
  alter its first intonation and cost another second of audio. The limit is
  `EDGE_CARRIER_MAX_WORDS`. *Not taken:* a carrier on every Edge segment (simpler,
  but it changes what already sounds right).
- **CA-58 The carrier sentences are the ones Alec heard.** French "Écoutez bien
  le mot suivant :", English "Listen carefully to the following word:". The
  English one covers the mirror case, an English gloss that looks French, on
  Seraphina. The cut falls 20 ms before the first word's reported start, as in
  the probe files, and the audio stays lossless until the one normalising
  encode. *Not taken:* a shorter carrier (less audio, but it was not what was
  judged); re-encoding the cut as MP3 (one more lossy generation).
- **CA-59 A segment that cannot be cut is generated without a carrier.** If the
  word offsets do not match, or ffmpeg fails, the previous behaviour applies and
  a warning is logged; the card still gets audio. *Not taken:* failing the
  segment, which would turn an unusual text into a missing card.
- **CA-60 `edge_language_version` is in the Edge provider's identity only.** The
  shared base identity that pins version 1 key shapes (`get_edge_provider_identity`)
  is untouched, so those pins hold; every Edge segment, short or long, refills
  once, because the identity does not know the voice. *Not taken:* a version
  that only moves multilingual-voice segments, which needs the voice in
  `identity()`.

Rulings for the review stage (2026-11-07). CA-61 is Alec's and lives in the plan
file (quoted above). Option taken, then option not taken.

- **CA-62 One tempo field, `tightPauseMs`, default 120 ms, serves both uses.**
  The short pause between a tag and its owner and each side of the spoken "or"
  are the same field, in all seven profiles, in the dialog as "Tag / or pause
  (ms)". (The managing chat's term; the code had no reason to differ.) *Not
  taken:* two fields; a pause that is a fraction of the segment.
- **CA-63 The "or" replaces the pause between the two alternatives; it is not
  added to it.** Ruling 4 says "a small pause each side". The plan gives the
  previous translation a proportional pause after it (200 to 1200 ms), and
  adding that to the tight pause would put the "or" far from the alternative it
  follows, up to 1.3 s. So the block is tight, "or", tight, and the previous
  segment's pause after and the alternative's pause before are not laid out.
  Earcons stay where they are. *Not taken:* adding the plan's pauses to the
  tight ones (the literal reading of "a pause each side" plus the plan).
- **CA-64 Which alternative takes an "or" is decided from the plan alone, among
  the spoken segments, and only where the plan is unambiguous.** Same nonempty
  `contentNodeId`, same base language, language `en` or `fr` (a language with no
  word has none), role `alternative` after `translation` or `alternative`, and
  `repetitionNumber` 1 (the second repetition of an alternative is that
  alternative again, not another one). An unspoken segment is not "between"
  anything. *Not taken:* inferring alternatives from the text; an "or" for a
  language we have no word for; an "or" before every repetition.
- **CA-65 The "or" is a segment of its own with the text `or,` / `ou,`.** The
  comma stays in the text (the engine pauses on it and the tail trim removes the
  silence after it). It is synthesised in the content voice, whatever the voice
  role of the alternative, at the speech profile's rate times the tempo
  profile's rate, not at the alternative's `speakingRate`; its role in its
  identity is `connective` (not a plan role). So it is shared by every
  alternative of a language, voice and rate. *Not taken:* the alternative's own
  rate (one clip per rate); a clip without the comma; adding `or` to the
  alternative's text (it would change that clip's key).
- **CA-66 A tag's tight pause overrides only the tag's own side; the owner's
  pauses are not touched.** This is the managing chat's term C taken literally
  ("No other pause changes"). The consequence for RCE: when a tag follows its
  owner, the owner's pause after sits on the same gap as the tag's tight pause
  before and adds to it, so the plan should give the owner `{"kind": "none"}`
  there (the fixture does). *Not taken:* also zeroing the owner's pause on the
  tag's side, which would make the tight gap hold whatever RCE emits.
- **CA-67 `attachedTo` is validated as an id and no more.** It must name another
  segment of the same plan, forward or backward, as the brief says. It may name
  an unspoken segment or a segment that is itself a tag; in either case, or when
  the tag itself is unspoken, there is no attached side and the plan's pauses
  apply. *Not taken:* rejecting chains, cycles, or an unspoken owner (nothing in
  the ruling needs the rule, and a plan that is wrong in that way is still
  playable).
- **CA-68 `stitch_version` is `"2"` and the track name carries the attached
  side, not the owner.** Two tags on the same side of different owners give the
  same track. The "or" clip's identity, text, voice and rate are in the name of
  the track that uses it. Every version 2 track is rebuilt once, from the cached
  audio. *Not taken:* leaving `"1"` and renaming only the tracks that use the
  new features (the tempo identity gained a field, so every name moved anyway).
- **CA-69 `speech_text_version` is `"4"`, and the clitic half of the brief needed
  no code.** The bracket rule is the change; the version is global to every
  provider's identity, so every segment's audio refills once, including text
  with no bracket. A hyphen counts as joining only when a letter or digit is on
  its other side (`[x]-like`, not `[x] - y`); a digit does not attach (`3[x]`).
  The lone-letter rule already never spells a letter touching an apostrophe, so
  `'s 'd 'll 're 've 'm n't` were safe; the tests pin it. *Not taken:* a second
  rule for clitics; bumping only for text with brackets (a key cannot see the
  text it keys).
- **CA-70 The v2 fixture's idiom block now has an "or".** `ds-14` (translation)
  and `ds-15` (alternative) already share a node and a language, so the rule
  applies there as well; the fixture, which was written for roles and not for
  this, was left as it was and the e2e check was changed to expect it. Section 4
  was added for the new cases. *Not taken:* giving `ds-15` another node to keep
  the old timeline.

### Earcons, the connective after an example, the audio audit (CA-71, 2026-11-09)

**Ruling CA-71 (Alec, 2026-11-09, Denver, after reviewing every deck following
RCE's card-6 install), verbatim.** The managing chat's reading follows the quote
and is its own, not Alec's.

```
(1) THE EARCONS (Alec, 19:17): "A note on the earcons ― There should be a unique
earcon for: 1. Marking the start of a numbered section 2. Marking the start of a lettered
sub-section. As discussed, these should occur before the number or letter and not after. There
should be no other earcons, unless I'm missing an important point of demarcation that you think
would warrant its own unique earcon?"
(2) THE IDIOM BLOCK (Alec, 19:19; the one idiom heading he named is omitted, as card text):
"I agree with the idiom block, but we need to make
sure that it truly is for idioms such as [an idiom heading] that appear within a sense. If we're
looking at a "set phrase", "locution", "compound word", or "mots composés" section, I absolutely
do not want or need an earcon before every individual item in those sections."
(3) NEVER SILENT (Alec, 19:08, said of a Deep Study card whose front carried a speech plan with no
segments and so no audio): "This should never ever happen for any reason on any card in any deck."
```

The managing chat's reading of the three parts (its own): (1) and (2) decide
three earcons -- a numbered section's start, a lettered sub-section's start, the
heading of an idiom block inside a sense (once per block, never per item) -- each
BEFORE the thing it marks, and no other; (3) decides that a side whose plan has
spoken segments must have audio. The prevention is RCE's (card-8's contract test
that a side with text has a plan with segments; card-7's visible "no audio" mark
on the template); this add-on's part is the net under it, the audio audit, so
that any silence that still occurs is reported and not discovered in review.

What this stage does about it: item A the three earcon kinds, item B the
connective after an example, item C the audit, item D (read only) the pause
lengths. The session's own rulings follow in "Rulings for review batch 2" below.

**A. The three earcon kinds.** The plan's `earconBefore` accepts `sectionNumber`
(the start of a numbered section), `sectionLetter` (the start of a lettered
sub-section) and `idiomHeading` (the heading of an idiom block inside a sense,
once per block and never per item), beside the original three, which stay
accepted in `earconBefore` and `earconAfter`. A new kind in `earconAfter` is a
validation error for the whole plan. The layout is unchanged: pause before,
earcon, the fixed 120 ms gap, speech. Which segments carry the kinds is RCE's
(card-8). Each has a default tone (table under "Earcons" above), generated into
the same `user_files/earcons` folder, calibrated to -20 LUFS, and replaceable by
a file in the `earcons` map (`config.json`, `settings.py`, and a row each in the
dialog's earcon list); a blank path is the default.

**B. The connective after an example line.** An `alternative` whose previous
spoken segment is an `exampleSource` or an `exampleTarget` of the same
`contentNodeId` and the same base language takes the same "or" block as one
after a translation: `ou,` after a French line, `or,` after an English one, the
block replacing the two pauses on the gap (CA-63). A gloss still never takes it
and an alternative whose language differs from its predecessor's takes none
(CA-64 unchanged). RCE marks the dictionary's `|`, an inline "ou" / "or" inside
one translation or example and the "/" between alternatives inside one phrase
as role `alternative` on the same node, in that segment's language, with the
marker dropped from the text.

**C. The audio audit** (`src/audio_audit.py`; reported by
`anki_integration/browser.process_note_ids`). After every generation run, the
sides that carry a schema-version-2 plan are audited and reported as counts with
note ids, never a segment's text:

| Count | Meaning | Reasons (fixed phrases) |
|---|---|---|
| silent sides | the plan has spoken segments, no audio was produced or attached | no track was produced; the track file is missing from Anki's media folder; the audio field is empty; the track could not be copied into Anki's media folder; synthesis failed |
| empty sides | the plan has no spoken segment (no segments, or every one `spoken: false`): RCE's defect | the plan has no spoken segment |
| rejected plans | the validator refused the plan | the plan was refused by the validator |

Where: the run's result message (the information box of a browser run, or its
returned message), as `Audio audit: 0 silent sides, 0 empty sides, 0 rejected
plans.` when clean, and as a banner (`*** AUDIO AUDIT: n SIDES WITHOUT AUDIO THAT
SHOULD HAVE SOME ***`) with the three counts and the notes when not, in a
warning box instead of an information box. A failed run carries it at the end of
its failure message. The add-on's log gets one line of counts and ids. An
unattended run (the immediate-audio poll) shows a warning dialog when the audit
is not clean; a watched run (Tools > Generate Pending RCE Audio) shows it inside
its own result.

**D. The pause lengths, read only.** No file under `src/providers` and no pause,
tempo, carrier, voice or provider code changed for this item.

| Kind | What it yields (every profile) |
|---|---|
| `none` | 0 ms |
| `fixed` | the plan's milliseconds, exactly, in every profile |
| `boundary` | default 700; deep-entry-study 900; deep-recall 900; sense-map, translation-group, example, sentence 600 |
| `tight` (a tag's side, an "or"'s two sides) | 120 in all seven profiles |
| `proportional` at scale 1 | `0.35 x speech` clamped 250 to 1200 (default, deep-entry-study); `0.45 x speech` clamped 300 to 1500 (deep-recall); `0.30 x speech` clamped 200 to 1000 (the other four). For a one-second headword: 350, 350, 450, 300 ms |
| a head-line value | none exists in the table. The head line's pause is the plan's: RCE emits `fixed 900` after the headword (the design note, section 3) on every side, so it is 900 ms in every profile and the tempo table cannot move it |

What would make the Sense Map front's pause brief, touching no other pause: RCE
(card-8) emitting `{"kind": "proportional", "scale": 1.0}` instead of
`{"kind": "fixed", "milliseconds": 900}` after the front's head line. That kind
reads as brief: in the `sense-map` profile it is 0.30 of the headword's speech
clamped to 200 to 1000 ms (about 200 to 400 ms for a headword of a second or
two). `tight` (120 ms) is shorter than a pause between a headword and a gloss
wants to be, and `boundary` (600 ms in `sense-map`) is the long one. The back's
head line takes `boundary` (900 ms in `deep-entry-study` and `deep-recall`, 600
in `sense-map`). No add-on change is needed for either. If a separate "brief"
length that is not tied to the headword's duration is wanted later, it would be
a new tempo field (like `tightPauseMs`), which is an add-on change and has not
been made.

### Rulings for review batch 2 (2026-11-09)

CA-71 is Alec's (above). The session's own calls, option taken, then option not
taken. Taken unattended, on the session's own read of the code.

- **CA-72 `stitch_version` stays `"2"`; no track refills for A or B except the
  ones that use the new features.** The track identity records each segment's
  earcon name and the sha256 of each earcon file *used*, and the "or" clip of a
  segment that has one; a track using only the old three names has the same name
  as before (the legacy fixture plan, front and back, gave the identical file
  names before and after this stage), a track using a new name could not exist
  before (the plan was refused), and a track that now gets an "or" differs by
  that clip alone. *Not taken:* stepping to `"3"`, which would rebuild every
  version 2 track once for no change.
- **CA-73 The three names are `sectionNumber`, `sectionLetter`, `idiomHeading`,
  as suggested; `VALID_EARCONS_BEFORE` has six, `VALID_EARCONS_AFTER` the old
  three, `VALID_EARCONS` is the six.** The old names stay accepted in both
  places because a plan that still carries one must not fail. *Not taken:*
  other names; accepting the new names in both places and only documenting
  "before".
- **CA-74 A lettered sub-section's role stays `sectionNumber`.** The contract
  has no role for a letter (the design note and CA-61 (8) treat numbers and
  letters together, both label voice), so the segment of a letter is a
  `sectionNumber` segment whose `earconBefore` is `sectionLetter`. The earcon
  kind, not the role, tells a number from a letter. *Not taken:* a new role
  `sectionLetter`, a contract change RCE would have to follow, with no effect on
  what is heard.
- **CA-75 The tones.** `sectionNumber`: a falling two-note step (A5 then D5, 110
  ms each, 220 ms), the longest and most definite. `sectionLetter`: the lighter
  sibling, a rising two-note step (G5 then C6, 65 ms each, 130 ms), higher and
  about half as long. `idiomHeading`: a low falling glide (A4 to E4, 240 ms), in
  the register none of the other five uses. Told apart by direction, pitch and
  length, which `test_earcons.py` measures from the generated audio for every
  pair of the six (measured: 731.8 Hz falling / 915.4 Hz rising / 383.3 Hz
  falling, against 1316.7 flat, 654.5 rising and 388.9 flat). `EarconTone` gains
  `notes` (steady notes joined end to end, each with soft edges) and
  `fade_milliseconds`; `EARCON_VERSION` stays `"1"` because the original three
  tones are unchanged and a new tone has its own file name. *Not taken:* trains
  of pulses with silent gaps (the e2e frequency probe reads them unreliably);
  bumping the tone version.
- **CA-76 The previous-role set gains `exampleSource` and `exampleTarget`** and
  nothing else about CA-64 changes (same nonempty node, same base language,
  repetition 1, `en` or `fr`). The word follows the alternative's language
  (CA-65). *Not taken:* `gloss` (a sense's gloss list keeps its small pauses);
  letting an English alternative continue a French example line.
- **CA-77 The audit reports in the run's own result, and reports only.** It adds
  no tag, withholds no "ready" tag and fails no run by itself: a silent side is
  reported (banner, warning box, log line, and a warning for an unattended run)
  and the notes are published as before. *Not taken:* refusing to mark a note
  ready while a side is silent, which would change which cards the automation
  treats as done on Alec's say-so, and which this stage was not asked for.
- **CA-78 The run stays all-or-nothing, but every refused plan is counted.** The
  contract reads both sides of a plan (the message is still the first refusal's)
  and the browser path scans the whole selection before it stops, so a batch
  with three refused plans reports three. *Not taken:* skipping the refused notes
  and processing the rest, a change to the run's transaction that nobody asked
  for.
- **CA-79 The audit's scope and its reasons.** Only schema version 2 sides are
  audited (a version 1 plan has no `spoken` flag; the generic path is not the
  audit's); a refused plan is counted whatever its version because it cannot be
  read. When a run fails at a note, that note's spoken sides are reported silent
  with the reason "synthesis failed" (or, if the copy into Anki's media failed,
  every audited note's, with its own reason); the notes after the failing one
  are not named, because the run never reached them. Reasons are fixed phrases:
  an exception's text can hold a segment's text and is never put in a report or
  the log.
- **CA-80 Item D is read only** and its finding is in the table above: a head
  line's pause is the plan's `fixed 900`, so the tempo table has no value for it;
  `proportional` reads as brief and `boundary` as long, and the change is RCE's.

**What refills.** Nothing, for these three items: no version moved
(`speech_text_version` `"4"`, `stitch_version` `"2"`, `edge_language_version`
`"1"`, `role_voice_version` `"1"`, `loudness_version` `"1"`, `EARCON_VERSION`
`"1"`). The three new tones are generated into `user_files/earcons` the first time
a plan asks for one. A track gets a new name only if its plan changes, or if it
now has an "or" it did not have (an alternative after a French or English
example line).

### Tests

`tests/test_speech_plan_v2.py` (17 checks): every field, every rejection, version
1 unaffected. `tests/test_role_voices.py` (25): defaults, migration, resolution,
fallback, cache splits, one role regenerating, both pickers' choices.
`tests/test_tempo_pauses.py` (16): the note's table, the formula and clamp, the
trimmed duration, what refills. `tests/test_earcons.py` (10): the tone
specification, generated once, replacement, position, keys.
`tests/test_speech_plan_v2_e2e.py` (7; the fixture has a fourth section: a tag before its owner, an example with a translation and two alternatives, a tag after its owner, and the timeline is walked against the ruling restated in the test): the fixture in
`tests/fixtures/speech_plan_v2.json` through parsing, resolution, the fake
worker's protocol, normalisation, earcons, stitching and MP3 export; each voice
is given its own pitch, and the decoded track is checked for who spoke, the
earcons at their offsets and silence in the pauses. The version 1 fixture's keys
and track names are pinned. `tests/test_edge_language.py` (11 checks): when a
carrier applies and when it does not, the offsets, the cut, the fallbacks, the
retry, the routing in `EdgeProvider.synthesize`, normalisation to a real MP3, and
the identity change; no test reaches the service. `tests/test_speech_text.py`
gained 3 checks (brackets that touch a word, the clitics, the version) and
`tests/test_attached_and_alternatives.py` (15) is new: the `tightPauseMs` field,
the attached side from a tag's place, the stitched pauses on both sides of an
owner, who takes an "or" and who does not, the block's layout and what it
replaces, one cached clip per language and voice, and what moves the track
name. Total after review batch 1: 305 checks in 24 modules (284 in 23 before).

Review batch 2 added 20: `tests/test_speech_plan_v2.py` +3 (the new kinds before,
not after; the old names still parse in both places), `tests/test_earcons.py` +4
(the six tones told apart by direction, pitch and length; a replacement file
through the map and the shipped defaults; a new earcon plays before the speech
and never after; a new earcon moves the track and never the segments, and a
legacy track keeps its name), `tests/test_attached_and_alternatives.py` +3 (the
"or" after an example source and target in the alternative's language; the
negatives; the block replacing the pauses of the gap) and the new
`tests/test_audio_audit.py` +10 (the audited sides; a clean run; one silent side;
the other silent reasons; empty plans; refused plans; a failed synthesis; a failed
copy; an unattended run; the log line). The fixture
`tests/fixtures/speech_plan_v2.json` moved its four section earcons to
`sectionNumber`, gained a lettered sub-section (`ds-26`) and an idiom heading
(`ds-27`), and keeps the old names in `deepRecallBack`. Total: 325 checks in 25
modules.

### Review batch 3: Anki freezes with the add-on enabled (CA-81, 2026-11-10)

**Ruling CA-81 (Alec, 2026-11-09 and 2026-11-10, Denver), verbatim.** The
managing chat's reading follows the quote and is its own, not Alec's.

```
(1) NO WIPE ON AN EMPTY PLAN (the managing chat's card to Alec of 2026-11-09 asked:
AnkiTTS clears a side's audio when the plan for that side is empty; should AnkiTTS also
refuse to wipe existing audio on an empty plan? Alec's answer, verbatim): "Yes, as a small
AnkiTTS follow-up, bundled with the next batch (Recommended)".
(2) NEVER SILENT (Alec's words as section 18's CA-71 (3) holds them): "This should never
ever happen for any reason on any card in any deck."
```

The managing chat's reading (its own): (1) decides that a side whose new plan has
no spoken segment keeps whatever audio it already has; and a report that freezes
Anki is worse than the silence it reports, so the audit must tell Alec and must
never be able to stop Anki or the run.

#### The freeze, diagnosed (item A, written before any edit to the code)

**What the log holds.** `addon/user_files/logs/ankitts.log`, 501,948 bytes, last
written 2026-11-10 23:10:48, 322 lines dated 2026-11-10; read only, and only the
type of each line, its level, thread and time, and counts were taken from it. Every
line from a worker thread is INFO; the only WARNING of the day is the audit's, from
the main thread; there is no ERROR, no traceback, no timeout and no
"X failed for" line.

| Time (Denver) | Thread | Event |
|---|---|---|
| 10:04:48, 22:50:11 | Main | the add-on loaded (twice) |
| 22:52:41 to 22:52:57 | `ankitts-rce_0..2` | the first run (three or more notes: its audit counted three empty fronts): 16 syntheses completed, median 1.09 s, longest 1.87 s |
| 22:53:14 | Main | the audit's WARNING line (17 s after the last synthesis: stitching, copying, publishing, auditing, all on this thread), then the warning box |
| 22:53:14 to 23:00:24 | none | nothing logged for 7 min 10 s: the box was waiting for OK, inside the run, with the add-on's `busy` flag set |
| 23:00:24 to 23:05:28 | `ankitts-rce_0..2` | a second run begins within seconds of the box closing: 81 syntheses, median 1.28 s, longest 2.83 s, longest silence between worker lines 16.7 s; **still completing syntheses at the same pace in its last 30 s** (2 completions); the last line is 23:05:28 |
| 23:05:47 | Main | the add-on loaded (Alec restarted Anki) |
| 23:05:51 to 23:07:53 | `ankitts-rce_0..1` | a run again **4 s after the load**: 0 fresh syntheses (the cache answered), longest silence 58.3 s; the last line is 23:07:53 |
| 23:09:49 | Main | the add-on loaded (sync off) |
| 23:09:51 to 23:10:48 | `ankitts-rce_0..1` | a run again, **2 s after the load**: 0 fresh syntheses, longest silence 18.6 s; the last line is 23:10:48 |

**The mechanism.** Everything above runs on Anki's main thread, in the slot of a
one-second `QTimer`:

- `addon/__init__.py` starts `rce_audio_timer` (1000 ms) whose timeout is
  `RceAudioAutomationController.poll_immediate_requests`; `resume_rce_audio_polling()`
  is called at import and on `collection_did_load`, and `RceAudioPollingLifecycle.resume`
  runs `recover_after_restart` and starts the timer.
- `poll_immediate_requests` finds the notes tagged `rce-audio::pending` and
  `rce-audio::immediate` (`IMMEDIATE_AUDIO_QUERY`) and calls `_process`
  (`rce_audio_automation.py`), which calls `process_note_ids` (`browser.py`) and
  waits for it. That function parses every plan, calls
  `batch_processor.process_notes` (a loop over the notes; per note
  `structured_audio._synthesize_missing_segments` starts a `ThreadPoolExecutor`
  and the calling thread waits on `future.result()`, then stitches with ffmpeg),
  copies the files, and only then writes the audio fields and tags the notes
  ready. The synthesis happens on worker threads, but the thread that called the
  slot is blocked for the whole run: no event is pumped, and Windows reports Not
  Responding after about five seconds.
- Nothing is published until the last note is done. Ending Anki mid-run therefore
  loses the run (the cache keeps the synthesised clips, not the tracks or the fields),
  and the note keeps the `processing` tag it was given at the start.
- At the next start `recover_after_restart` turns every `processing` note into
  `pending` + `failed`, and **keeps its `immediate` tag**
  (`mark_interrupted_processing`), so the poll picks it up again about a second after
  the collection loads: the log shows the run beginning 4 s and 2 s after the add-on
  loaded. Every start while the pending audio stands begins the same minutes-long
  run on the main thread, before the main window is usable.

**What the box did.** The warning box was not what froze Anki. It is raised on the
main thread (the audit's line is logged by `MainThread`), inside the slot, and it
waited seven minutes for a click because that is what a box does. The click let the
run end; the next poll, one second later, found the notes that were still queued and
began the long run, and from the click on the window was Not Responding with a run that
was healthy and not finished (81 syntheses so far; how many the run needed is not in the
log, because a run logs nothing about how many notes it holds, which CA-89 now does).

**The managing chat's two guesses, tested.** (1) *The warning dialog is raised from
work that is not on Anki's main thread:* **wrong**. The log's thread for the audit is
`MainThread`, `_process` is called by the timer's slot, and the reproduction below
records the thread of every dialog and finds the main one, today. (2) *The automation
that resumes pending audio when the profile opens blocks the main thread or loops on
the same notes:* **right on both counts**, and it is not only the start-up path: the
blocking is in every unattended and every manual run, and the "loop" is the recovery
that keeps `immediate`, together with a run that publishes nothing until it is over.

**What is proven and what is not.** Proven, by the code and the reproduction: a run
of N notes holds the main thread for the whole of its duration (the first run, of three
or more notes, took 34 s from its first synthesis to the audit's line, half of it
synthesis and half stitching, copying and publishing; the second had run 303 s and was not
finished), and is lost if Anki is ended before it finishes. Consistent with the log
and not provable from it: that this is *all* Alec saw. The second run was progressing
at its normal pace when it was ended, and the two restart runs were inside their cache
answers and stitching, for which the log has no lines. A stall inside ffmpeg
(`providers.audio._run_ffmpeg` and pydub's own calls have no timeout) would look the same
from outside and cannot be excluded; this batch does not bound it (a timeout belongs in
`src/providers/audio.py`, which the batch's scope leaves alone, CA-87), and with the run off the
main thread it can no longer freeze Anki: it can only hold one background run. His
observation of about 2 per cent processor and no disk or network is what waiting for
worker threads and the speech service looks like.

**The reproduction** (`tests/test_unattended_run.py`,
`check_a_slow_batch_does_not_hold_the_timer_slot`): fake window with a `taskman` that
runs tasks on a real thread, a collection that answers tag searches as Anki does, the
fake provider and the stand-in stitcher; three queued notes, two with an empty front
plan; the batch held on an event. RED on `534e983` for this reason: the slot does not
return until the batch is over, and the batch runs on the calling thread. The same
check asserts that every dialog is raised on the main thread (true today).

#### Rulings for review batch 3 (2026-11-10 to 2026-11-11)

CA-81 is Alec's (above). The session's own calls, option taken, then option not
taken. Taken unattended, on the session's own read of the code and the log. The
Anki 26.5 install ships its modules compiled only; the signatures used here were
read from the bytecode of `aqt/taskman.pyc` and `aqt/utils.pyc` (program files, not
Alec's data): `TaskManager.run_in_background(task, on_done, args, uses_collection)`,
`TaskManager.run_on_main(closure)`, `tooltip(msg, period, parent, x_offset,
y_offset)`. Nothing here has been run in a real Anki.

- **CA-82 A run has three parts, and only the middle one leaves the main thread.**
  *Prepare* (main): settings, the notes, their jobs, the audit's first counts.
  *Generate* (a background task through `mw.taskman.run_in_background(...,
  uses_collection=False)`): synthesis, stitching, copying into Anki's media; it
  touches no collection and no Qt object and never raises (a failure comes back as a
  value). *Publish* (main, from the task's `on_done`): the notes are read again, so a
  note edited meanwhile is written back as he left it plus the audio; the audio
  fields are written, the notes tagged ready, each side audited, the result shown.
  The browser menu action and the automation (the one-second poll, **Tools > Generate
  Pending RCE Audio**) share `browser.start_note_run`; `browser.process_note_ids` keeps
  the same three parts on the calling thread for the editor's button and the checks.
  *Not taken:* running the whole of `process_note_ids` in the background (it reads
  and writes the collection, which Anki's own code does off the main thread only
  through its operation classes, and which could not be tried here); Anki's
  `QueryOp`/`with_progress` (a progress window for an unattended run, and an API not
  tried here); a progress dialog.
- **CA-83 The notice is Anki's tooltip: 20 seconds, once per run, counts only.** An
  unattended run (anything Alec did not start by hand) that finds a dirty audit shows
  no dialog; it writes the audit's line to the log (counts and ids, as before), puts the
  three counts in the run's outcome (`audit`, `audit_notice`), and shows
  `AudioAudit.notice()` through `aqt.utils.tooltip` (`ui.show_notice`, 20 000 ms,
  `ui.NOTICE_PERIOD_MS`): "AnkiTTS audio audit: 3 sides without audio that should
  have some (0 silent, 3 empty, 0 rejected). The note ids are in the AnkiTTS log." A
  run Alec starts by hand shows the one result box it already had, with the audit's
  lines; no second box and no notice. A dirty audit fails, retries and re-queues
  nothing; an empty side is reported once per run and the note is ready like any other.
  Every function that shows something goes through `anki_integration/ui.py`: off the
  main thread a call is queued with `mw.taskman.run_on_main`, and with no task manager
  it is dropped and logged, never made. *Not taken:* a custom non-modal window (a Qt
  object the checks cannot exercise); a notice that stays until clicked (a click is
  what is being removed; the period is one constant if 20 s proves too short); one
  notice per note.
- **CA-84 The resume of pending audio at profile open is scheduled, not run, in the
  hook.** `collection_did_load`, `collection_did_temporarily_close` and the import-time
  call now call `RceAudioPollingLifecycle.resume_later`, which only schedules
  `resume_safely` three seconds later (`RESUME_DELAY_MS`, `QTimer.singleShot`); a
  failure in the resume, or in the scheduler, is logged by exception type and never
  raised into Anki. The automation **still runs at start-up**: after those three
  seconds the recovery turns interrupted `processing` notes back into pending (keeping
  `immediate`), the poll finds them and starts the run, which is now in the background.
  *Not taken:* removing the start-up resume (it is how the fifteen rows get their
  audio without a click); a longer delay; running the recovery in the background (it is
  one search and a few tag writes).
- **CA-85 One run at a time; a closing collection stops a run between notes; a
  changed collection is never written.** `browser.run_in_flight()` is shared by the
  poll, the manual command and the browser action (a second request is refused with a
  message, or ignored by the poll). Suspending the polling (profile close, temporary
  close) sets `cancel_requested`; `process_notes(should_cancel=...)` stops with
  `RunCancelled` before the next note, so Anki is not held open for the rest of a
  batch. If the collection closed, or another one is open, when the run comes back, it
  is not published and no tag is changed; the notes keep the tags they had and the next
  start recovers them. A resume that arrives in the middle of a run (a temporary close
  of the collection; it could not before, while the run held the main thread) leaves the
  poll timer running and schedules itself again, instead of stopping the timer for good.
  *Not taken:* waiting for the run at close; stopping inside a note (a thread cannot be
  stopped safely).
- **CA-86 Pending is the tag, an empty side does not keep a note pending, and nothing
  had to change there.** The automation's test of pending audio is a tag search:
  `IMMEDIATE_AUDIO_QUERY` (`tag:rce-audio::pending tag:rce-audio::immediate`, the poll)
  and `PENDING_AUDIO_QUERY` (`tag:rce-audio::pending`, the Tools command). A note leaves
  both when `publish_run` tags it `rce-audio::ready`, which it does for every note it
  publishes, whether or not a side had a plan with nothing to speak. The new check runs
  the real pipeline over three notes (two with an empty front) with three consecutive
  polls: work 3, 0, 0, every note `ready`, the back of an empty-front note generated, the
  manual command finding nothing. What did not terminate on 2026-11-10 was not an empty
  side: it was a run killed before it published, plus the recovery that keeps `immediate`
  (CA-82 and CA-84 are the cure). *Not taken:* dropping `immediate` when recovering an
  interrupted note (the unattended run at start-up is how the audio gets made); a retry
  counter (a note that crashed Anki on every attempt would loop at start; none has been
  seen, and it is recorded as a residual risk).
- **CA-87 No ffmpeg timeout in this batch.** `providers.audio._run_ffmpeg` calls
  `subprocess.run` with no timeout while holding `_encode_lock`, and pydub's own calls
  have none; a timeout belongs in `src/providers/audio.py`, which item E leaves alone. With
  the run off the main thread a stuck ffmpeg holds one background run (and the
  automation's `busy`) until Anki is restarted, and no longer the window. The next batch
  should add one. *Not taken:* a main-thread watchdog that abandons a run after N minutes
  (the thread cannot be killed; it would go on writing files).
- **CA-88 The empty-plan rule is in `note_mapper.write_audio_fields`, for structured RCE
  jobs only.** A side whose result has no filename keeps the field as it is; a side with
  a filename replaces it; a generic field with an empty track is still cleared (it has no
  plan: its text is gone); the destination field must still exist, whether or not the
  side is empty. `iter_processed_audio_outputs` is unchanged (it still yields the
  `None` filename; its docstring said "so its destination field is cleared" and now
  says where the rule lives). The audit still counts the side as empty. Checks that
  pinned the clearing: `check_browser_mixed_batch_publication` expected `""` for a back
  track of `None` over `[sound:old-back.mp3]` and now expects the old tag; no other
  check started from a non-empty field. New: `check_an_empty_plan_leaves_the_audio_field_alone`
  (test_rce_contract) and `check_an_empty_front_keeps_its_audio_and_the_back_is_written`
  (test_audio_audit). *Not taken:* skipping inside the iterator (it would change what the
  media copy and the checks see, for no gain); clearing the field when the plan changes
  from spoken to empty (CA-81 (1) says the opposite).
- **CA-89 The run says where it is.** `Audio run requested for N note(s) (unattended |
  by hand)`, `Audio run started: N note(s).`, one `Audio run: note i of N done.` per
  note, and `Audio run finished: success|failure in S s; audit a silent, b empty, c
  rejected.`: counts and seconds, never text (every line carries its own timestamp). If a
  run ever stalls, the last such line is how far it got. *Not taken:* a heartbeat thread.

**What refills.** Nothing: no version moved (`speech_text_version` `"4"`,
`stitch_version` `"2"`, `edge_language_version` `"1"`, `role_voice_version` `"1"`,
`loudness_version` `"1"`, `EARCON_VERSION` `"1"`), no file under `src/providers` changed,
and the tempo table, the voices, the carrier route, the earcons and the connective rule are
as they were. A track that was already published keeps its audio; a track for an empty plan
is no longer cleared.

**Tests.** The new `tests/test_unattended_run.py` (10 checks: the reproduction; one notice
and no box; one box by hand; pending terminates, 3 jobs then 0 then 0; the start-up resume
deferred and unable to raise; a resume during a run; a closing collection; one run at a
time and a changed collection; the cancel hook; nothing reaches a dialog from another
thread), +1 in
`test_rce_contract.py`, +1 in `test_audio_audit.py`. Changed on purpose: the unattended
audit check (`check_an_unattended_run_tells_alec_without_a_box_and_a_clean_one_stays_quiet`:
a notice and no box, where it asserted a warning box), `check_browser_mixed_batch_publication`
(CA-88), and the checks that replaced `automation.process_note_ids` now replace
`automation.start_note_run` through `synchronous_run`. Total: 337 checks in 26 modules
(325 in 25 before this batch).

### Review batch 4: "or" / "ou" after a main translation and an idiom heading; symbols reach the voice; a stitching timeout (CA-90, 2026-11-12)

**Ruling CA-90 (Alec, 2026-11-12, Denver), verbatim.** Where Alec's words held a
card's text, the text is replaced by a pointer in square brackets naming the
construct; the bracketed pointers are the ruling's recorded text. The managing
chat's reading follows the quote and is its own, not Alec's.

```
CA-90. (1) (Alec, 2026-11-12, 08:11): "[an English translation holding the inline connective]" is
still being pronounced as "[the same with the connective as two English letters]" and "[an English
example translation holding it]" likewise; it should be "[first alternative], or, [second]" in
English, and any French examples that might have the English connective between two French
alternatives should be pronounced "[first], ou, [second]". (2) (08:24): "I mean, shouldn't ALL
slashes be read as "or" or "ou" according to what language they appear in? I can't really think of
a scenario where I wouldn't want a slash to be pronounced that way during my audio-only study. Can
you?" and his answer to the managing chat's card on how a slash inside a spoken phrase is read
aloud, verbatim: "Always or / ou, except a counted exception list (Recommended)". (3) (08:43): "%
and € are not being pronounced in English or French. This cannot be happening with these or any
other common symbols that are likely to appear throughout the dictionary in both languages." (4)
THE ORDER (his answer to the managing chat's card, verbatim): "Audio stage + AnkiTTS batch 4, then
display stage, then Le Robert & CLÉ (Recommended)".
```

The managing chat's reading (its own): (1) and (2) are RCE's to split (it turns
each mark into a segment of role `alternative` and drops the mark from the text);
AnkiTTS's share is to say the word wherever RCE marks an alternative that
continues a main translation or an idiom heading, which today it never does; (3)
is RCE's first (its plans drop the signs before AnkiTTS sees them), and AnkiTTS's
share is to prove, and where needed make sure, that a sign in a segment's text
reaches the voice.

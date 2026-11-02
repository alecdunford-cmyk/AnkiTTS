# AnkiTTS synthesis providers: design

Status: accepted design, built in stages B–H on 2026-11-01. This document is
the durable home of the card-and-audio rulings CA-3 onward. CA-1 and CA-2 are
in `D:\RCE-Project-Archive\Session-Handoffs\AnkiTTS-Card-Audio-Bakeoff-Plan-20261029.md`.
The audio-defect fixes of the same day (ruling CA-21 and CA-22 to CA-28: the
trim margin and speech-text preparation) are in section 15.

## 1. Why

Up to v1.0.0 and the structured-RCE commits, `generator.create_audio` called
`edge_tts` directly. No other engine could plug in, and the generic path's
cache key did not record which engine made a file. Ruling CA-3 makes Kyutai
Pocket TTS the primary engine, Fish Audio the second provider and Edge the
last resort. This design is the seam that makes that possible.

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

- Settings key `provider_chain`, default `["pocket", "fish", "edge"]`.
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
  non-default value is ignored. **Correction (2026-11-01):** an earlier
  version of this document said loudness stays even because the stitcher
  normalises every segment. It does not: the stitcher trims and joins only.
  Pocket's English clone measured about 12 dB quieter than its French clone
  (mean -36.7 against -24.9 dBFS, `docs/audio-tail-diagnosis-20261101.md`), so
  a mixed card has a level step. Per-segment loudness normalisation is parked
  (section 16).

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
`identity()` adds `speech_text_version` to it (section 15).
Health is configuration-only (always ok). Edge failures surface during
synthesis.

## 9. Settings schema and migration

The live add-on reads **Anki's add-on config**, not `settings.json`
(CA-4): `mw.addonManager.getConfig(...)`, which is `addon/config.json`
(defaults) overlaid by `addon/meta.json["config"]` (what the dialog saved).
`settings.json` at the repo root is a developer file read only by
`SettingsManager` (dev scripts). The inventory's guess that the add-on reads
`addon/settings.json` was wrong. New keys:

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

Regression tests: `tests/test_stitcher.py`, including a fake-worker clip whose
last 60 ms is quiet speech (about -50 dBFS) that the stitched track must keep
(and that the old -45 dBFS rule would have removed).

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
| 4 | `→` becomes a comma (a short pause) and `≈` is dropped, in any language. Bracketed `[...]` and `{...}` labels are **spoken in the flow of the sentence**, with no pause (CA-29, CA-34). Parentheses are kept. | `chat → cat` → `chat, cat`; `faire [quelque chose] à [quelqu'un]` → `faire quelque chose à quelqu'un` |
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

`speech_text.SPEECH_TEXT_VERSION` (currently `"3"`; rules 5 to 10 came with version 2, the no-pause labels and hyphenated units with version 3) is a field of the identity
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

- **CA-22 Trim at -60 dBFS with a 50 ms margin.** *Not taken:* the managing
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

## 16. Parked

- **Qwen3-TTS** (0.6B / 1.7B). Trigger: "if Pocket's French ever disappoints
  on real cards" (CA-3 part 2). It would be a fourth provider behind the same
  interface, in its own venv.
- **`Playback Plan`** is still required on RCE notes and still not consumed
  (inventory). It is unchanged here.
- **RCE marks alternatives in the speech plan** (trigger: sem-2b closed). The
  clean fix for defects 2 and 3: RCE would say which words are alternatives
  and the slash and bare-`or` heuristics in `speech_text.py` could go.
- **Per-segment loudness normalisation.** Trigger: Alec hears the level step
  between English and French segments in one track (about 12 dB between the two
  Pocket clones). Not built; section 5 no longer claims it exists.
- **A different voice for notes, headings and labels, and spoken section
  numbers** (Alec, 2026-11-01). Not built, because both halves need RCE:
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

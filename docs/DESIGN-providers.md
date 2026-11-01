# AnkiTTS synthesis providers: design

Status: accepted design, built in stages B–H on 2026-11-01. This document is
the durable home of the card-and-audio rulings CA-3 onward. CA-1 and CA-2 are
in `D:\RCE-Project-Archive\Session-Handoffs\AnkiTTS-Card-Audio-Bakeoff-Plan-20261029.md`.

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
  (Pocket) or `reference_id` (Fish). It feeds the cache key and the track
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
  non-default value is ignored. Loudness stays even because every segment is
  normalised by the existing stitcher path.

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
`<edge_tts version>`. It is unchanged, so the structured key shape is too.
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

Later rulings made during the build are appended below.

## 15. Parked

- **Qwen3-TTS** (0.6B / 1.7B). Trigger: "if Pocket's French ever disappoints
  on real cards" (CA-3 part 2). It would be a fourth provider behind the same
  interface, in its own venv.
- **`Playback Plan`** is still required on RCE notes and still not consumed
  (inventory). It is unchanged here.

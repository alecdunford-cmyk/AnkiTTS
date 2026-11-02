# Audio tail diagnosis: cut-off endings (2026-11-01)

Ruling CA-21 point 1: English (and possibly French) Pocket audio is cut off
abruptly on the last syllable. This note records the measurements that decide
which of three suspects is real. No code was changed in this stage.

## Method

- HEAD `f59fd90`, real Pocket worker (engine venv, Alec's cloned voices),
  chain `["pocket"]`, through `generator.create_audio` exactly as the add-on
  calls it. Rate is the profile default (`+0%`), so Pocket's tempo is 1 and no
  `atempo` filter runs.
- 12 invented phrases: 3 English and 3 French bases (two short glosses and a
  sentence in each language), each synthesised **without** and **with** a
  final full stop. Endings chosen to include word-final plosives (`k`, `t`).
- Every intermediate kept: the worker WAV (copied before the add-on deletes
  it), the MP3 cache file, and a single-segment track made by
  `stitcher.stitch_structured_audio` (no pauses, so the track ends where the
  trim ends).
- Measured with pydub (10 ms RMS windows, dBFS): the last 300 ms envelope of
  each file, where the sound ends at -45 dBFS (the stitcher's threshold) and
  at -60 dBFS, how much the trim removes, and how much of what it removes is
  still audible (windows above -60 dBFS).
- I cannot listen, so "cut off" is inspected as energy: a clip that ends while
  its level is still near the speech average ends abruptly; a clip that
  decays to near silence does not.
- The harness and every file are in
  `C:\Users\alecd\pf-scratch\tts-bakeoff\defects\diagnosis\` (invented
  phrases only; `results.json`, `more.json`, `diag_*.py`).

## Measurements

"Trim removes" is what `trim_trailing_silence` takes off the end; "audible"
counts the 10 ms windows in that removed part that are above -60 dBFS.
"Stitched last 10 ms" is the level of the final 10 ms of the published track.

| case | full stop | WAV ms | trim removes ms | sound ends @-45 / @-60 (ms) | audible part removed (ms) | stitched last 10 ms (dBFS) | MP3 minus WAV length | WAV mean level (dBFS) |
|---|---|---|---|---|---|---|---|---|
| en-1-nostop | no | 1840 | 480 | 1360 / 1470 | 110 | -43.5 | 0 ms | -36.0 |
| en-1-stop | yes | 1760 | 480 | 1280 / 1390 | 110 | -40.8 | 0 ms | -38.0 |
| en-2-nostop | no | 2400 | 110 | 2290 / 2320 | 30 | -35.5 | 0 ms | -36.8 |
| en-2-stop | yes | 2480 | 110 | 2370 / 2430 | 60 | -44.1 | 0 ms | -36.1 |
| en-3-nostop | no | 2560 | 350 | 2210 / 2440 | 230 | -43.0 | 0 ms | -36.6 |
| en-3-stop | yes | 2640 | 270 | 2370 / 2480 | 110 | -43.5 | 0 ms | -36.8 |
| fr-1-nostop | no | 1760 | 530 | 1230 / 1260 | 30 | -43.9 | 0 ms | -25.6 |
| fr-1-stop | yes | 1680 | 510 | 1170 / 1210 | 40 | -44.4 | 0 ms | -26.6 |
| fr-2-nostop | no | 2160 | 330 | 1830 / 1850 | 20 | -44.9 | 0 ms | -23.0 |
| fr-2-stop | yes | 2160 | 380 | 1780 / 1810 | 30 | -40.5 | 0 ms | -23.6 |
| fr-3-nostop | no | 1680 | 440 | 1240 / 1250 | 10 | -42.6 | 0 ms | -25.3 |
| fr-3-stop | yes | 1680 | 450 | 1230 / 1240 | 10 | -44.5 | 0 ms | -25.3 |

Summary by language:

| | mean speech level | audible part removed (mean / max) | stitched track ends at |
|---|---|---|---|
| English | -36.7 dBFS | 108 ms / 230 ms | -35.5 to -44.1 dBFS (the speech average is -36.7: the clip ends mid-speech) |
| French | -24.9 dBFS | 23 ms / 40 ms | -40.5 to -44.9 dBFS (about 18 dB below the average) |

The detail behind the English rows: the WAV's last 300 ms is digital silence
(-80 dBFS), but ahead of that sits a decay that runs well below -45 dBFS.
`en-3-nostop` carries about 200 ms at -48 to -63 dBFS (a soft final
syllable) after the trim point. `en-2-nostop` ends in a plosive release: a
burst at -35 dBFS, then a decay of -48, -45, -49, -53, -56, -60, -62 dBFS
over about 80 ms. The stitched track ends on the burst itself (-35.5 dBFS),
a hard stop in the middle of the `k`.

## The three suspects

**(a) The trim biting into the final consonant: REAL, for English.**
`SILENCE_THRESHOLD_DB = -45` is an absolute level. Pocket's English clone
speaks quietly: mean level -36.7 dBFS, so the threshold sits only 9 dB below
the average and inside the word-final decay. The trim removes on average
108 ms of audible content from each English clip (up to 230 ms), and every
English track ends between -35 and -44 dBFS, at or near speech level. French
averages -24.9 dBFS, so the same threshold is 20 dB below the average and the
loss is 10 to 40 ms: smaller, and probably borderline audible, which matches
Alec's "possibly French". The cut is the same mechanism in both languages and
scales with how quiet the voice is.

**(b) The engine stopping early on text with no terminal punctuation: RULED
OUT.** Pocket already completes the text itself: its `prepare_text_prompt`
(default `append_terminal_punctuation=True`, set by neither the English nor
the French config) turns `a paper lantern` into `A paper lantern.` and
`une petite barque` into `Une petite barque.` before synthesis. In the data,
clips without a final stop are no shorter and no more abruptly ended than
clips with one (mean WAV length 2067 ms for both sets; audible part removed
72 ms without a stop against 60 ms with one; every pair shows the same tail
shape). A terminal-punctuation rule in AnkiTTS would change nothing.

**(c) The atempo / encode step: RULED OUT.** Tempo is 1, so no `atempo`
filter runs. The MP3 has exactly the WAV's length in all 12 cases. The point
where the sound ends at -45 dBFS is the same or at most 20 ms earlier in the
MP3 in 11 cases; in `en-3-stop` it is 90 ms earlier (2280 against 2370 ms),
because that tail hovers around -45 dBFS and the threshold crossing is
unstable, so the MP3's codec smoothing tips it earlier. That is the same
threshold problem, not an encode loss. The stitched track's length equals
the MP3's trim point in all 12 cases: the loss happens in the trim.

## Premise correction

The managing chat expected Pocket's WAV to end with almost no silence. It
does not: every WAV ends with 110 to 530 ms of near-digital silence
(-80 dBFS). The trim does remove that silence, as intended; the damage is the
sub-threshold decay that sits in front of it.

## What the margin has to cover, from the data

Candidate rules, replayed against the 12 WAVs. "Lost" is audible content
(above -60 dBFS) the rule would cut; "extra silence" is dead air it would keep
after the sound has ended at -60 dBFS (this shifts the authoritative pauses
of the structured path and the text-derived pauses of the generic path).

| rule | lost, English (mean / max ms) | lost, French | extra silence, English (mean / max ms) | extra silence, French |
|---|---|---|---|---|
| now: -45 dBFS, +0 ms | 108 / 230 | 23 / 40 | 0 / 0 | 0 / 0 |
| -45 dBFS, +100 ms | 27 / 130 | 0 / 0 | 18 / 70 | 77 / 90 |
| -45 dBFS, +150 ms | 13 / 80 | 0 / 0 | 42 / 80 | 127 / 140 |
| -45 dBFS, +250 ms | 0 / 0 | 0 / 0 | 95 / 140 | 227 / 240 |
| -60 dBFS, +30 ms | 0 / 0 | 0 / 0 | 30 / 30 | 30 / 30 |
| -60 dBFS, +50 ms | 0 / 0 | 0 / 0 | 50 / 50 | 50 / 50 |

A margin alone needs +250 ms to be safe and then adds 100 to 240 ms of dead
air to every clip. Moving the threshold to the real end of the sound
(-60 dBFS) and keeping a 50 ms margin loses nothing, adds a constant 50 ms,
and stays well above both noise floors that matter: Pocket's tail is
-80 to -84 dBFS, and an invented Edge phrase measured here ends in true digital
silence (-120 dBFS, last 300 ms, both languages).

## Conclusion

Suspect (a) is the cause: a fixed -45 dBFS threshold that is too close to
the level of quiet English speech. Fix it in the stitcher (stage B) by trimming
at -60 dBFS and keeping a 50 ms safety margin. No terminal punctuation is
added to the engine's text (the engine already does it), and no change is
made to the encode step.

## Amendment (2026-11-01, CA-37)

After per-segment loudness normalisation (docs/DESIGN-providers.md, section 17)
the trim threshold is -50 dBFS, not -60: normalised audio is up to 22 dB louder
and its tail rose from -80 dBFS to about -60. The measurements above are of the
unnormalised clips and still describe why -45 dBFS was wrong for them.

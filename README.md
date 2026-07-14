\# AnkiTTS



\*\*Generate high-quality multilingual speech automatically for your Anki cards using Microsoft Edge Neural voices.\*\*



AnkiTTS is an Anki add-on designed to make audio generation effortless. It supports automatic language detection, configurable speech profiles, browser batch generation, deterministic caching, and seamless integration into your Anki workflow.



\---



\## Features



\- 🎙 Automatic text-to-speech generation for Anki cards

\- 🌍 Automatic language detection for mixed-language text

\- 🇫🇷 French, 🇺🇸 English, and 🇯🇵 Japanese support out of the box

\- 🎚 Independent Speech Profiles for each language

&#x20; - Voice

&#x20; - Rate

&#x20; - Pitch

&#x20; - Volume

\- 📚 Configurable field mappings

\- ⚡ Batch generation from the Anki Browser

\- 💾 Intelligent audio cache

\- 🗑 Built-in cache management

\- 🔤 Unicode-safe filenames

\- 🧪 Regression test suite

\- ✅ Included validation deck and QA guide



\---



\# Why AnkiTTS?



Creating audio manually for flashcards is slow and repetitive.



AnkiTTS automates the entire process while still giving you complete control over how every field is spoken.



Whether your cards contain:



\- French vocabulary

\- Japanese vocabulary

\- English definitions

\- Mixed-language example sentences

\- Pronunciation notes



AnkiTTS generates natural speech automatically.



\---



\# Speech Profiles



Each language has its own independent speech profile.



Each profile stores:



\- Voice

\- Speaking rate

\- Pitch

\- Volume



Mappings simply choose which profile they should use.



This allows, for example:



| Language | Voice |

|-----------|-------|

| French | Denise |

| English | Jenny |

| Japanese | Nanami |



Each with completely independent speech settings.



\---



\# Field Mappings



Field mappings connect Anki text fields to audio fields.



Example:



| Mapping | Text Field | Audio Field | Speech Profile |

|---------|------------|-------------|----------------|

| Expression | Front | Front Audio | Front Language |

| Definition | Back | Back Audio | Automatic |



Mappings are fully configurable through the Settings dialog.



\---



\# Browser Batch Generation



Generate audio for hundreds of notes in one operation.



The batch processor reports:



\- Notes processed

\- Generated segments

\- Cache hits

\- Skipped segments



\---



\# Intelligent Audio Cache



Generated speech is cached using:



\- text

\- detected language

\- voice

\- speaking rate

\- pitch

\- volume



Changing any speech setting automatically regenerates only the audio that actually needs updating.



\---



\# Unicode Support



AnkiTTS preserves readable filenames across virtually every writing system, including:



\- Latin alphabets

\- French accents

\- Japanese

\- Chinese

\- Korean

\- Cyrillic

\- Arabic

\- Devanagari



while remaining fully compatible with Windows filenames.



\---



\# Validation



This repository includes:



\- Automated regression tests

\- Validation deck

\- QA guide



used to verify every release before publication.



\---



\# Requirements



\- Anki 26.x

\- Python 3.13+

\- FFmpeg

\- Microsoft Edge Neural TTS



\---



\# Roadmap



Future releases are expected to include:



\- Background batch generation

\- Additional TTS providers

\- Per-note-type configurations

\- Import/export of settings

\- Smarter cache cleanup

\- Additional language support



\---



\# Contributing



Bug reports, feature requests, and pull requests are welcome.



If you discover a reproducible issue, please include:



\- Anki version

\- Operating system

\- Steps to reproduce

\- Relevant console output or traceback



\---



\# License



MIT License



\---



\# Philosophy



AnkiTTS was built around one simple idea:



> Creating natural audio for language-learning flashcards should be effortless.



Once configured, generating high-quality pronunciation should become a one-click operation, allowing you to spend your time learning languages instead of managing media files.


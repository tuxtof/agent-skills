# sous-titres-fr

Creates French subtitles (`.fr.srt`) for movies and TV shows stored locally. Reuses subtitles already present in the video first, only runs Whisper as a last resort, then translates following French subtitling conventions.

The skill's instructions are written in French, since it produces French subtitles. It triggers on requests in any language ("french subs for this show" works as well as "fais-moi des sous-titres fr").

## Installation

```bash
npx skills add tuxtof/agent-skills --skill sous-titres-fr
```

See the [main README](../../README.md#installation) for manual installation.

## What it does

Ask something like "make French subtitles for this movie" or "subtitle all of season 1 in this folder". The agent:

1. **Inspects the video** (`probe.py`) and picks the best source, in this order:
   - a `.fr.srt` already sits next to the video → nothing to do;
   - an embedded French track → extract it as is;
   - an embedded English track or an external `.srt` → extract, then translate;
   - otherwise → transcribe with Whisper, then translate.

   *Forced* tracks (which only cover a few lines) are skipped, unless they are actually complete and mislabeled. Image-based tracks (PGS/VobSub from Blu-rays and DVDs) are reported, since they can't be read without OCR.
2. **Cleans** the subtitles: tags, hearing-impaired annotations (`[MUSIC]`, `(sighs)`, `JOHN:`), song lyrics.
3. **Translates** in chunks of 100 subtitles, never exposing or changing timecodes, following French subtitling rules: 42 characters per line, 2 lines max, reading speed, typography (spaces before `? ! :`, « » quotes), dialogue dashes, consistent *tu*/*vous*.
4. **Checks** the result: same number of subtitles and same timecodes as the source, overlong lines, reading speed compared with the original, untranslated lines.
5. **Delivers** `Video.Name.fr.srt` next to the video, so VLC, Plex, Jellyfin or Infuse load it automatically.

For a TV show, a **shared glossary** (characters, nicknames, *tu*/*vous* between characters, recurring vocabulary) is built before translating and kept in `~/.local/share/sous-titres-fr/<Show>/glossaire.md`. Later episodes, even processed weeks apart, keep the same choices. Episodes can be translated in parallel by sub-agents.

## Requirements

- `ffmpeg` and `ffprobe`
- Python 3.10 or later (standard library only)
- Only when no subtitle track is usable: Whisper. On Apple Silicon, the skill runs [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper) through `uvx`, with nothing to install beforehand; otherwise `openai-whisper`.

The agent does the translation itself: no translation API key is needed.

## Contents

```
sous-titres-fr/
├── SKILL.md                              # full workflow followed by the agent
├── README.md                             # this file
├── scripts/
│   ├── probe.py                          # inspects tracks and recommends a source (JSON)
│   └── srt_tools.py                      # clean, split, merge, check, from-whisper
└── references/
    └── regles-sous-titrage-fr.md         # French subtitling rules, with examples
```

The scripts can also be used on their own (from this folder):

```bash
# Which source should be used for these videos?
python3 scripts/probe.py /path/Season1/*.mkv

# Check a translation against its source
python3 scripts/srt_tools.py check Movie.fr.srt --ref Movie.en.srt --all
```

## Limitations

- Image-based subtitles (PGS, VobSub) are not converted to text: the skill falls back to Whisper.
- Without an Apple GPU or CUDA, Whisper is slow on a full movie (roughly real time or slower).
- A 45-minute episode is about 700 subtitles: translating it uses a significant number of tokens.

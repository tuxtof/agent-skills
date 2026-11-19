# agent-skills

[![skills.sh](https://skills.sh/b/tuxtof/agent-skills)](https://skills.sh/tuxtof/agent-skills)

Skills for coding agents (OpenCode, Claude Code, Codex, Cursor…). A skill is a folder containing a `SKILL.md` file (instructions plus a description that tells the agent when to load it) and, when needed, scripts and reference documents the agent uses during the task.

## Available skills

| Skill | Description |
|---|---|
| [`sous-titres-fr`](skills/sous-titres-fr/) | Creates French subtitles for local movies and TV shows, reusing embedded subtitles before falling back to Whisper. |

Each skill has its own README with details and requirements.

## Installation

With the [`skills`](https://github.com/vercel-labs/skills) CLI:

```bash
npx skills add tuxtof/agent-skills --skill <skill-name>
```

Or manually, by copying (or symlinking) the skill folder into your agent's skills directory:

```bash
git clone https://github.com/tuxtof/agent-skills.git
ln -s "$PWD/agent-skills/skills/<skill-name>" ~/.agents/skills/<skill-name>
```

Depending on the agent, the directory may also be `~/.claude/skills/`, `~/.config/opencode/skills/` or `.agents/skills/` inside a project.

## License

[Apache 2.0](LICENSE)

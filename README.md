# post-master

A light, AI-native Postman: Claude Code tests your APIs through a skill, saves every case as its own file,
and you review them in a read-only browser UI.

- `skills/api-testing/SKILL.md` — the skill
- `skills/api-testing/reference.md` — scenario/suite file reference
- `skills/api-testing/scripts/post_master.py` — the `post-master` runner (stdlib Python + `jq`)
- `skills/api-testing/scripts/viewer.html` — UI served by `post-master serve`

## Install

```
curl -fsSL https://raw.githubusercontent.com/chauhan17nitin/post-master/master/install.sh | sh
```

Needs `python3` (3.8+) and `jq`. It puts the `post-master` command in `~/.local/bin` and links the skill into
`~/.claude/skills/`; the files live in `~/.post-master`. Run it again to update.

See `ROADMAP.md` for what is planned.

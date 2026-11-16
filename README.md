# post-master

A light, AI-native Postman: Claude Code tests your APIs through a skill, saves every case as its own file,
and you review them in a read-only browser UI.

- `skills/api-testing/SKILL.md` — the skill
- `skills/api-testing/reference.md` — scenario/suite file reference
- `skills/api-testing/scripts/post_master.py` — the `post-master` runner (stdlib Python + `jq`)
- `skills/api-testing/scripts/viewer.html` — UI served by `post-master serve`

Install: copy or symlink `skills/api-testing` into `~/.claude/skills/` or a repo's `.claude/skills/`.

See `ROADMAP.md` for what is planned.

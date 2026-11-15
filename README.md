# post-master

API testing skill for Claude Code, with a read-only browser UI.

- `skills/api-testing/SKILL.md` — the skill
- `skills/api-testing/reference.md` — scenario/suite file reference
- `skills/api-testing/scripts/apitest.py` — runner (stdlib Python + `jq`)
- `skills/api-testing/scripts/viewer.html` — UI served by `apitest.py serve`

Install: copy or symlink `skills/api-testing` into `~/.claude/skills/` or a repo's `.claude/skills/`.

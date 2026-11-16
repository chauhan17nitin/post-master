# post-master

A light, AI-native Postman. Claude Code tests your APIs, saves every test case as its own readable file, and you
review all of it in a browser UI.

AI is good at testing APIs, but you should always be able to see exactly what it tested for you. post-master
makes that the default: nothing is tested without leaving a file you can read, diff and re-run.

## Install

```
curl -fsSL https://raw.githubusercontent.com/chauhan17nitin/post-master/master/install.sh | sh
```

Needs `python3` (3.8+) and `jq`, nothing else. It puts the `post-master` command in `~/.local/bin` and links the
skill into `~/.claude/skills/`; the files live in `~/.post-master`. Run it again to update.

## Use

1. **Ask Claude Code to test an API**, in any project:
   > test the create-subscription endpoint, including the validation errors

   Claude asks where to save the tests, writes one file per case, runs them and reports what passed and failed.

2. **Review in the browser:**
   ```
   post-master serve              # opens the last folder you used
   post-master serve <folder>     # or a specific one
   ```
   Browse every case, see the request, the response and each check. "Send request" fires a case live without
   saving anything. Switch folders from the bar at the top of the sidebar.

## Try the example

A ready-made suite against the public [httpbin.org](https://httpbin.org) service ships with the install:

```
post-master run ~/.post-master/examples/httpbin
post-master serve ~/.post-master/examples
```

Seven cases across three endpoints: an echoed JSON body, status codes, and a bearer-token check.

## How tests are stored

```
<root>/<feature>/
  00-suite.md          base URLs, variables, named requests
  00-index.md          summary of the latest run
  <NN-api>/            one folder per endpoint
    setup/             preconditions
    success/           cases that should return 2xx
    error/             cases that should return 4xx/5xx
```

Each case is a Markdown file: a report of the last run on top, then the definition as JSON. Claude edits the
definition; the `post-master` command decides PASS or FAIL and writes the report. Secrets are referenced by
environment-variable name and never written to these files.

## Commands

| Command | What it does |
|---|---|
| `post-master serve [folder]` | Open the review UI (`server` also works) |
| `post-master run <feature>` | Run the cases and write their reports (`--only 02`, `--env staging`) |
| `post-master lint <feature>` | Check the files, numbering and for leaked secrets |
| `post-master init <feature>` | Create a new feature folder |
| `post-master new <path>` | Create a case skeleton |
| `post-master root [--set PATH]` | Show or set the default folder for all features |

## Repository

- `skills/api-testing/SKILL.md` — the skill Claude follows
- `skills/api-testing/reference.md` — the suite and case file format
- `skills/api-testing/scripts/post_master.py` — the `post-master` command
- `skills/api-testing/scripts/viewer.html` — the review UI
- `examples/httpbin/` — the example suite
- `ROADMAP.md` — what is planned

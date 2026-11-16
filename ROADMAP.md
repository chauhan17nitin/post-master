# post-master v0 roadmap

**Goal:** a light, AI-native Postman. Claude tests APIs through a skill, saves every case as its own file,
and you review all of it in a browser UI started with `post-master serve <folder>`.

**v0 scope:** API testing + a readable review UI. The UI stays read-only (browse, plus a live "Send request"
that saves nothing).

## Already done

| Piece | State |
|---|---|
| Skill that makes Claude document every test | Done: `skills/api-testing/SKILL.md` + `reference.md` |
| One file per case, fixed format, in a folder | Done: `<root>/<feature>/<NN-api>/{setup,success,error}/<NN-case>.md` |
| Runner that decides PASS/FAIL and writes reports | Done: `apitest.py` (`init`, `new`, `run`, `lint`, `index`) |
| Secrets never written to files | Done: redaction + leak check in `lint` |
| Review UI in the browser | Done: `apitest.py serve` + `viewer.html`, refreshes every 3s while Claude works |
| Start the UI on a folder | Done, but only through `python3 <long path>/apitest.py serve <folder>` |

You confirmed it works well on a real API, so nothing below is a bug fix. It is all packaging and the gaps
between the script and the goal.

## Steps

### 1. One name everywhere — ✅ done (not yet run; see "Check" below)
- Script is now `post_master.py`; command name, messages, skill text, UI title and README say `post-master`.
- Config moved to `~/.claude/post-master.json`; the old `api-testing.json` is still read, so the saved root survives.
- Kept on purpose: the skill is still called `api-testing` (it names what the skill does), and the hidden
  `apitest:` markers inside scenario files are unchanged so existing suites keep working.
- **Check:** `python3 skills/api-testing/scripts/post_master.py serve` on an existing suite, and one live "Send request".

### 2. A real `post-master` command
- `post-master serve <folder>` opens the UI. `server` works as an alias, since that is how the goal spells it.
- Same subcommands as today: `root`, `init`, `new`, `run`, `lint`, `index`.
- `post-master --version` and a clear `--help`.

### 3. Install with one line, nothing else to set up
Decided: an install script for v0; a Go binary after v0 (step 9).
- `curl … | sh` puts `post-master` on PATH and installs the skill into `~/.claude/skills/`.
- It relies on `python3` and `jq` already being on the machine; the installer checks for both and says
  what is missing.

### 4. Skill uses the command
- `SKILL.md` calls `post-master …` instead of `python3 <skill dir>/scripts/apitest.py …`.
- If the command is missing, the skill tells Claude to give the user the install line.

### 5. Pick a folder from the UI
Today the folder is fixed when the server starts.
- Folder bar at the top: current folder, a list of recent folders, a box to paste another path.
- Server gets a "switch folder" call and remembers recents in the config file.
- `post-master serve` with no folder opens the last one; with nothing saved, it shows the folder box instead
  of exiting with an error.
- A path that has no test suites shows a plain message, not a crash.

### 6. First-run experience
- A small example suite (against a public echo API) so a new user sees a full UI in one minute.
- README rewritten: what it is, install line, "ask Claude to test an API", "run `post-master serve`", one screenshot.

### 7. Safety net
- Tests for the runner's core: asserts, variable lookup, redaction, lint. None exist today.
- Add a LICENSE.
- Commit `goal.txt` (currently untracked) or fold it into the README.

### 8. Ship v0
- Tag `v0.1.0`, publish the install line, try it on a clean machine.

### 9. Move to a Go binary (after v0)
- Rewrite the runner and server in Go with jq built in: one downloaded file, zero dependencies.
- Same commands, same file format, same UI; the install line stays the same and just fetches the binary.

## Order and size

| # | Step | Size | Needs |
|---|---|---|---|
| 1 | One name ✅ | S | – |
| 2 | `post-master` command | S | 1 |
| 3 | One-line install | M | 2 |
| 4 | Skill uses the command | S | 2 |
| 5 | Folder picker in UI | M | 2 |
| 6 | Example + README | S | 3, 5 |
| 7 | Tests, license | M | 1 |
| 8 | Release | S | 1–7 |
| 9 | Go binary | L | 8 |

## After v0 (not now)
Go binary (step 9), re-run from the UI, editing cases in the UI, import from
Postman/OpenAPI, anything beyond API testing.

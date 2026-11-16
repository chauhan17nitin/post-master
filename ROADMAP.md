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

### 2. A real `post-master` command — ✅ done (not yet run; see "Check" below)
- The script is executable and `bin/post-master` is a symlink to it, so it runs as a plain command.
- `post-master serve <folder>` opens the UI; `server` is an alias, since that is how the goal spells it.
- Same subcommands as before: `root`, `init`, `new`, `run`, `lint`, `index`, each with a help line.
- `post-master --version` prints `post-master 0.1.0`.
- Try it before the installer exists: `export PATH="$PWD/bin:$PATH"` from the repo root.
- **Check:** `post-master --version`, `post-master --help`, `post-master server <folder>`.

### 3. Install with one line, nothing else to set up — ✅ done (tested in a sandbox, not from GitHub)
Decided: an install script for v0; a Go binary after v0 (step 9).
- `install.sh`: `curl -fsSL https://raw.githubusercontent.com/chauhan17nitin/post-master/master/install.sh | sh`
- Checks for `python3` (3.8+) and `jq` first and says what is missing; changes nothing if either is absent.
- Files go to `~/.post-master`; `~/.local/bin/post-master` and `~/.claude/skills/api-testing` are links into it.
  Running it again updates. An existing real skill folder is kept as a backup, never deleted.
- **Works for others only once** the repo is public and this branch is merged to `master`.
- **Check:** after that, run the curl line on your machine, then `post-master --version`.

### 4. Skill uses the command — ✅ done (not yet tried in a real Claude session)
- `SKILL.md` calls `post-master …` directly and checks `post-master --version; jq --version` first.
- Command missing: Claude falls back to the script bundled in the skill for that session, so testing still
  works, and gives the user the install line. `jq` missing: Claude asks the user to install it.
- **Check:** ask Claude to test an API once with `post-master` on PATH and once without.

### 5. Pick a folder from the UI — ✅ done (UI tested against a mock server; the Python side is not yet run)
- Folder bar at the top of the sidebar: current folder, recent folders, and a box to paste another path.
- Switching happens without a restart. The last 8 folders are remembered in `~/.claude/post-master.json`.
- `post-master serve` with no folder opens the last one; with nothing saved, the UI opens on the folder box.
- A path with no suites shows a plain message and keeps the current folder.
- **Check:** `post-master serve`, switch to another suite folder, paste a wrong path, restart with no argument.

### 6. First-run experience — ✅ done
- `examples/httpbin/`: 7 cases across 3 endpoints of the public httpbin.org service. It ships unrun, so every
  case shows "not run" until `post-master run` is used on it.
- README rewritten: what it is, install line, how to use it, the example, file layout, command table.
- Two screenshots of the real UI on the example's results are in `docs/` and shown in the README.
- **Check:** `post-master run examples/httpbin` (expect 7 PASS), `post-master lint examples/httpbin`, then `serve`.

### 7. Safety net — ✅ written (tests not yet run)
- `tests/test_post_master.py`: about 70 tests, standard library only. They cover variables, redaction, request
  building, every assert operator, the file format, lint, the folder list, and a full run against a local
  fake API (pass, fail, expected error, unreachable service, token redaction).
- `LICENSE`: MIT.
- `goal.txt` is still untracked: the README now states the goal, so decide whether to commit or delete it.
- **Check:** `python3 -m unittest discover -s tests -v` from the repo root. Needs `jq`; no network.

### 8. Ship v0 — ✅ done
- Merged to `master`, repo made public with a description and topics, tagged `v0.1.0`.
- The install line was run from GitHub into empty folders and produced a correct install.
- **Still worth doing once:** run the install line on a second machine that has never had post-master.

### 9. Move to a Go binary (after v0)
- Rewrite the runner and server in Go with jq built in: one downloaded file, zero dependencies.
- Same commands, same file format, same UI; the install line stays the same and just fetches the binary.

## Order and size

| # | Step | Size | Needs |
|---|---|---|---|
| 1 | One name ✅ | S | – |
| 2 | `post-master` command ✅ | S | 1 |
| 3 | One-line install ✅ | M | 2 |
| 4 | Skill uses the command ✅ | S | 2 |
| 5 | Folder picker in UI ✅ | M | 2 |
| 6 | Example + README ✅ | S | 3, 5 |
| 7 | Tests, license ✅ (run pending) | M | 1 |
| 8 | Release ✅ | S | 1–7 |
| 9 | Go binary | L | 8 |

## After v0 (not now)
Go binary (step 9), re-run from the UI, editing cases in the UI, import from
Postman/OpenAPI, anything beyond API testing.

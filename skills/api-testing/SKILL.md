---
name: api-testing
description: Use when asked to test, hit, QA or verify API endpoints (REST/HTTP), write or save API test scenarios, re-run previously saved API scenarios, or check that an endpoint returns the expected 2xx or validation/4xx error — for any service.
---

# API testing

## Overview

Every API test is saved as a scenario file and run by a script, so results are recorded the same way every time.
The `post-master` command (stdlib Python + `jq`) makes the HTTP calls, checks the expectations, and writes the report. **You write definitions; the script decides PASS/FAIL and writes everything else.**

```
<root>/<feature>/                     e.g. ~/api-testing/subscriptions/
  00-suite.md   00-index.md   runs.jsonl   .gitignore   _local/ (raw responses, captured vars — never shared)
  <NN-api>/                           one folder per API endpoint, e.g. 01-install-app/
    setup/<NN-slug>.md                preconditions (created data, tokens). A failing setup BLOCKS the rest of the API folder
    success/<NN-slug>.md              expected 2xx
    error/<NN-slug>.md                expected 4xx/5xx (validation, 404, conflict…). Getting that error = PASS
```

Scenario ID = `<api no>/<case no>`, e.g. `01/03`. Numbers are unique per API folder across setup/success/error and set run order.

Each scenario file: Postman-like report (method, URL, path params, query, headers, body, curl, expected vs actual,
response, side-effect calls) → `## Notes` (yours) → `## Definition` JSON (source of truth, the only part you edit) →
Last run data JSON (script-owned; what the report and any UI render from).

## Workflow

**Before step 1**, run `post-master --version; jq --version` once.

- It prints a version: use `post-master` as written below.
- `post-master: command not found`: the command is not installed on PATH. For this session type
  `python3 <this skill's base directory>/scripts/post_master.py` wherever `post-master` appears below — always the full
  command (a `$T` shell variable does not word-split in zsh) — and tell the user once that this line installs it, so
  they can run `post-master serve` themselves:
  `curl -fsSL https://raw.githubusercontent.com/chauhan17nitin/post-master/master/install.sh | sh`
- `jq: command not found`: ask the user to install it (`brew install jq` / `sudo apt install jq`) and stop until they have.

1. **Root.** `post-master root`. If it prints `NOT SET`, ask the user which folder to save scenarios in, then `post-master root --set <path>`.
2. **Feature folder.** Ask the user for the feature folder name (propose one, e.g. the ticket or feature slug). If it exists,
   read its `00-suite.md` and `00-index.md` and reuse them. If not: `post-master init <root>/<feature>`.
3. **Suite.** Edit the `## Definition` JSON of `00-suite.md`: `envs` (base URLs), `vars` (IDs), `secrets` (var → **env-var name**,
   never the value), `default_headers`, one named request per endpoint under `requests`, and one `apis` entry per API folder —
   `"01-create-subscription": {"title": "Create subscription", "request": "createSubscription"}` — naming the request that
   folder tests (setup steps may call others). `post-master new` adds a stub entry for a new folder; fill it in. Read the controller/DTOs for exact
   paths and contracts. Fill in the hand-written sections above it (scope, services, auth, reset).
4. **Plan.** List the scenarios per API (success + error cases, setups) as a short table and show the user, then create each:
   `post-master new <root>/<feature>/<NN-api>/<setup|success|error>/<NN-slug>` and edit its `## Definition` JSON
   (`title`, `what` = 1–2 lines, `request`, `expect`, optional `capture`, `before`, `verify`, `view`). See `reference.md`.
5. **Run.** Secrets must be exported in the shell first — if any are missing, tell the user to run `! export NAME=…`.
   `post-master run <root>/<feature>` (all) or `--only 02` (one API) / `--only 02/05,03/01` (cases) · `--env staging`.
6. **Triage.** For each FAIL/BLOCKED, open the file and read Expected vs actual. Decide: API bug, or wrong expectation?
   - Wrong expectation: fix it only when the user's intent or the code clearly says so, say you did, re-run.
   - API bug: leave the scenario as it is and FAILing — that is the finding. Explain it in `## Notes`, add it to Findings
     in `00-index.md`, and set `known_issue` only when a ticket exists.
7. **Finish.** `post-master lint <root>/<feature>` must print `lint: OK` (run it in a shell where the secrets are exported,
   so it can also check their values didn't leak). Update the hand-kept part of `00-index.md` (Findings, State left
   behind, Not covered). Report the run summary line, each FAIL/BLOCKED with its reason, and the path to `00-index.md`.

## Reviewing in the browser

When the user wants to review or browse the suite: start `post-master serve <root or feature>` **in the background** and give
them the printed `http://127.0.0.1:…` URL (it also opens Chrome). The viewer is read-only: its "Send request" fires the
call live and shows the result, but never writes to the suite — saved results change only through `post-master run`.
Secrets must be exported in the shell that starts `serve` for live sends to work.

## Rules

- Edit only: the `## Definition` JSON, `## Notes`, the suite's hand-written sections, and `00-index.md` below the marker.
  The report, `last_run`, `runs.jsonl` and the index above the marker are written by the script.
- Case `title`s are ≤ 40 characters, sentence case, and never repeat the feature or API name (the folder already says it):
  `Blank name rejected`, not `Subscription create — blank name returns 400`.
- Create scenarios with `post-master new`; never renumber — insert with a letter (`05b-…`), retire with `"retired": "<reason>"`.
- A scenario's folder must match its expected status (`lint` enforces it). If the contract changes 400 → 200, move the file
  from `error/` to `success/` keeping its number.
- Secrets go in `secrets` as env-var names and are referenced as `{{var}}`. Mark captured tokens `"secret": true`.
- Every expectation is a `jq` assert with an operator. Prefer checking error `code` + message for error cases, and add a
  `verify` call when the API changes state (and, for error cases, that nothing changed).

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing PASS/results into the file by hand | Run `post-master run`; it writes them |
| Hard-coding URLs/IDs in each scenario | Named request in `00-suite.md` + `{{vars}}` |
| An error case placed in `success/` because "the test passes" | Folder = what the API should return, not the test result |
| Create cases fail with 409/duplicate on the second run | Make unique fields unique per run: `"name": "widget-{{$runTag}}"` |
| Re-running one case that needs an ID from an earlier case | Captures persist in `_local/vars.json`; run the producer once, or `--only` the whole API |
| BLOCKED `missing env var X` | Ask the user to `! export X=…`, re-run |

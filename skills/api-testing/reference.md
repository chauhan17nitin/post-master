# api-testing — definition reference

All definitions are JSON inside the `## Definition` ```json block at the bottom of each file.

## `00-suite.md`

```json
{
  "format": 1,
  "title": "Subscriptions — create and cancel",
  "what": "Create/cancel subscriptions for an account and the plan limits around them.",
  "links": ["https://tracker.example.com/PROJ-123"],
  "default_env": "local",
  "envs": {
    "local":   {"apiUrl": "http://localhost:8080/api", "billingUrl": "http://localhost:8081/billing"},
    "staging": {"apiUrl": "https://…", "accountId": "<staging id>"}
  },
  "vars": {"accountId": "28e8be64-…", "proPlanId": "afad9db9-…"},
  "secrets": {"serviceApiKey": "SERVICE_API_KEY"},
  "default_headers": {"Content-Type": "application/json", "X-Request-Id": "{{$runTag}}"},
  "redact_keys": [],
  "requests": {
    "createSubscription": {"method": "POST", "url": "{{apiUrl}}/v1/accounts/:accountId/subscriptions",
                           "path_params": {"accountId": "{{accountId}}"}},
    "cancelSubscription": {"method": "POST", "url": "{{apiUrl}}/v1/accounts/:accountId/subscriptions/:planId/cancel",
                           "path_params": {"accountId": "{{accountId}}", "planId": "{{proPlanId}}"}},
    "getBilling": {"method": "GET", "url": "{{billingUrl}}/v1/accounts/:accountId/billing",
                   "path_params": {"accountId": "{{accountId}}"}}
  }
}
```

`apis` (required, one entry per API folder; `lint` enforces it): `{"<NN-api folder>": {"title": "Create subscription",
"request": "<named request this folder tests>"}}`. The viewer shows the title with that request's method, so two folders
on the same path (e.g. create vs list) stay distinct; setup steps inside the folder don't change it.

Variable lookup order: `vars` → `envs.<env>` → captured vars (`_local/vars.json`, from earlier scenarios/runs) → `secrets` (from the shell env).
Vars may reference other vars (`"thingName": "widget-{{$runTag}}"`).

Built-in run vars: `{{$runId}}` (e.g. `2026-11-03T184312-local`), `{{$runTag}}` (short unique hex per run — use it for
fields with a unique constraint so re-runs don't hit duplicates), `{{$now}}` (epoch ms at run start).

## Scenario

```json
{
  "title": "Cancel blocked while invoice is unpaid",
  "what": "Cancelling is refused while the account has an unpaid invoice, and nothing changes.",
  "tags": ["cancel"],
  "known_issue": "",
  "before": [],
  "request": {
    "use": "cancelSubscription",
    "path_params": {"planId": "{{proPlanId}}"},
    "query": {},
    "headers": {},
    "body_type": "json",
    "body": {"reason": "too expensive"}
  },
  "expect": {
    "status": 400,
    "headers": [],
    "body": [
      {"name": "error code", "jq": ".error.code", "eq": "ERR_001"},
      {"name": "message", "jq": ".error.message", "contains": "unpaid invoice"}
    ]
  },
  "capture": {"subscriptionId": ".data.id", "token": {"jq": ".data.token", "secret": true}},
  "verify": [
    {"name": "plan unchanged", "use": "getBilling",
     "expect": {"status": 200, "body": [{"jq": ".data.plan", "eq": "PRO"}]}}
  ],
  "view": ".data | map({id, status})",
  "last_run": {"status": "NOT_RUN"}
}
```

| Key | Meaning |
|---|---|
| `request` | `use` a named request and override `path_params` / `query` / `headers` (merged key by key; a `null` value **removes** the key, including `default_headers`, e.g. `"headers": {"Authorization": null}` for a missing-auth case) and `body` (replaced; omit it to keep the named request's body, `null` for no body). Or give `method` + `url` inline. URL path params are `:name`. `body_type`: `json` (default), `form`, `raw` |
| `expect.status` | int or list of ints. Must be 2xx in `success/` and `setup/`, ≥400 in `error/` |
| `expect.body` / `expect.headers` | asserts; headers are lower-cased keys |
| `capture` | `var: "<jq>"` or `var: {"jq": …, "secret": true}`. Stored for later scenarios and later runs |
| `before` | steps run first. A failing step → BLOCKED. Captures are visible to the main request |
| `verify` | follow-up calls proving side effects. Count toward PASS. They see vars captured by the main request |

A step is a request with `name`, `expect` and `capture` added at the same level (overrides are flat, not nested):

```json
{"name": "fetch created thing", "use": "getThing", "path_params": {"thingId": "{{thingId}}"},
 "expect": {"status": 200, "body": [{"jq": ".data.name", "eq": "{{thingName}}"}]}}
```
| `view` | jq used to trim responses longer than 80 lines in the report (full body is in `_local/responses/`) |
| `known_issue` | ticket id, shown next to a FAIL |
| `retired` | reason; the scenario is skipped and shown as retired |

`{{var}}` works anywhere in requests and expected values. A string that is exactly `"{{var}}"` keeps the var's type
(number, bool, object). Inside a jq filter use `$var` instead.

## Asserts

`{"name": "<optional label>", "jq": "<filter>", "<op>": <value>}` — the filter's outputs are "the values".

| op | passes when |
|---|---|
| `eq` | exactly one value, equal (`true` ≠ `1`) |
| `ne` | exactly one value, not equal |
| `contains` | exactly one string value containing the text |
| `matches` | exactly one string value matching the regex |
| `includes` | the values (or the single list value) include every listed item |
| `count` | number of values == N (`".data[]"`, count 3) |
| `exists` | at least one non-null value |
| `absent` | no values, or only nulls |

Comparisons: put them in jq — `{"jq": ".total >= 3", "eq": true}`.

## Statuses

| Status | Meaning |
|---|---|
| PASS | status matched and every assert (incl. verify) passed |
| FAIL | got an HTTP response (any code, 5xx included) that broke an expectation |
| BLOCKED | no HTTP response (service down/timeout), missing secret/var, failed `before` step or failed setup in the same API folder |
| NOT_RUN | defined, never run |

## Files the script owns

- The Last run data block (status, definition hash, every check with expected/actual, the redacted request with curl, the
  redacted response — trimmed above 80 lines — and before/verify calls). The index marks a case "edited since run" when
  its definition changed after its last run.
- The whole report above `## Notes`, `runs.jsonl` (one `run` line + one `result` line per scenario),
  `00-index.md` above the marker, `_local/` (raw responses, `vars.json` captures — gitignored).
- Redaction: declared secrets, `"secret": true` captures, token-like keys (`authorization`, `cookie`, `token`, `access_token`,
  `api_key`, `client_secret`, …, plus `redact_keys`) and JWT/Bearer/`sk_` patterns become `***`; curl shows `${ENV_VAR}`.
  `lint` greps for leaks as a backstop.

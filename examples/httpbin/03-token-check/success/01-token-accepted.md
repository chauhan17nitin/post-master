# 03/01 — Token accepted

> A request carrying a bearer token is authenticated. The token shows as *** in the report.

**Last run:** ⚪ NOT_RUN · expects 2xx

## Request

_Not sent. Definition:_

```json
{
  "use": "checkToken"
}
```

## Notes

_None._

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "title": "Token accepted",
  "what": "A request carrying a bearer token is authenticated. The token shows as *** in the report.",
  "tags": [],
  "request": {
    "use": "checkToken"
  },
  "expect": {
    "status": 200,
    "body": [
      {
        "name": "authenticated",
        "jq": ".authenticated",
        "eq": true
      }
    ]
  },
  "capture": {},
  "verify": [],
  "view": ""
}
```

<!-- apitest:last-run — written by apitest.py, do not edit -->
<details><summary>Last run data (JSON)</summary>

```json
{
  "status": "NOT_RUN"
}
```
</details>

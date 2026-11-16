# 02/02 — 404 returned when asked

> Asking for status 404 returns 404. Getting the error is the pass.

**Last run:** ⚪ NOT_RUN · expects an error

## Request

_Not sent. Definition:_

```json
{
  "use": "getStatus",
  "path_params": {
    "code": "404"
  }
}
```

## Notes

_None._

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "title": "404 returned when asked",
  "what": "Asking for status 404 returns 404. Getting the error is the pass.",
  "tags": [],
  "request": {
    "use": "getStatus",
    "path_params": {
      "code": "404"
    }
  },
  "expect": {
    "status": 404,
    "body": []
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

# 02/03 — 503 returned when asked

> A 5xx response is still an HTTP response, so it is checked like any other status.

**Last run:** ⚪ NOT_RUN · expects an error

## Request

_Not sent. Definition:_

```json
{
  "use": "getStatus",
  "path_params": {
    "code": "503"
  }
}
```

## Notes

_None._

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "title": "503 returned when asked",
  "what": "A 5xx response is still an HTTP response, so it is checked like any other status.",
  "tags": [],
  "request": {
    "use": "getStatus",
    "path_params": {
      "code": "503"
    }
  },
  "expect": {
    "status": 503,
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

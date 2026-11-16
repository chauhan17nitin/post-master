# 03/02 — Missing token rejected

> Without an Authorization header the service answers 401 and asks for a bearer token.

**Last run:** ⚪ NOT_RUN · expects an error

## Request

_Not sent. Definition:_

```json
{
  "use": "checkToken",
  "headers": {
    "Authorization": null
  }
}
```

## Notes

_None._

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "title": "Missing token rejected",
  "what": "Without an Authorization header the service answers 401 and asks for a bearer token.",
  "tags": [],
  "request": {
    "use": "checkToken",
    "headers": {
      "Authorization": null
    }
  },
  "expect": {
    "status": 401,
    "headers": [
      {
        "name": "www-authenticate",
        "jq": ".[\"www-authenticate\"]",
        "eq": "Bearer"
      }
    ],
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

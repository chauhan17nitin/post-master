# 01/02 — Query parameters echoed back

> Query parameters arrive as strings under args.

**Last run:** ⚪ NOT_RUN · expects 2xx

## Request

_Not sent. Definition:_

```json
{
  "use": "echo",
  "query": {
    "page": "2",
    "sort": "name"
  }
}
```

## Notes

_None._

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "title": "Query parameters echoed back",
  "what": "Query parameters arrive as strings under args.",
  "tags": [],
  "request": {
    "use": "echo",
    "query": {
      "page": "2",
      "sort": "name"
    }
  },
  "expect": {
    "status": 200,
    "body": [
      {
        "name": "page",
        "jq": ".args.page",
        "eq": "2"
      },
      {
        "name": "sort",
        "jq": ".args.sort",
        "eq": "name"
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

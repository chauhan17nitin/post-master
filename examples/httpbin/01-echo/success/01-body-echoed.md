# 01/01 — JSON body echoed back

> The service returns the JSON body it was sent, unchanged.

**Last run:** ⚪ NOT_RUN · expects 2xx

## Request

_Not sent. Definition:_

```json
{
  "use": "echo"
}
```

## Notes

_None._

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "title": "JSON body echoed back",
  "what": "The service returns the JSON body it was sent, unchanged.",
  "tags": [],
  "request": {
    "use": "echo"
  },
  "expect": {
    "status": 200,
    "body": [
      {
        "name": "name",
        "jq": ".json.name",
        "eq": "widget"
      },
      {
        "name": "quantity",
        "jq": ".json.qty",
        "eq": 3
      },
      {
        "name": "method",
        "jq": ".method",
        "eq": "POST"
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

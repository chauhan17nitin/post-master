# httpbin — example suite

## Scope
- An example to try post-master with. It tests nothing of yours: every request goes to the public service httpbin.org.
- In scope: a JSON body echoed back, query parameters, status codes, a bearer-token check.

## Services
- httpbin — https://httpbin.org (public, no account needed)

## Auth
- None. The token case sends a made-up value (`demoToken` in `vars`). A real suite would declare the env-var name under
  `secrets` instead, so the value never reaches these files.

## Resetting for a re-run
- Nothing to reset: httpbin keeps no state.

<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->
## Definition

```json
{
  "format": 1,
  "title": "httpbin — example suite",
  "what": "A small tour of post-master against the public httpbin.org echo service: echoed bodies, status codes and a token check.",
  "links": [
    "https://httpbin.org"
  ],
  "default_env": "public",
  "envs": {
    "public": {
      "baseUrl": "https://httpbin.org"
    }
  },
  "vars": {
    "demoToken": "demo-token"
  },
  "secrets": {},
  "default_headers": {
    "Content-Type": "application/json"
  },
  "redact_keys": [],
  "requests": {
    "echo": {
      "method": "POST",
      "url": "{{baseUrl}}/anything",
      "body": {
        "name": "widget",
        "qty": 3
      }
    },
    "getStatus": {
      "method": "GET",
      "url": "{{baseUrl}}/status/:code",
      "path_params": {
        "code": "200"
      }
    },
    "checkToken": {
      "method": "GET",
      "url": "{{baseUrl}}/bearer",
      "headers": {
        "Authorization": "Bearer {{demoToken}}"
      }
    }
  },
  "apis": {
    "01-echo": {
      "title": "Echo request",
      "request": "echo"
    },
    "02-status-codes": {
      "title": "Return a status code",
      "request": "getStatus"
    },
    "03-token-check": {
      "title": "Check bearer token",
      "request": "checkToken"
    }
  }
}
```

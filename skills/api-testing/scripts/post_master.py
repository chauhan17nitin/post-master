#!/usr/bin/env python3
"""post-master — run and record API test scenarios (stdlib only; needs the `jq` CLI).

Layout:  <root>/<feature>/<NN-api>/{setup,success,error}/<NN-slug>.md
Each scenario is one .md file: a generated, Postman-like report on top, a hand-written `## Notes`
section, then `## Definition` — a ```json block (definition + last_run) that is the source of truth.

Commands:
  root [--set PATH]                      show / remember the root folder for all features
  init  <feature-dir>                    create 00-suite.md, 00-index.md, .gitignore
  new   <feature>/<NN-api>/<setup|success|error>/<NN-slug>   create a scenario skeleton
  run   <feature-dir> [--env E] [--only 02,03/05] [--timeout 30]
  index <feature-dir>                    regenerate 00-index.md
  lint  <feature-dir>                    validate files, numbering, folder vs status, secret leaks
  serve [root-or-feature] [--port 4777]  read-only viewer in the browser; "Send" fires a request without saving
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FORMAT = 1
CONFIG_FILE = Path.home() / ".claude" / "post-master.json"
OLD_CONFIG_FILE = Path.home() / ".claude" / "api-testing.json"   # pre-rename name; read as a fallback, never written
KINDS = ("setup", "success", "error")
OPS = ("eq", "ne", "contains", "includes", "matches", "count", "exists", "absent")
TOKEN_KEYS = {"authorization", "proxy_authorization", "cookie", "set_cookie", "access_token",
              "refresh_token", "id_token", "token", "jwt", "api_key", "apikey", "x_api_key", "client_secret"}
LEAK_PATTERNS = [r"Bearer\s+[A-Za-z0-9._~+/-]{12,}", r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
                 r"\bsk_(live|test)_[A-Za-z0-9]{6,}", r"\bsk-[A-Za-z0-9]{20,}"]
ICON = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "⛔", "SKIPPED": "⏭", "NOT_RUN": "⚪", "RETIRED": "🪦"}
INDEX_MARKER = "<!-- api-testing: hand-kept below this line -->"
NOTES_HEADING = "## Notes"
MAX_BODY_LINES = 80          # trimmed size in the markdown report
MAX_DATA_LINES = 2000        # size kept in the last-run JSON block (what the viewer shows)
CASE_RE = re.compile(r"^(\d+)([a-z]?)-([a-z0-9][a-z0-9-]*)\.md$")
API_RE = re.compile(r"^(\d+)-[a-z0-9][a-z0-9-]*$")


class Unresolved(Exception):
    pass


def load_config():
    for f in (CONFIG_FILE, OLD_CONFIG_FILE):
        if f.exists():
            return json.loads(f.read_text())
    return {}


# ---------------------------------------------------------------- files

DEF_MARKER = "<!-- apitest:definition — source of truth, edit the JSON below; everything above it except Notes is generated -->"
RUN_MARKER = "<!-- apitest:last-run — written by apitest.py, do not edit -->"


def json_block_after(text, marker, path):
    i = text.find(marker)
    if i < 0:
        return None, -1
    start = text.find("```json\n", i)
    end = text.find("\n```", start + 8)
    if start < 0 or end < 0:
        raise ValueError(f"{path}: expected a ```json block under '{marker[:24]}…'")
    try:
        return json.loads(text[start + 8:end]), i
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: JSON under '{marker[:24]}…' is invalid: {e}")


def read_doc(path):
    """Return (definition incl. last_run, report body above the definition)."""
    text = Path(path).read_text()
    meta, i = json_block_after(text, DEF_MARKER, path)
    if meta is None:
        raise ValueError(f"{path}: no definition block (missing '{DEF_MARKER[:22]}…' marker)")
    last_run, _ = json_block_after(text, RUN_MARKER, path)
    if last_run is not None:
        meta["last_run"] = last_run
    return meta, text[:i].rstrip() + "\n"


def write_doc(path, meta, body):
    meta = dict(meta)
    last_run = meta.pop("last_run", None)
    text = (body.rstrip() + "\n\n" + DEF_MARKER + "\n## Definition\n\n```json\n"
            + json.dumps(meta, indent=2, ensure_ascii=False) + "\n```\n")
    if last_run is not None:
        text += ("\n" + RUN_MARKER + "\n<details><summary>Last run data (JSON)</summary>\n\n```json\n"
                 + json.dumps(last_run, indent=2, ensure_ascii=False) + "\n```\n</details>\n")
    Path(path).write_text(text)


def definition_hash(meta):
    d = {k: v for k, v in meta.items() if k != "last_run"}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


def keep_notes(old_body):
    i = old_body.find("\n" + NOTES_HEADING + "\n")
    if i >= 0:
        return old_body[i + 1:]
    return NOTES_HEADING + "\n\n_None._\n"


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_suite(feature):
    path = Path(feature) / "00-suite.md"
    if not path.exists():
        sys.exit(f"no 00-suite.md in {feature} — run: post-master init {feature}")
    return read_doc(path)[0]


def case_key(name):
    m = CASE_RE.match(name)
    return (int(m.group(1)), m.group(2)) if m else (10 ** 6, name)


def list_cases(feature):
    """Return [(api_dir, kind, path)] in run order: api folders by number, cases by number."""
    out = []
    apis = sorted([d for d in Path(feature).iterdir() if d.is_dir() and API_RE.match(d.name)],
                  key=lambda d: int(d.name.split("-")[0]))
    for api in apis:
        cases = []
        for kind in KINDS:
            folder = api / kind
            if folder.is_dir():
                cases += [(api, kind, p) for p in folder.glob("*.md")]
        cases.sort(key=lambda c: case_key(c[2].name))
        out += cases
    return out


def case_id(api, path):
    m = CASE_RE.match(path.name)
    num = (m.group(1) + m.group(2)) if m else path.stem
    return f"{api.name.split('-')[0]}/{num}"


def local_dir(feature):
    return Path(feature) / "_local"


def load_captures(feature):
    p = local_dir(feature) / "vars.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_captures(feature, captures):
    local_dir(feature).mkdir(exist_ok=True)
    (local_dir(feature) / "vars.json").write_text(json.dumps(captures, indent=2))


# ---------------------------------------------------------------- vars & redaction

VAR_RE = re.compile(r"\{\{\s*(\$?[A-Za-z_][\w.-]*)\s*\}\}")


def substitute(value, variables, depth=0):
    """Replace {{var}} recursively (vars may reference other vars). Exactly "{{var}}" keeps the var's type."""
    if depth > 5:
        raise ValueError("vars reference each other in a loop")
    if isinstance(value, str):
        def lookup(name):
            if name not in variables:
                raise Unresolved(name)
            return substitute(variables[name], variables, depth + 1)
        whole = VAR_RE.fullmatch(value.strip())
        if whole:
            return lookup(whole.group(1))
        return VAR_RE.sub(lambda m: (lambda v: v if isinstance(v, str) else json.dumps(v))(lookup(m.group(1))), value)
    if isinstance(value, list):
        return [substitute(v, variables, depth) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables, depth) for k, v in value.items()}
    return value


class Redactor:
    def __init__(self, suite):
        self.values = {}            # secret value -> display in curl
        self.keys = TOKEN_KEYS | {norm_key(k) for k in suite.get("redact_keys", [])}

    def add(self, value, shown="***"):
        if isinstance(value, str) and len(value) >= 4:
            self.values[value] = shown

    def text(self, s, for_curl=False):
        for v, shown in sorted(self.values.items(), key=lambda kv: -len(kv[0])):
            s = s.replace(v, shown if for_curl else "***")
        for pat in LEAK_PATTERNS:
            s = re.sub(pat, "***", s)
        return s

    def obj(self, o):
        if isinstance(o, dict):
            return {k: ("***" if norm_key(k) in self.keys and v not in (None, "") else self.obj(v))
                    for k, v in o.items()}
        if isinstance(o, list):
            return [self.obj(v) for v in o]
        if isinstance(o, str):
            return self.text(o)
        return o


def norm_key(k):
    return k.lower().replace("-", "_")


def build_vars(feature, suite, env):
    variables = dict(suite.get("vars", {}))
    variables.update(suite.get("envs", {}).get(env, {}))
    variables.update(load_captures(feature))
    redactor = Redactor(suite)
    missing = {}
    for name, env_name in suite.get("secrets", {}).items():
        if env_name in os.environ:
            variables[name] = os.environ[env_name]
            redactor.add(os.environ[env_name], "${" + env_name + "}")
        else:
            missing[name] = env_name
    for name in load_secret_capture_names(feature):
        if name in variables:
            redactor.add(variables[name])
    return variables, redactor, missing


def load_secret_capture_names(feature):
    p = local_dir(feature) / "secret-vars.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def mark_secret_capture(feature, name):
    names = load_secret_capture_names(feature) | {name}
    local_dir(feature).mkdir(exist_ok=True)
    (local_dir(feature) / "secret-vars.json").write_text(json.dumps(sorted(names)))


# ---------------------------------------------------------------- requests

def merge_request(spec, suite):
    """Named request + overrides. path_params/query/headers merge; a null value deletes that key."""
    spec = {k: v for k, v in spec.items() if k not in ("name", "expect", "capture")}
    base = {}
    if "use" in spec:
        name = spec.pop("use")
        if name not in suite.get("requests", {}):
            raise ValueError(f"unknown named request '{name}' (define it in 00-suite.md → requests)")
        base = json.loads(json.dumps(suite["requests"][name]))
    merged = dict(base)
    for key in ("path_params", "query", "headers"):
        start = suite.get("default_headers", {}) if key == "headers" else {}
        both = {**start, **base.get(key, {}), **(spec.pop(key, None) or {})}
        merged[key] = {k: v for k, v in both.items() if v is not None}
    merged.update(spec)
    merged.setdefault("body_type", "json")
    return merged


def resolve_request(spec, suite, variables):
    req = substitute(merge_request(spec, suite), variables)
    url = req["url"]
    for k, v in req["path_params"].items():
        url = re.sub(r":" + re.escape(k) + r"(?=/|\?|$)", urllib.parse.quote(str(v), safe=""), url)
    if req["query"]:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: (json.dumps(v) if isinstance(v, bool) else v) for k, v in req["query"].items()}, doseq=True)
    req["full_url"] = url
    return req


def encode_body(req):
    body = req.get("body")
    if body is None:
        return None
    if req["body_type"] == "json":
        return json.dumps(body).encode()
    if req["body_type"] == "form":
        return urllib.parse.urlencode(body, doseq=True).encode()
    return (body if isinstance(body, str) else json.dumps(body)).encode()


def send(req, timeout):
    """Return call dict. Raises ConnectionError when there is no HTTP response at all."""
    data = encode_body(req)
    headers = dict(req["headers"])
    if data is not None and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = {"json": "application/json", "form": "application/x-www-form-urlencoded"}.get(
            req["body_type"], "text/plain")
    r = urllib.request.Request(req["full_url"], data=data, method=req["method"].upper(), headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            status, raw, rh = resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        status, raw, rh = e.code, e.read(), e.headers
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectionError(str(getattr(e, "reason", e)))
    ms = int((time.monotonic() - start) * 1000)
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed, is_json = json.loads(text), True
    except json.JSONDecodeError:
        parsed, is_json = text, False
    return {"req": req, "status": status, "ms": ms, "text": text, "json": parsed, "is_json": is_json,
            "headers": {k.lower(): v for k, v in rh.items()}}


def save_response(feature, api, path, step, call):
    m = CASE_RE.match(path.name)
    num = (m.group(1) + m.group(2)) if m else path.stem
    out = local_dir(feature) / "responses" / api.name
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{num}.{step}.json"
    f.write_text(json.dumps(call["json"], indent=2, ensure_ascii=False) if call["is_json"] else call["text"])
    (out / f"{num}.{step}.headers.json").write_text(json.dumps(call["headers"], indent=2))
    call["file"] = str(f.relative_to(feature))


# ---------------------------------------------------------------- assertions

def jq_values(flt, data, variables):
    args = ["jq", "-c"]
    for k, v in variables.items():
        if re.fullmatch(r"[A-Za-z_]\w*", k):
            args += ["--argjson", k, json.dumps(v)]
    args.append(flt)
    p = subprocess.run(args, input=json.dumps(data), capture_output=True, text=True)
    if p.returncode != 0:
        raise ValueError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "jq failed")
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def evaluate(assertion, data, variables):
    """Return (passed, expected_text, actual_text)."""
    op = next((o for o in OPS if o in assertion), None)
    if op is None:
        return False, "?", f"no operator; use one of {', '.join(OPS)}"
    try:
        want = substitute(assertion[op], variables)
    except Unresolved as e:
        return False, show_expected(op, assertion[op]), f"unknown var {{{{{e}}}}}"
    try:
        vals = jq_values(assertion["jq"], data, variables)
    except ValueError as e:
        return False, show_expected(op, want), f"jq error: {e}"
    one = vals[0] if len(vals) == 1 else None
    if op == "eq":
        ok = len(vals) == 1 and same(one, want)
    elif op == "ne":
        ok = len(vals) == 1 and not same(one, want)
    elif op == "contains":
        ok = len(vals) == 1 and isinstance(one, str) and str(want) in one
    elif op == "matches":
        ok = len(vals) == 1 and isinstance(one, str) and re.search(want, one) is not None
    elif op == "includes":
        pool = one if len(vals) == 1 and isinstance(one, list) else vals
        ok = all(any(same(w, v) for v in pool) for w in (want if isinstance(want, list) else [want]))
    elif op == "count":
        ok = len(vals) == want
    elif op == "exists":
        ok = any(v is not None for v in vals)
    else:
        ok = all(v is None for v in vals)
    actual = f"{len(vals)} value(s)" if op == "count" else (", ".join(compact(v) for v in vals) or "(nothing)")
    return ok, show_expected(op, want), actual


def show_expected(op, want):
    if op in ("exists", "absent"):
        return op
    if op == "eq":
        return compact(want)
    return f"{op} {compact(want)}"


def compact(v, limit=90):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def check_status(expected, actual):
    allowed = expected if isinstance(expected, list) else [expected]
    return actual in allowed, " or ".join(str(a) for a in allowed)


def run_expect(label, expect, call, variables):
    """Return list of check dicts for one call."""
    checks = []
    if "status" in expect:
        ok, exp = check_status(expect["status"], call["status"])
        checks.append({"name": f"{label}HTTP status", "ok": ok, "expected": exp, "actual": str(call["status"])})
    for a in expect.get("headers", []):
        ok, exp, act = evaluate(a, call["headers"], variables)
        checks.append({"name": label + "header: " + a.get("name", a["jq"]), "ok": ok, "expected": exp, "actual": act})
    for a in expect.get("body", []):
        ok, exp, act = evaluate(a, call["json"], variables)
        checks.append({"name": label + a.get("name", a["jq"]), "ok": ok, "expected": exp, "actual": act})
    return checks


def run_captures(capture, call, variables, feature):
    got = {}
    for var, spec in (capture or {}).items():
        spec = {"jq": spec} if isinstance(spec, str) else spec
        vals = jq_values(spec["jq"], call["json"], variables)
        if len(vals) != 1 or vals[0] is None:
            raise ValueError(f"capture '{var}' via `{spec['jq']}` gave {len(vals)} value(s)")
        got[var] = vals[0]
        if spec.get("secret"):
            mark_secret_capture(feature, var)
    return got


# ---------------------------------------------------------------- running one scenario

def run_scenario(feature, suite, api, kind, path, variables, redactor, missing, timeout, run_id, env, blocked_by):
    meta, old_body = read_doc(path)
    cid = case_id(api, path)
    result = {"status": "NOT_RUN", "checks": [], "main": None, "verify": [], "before": [], "captured": {},
              "blocked_by": None}

    def blocked(reason):
        result["status"], result["blocked_by"] = "BLOCKED", reason

    try:
        if blocked_by:
            blocked(blocked_by)
            raise StopIteration
        for i, step in enumerate(meta.get("before", []), 1):
            call = send(resolve_request(step, suite, variables), timeout)
            save_response(feature, api, path, f"before-{i}", call)
            checks = run_expect(f"before: {step.get('name', i)} · ", step.get("expect", {}), call, variables)
            result["before"].append((step, call, checks))
            if not all(c["ok"] for c in checks):
                blocked(f"before step '{step.get('name', i)}' failed")
                raise StopIteration
            variables.update(run_captures(step.get("capture"), call, variables, feature))
        call = send(resolve_request(meta["request"], suite, variables), timeout)
        save_response(feature, api, path, "main", call)
        result["main"] = call
        result["checks"] += run_expect("", meta.get("expect", {}), call, variables)
        try:
            captured = run_captures(meta.get("capture"), call, variables, feature)
            variables.update(captured)
            result["captured"] = captured
        except ValueError as e:
            result["checks"].append({"name": "capture", "ok": False, "expected": "1 value", "actual": str(e)})
        for i, step in enumerate(meta.get("verify", []), 1):
            vcall = send(resolve_request(step, suite, variables), timeout)
            save_response(feature, api, path, f"verify-{i}", vcall)
            checks = run_expect(f"verify: {step.get('name', i)} · ", step.get("expect", {}), vcall, variables)
            result["verify"].append((step, vcall, checks))
            result["checks"] += checks
        result["status"] = "PASS" if all(c["ok"] for c in result["checks"]) else "FAIL"
    except StopIteration:
        pass
    except Unresolved as e:
        name = str(e)
        blocked(f"missing env var {missing[name]}" if name in missing else f"unknown var {{{{{name}}}}}")
    except ConnectionError as e:
        blocked(f"env: no HTTP response ({e})")
    except ValueError as e:
        blocked(f"definition error: {e}")

    for name in result["captured"]:
        if name in load_secret_capture_names(feature):
            redactor.add(result["captured"][name])
    failed = [c["name"] for c in result["checks"] if not c["ok"]]
    main = result["main"]
    meta["last_run"] = {
        "status": result["status"], "run_id": run_id, "at": now_iso(), "env": env,
        "definition_hash": definition_hash(meta),
        "http_status": main["status"] if main else None,
        "duration_ms": main["ms"] if main else None,
        "failed": failed, "blocked_by": result["blocked_by"],
        "captured": {k: ("***" if k in load_secret_capture_names(feature) else v)
                     for k, v in result["captured"].items()},
        "checks": [{**c, "actual": redactor.text(c["actual"])} for c in result["checks"]],
        "request": request_data(main["req"], redactor) if main else None,
        "response": response_data(main, None, redactor, max_lines=MAX_DATA_LINES) if main else None,
        "before": [call_summary(step, call, checks, redactor) for step, call, checks in result["before"]],
        "verify": [call_summary(step, call, checks, redactor) for step, call, checks in result["verify"]],
    }
    write_doc(path, meta, render(cid, kind, meta, result, redactor, keep_notes(old_body)))
    return cid, meta, result


# ---------------------------------------------------------------- last_run data (what a UI reads)

def request_data(req, redactor):
    return {"method": req["method"].upper(), "url": redactor.text(req["full_url"]),
            "path_params": redactor.obj(req["path_params"]), "query": redactor.obj(req["query"]),
            "headers": redactor.obj(req["headers"]), "body_type": req["body_type"],
            "body": redactor.obj(req.get("body")), "curl": render_curl(req, redactor)}


def response_data(call, view, redactor, max_lines=MAX_BODY_LINES):
    data = {"status": call["status"], "ms": call["ms"], "headers": redactor.obj(call["headers"]),
            "file": call.get("file"), "trimmed": None}
    body = redactor.obj(call["json"]) if call["is_json"] else redactor.text(call["text"])
    lines = (json.dumps(body, indent=2) if call["is_json"] else body).count("\n") + 1
    if lines > max_lines and view and call["is_json"]:
        try:
            body = redactor.obj(jq_values(view, call["json"], {}))
            data["trimmed"] = f"view `{view}` ({lines} lines in full)"
        except ValueError:
            pass
    if data["trimmed"] is None and lines > max_lines:
        text = json.dumps(body, indent=2, ensure_ascii=False) if call["is_json"] else body
        body = "\n".join(text.splitlines()[:max_lines])
        data["trimmed"] = f"first {max_lines} of {lines} lines"
    data["body"] = body
    return data


def call_summary(step, call, checks, redactor):
    return {"name": step.get("name", ""), "ok": all(c["ok"] for c in checks),
            "checks": [{**c, "name": c["name"].split(" · ", 1)[-1], "actual": redactor.text(c["actual"])} for c in checks],
            "request": request_data(call["req"], redactor), "response": response_data(call, None, redactor, max_lines=MAX_DATA_LINES)}


# ---------------------------------------------------------------- rendering

def md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def pretty(call):
    if call["is_json"]:
        return json.dumps(call["json"], indent=2, ensure_ascii=False), "json"
    return call["text"], "text"


def render_request(req, redactor):
    lines = [f"`{req['method'].upper()} {redactor.text(req['full_url'])}`", ""]
    def kv(d):
        return ", ".join(f"`{k}={redactor.text(v if isinstance(v, str) else json.dumps(v))}`" for k, v in d.items())
    pp, q = kv(req["path_params"]) or "none", kv(req["query"]) or "none"
    lines.append(f"Path params: {pp} · Query: {q}  ")
    lines.append("Headers:")
    for k, v in redactor.obj(req["headers"]).items():
        lines.append(f"- `{k}: {v}`")
    if req.get("body") is not None:
        body = redactor.obj(req["body"])
        lang = "json" if req["body_type"] == "json" else "text"
        text = json.dumps(body, indent=2, ensure_ascii=False) if not isinstance(body, str) else body
        lines += ["", f"Body ({req['body_type']}):", "", f"```{lang}", text, "```"]
    lines += ["", "<details><summary>curl</summary>", "", "```bash", render_curl(req, redactor), "```", "</details>"]
    return "\n".join(lines)


def render_curl(req, redactor):
    def q(s):
        s = redactor.text(s, for_curl=True)
        return '"' + s.replace('"', '\\"') + '"' if "${" in s else "'" + s.replace("'", "'\\''") + "'"
    parts = [f"curl -sS -X {req['method'].upper()} {q(req['full_url'])}"]
    for k, v in req["headers"].items():
        parts.append(f"  -H {q(f'{k}: {v}')}")
    if req.get("body") is not None:
        data = encode_body(req).decode()
        if req["body_type"] == "json":
            data = json.dumps(req["body"], indent=2, ensure_ascii=False)
        parts.append("  --data-binary @- <<'EOF'\n" + redactor.text(data) + "\nEOF")
    return " \\\n".join(parts)


def render_response(call, view, redactor):
    text, lang = pretty(call)
    text = redactor.text(json.dumps(redactor.obj(call["json"]), indent=2, ensure_ascii=False)) if call["is_json"] \
        else redactor.text(text)
    lines = [f"## Response — HTTP {call['status']} · {call['ms']} ms", ""]
    n = text.count("\n") + 1
    if n > MAX_BODY_LINES and view and call["is_json"]:
        try:
            shown = "\n".join(json.dumps(v, indent=2, ensure_ascii=False) for v in jq_values(view, call["json"], {}))
            lines += [f"Trimmed with view `{view}` ({n} lines in full: `{call['file']}`)", "", f"```json", redactor.text(shown), "```"]
        except ValueError as e:
            lines += [f"view failed ({e}); first {MAX_BODY_LINES} lines:", "", f"```{lang}",
                      "\n".join(text.splitlines()[:MAX_BODY_LINES]), "```"]
    elif n > MAX_BODY_LINES:
        lines += [f"First {MAX_BODY_LINES} of {n} lines (full: `{call['file']}`; set `view` to trim):", "",
                  f"```{lang}", "\n".join(text.splitlines()[:MAX_BODY_LINES]), "```"]
    else:
        lines += [f"```{lang}", text, "```"]
    hdr = json.dumps(redactor.obj(call["headers"]), indent=2)
    lines += ["", "<details><summary>response headers</summary>", "", "```json", hdr, "```", "</details>"]
    return "\n".join(lines)


def render(cid, kind, meta, result, redactor, notes):
    lr = meta.get("last_run", {"status": "NOT_RUN"})
    status = lr["status"]
    label = {"setup": "setup", "success": "expects 2xx", "error": "expects an error"}[kind]
    out = [f"# {cid} — {meta.get('title', '')}", "", f"> {meta.get('what', '')}", ""]
    line = f"**Last run:** {ICON.get(status, '')} {status}"
    if lr.get("at"):
        line += f" · {lr['at'][:16].replace('T', ' ')} · env `{lr.get('env')}` · run `{lr.get('run_id')}`"
    line += f" · {label}"
    if meta.get("known_issue") and status == "FAIL":
        line += f" · known issue {meta['known_issue']}"
    out.append(line)
    if lr.get("blocked_by"):
        out.append(f"\n**Blocked by:** {lr['blocked_by']}")
    out.append("")
    for step, call, checks in result.get("before", []):
        out += [f"<details><summary>before: {step.get('name', '')} → HTTP {call['status']}</summary>", "",
                render_request(call["req"], redactor), "", "</details>", ""]
    out += ["## Request", ""]
    main = result.get("main")
    if main:
        out.append(render_request(main["req"], redactor))
    else:
        out += ["_Not sent. Definition:_", "", "```json", json.dumps(meta.get("request", {}), indent=2), "```"]
    out.append("")
    if result.get("checks"):
        out += ["## Expected vs actual", "", "| Check | Expected | Actual | |", "|---|---|---|---|"]
        for c in result["checks"]:
            out.append(f"| {md_cell(c['name'])} | `{md_cell(c['expected'])}` | `{md_cell(redactor.text(c['actual']))}` "
                       f"| {'✅' if c['ok'] else '❌'} |")
        out.append("")
    if main:
        out += [render_response(main, meta.get("view"), redactor), ""]
    if result.get("verify"):
        out += ["## Side effects (verify calls)", ""]
        for i, (step, call, checks) in enumerate(result["verify"], 1):
            ok = all(c["ok"] for c in checks)
            out.append(f"{i}. {'✅' if ok else '❌'} **{step.get('name', '')}** — "
                       f"`{call['req']['method'].upper()} {redactor.text(call['req']['full_url'])}` → {call['status']}")
            text, lang = pretty(call)
            if call["is_json"]:
                text = json.dumps(redactor.obj(call["json"]), indent=2, ensure_ascii=False)
            if text.count("\n") < 40:
                out += ["", f"   <details><summary>response</summary>", "", f"   ```{lang}",
                        "\n".join("   " + l for l in redactor.text(text).splitlines()), "   ```", "   </details>", ""]
            else:
                out.append(f"   (full response: `{call['file']}`)")
        out.append("")
    out.append(notes.rstrip() + "\n")
    return "\n".join(out)


# ---------------------------------------------------------------- index

def write_index(feature):
    feature = Path(feature)
    suite = load_suite(feature)
    rows, counts = [], {}
    for api, kind, path in list_cases(feature):
        meta, _ = read_doc(path)
        lr = meta.get("last_run") or {"status": "NOT_RUN"}
        st = "RETIRED" if meta.get("retired") else lr["status"]
        if lr.get("definition_hash") and lr["definition_hash"] != definition_hash(meta):
            lr = {**lr, "changed": True}
        rows.append((api, kind, path, meta, lr, st))
        if kind != "setup" and st != "RETIRED":
            counts[st] = counts.get(st, 0) + 1
    runs = read_runs(feature)
    last = runs[-1] if runs else None
    out = [f"# {suite.get('title', feature.name)} — index", "",
           f"Context: [00-suite.md](00-suite.md) · History: `runs.jsonl` · _Above the marker is generated by "
           f"`post-master index` — don't edit it._", ""]
    total = sum(counts.values())
    summary = " · ".join(f"{ICON[s]} {counts.get(s, 0)} {s}" for s in ("PASS", "FAIL", "BLOCKED", "NOT_RUN"))
    out.append(f"**Latest run:** `{last['run_id']}` · env `{last['env']}` · {total} scenarios · {summary}" if last
               else f"**No runs yet** · {total} scenarios")
    out.append("")
    attention = [r for r in rows if r[5] in ("FAIL", "BLOCKED")]
    if attention:
        out += ["## Needs attention", ""]
        for api, kind, path, meta, lr, st in attention:
            why = lr.get("blocked_by") or ", ".join(lr.get("failed", []))
            known = f" (known: {meta['known_issue']})" if meta.get("known_issue") else ""
            out.append(f"- {ICON[st]} **{case_id(api, path)}** [{meta.get('title')}]({path.relative_to(feature)}) — "
                       f"{md_cell(why)}{known}")
        out.append("")
    for api in sorted({r[0] for r in rows}, key=lambda d: d.name):
        api_rows = [r for r in rows if r[0] == api]
        out += [f"## {api.name}", ""]
        for kind, heading in (("setup", "Setup"), ("success", "Should succeed (2xx)"),
                              ("error", "Should return an error (4xx/5xx)")):
            krows = [r for r in api_rows if r[1] == kind]
            if not krows:
                continue
            out += [f"**{heading}**", "", "| ID | Scenario | Expected | Actual | Status | Last run |",
                    "|---|---|---|---|---|---|"]
            for _, _, path, meta, lr, st in krows:
                exp = meta.get("expect", {}).get("status", "")
                exp = " or ".join(map(str, exp)) if isinstance(exp, list) else exp
                out.append(f"| {case_id(api, path)} | [{md_cell(meta.get('title'))}]({path.relative_to(feature)}) | "
                           f"{exp} | {lr.get('http_status') or '—'} | {ICON.get(st, '')} {st}"
                           f"{' ⚠ edited since run' if lr.get('changed') else ''} | "
                           f"{(lr.get('at') or '—')[:10]} |")
            out.append("")
    if runs:
        out += ["## Recent runs", "", "| Run | Env | Scope | PASS | FAIL | BLOCKED |", "|---|---|---|---|---|---|"]
        for r in runs[-10:][::-1]:
            out.append(f"| `{r['run_id']}` | {r['env']} | {', '.join(r['scope']) or 'all'} | "
                       f"{r['counts'].get('PASS', 0)} | {r['counts'].get('FAIL', 0)} | {r['counts'].get('BLOCKED', 0)} |")
        out.append("")
    index = feature / "00-index.md"
    hand = "\n## Findings\n\n_None yet._\n\n## State left behind\n\n_What the last run left in the system "\
           "(created entities, toggled flags) so the next run knows where it starts._\n\n## Not covered\n\n_None._\n"
    if index.exists():
        old = index.read_text()
        if INDEX_MARKER in old:
            hand = old.split(INDEX_MARKER, 1)[1]
    index.write_text("\n".join(out) + "\n" + INDEX_MARKER + hand)


def read_runs(feature):
    p = Path(feature) / "runs.jsonl"
    if not p.exists():
        return []
    runs, by_id = [], {}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["type"] == "run":
            rec["counts"] = {}
            by_id[rec["run_id"]] = rec
            runs.append(rec)
        elif rec["type"] == "result" and rec["run_id"] in by_id:
            c = by_id[rec["run_id"]]["counts"]
            c[rec["status"]] = c.get(rec["status"], 0) + 1
    return runs


def append_run(feature, rec):
    with open(Path(feature) / "runs.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- commands

def cmd_run(a):
    feature = Path(a.feature)
    suite = load_suite(feature)
    env = a.env or suite.get("default_env", "local")
    if env not in suite.get("envs", {env: {}}):
        sys.exit(f"env '{env}' not in 00-suite.md envs: {list(suite.get('envs', {}))}")
    scope = [s.strip() for s in (a.only or "").split(",") if s.strip()]
    run_id = dt.datetime.now().strftime("%Y-%m-%dT%H%M%S") + "-" + env
    existing = {r["run_id"] for r in read_runs(feature)}
    while run_id in existing:
        run_id += "b"
    variables, redactor, missing = build_vars(feature, suite, env)
    variables.update({"$runId": run_id, "$runTag": format(int(time.time() * 1000) % 36 ** 6, "x"),
                      "$now": int(time.time() * 1000)})
    append_run(feature, {"type": "run", "run_id": run_id, "at": now_iso(), "env": env, "scope": scope,
                         "note": a.note or ""})
    cases = list_cases(feature)

    def in_scope(api, kind, path):
        if not scope:
            return True
        cid, api_no = case_id(api, path), api.name.split("-")[0]
        # setups of an api run whenever anything in that api is selected
        return cid in scope or api_no in scope or (kind == "setup" and any(s.split("/")[0] == api_no for s in scope))

    setup_failed = {}
    results = []
    for api, kind, path in cases:
        if not in_scope(api, kind, path):
            continue
        meta, _ = read_doc(path)
        if meta.get("retired"):
            continue
        cid, meta, res = run_scenario(feature, suite, api, kind, path, variables, redactor, missing, a.timeout,
                                      run_id, env, setup_failed.get(api.name))
        if kind == "setup" and res["status"] != "PASS":
            setup_failed.setdefault(api.name, f"setup {cid} {res['status']}")
        captured = meta["last_run"]["captured"]
        all_caps = load_captures(feature)
        all_caps.update(res["captured"])
        save_captures(feature, all_caps)
        append_run(feature, {"type": "result", "run_id": run_id, "id": cid, "kind": kind,
                             "file": str(path.relative_to(feature)), "status": res["status"],
                             "http": meta["last_run"]["http_status"], "ms": meta["last_run"]["duration_ms"],
                             "failed": meta["last_run"]["failed"], "blocked_by": res["blocked_by"],
                             "captured": captured, "at": meta["last_run"]["at"]})
        results.append((cid, kind, res["status"], meta["last_run"], meta.get("title", "")))
        why = res["blocked_by"] or "; ".join(meta["last_run"]["failed"])
        print(f"{ICON[res['status']]} {res['status']:<7} {cid:<8} {kind:<7} {meta.get('title', '')}"
              + (f"  — {why}" if why else ""))
    write_index(feature)
    counts = {}
    for r in results:
        if r[1] != "setup":
            counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"\nrun {run_id}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"  → {feature}/00-index.md")
    if not results:
        print("nothing matched --only " + ",".join(scope))


def cmd_index(a):
    write_index(a.feature)
    print(f"wrote {Path(a.feature) / '00-index.md'}")


def cmd_lint(a):
    feature = Path(a.feature)
    problems = []
    try:
        suite = load_suite(feature)
    except ValueError as e:
        sys.exit(str(e))
    if suite.get("format") != FORMAT:
        problems.append(f"00-suite.md: format must be {FORMAT}")
    for d in feature.iterdir():
        if d.is_dir() and not d.name.startswith(("_", ".")) and not API_RE.match(d.name):
            problems.append(f"{d.name}/: api folders must be named NN-slug (e.g. 01-install-app)")
    apis = suite.get("apis", {})
    for d in sorted(feature.iterdir()):
        if d.is_dir() and API_RE.match(d.name):
            spec = apis.get(d.name)
            if not isinstance(spec, dict) or not spec.get("title") or not spec.get("request"):
                problems.append(f"00-suite.md: apis.{d.name} needs a title and the named request it tests, "
                                f'e.g. {{"title": "{humanize(d.name)}", "request": "<name>"}}')
            elif spec["request"] not in suite.get("requests", {}):
                problems.append(f"00-suite.md: apis.{d.name}.request '{spec['request']}' is not in requests")
    seen = {}
    for api, kind, path in list_cases(feature):
        rel = path.relative_to(feature)
        if not CASE_RE.match(path.name):
            problems.append(f"{rel}: file must be named NN-slug.md (lowercase, hyphens)")
        cid = case_id(api, path)
        if cid in seen:
            problems.append(f"{rel}: number clashes with {seen[cid]} — numbers are unique per api folder")
        seen[cid] = rel
        try:
            meta, _ = read_doc(path)
        except ValueError as e:
            problems.append(str(e))
            continue
        for key in ("title", "what", "request", "expect"):
            if key not in meta:
                problems.append(f"{rel}: missing '{key}'")
        st = meta.get("expect", {}).get("status")
        if st is None:
            problems.append(f"{rel}: expect.status is required")
        else:
            sts = st if isinstance(st, list) else [st]
            if kind in ("success", "setup") and not all(200 <= s < 300 for s in sts):
                problems.append(f"{rel}: in {kind}/ but expects {st} — move it to error/")
            if kind == "error" and not all(s >= 400 for s in sts):
                problems.append(f"{rel}: in error/ but expects {st} — move it to success/")
        steps = meta.get("before", []) + meta.get("verify", [])
        for step in [meta.get("request", {})] + steps:
            if "use" in step and step["use"] not in suite.get("requests", {}):
                problems.append(f"{rel}: unknown named request '{step['use']}'")
        for expect in [meta.get("expect", {})] + [s.get("expect", {}) for s in steps]:
            for asr in expect.get("body", []) + expect.get("headers", []):
                if "jq" not in asr or not any(o in asr for o in OPS):
                    problems.append(f"{rel}: assert {asr} needs 'jq' and one of {', '.join(OPS)}")
    secret_values = [os.environ[e] for e in suite.get("secrets", {}).values() if len(os.environ.get(e, "")) >= 4]
    for f in list(feature.rglob("*.md")) + [feature / "runs.jsonl"]:
        if not f.exists() or "_local" in f.parts:
            continue
        text = f.read_text()
        for pat in LEAK_PATTERNS:
            if re.search(pat, text):
                problems.append(f"{f.relative_to(feature)}: looks like a secret (/{pat}/) — redact it")
        for v in secret_values:
            if v in text:
                problems.append(f"{f.relative_to(feature)}: contains the value of a declared secret")
    if not (feature / ".gitignore").exists() or "_local" not in (feature / ".gitignore").read_text():
        problems.append(".gitignore must ignore _local/")
    for p in problems:
        print("✗ " + p)
    print("lint: OK" if not problems else f"lint: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


SUITE_TEMPLATE = {
    "format": FORMAT,
    "title": "<Feature name — what is being tested>",
    "what": "<1–2 lines: scope of this feature's tests>",
    "links": [],
    "default_env": "local",
    "envs": {"local": {"baseUrl": "http://localhost:8080"}},
    "vars": {"thingId": "<id>"},
    "secrets": {},
    "default_headers": {"Content-Type": "application/json"},
    "redact_keys": [],
    "requests": {
        "getThing": {"method": "GET", "url": "{{baseUrl}}/api/v1/things/:thingId",
                     "path_params": {"thingId": "{{thingId}}"}, "headers": {}}
    },
    "apis": {
        "01-get-thing": {"title": "Get thing", "request": "getThing"}
    },
}

SUITE_BODY = """# {title}

## Scope
- <what is in scope / out of scope>

## Services
- <service> — <base url per env>, branch `<branch>`

## Auth
- <how requests authenticate; secrets are env-var names in `secrets`, exported before running>

## Resetting for a re-run
- <how to bring the system back to the starting state>
"""


def cmd_init(a):
    feature = Path(a.feature)
    feature.mkdir(parents=True, exist_ok=True)
    suite = feature / "00-suite.md"
    if suite.exists():
        print(f"exists: {suite}")
    else:
        write_doc(suite, SUITE_TEMPLATE, SUITE_BODY.format(title=feature.name))
        print(f"created {suite} — fill in envs, vars, secrets, requests")
    gi = feature / ".gitignore"
    if not gi.exists():
        gi.write_text("_local/\n")
    if not (feature / "00-index.md").exists():
        write_index(feature)
    print(f"created {feature / '00-index.md'}")


def cmd_new(a):
    path = Path(a.path)
    if path.suffix != ".md":
        path = path.with_suffix(".md")
    kind = path.parent.name
    if kind not in KINDS:
        sys.exit(f"parent folder must be one of {KINDS}: <feature>/<NN-api>/<{'|'.join(KINDS)}>/<NN-slug>")
    if not API_RE.match(path.parent.parent.name):
        sys.exit("api folder must be named NN-slug, e.g. 01-install-app")
    if not CASE_RE.match(path.name):
        sys.exit("file must be named NN-slug.md (lowercase, hyphens), e.g. 03-rejects-duplicate-install.md")
    if path.exists():
        sys.exit(f"exists: {path}")
    status = 400 if kind == "error" else 200
    body_asserts = ([{"name": "error code", "jq": ".error.code", "eq": "<CODE>"},
                     {"name": "error message", "jq": ".error.message", "contains": "<text>"}]
                    if kind == "error" else [{"name": "<what>", "jq": ".data.<field>", "eq": "<value>"}])
    meta = {
        "title": "<short name>",
        "what": "<1–2 lines: what this proves>",
        "tags": [],
        "request": {"use": "<namedRequest from 00-suite.md>"},
        "expect": {"status": status, "body": body_asserts},
        "capture": {},
        "verify": [],
        "view": "",
        "last_run": {"status": "NOT_RUN"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    api = path.parent.parent
    suite_file = api.parent / "00-suite.md"
    if suite_file.exists():
        smeta, sbody = read_doc(suite_file)
        if api.name not in smeta.get("apis", {}):
            smeta.setdefault("apis", {})[api.name] = {"title": humanize(api.name), "request": "<namedRequest this API folder tests>"}
            write_doc(suite_file, smeta, sbody)
            print(f"registered {api.name} in 00-suite.md apis — set its title and request")
    write_doc(path, meta, render(case_id(api, path), kind, meta, {}, Redactor({}), NOTES_HEADING + "\n\n_None._\n"))
    print(f"created {path}")


# ---------------------------------------------------------------- viewer (read-only; `serve`)
# The viewer never writes to the suite. "Send" fires the request live and returns the result to the browser only.

def find_features(folder):
    folder = Path(folder).resolve()
    if (folder / "00-suite.md").exists():
        return folder.parent, [folder]
    return folder, sorted(p.parent for p in folder.glob("*/00-suite.md"))


def endpoint_of(suite, spec):
    """'METHOD /path' for a request spec (named via `use`, or inline)."""
    named = suite.get("requests", {}).get(spec.get("use"), {})
    method, url = spec.get("method") or named.get("method"), spec.get("url") or named.get("url")
    return (method.upper() + " " + re.sub(r"^\{\{[^}]+\}\}", "", url)) if method and url else ""


def api_info(suite, api_name, cases):
    """(title, endpoint) of an API folder. Declared in 00-suite.md `apis`; otherwise guessed from its test cases."""
    spec = suite.get("apis", {}).get(api_name) or {}
    if isinstance(spec, str):
        spec = {"title": spec}
    endpoint = endpoint_of(suite, {"use": spec["request"]}) if spec.get("request") else ""
    if not endpoint:
        votes = {}
        for kind, _, meta in cases:
            if kind != "setup":
                ep = endpoint_of(suite, meta.get("request", {}))
                if ep:
                    votes[ep] = votes.get(ep, 0) + 1
        endpoint = max(votes, key=votes.get) if votes else ""
    return spec.get("title", ""), endpoint


def humanize(api_name):
    words = api_name.split("-", 1)[-1].replace("-", " ")
    return words[:1].upper() + words[1:]


def tree_data(folder):
    root, features = find_features(folder)
    out, stamp = [], 0.0
    for feature in features:
        try:
            suite = load_suite(feature)
        except (ValueError, SystemExit) as e:
            out.append({"key": feature.name, "title": feature.name, "error": str(e), "apis": []})
            continue
        apis = {}
        for api, kind, path in list_cases(feature):
            stamp = max(stamp, path.stat().st_mtime)
            try:
                meta, _ = read_doc(path)
            except ValueError as e:
                meta = {"title": path.name, "error": str(e), "last_run": {"status": "BROKEN"}}
            apis.setdefault(api.name, []).append((kind, path, meta))
        api_list = []
        for name, cases in apis.items():
            title, endpoint = api_info(suite, name, cases)
            rows = []
            for kind, path, meta in cases:
                lr = meta.get("last_run") or {"status": "NOT_RUN"}
                exp = meta.get("expect", {}).get("status")
                rows.append({"id": case_id(feature / name, path), "file": str(path.relative_to(feature)), "kind": kind,
                             "title": meta.get("title", path.stem), "what": meta.get("what", ""),
                             "status": "RETIRED" if meta.get("retired") else lr.get("status", "NOT_RUN"),
                             "http": lr.get("http_status"), "expected": exp, "at": lr.get("at"),
                             "known_issue": meta.get("known_issue") or None, "error": meta.get("error"),
                             "why": ", ".join(lr.get("failed") or []) or lr.get("blocked_by") or "",
                             "changed": bool(lr.get("definition_hash")) and lr.get("definition_hash") != definition_hash(meta)})
            api_list.append({"name": name, "title": title, "endpoint": endpoint, "cases": rows})
        for extra in ("00-suite.md", "00-index.md", "runs.jsonl"):
            if (feature / extra).exists():
                stamp = max(stamp, (feature / extra).stat().st_mtime)
        _, _, missing = build_vars(feature, suite, suite.get("default_env", "local"))
        out.append({"key": str(feature.relative_to(root)), "title": suite.get("title", feature.name),
                    "what": suite.get("what", ""), "envs": list(suite.get("envs", {})) or ["local"],
                    "default_env": suite.get("default_env", "local"), "missing_secrets": sorted(missing.values()),
                    "runs": read_runs(feature)[-10:][::-1], "apis": api_list,
                    "index_notes": real_notes(feature)})
    return {"root": str(root), "stamp": stamp, "features": out}


def real_notes(feature):
    """Hand-kept part of 00-index.md, or "" when it only holds headings and _placeholder_ lines."""
    index = Path(feature) / "00-index.md"
    if not index.exists() or INDEX_MARKER not in index.read_text():
        return ""
    notes = index.read_text().split(INDEX_MARKER, 1)[1]
    lines = [l.strip() for l in notes.splitlines() if l.strip()]
    if all(l.startswith("#") or re.fullmatch(r"_.*_", l) for l in lines):
        return ""
    return notes


def safe_path(root, feature_key, file=None):
    root = Path(root).resolve()
    feature = (root / feature_key).resolve()
    if root not in feature.parents and feature != root:
        raise ValueError("path outside root")
    if not (feature / "00-suite.md").exists():
        raise ValueError("not a feature folder")
    if file is None:
        return feature, None
    path = (feature / file).resolve()
    if feature not in path.parents or path.suffix != ".md":
        raise ValueError("path outside feature")
    return feature, path


def case_data(root, feature_key, file):
    feature, path = safe_path(root, feature_key, file)
    meta, body = read_doc(path)
    last_run = meta.pop("last_run", None)
    i = body.find("\n" + NOTES_HEADING + "\n")
    notes = body[i + len(NOTES_HEADING) + 2:].strip() if i >= 0 else ""
    api = path.parent.parent
    cid = case_id(api, path)
    history = []
    p = feature / "runs.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("type") == "result" and rec.get("id") == cid:
                    history.append(rec)
    suite = load_suite(feature)
    if last_run:
        fill_trimmed_from_local(feature, suite, api, cid, last_run)
    return {"id": cid, "kind": path.parent.name, "file": file, "definition": meta, "last_run": last_run,
            "notes": "" if notes == "_None._" else notes, "history": history[::-1][:30],
            "changed": bool(last_run and last_run.get("definition_hash")) and last_run["definition_hash"] != definition_hash(meta),
            "has_full_response": (local_dir(feature) / "responses" / api.name /
                                  f"{cid.split('/')[1]}.main.json").exists(),
            "suite_requests": suite.get("requests", {})}


def fill_trimmed_from_local(feature, suite, api, cid, last_run):
    """Older runs saved only 80 lines. If the raw response is still in _local/, show it in full (redacted)."""
    _, redactor, _ = build_vars(feature, suite, suite.get("default_env", "local"))
    folder = local_dir(feature) / "responses" / api.name
    num = cid.split("/")[1]
    steps = [("main", last_run.get("response"))]
    steps += [(f"before-{i}", s.get("response")) for i, s in enumerate(last_run.get("before") or [], 1)]
    steps += [(f"verify-{i}", s.get("response")) for i, s in enumerate(last_run.get("verify") or [], 1)]
    for step, resp in steps:
        f = folder / f"{num}.{step}.json"
        if not resp or not resp.get("trimmed") or not f.exists():
            continue
        text = f.read_text()
        try:
            resp["body"] = redactor.obj(json.loads(text))
        except json.JSONDecodeError:
            resp["body"] = redactor.text(text)
        resp["trimmed"] = None


def full_response(root, feature_key, file):
    feature, path = safe_path(root, feature_key, file)
    suite = load_suite(feature)
    _, redactor, _ = build_vars(feature, suite, suite.get("default_env", "local"))
    num = case_id(path.parent.parent, path).split("/")[1]
    f = local_dir(feature) / "responses" / path.parent.parent.name / f"{num}.main.json"
    text = f.read_text()
    try:
        return {"body": redactor.obj(json.loads(text))}
    except json.JSONDecodeError:
        return {"body": redactor.text(text)}


def fire(root, feature_key, file, env, timeout=30):
    """Send the scenario's main request now and evaluate its expectations. Writes nothing."""
    feature, path = safe_path(root, feature_key, file)
    suite = load_suite(feature)
    meta, _ = read_doc(path)
    env = env or suite.get("default_env", "local")
    variables, redactor, missing = build_vars(feature, suite, env)
    variables.update({"$runId": "live-" + dt.datetime.now().strftime("%H%M%S"),
                      "$runTag": format(int(time.time() * 1000) % 36 ** 6, "x"), "$now": int(time.time() * 1000)})
    try:
        req = resolve_request(meta["request"], suite, variables)
    except Unresolved as e:
        name = str(e)
        return {"error": f"missing env var {missing[name]} — export it in the shell that runs `serve`"
                if name in missing else f"unknown var {{{{{name}}}}} (captured by an earlier scenario? run it via Claude first)"}
    except ValueError as e:
        return {"error": str(e)}
    try:
        call = send(req, timeout)
    except ConnectionError as e:
        return {"error": f"no HTTP response: {e}", "request": request_data(req, redactor)}
    checks = run_expect("", meta.get("expect", {}), call, variables)
    return {"env": env, "status": "PASS" if all(c["ok"] for c in checks) else "FAIL",
            "checks": [{**c, "actual": redactor.text(c["actual"])} for c in checks],
            "request": request_data(req, redactor), "response": response_data(call, None, redactor, max_lines=5000),
            "at": now_iso()}


def cmd_serve(a):
    import http.server
    import threading
    import webbrowser
    saved_root = load_config().get("root")
    folder = Path(a.folder or saved_root or ".").expanduser().resolve()
    root, features = find_features(folder)
    if not features:
        sys.exit(f"no feature folders (with 00-suite.md) under {folder}")
    html_file = Path(__file__).parent / "viewer.html"
    host = "127.0.0.1"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def same_origin(self):
            allowed = {f"{host}:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in allowed and (origin is None or origin.split("//", 1)[-1] in allowed)

        def do_GET(self):
            if not self.same_origin():
                return self.reply(403, {"error": "forbidden"})
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path == "/":
                    return self.reply(200, html_file.read_bytes(), "text/html")
                if u.path == "/api/tree":
                    return self.reply(200, tree_data(folder))
                if u.path == "/api/case":
                    return self.reply(200, case_data(root, q["feature"], q["file"]))
                if u.path == "/api/full-response":
                    return self.reply(200, full_response(root, q["feature"], q["file"]))
                return self.reply(404, {"error": "not found"})
            except (ValueError, KeyError, OSError) as e:
                return self.reply(400, {"error": str(e)})

        def do_POST(self):
            if not self.same_origin() or self.headers.get("X-Post-Master") != "1":
                return self.reply(403, {"error": "forbidden"})
            if self.path != "/api/fire":
                return self.reply(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                return self.reply(200, fire(root, body["feature"], body["file"], body.get("env"), a.timeout))
            except (ValueError, KeyError, OSError) as e:
                return self.reply(400, {"error": str(e)})

    server = None
    for port in range(a.port, a.port + 20):
        try:
            server = http.server.ThreadingHTTPServer((host, port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"no free port in {a.port}–{a.port + 19}")
    url = f"http://{host}:{server.server_port}/"
    print(f"post-master viewer: {url}  (folder: {folder}) — read-only; Ctrl+C to stop")
    if not a.no_open:
        def open_browser():
            if sys.platform == "darwin" and subprocess.run(["open", "-a", "Google Chrome", url],
                                                           capture_output=True).returncode == 0:
                return
            webbrowser.open(url)
        threading.Timer(0.4, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def cmd_root(a):
    cfg = load_config()
    if a.set:
        cfg["root"] = str(Path(a.set).expanduser().resolve())
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        print(f"root set: {cfg['root']}  (saved in {CONFIG_FILE})")
    elif cfg.get("root"):
        print(cfg["root"])
    else:
        print("NOT SET — ask the user where to save scenarios, then: post-master root --set <path>")
        sys.exit(2)


def main():
    p = argparse.ArgumentParser(prog="post-master", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("root"); s.add_argument("--set"); s.set_defaults(fn=cmd_root)
    s = sub.add_parser("init"); s.add_argument("feature"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("new"); s.add_argument("path"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("run"); s.add_argument("feature"); s.add_argument("--env")
    s.add_argument("--only", help="comma list of api numbers (02) or ids (02/05)")
    s.add_argument("--timeout", type=float, default=30); s.add_argument("--note")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("index"); s.add_argument("feature"); s.set_defaults(fn=cmd_index)
    s = sub.add_parser("lint"); s.add_argument("feature"); s.set_defaults(fn=cmd_lint)
    s = sub.add_parser("serve", help="read-only browser viewer for a root or feature folder")
    s.add_argument("folder", nargs="?", help="root or feature folder (default: saved root)")
    s.add_argument("--port", type=int, default=4777); s.add_argument("--timeout", type=float, default=30)
    s.add_argument("--no-open", action="store_true"); s.set_defaults(fn=cmd_serve)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

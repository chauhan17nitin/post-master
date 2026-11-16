"""Tests for the post-master runner. Standard library only.

Run from the repo root:   python3 -m unittest discover -s tests -v

Tests that evaluate asserts or run scenarios need the `jq` CLI and are skipped without it.
Nothing here touches the network or your real ~/.claude config.
"""
import argparse
import contextlib
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "api-testing" / "scripts"))

import post_master as pm  # noqa: E402

HAS_JQ = shutil.which("jq") is not None
needs_jq = unittest.skipUnless(HAS_JQ, "needs the jq CLI")


def quiet(fn, *args):
    """Call a command function, returning (exit code or None, printed text)."""
    out = io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            fn(*args)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


class TempDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()


def make_feature(root, name="shop"):
    """A lint-clean feature with one success case, built with the real init/new commands."""
    feature = root / name
    quiet(pm.cmd_init, argparse.Namespace(feature=str(feature)))
    case = feature / "01-get-thing" / "success" / "01-found.md"
    quiet(pm.cmd_new, argparse.Namespace(path=str(case)))
    edit(case, title="Thing found", what="An existing thing is returned.", request={"use": "getThing"},
         expect={"status": 200, "body": [{"name": "name", "jq": ".name", "eq": "widget"}]})
    return feature, case


def edit(path, **changes):
    meta, body = pm.read_doc(path)
    meta.update(changes)
    pm.write_doc(path, meta, body)


# ------------------------------------------------------------------ variables

class SubstituteTest(unittest.TestCase):
    def test_whole_string_keeps_the_type(self):
        self.assertEqual(pm.substitute("{{n}}", {"n": 5}), 5)
        self.assertIs(pm.substitute("{{flag}}", {"flag": True}), True)
        self.assertEqual(pm.substitute("{{obj}}", {"obj": {"a": 1}}), {"a": 1})

    def test_inside_a_string_becomes_text(self):
        self.assertEqual(pm.substitute("id-{{n}}", {"n": 5}), "id-5")
        self.assertEqual(pm.substitute("on={{flag}}", {"flag": True}), "on=true")

    def test_vars_may_reference_other_vars(self):
        self.assertEqual(pm.substitute("{{name}}", {"name": "widget-{{tag}}", "tag": "ab12"}), "widget-ab12")

    def test_run_vars_start_with_a_dollar(self):
        self.assertEqual(pm.substitute("w-{{$runTag}}", {"$runTag": "ab12"}), "w-ab12")

    def test_lists_and_dicts_are_walked(self):
        got = pm.substitute({"a": ["{{x}}", {"b": "{{x}}!"}], "n": 1}, {"x": "v"})
        self.assertEqual(got, {"a": ["v", {"b": "v!"}], "n": 1})

    def test_unknown_var_names_itself(self):
        with self.assertRaises(pm.Unresolved) as cm:
            pm.substitute("{{nope}}", {})
        self.assertEqual(str(cm.exception), "nope")

    def test_a_loop_is_an_error_not_a_hang(self):
        with self.assertRaises(ValueError):
            pm.substitute("{{a}}", {"a": "{{a}}"})


class BuildVarsTest(TempDir):
    SUITE = {"vars": {"baseUrl": "from-vars", "thingId": 1},
             "envs": {"local": {"baseUrl": "from-env"}},
             "secrets": {"apiKey": "PM_TEST_API_KEY"}}

    def test_env_overrides_vars(self):
        variables, _, _ = pm.build_vars(self.tmp, self.SUITE, "local")
        self.assertEqual(variables["baseUrl"], "from-env")
        self.assertEqual(variables["thingId"], 1)

    def test_captures_override_env(self):
        (self.tmp / "_local").mkdir()
        (self.tmp / "_local" / "vars.json").write_text(json.dumps({"baseUrl": "from-capture", "orderId": 9}))
        variables, _, _ = pm.build_vars(self.tmp, self.SUITE, "local")
        self.assertEqual(variables["baseUrl"], "from-capture")
        self.assertEqual(variables["orderId"], 9)

    def test_secret_comes_from_the_environment_and_is_redacted(self):
        with mock.patch.dict(os.environ, {"PM_TEST_API_KEY": "value-of-the-key"}):
            variables, redactor, missing = pm.build_vars(self.tmp, self.SUITE, "local")
        self.assertEqual(variables["apiKey"], "value-of-the-key")
        self.assertEqual(missing, {})
        self.assertEqual(redactor.text("key=value-of-the-key"), "key=***")
        self.assertEqual(redactor.text("key=value-of-the-key", for_curl=True), "key=${PM_TEST_API_KEY}")

    def test_missing_secret_is_reported_by_env_var_name(self):
        env = {k: v for k, v in os.environ.items() if k != "PM_TEST_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            variables, _, missing = pm.build_vars(self.tmp, self.SUITE, "local")
        self.assertNotIn("apiKey", variables)
        self.assertEqual(missing, {"apiKey": "PM_TEST_API_KEY"})


# ------------------------------------------------------------------ redaction

class RedactorTest(unittest.TestCase):
    def test_token_like_keys_are_masked(self):
        r = pm.Redactor({})
        got = r.obj({"Authorization": "abc", "X-Api-Key": "k", "access_token": "t", "name": "widget"})
        self.assertEqual(got, {"Authorization": "***", "X-Api-Key": "***", "access_token": "***", "name": "widget"})

    def test_empty_values_are_left_alone(self):
        self.assertEqual(pm.Redactor({}).obj({"token": "", "cookie": None}), {"token": "", "cookie": None})

    def test_suite_can_add_keys(self):
        r = pm.Redactor({"redact_keys": ["origin"]})
        self.assertEqual(r.obj({"origin": "10.0.0.1", "url": "u"}), {"origin": "***", "url": "u"})

    def test_nested_structures(self):
        got = pm.Redactor({}).obj({"data": [{"token": "t", "id": 1}]})
        self.assertEqual(got, {"data": [{"token": "***", "id": 1}]})

    def test_known_secret_values_are_masked_anywhere(self):
        r = pm.Redactor({})
        r.add("s3cr3t-value")
        self.assertEqual(r.obj({"note": "sent s3cr3t-value ok"}), {"note": "sent *** ok"})

    def test_very_short_values_are_not_treated_as_secrets(self):
        r = pm.Redactor({})
        r.add("abc")
        self.assertEqual(r.text("abc"), "abc")

    def test_bearer_and_jwt_patterns(self):
        r = pm.Redactor({})
        self.assertEqual(r.text("Authorization: Bearer abcdefghijklmnop"), "Authorization: ***")
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0"
        self.assertNotIn(jwt, r.text("token " + jwt))


# ------------------------------------------------------------------ requests

class RequestTest(unittest.TestCase):
    def suite(self):
        return {"default_headers": {"Content-Type": "application/json", "X-Trace": "1"},
                "requests": {"getThing": {"method": "GET", "url": "{{base}}/things/:id",
                                          "path_params": {"id": "{{thingId}}"},
                                          "headers": {"Authorization": "Bearer {{token}}"}}}}

    def test_named_request_gets_default_headers(self):
        req = pm.merge_request({"use": "getThing"}, self.suite())
        self.assertEqual(req["headers"], {"Content-Type": "application/json", "X-Trace": "1",
                                          "Authorization": "Bearer {{token}}"})
        self.assertEqual(req["body_type"], "json")
        self.assertNotIn("use", req)

    def test_null_removes_a_header(self):
        req = pm.merge_request({"use": "getThing", "headers": {"Authorization": None, "X-Trace": None}}, self.suite())
        self.assertEqual(req["headers"], {"Content-Type": "application/json"})

    def test_overrides_do_not_change_the_suite(self):
        suite = self.suite()
        pm.merge_request({"use": "getThing", "headers": {"Authorization": None}, "path_params": {"id": "9"}}, suite)
        self.assertEqual(suite, self.suite())

    def test_step_keys_are_not_sent(self):
        req = pm.merge_request({"use": "getThing", "name": "n", "expect": {"status": 200}, "capture": {"x": ".id"}},
                               self.suite())
        for key in ("name", "expect", "capture"):
            self.assertNotIn(key, req)

    def test_unknown_named_request(self):
        with self.assertRaises(ValueError):
            pm.merge_request({"use": "nope"}, self.suite())

    def test_url_is_built_from_path_params_and_query(self):
        req = pm.resolve_request({"use": "getThing", "query": {"page": 2, "active": True}}, self.suite(),
                                 {"base": "http://h", "thingId": "a b", "token": "t"})
        self.assertEqual(req["full_url"], "http://h/things/a%20b?page=2&active=true")
        self.assertEqual(req["headers"]["Authorization"], "Bearer t")

    def test_path_param_only_replaces_a_whole_segment(self):
        req = pm.resolve_request({"method": "GET", "url": "http://h/x/:id/:idx", "path_params": {"id": "1"}}, {}, {})
        self.assertEqual(req["full_url"], "http://h/x/1/:idx")

    def test_body_encoding(self):
        self.assertIsNone(pm.encode_body({"body_type": "json"}))
        self.assertEqual(json.loads(pm.encode_body({"body_type": "json", "body": {"a": 1}})), {"a": 1})
        self.assertEqual(pm.encode_body({"body_type": "form", "body": {"a": 1, "b": 2}}), b"a=1&b=2")
        self.assertEqual(pm.encode_body({"body_type": "raw", "body": "hello"}), b"hello")


# ------------------------------------------------------------------ asserts

class StatusTest(unittest.TestCase):
    def test_single_and_list(self):
        self.assertEqual(pm.check_status(200, 200), (True, "200"))
        self.assertEqual(pm.check_status([200, 201], 404), (False, "200 or 201"))
        self.assertTrue(pm.check_status([200, 201], 201)[0])


@needs_jq
class EvaluateTest(unittest.TestCase):
    def ok(self, assertion, data, variables=None):
        return pm.evaluate(assertion, data, variables or {})[0]

    def test_eq(self):
        self.assertTrue(self.ok({"jq": ".a", "eq": 1}, {"a": 1}))
        self.assertFalse(self.ok({"jq": ".a", "eq": 2}, {"a": 1}))

    def test_eq_does_not_confuse_true_with_1(self):
        self.assertFalse(self.ok({"jq": ".a", "eq": True}, {"a": 1}))
        self.assertTrue(self.ok({"jq": ".a", "eq": True}, {"a": True}))

    def test_eq_needs_exactly_one_value(self):
        self.assertFalse(self.ok({"jq": ".a[]", "eq": 1}, {"a": [1, 1]}))

    def test_ne(self):
        self.assertTrue(self.ok({"jq": ".a", "ne": 2}, {"a": 1}))
        self.assertFalse(self.ok({"jq": ".a", "ne": 1}, {"a": 1}))

    def test_contains_and_matches(self):
        data = {"msg": "unpaid invoice on account"}
        self.assertTrue(self.ok({"jq": ".msg", "contains": "unpaid invoice"}, data))
        self.assertFalse(self.ok({"jq": ".msg", "contains": "refund"}, data))
        self.assertTrue(self.ok({"jq": ".msg", "matches": "^unpaid .* account$"}, data))
        self.assertFalse(self.ok({"jq": ".msg", "matches": "^invoice"}, data))

    def test_includes_on_a_list_or_a_stream(self):
        data = {"tags": ["a", "b", "c"]}
        self.assertTrue(self.ok({"jq": ".tags", "includes": ["a", "c"]}, data))
        self.assertTrue(self.ok({"jq": ".tags[]", "includes": ["b"]}, data))
        self.assertFalse(self.ok({"jq": ".tags", "includes": ["z"]}, data))

    def test_count(self):
        self.assertTrue(self.ok({"jq": ".items[]", "count": 3}, {"items": [1, 2, 3]}))
        self.assertFalse(self.ok({"jq": ".items[]", "count": 2}, {"items": [1, 2, 3]}))

    def test_exists_and_absent(self):
        data = {"a": 1, "b": None}
        self.assertTrue(self.ok({"jq": ".a", "exists": True}, data))
        self.assertFalse(self.ok({"jq": ".b", "exists": True}, data))
        self.assertFalse(self.ok({"jq": ".missing", "exists": True}, data))
        self.assertTrue(self.ok({"jq": ".b", "absent": True}, data))
        self.assertTrue(self.ok({"jq": ".missing", "absent": True}, data))
        self.assertFalse(self.ok({"jq": ".a", "absent": True}, data))

    def test_expected_value_can_use_a_var(self):
        self.assertTrue(self.ok({"jq": ".name", "eq": "{{thingName}}"}, {"name": "widget"}, {"thingName": "widget"}))

    def test_jq_filter_can_use_a_var(self):
        self.assertTrue(self.ok({"jq": ".id == $thingId", "eq": True}, {"id": 7}, {"thingId": 7, "$runTag": "x"}))

    def test_problems_fail_with_a_reason_instead_of_crashing(self):
        ok, _, actual = pm.evaluate({"jq": ".a"}, {"a": 1}, {})
        self.assertFalse(ok)
        self.assertIn("no operator", actual)
        ok, _, actual = pm.evaluate({"jq": ".[", "eq": 1}, {"a": 1}, {})
        self.assertFalse(ok)
        self.assertTrue(actual.startswith("jq error"))
        ok, _, actual = pm.evaluate({"jq": ".a", "eq": "{{nope}}"}, {"a": 1}, {})
        self.assertFalse(ok)
        self.assertIn("nope", actual)

    def test_status_headers_and_body_checks_together(self):
        call = {"status": 401, "headers": {"www-authenticate": "Bearer"}, "json": {"error": {"code": "E1"}}}
        checks = pm.run_expect("", {"status": 401,
                                    "headers": [{"name": "challenge", "jq": '.["www-authenticate"]', "eq": "Bearer"}],
                                    "body": [{"name": "code", "jq": ".error.code", "eq": "E2"}]}, call, {})
        self.assertEqual([(c["name"], c["ok"]) for c in checks],
                         [("HTTP status", True), ("header: challenge", True), ("code", False)])


# ------------------------------------------------------------------ files

class DocTest(TempDir):
    def test_round_trip_with_last_run(self):
        meta = {"title": "Näme", "expect": {"status": 200}, "last_run": {"status": "NOT_RUN"}}
        pm.write_doc(self.tmp / "c.md", meta, "# report\n\n## Notes\n\nmine\n")
        got, body = pm.read_doc(self.tmp / "c.md")
        self.assertEqual(got, meta)
        self.assertEqual(body, "# report\n\n## Notes\n\nmine\n")

    def test_round_trip_without_last_run(self):
        pm.write_doc(self.tmp / "s.md", {"format": 1}, "# suite\n")
        got, _ = pm.read_doc(self.tmp / "s.md")
        self.assertEqual(got, {"format": 1})

    def test_missing_definition_is_a_clear_error(self):
        (self.tmp / "x.md").write_text("# just markdown\n")
        with self.assertRaises(ValueError):
            pm.read_doc(self.tmp / "x.md")

    def test_broken_json_is_a_clear_error(self):
        (self.tmp / "x.md").write_text(pm.DEF_MARKER + "\n## Definition\n\n```json\n{not json}\n```\n")
        with self.assertRaises(ValueError):
            pm.read_doc(self.tmp / "x.md")

    def test_hash_ignores_last_run_and_key_order(self):
        a = {"title": "t", "expect": {"status": 200}, "last_run": {"status": "PASS"}}
        b = {"expect": {"status": 200}, "title": "t"}
        self.assertEqual(pm.definition_hash(a), pm.definition_hash(b))
        self.assertNotEqual(pm.definition_hash(a), pm.definition_hash({**b, "title": "other"}))

    def test_notes_survive_a_rewrite(self):
        self.assertEqual(pm.keep_notes("# r\n\n## Notes\n\nmine\n"), "## Notes\n\nmine\n")
        self.assertEqual(pm.keep_notes("# r\n"), "## Notes\n\n_None._\n")


class LayoutTest(TempDir):
    def test_case_numbers_and_ids(self):
        self.assertEqual(pm.case_key("03-a.md"), (3, ""))
        self.assertEqual(pm.case_key("05b-x.md"), (5, "b"))
        names = ["06-c.md", "05b-b.md", "05-a.md"]
        self.assertEqual(sorted(names, key=pm.case_key), ["05-a.md", "05b-b.md", "06-c.md"])
        self.assertEqual(pm.case_id(Path("01-install-app"), Path("05b-x.md")), "01/05b")

    def test_run_order_is_api_number_then_case_number(self):
        for rel in ("02-b/success/01-x.md", "01-a/error/02-y.md", "01-a/success/01-z.md", "10-c/setup/01-s.md",
                    "_local/success/01-ignored.md", "notes/success/01-ignored.md"):
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text("")
        got = [str(p.relative_to(self.tmp)) for _, _, p in pm.list_cases(self.tmp)]
        self.assertEqual(got, ["01-a/success/01-z.md", "01-a/error/02-y.md", "02-b/success/01-x.md",
                               "10-c/setup/01-s.md"])

    def test_find_features_from_a_root_or_a_feature(self):
        for name in ("b-feature", "a-feature"):
            (self.tmp / name).mkdir()
            (self.tmp / name / "00-suite.md").write_text("")
        (self.tmp / "not-a-feature").mkdir()
        self.assertEqual(pm.find_features(self.tmp), (self.tmp, [self.tmp / "a-feature", self.tmp / "b-feature"]))
        self.assertEqual(pm.find_features(self.tmp / "a-feature"), (self.tmp, [self.tmp / "a-feature"]))
        self.assertEqual(pm.find_features(self.tmp / "not-a-feature")[1], [])

    def test_viewer_cannot_read_outside_the_folder(self):
        feature = self.tmp / "shop"
        (feature / "01-a" / "success").mkdir(parents=True)
        (feature / "00-suite.md").write_text("")
        (feature / "01-a" / "success" / "01-ok.md").write_text("")
        (self.tmp / "secret.md").write_text("")
        self.assertEqual(pm.safe_path(self.tmp, "shop", "01-a/success/01-ok.md"),
                         (feature, feature / "01-a" / "success" / "01-ok.md"))
        for key, file in (("..", None), ("shop", "../secret.md"), ("shop", "00-suite.txt"), ("missing", None)):
            with self.assertRaises(ValueError, msg=f"{key} {file}"):
                pm.safe_path(self.tmp, key, file)


# ------------------------------------------------------------------ lint

class LintTest(TempDir):
    def lint(self, feature):
        return quiet(pm.cmd_lint, argparse.Namespace(feature=str(feature)))

    def test_a_fresh_filled_in_feature_is_clean(self):
        feature, _ = make_feature(self.tmp)
        code, out = self.lint(feature)
        self.assertEqual(code, 0, out)
        self.assertIn("lint: OK", out)

    def test_success_folder_must_expect_2xx(self):
        feature, case = make_feature(self.tmp)
        edit(case, expect={"status": 404, "body": []})
        code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("move it to error/", out)

    def test_unknown_named_request(self):
        feature, case = make_feature(self.tmp)
        edit(case, request={"use": "nope"})
        code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("unknown named request 'nope'", out)

    def test_assert_needs_an_operator(self):
        feature, case = make_feature(self.tmp)
        edit(case, expect={"status": 200, "body": [{"jq": ".name"}]})
        code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("needs 'jq' and one of", out)

    def test_number_clash_across_success_and_error(self):
        feature, _ = make_feature(self.tmp)
        quiet(pm.cmd_new, argparse.Namespace(path=str(feature / "01-get-thing" / "error" / "01-missing.md")))
        code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("number clashes", out)

    def test_leaked_token_is_caught(self):
        feature, case = make_feature(self.tmp)
        case.write_text(case.read_text().replace("_None._", "Sent with Bearer abcdefghijklmnopqrstuvwx"))
        code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("looks like a secret", out)

    def test_leaked_secret_value_is_caught(self):
        feature, case = make_feature(self.tmp)
        edit(feature / "00-suite.md", secrets={"apiKey": "PM_TEST_API_KEY"})
        case.write_text(case.read_text().replace("_None._", "the key is value-of-the-key"))
        with mock.patch.dict(os.environ, {"PM_TEST_API_KEY": "value-of-the-key"}):
            code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("contains the value of a declared secret", out)

    def test_api_folder_must_be_registered_in_the_suite(self):
        feature, _ = make_feature(self.tmp)
        (feature / "02-delete-thing").mkdir()
        code, out = self.lint(feature)
        self.assertEqual(code, 1)
        self.assertIn("apis.02-delete-thing", out)

    def test_shipped_example_is_clean(self):
        code, out = self.lint(REPO / "examples" / "httpbin")
        self.assertEqual(code, 0, out)


# ------------------------------------------------------------------ viewer data and config

class ViewerDataTest(unittest.TestCase):
    def test_tree_of_the_shipped_example(self):
        tree = pm.tree_data(REPO / "examples")
        self.assertEqual([f["key"] for f in tree["features"]], ["httpbin"])
        apis = tree["features"][0]["apis"]
        self.assertEqual([(a["name"], a["title"], a["endpoint"]) for a in apis],
                         [("01-echo", "Echo request", "POST /anything"),
                          ("02-status-codes", "Return a status code", "GET /status/:code"),
                          ("03-token-check", "Check bearer token", "GET /bearer")])
        self.assertEqual(sum(len(a["cases"]) for a in apis), 7)
        self.assertEqual([c["id"] for c in apis[1]["cases"]], ["02/01", "02/02", "02/03"])


class ConfigTest(TempDir):
    def setUp(self):
        super().setUp()
        for name, file in (("CONFIG_FILE", "post-master.json"), ("OLD_CONFIG_FILE", "api-testing.json")):
            patcher = mock.patch.object(pm, name, self.tmp / "cfg" / file)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_no_config_is_empty(self):
        self.assertEqual(pm.load_config(), {})
        self.assertEqual(pm.recent_folders(), [])

    def test_old_config_name_is_still_read(self):
        pm.OLD_CONFIG_FILE.parent.mkdir(parents=True)
        pm.OLD_CONFIG_FILE.write_text(json.dumps({"root": "/old"}))
        self.assertEqual(pm.load_config(), {"root": "/old"})
        pm.CONFIG_FILE.write_text(json.dumps({"root": "/new"}))
        self.assertEqual(pm.load_config(), {"root": "/new"})

    def test_recent_folders_newest_first_without_repeats(self):
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir(), b.mkdir()
        pm.remember_folder(a)
        pm.remember_folder(b)
        pm.remember_folder(a)
        self.assertEqual(pm.recent_folders(), [str(a), str(b)])

    def test_recent_folders_keep_the_saved_root_and_drop_deleted_ones(self):
        pm.CONFIG_FILE.parent.mkdir(parents=True)
        pm.CONFIG_FILE.write_text(json.dumps({"root": "/keep-me"}))
        gone, here = self.tmp / "gone", self.tmp / "here"
        gone.mkdir(), here.mkdir()
        pm.remember_folder(gone)
        pm.remember_folder(here)
        gone.rmdir()
        self.assertEqual(pm.recent_folders(), [str(here)])
        self.assertEqual(pm.load_config()["root"], "/keep-me")

    def test_recent_list_is_capped(self):
        for i in range(pm.MAX_RECENT + 3):
            folder = self.tmp / f"f{i}"
            folder.mkdir()
            pm.remember_folder(folder)
        recent = pm.recent_folders()
        self.assertEqual(len(recent), pm.MAX_RECENT)
        self.assertEqual(recent[0], str(self.tmp / f"f{pm.MAX_RECENT + 2}"))


# ------------------------------------------------------------------ end to end, against a local server

class FakeApi(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/api/v1/things/7":
            code, body = 200, {"id": "7", "name": "widget", "access_token": "s3cr3t-token-value"}
        else:
            code, body = 404, {"error": {"code": "NOT_FOUND", "message": "no such thing"}}
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@needs_jq
class RunTest(TempDir):
    def setUp(self):
        super().setUp()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.feature, self.found = make_feature(self.tmp)
        edit(self.feature / "00-suite.md", vars={"thingId": "7"},
             envs={"local": {"baseUrl": f"http://127.0.0.1:{self.server.server_port}"}})

    def new_case(self, kind, name, **definition):
        case = self.feature / "01-get-thing" / kind / f"{name}.md"
        quiet(pm.cmd_new, argparse.Namespace(path=str(case)))
        edit(case, **definition)
        return case

    def run_all(self):
        return quiet(pm.cmd_run, argparse.Namespace(feature=str(self.feature), env=None, only=None, timeout=5,
                                                    note=None))

    def test_pass_fail_and_expected_error(self):
        wrong = self.new_case("success", "02-wrong-name", title="Wrong name", what="Deliberately wrong.",
                              request={"use": "getThing"},
                              expect={"status": 200, "body": [{"name": "name", "jq": ".name", "eq": "gadget"}]})
        missing = self.new_case("error", "03-not-found", title="Unknown id rejected", what="404 for an unknown id.",
                                request={"use": "getThing", "path_params": {"thingId": "nope"}},
                                expect={"status": 404, "body": [{"name": "code", "jq": ".error.code", "eq": "NOT_FOUND"}]})
        _, out = self.run_all()
        runs = {p.name: pm.read_doc(p)[0]["last_run"] for p in (self.found, wrong, missing)}
        self.assertEqual({k: v["status"] for k, v in runs.items()},
                         {"01-found.md": "PASS", "02-wrong-name.md": "FAIL", "03-not-found.md": "PASS"}, out)
        self.assertEqual(runs["02-wrong-name.md"]["failed"], ["name"])
        self.assertEqual(runs["03-not-found.md"]["http_status"], 404)
        self.assertTrue((self.feature / "00-index.md").exists())
        self.assertEqual(len(pm.read_runs(self.feature)), 1)

    def test_token_in_the_response_never_reaches_the_report(self):
        self.run_all()
        self.assertNotIn("s3cr3t-token-value", self.found.read_text())
        self.assertEqual(pm.read_doc(self.found)[0]["last_run"]["response"]["body"]["access_token"], "***")

    def test_unreachable_service_is_blocked_not_failed(self):
        edit(self.feature / "00-suite.md", envs={"local": {"baseUrl": "http://127.0.0.1:1"}})
        self.run_all()
        last_run = pm.read_doc(self.found)[0]["last_run"]
        self.assertEqual(last_run["status"], "BLOCKED")
        self.assertIn("no HTTP response", last_run["blocked_by"])

    def test_notes_survive_a_run(self):
        self.found.write_text(self.found.read_text().replace("_None._", "Checked by hand on staging."))
        self.run_all()
        self.assertIn("Checked by hand on staging.", self.found.read_text())


if __name__ == "__main__":
    unittest.main()

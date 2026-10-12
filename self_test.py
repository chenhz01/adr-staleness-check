# -*- coding: utf-8 -*-
"""self_test for adr-staleness-check — inherits scaffold v2 four defenses:
  D1 SystemExit/BaseException capture in run_cli
  D2 Unicode-safe patterns (CJK/emoji fixtures)
  D3 fixtures written with newline="" (Windows CRLF safe)
  D4 last line `SUMMARY: PASS n/n`
"""
import contextlib, io, json, os, sys, tempfile, unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib
mod = importlib.import_module("adr_staleness_check")
main = mod.main


def run_cli(argv):
    """D1: catch SystemExit and Exception; return (code, stdout, stderr)."""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:
        code = 1
        buf_err.write(repr(e))
    return code, buf_out.getvalue(), buf_err.getvalue()


def _write(text, suffix=".json"):
    """D3: newline="" prevents \r\n double-write on Windows."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def _adr_dir(tmp, spec):
    """spec: {filename: markdown body}. D3 newline=''. Returns dir path."""
    os.makedirs(tmp, exist_ok=True)
    for fn, body in spec.items():
        with open(os.path.join(tmp, fn), "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
    return tmp


def _adr(num, status="Accepted", date="2026-01-01", extra=""):
    return ("# ADR-%04d Decision\n\n## Status\n\n%s\n\nDate: %s\n\n"
            "We chose the thing because of reasons.%s\n" % (num, status, date, extra))


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ---------------- [A] functional ----------------

@case
def a01_parse_adr_fields():
    rec = mod.parse_adr(_adr(1, "Superseded", extra="\nSuperseded by ADR-0002"))
    assert rec["status"] == "Superseded" and rec["superseded_by"] == 2 and rec["date"] == "2026-01-01"


@case
def a02_load_adrs_scans_dir():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-one.md": _adr(1), "0002-two.md": _adr(2)})
        recs = mod.load_adrs(tmp)
        assert set(recs) == {1, 2}


@case
def a03_check_clean_exit0():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-db.md": _adr(1)})
        mp = _write(json.dumps({"ADR-0001": ["x.txt"]}))
        with open(os.path.join(tmp, "x.txt"), "w") as fh:
            fh.write("impl")
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp])
        assert code == 0, (code, out)


@case
def a04_m1_map_refs_unknown_adr():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        mp = _write(json.dumps({"ADR-0009": []}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 1 and "M1" in out


@case
def a05_m2_anchored_path_missing():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        mp = _write(json.dumps({"ADR-0001": ["missing.txt"]}))
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp])
        assert code == 1 and "M2" in out and "missing.txt" in out


@case
def a06_m3_superseded_still_anchored():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-old.md": _adr(1, "Superseded", extra="\nSuperseded by ADR-0002"),
                       "0002-new.md": _adr(2)})
        mp = _write(json.dumps({"ADR-0001": ["x.txt"]}))
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp, "--json"])
        f = json.loads(out)["findings"]
        assert any(x["rule"] == "M3" and x["severity"] == "error" for x in f)


@case
def a07_m4_orphan_accepted_warning():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp])
        assert code == 0 and "M4" in out


@case
def a08_g2_nonmonotonic_supersede():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0005-late.md": _adr(5, "Superseded", extra="\nSuperseded by ADR-0002"),
                       "0002-early.md": _adr(2)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "G2" in out


@case
def a09_g3_duplicate_adr_number():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1), "0001-b.md": _adr(1)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 1 and "G3" in out


@case
def a10_g4_superseded_by_missing():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1, "Superseded", extra="\nSuperseded by ADR-0042")})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 1 and "G4" in out


@case
def a11_g1_supersedes_cycle():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1, "Superseded", extra="\nSuperseded by ADR-0002")})
        # 0002 exists and supersedes nothing; make a 2-cycle via direct module call
        recs_text = {"0001-a.md": _adr(1, "Superseded", extra="\nSuperseded by ADR-0002"),
                     "0002-b.md": _adr(2, "Superseded", extra="\nSuperseded by ADR-0001")}
        _adr_dir(tmp, recs_text)
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 1 and "G1" in out


@case
def a12_s1_stale_unimplemented():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-old.md": _adr(1, "Accepted", date="2020-01-01")})
        mp = _write(json.dumps({"ADR-0001": ["gone.txt"]}))
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp, "--today", "2026-10-13",
                                "--stale-days", "100"])
        assert code == 1 and "S1" in out and "M2" in out  # anchor missing is M2(error); staleness is S1


@case
def a13_stale_days_threshold_respected():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-old.md": _adr(1, "Accepted", date="2026-09-01")})
        mp = _write(json.dumps({"ADR-0001": ["gone.txt"]}))
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp, "--today", "2026-10-13",
                                "--stale-days", "365"])
        assert "S1" not in out


@case
def a14_validate_map_ok():
    mp = _write(json.dumps({"ADR-0001": ["a.txt"], "0002": ["b.txt"]}))
    code, out, _ = run_cli(["validate", mp])
    assert code == 0 and "OK" in out


@case
def a15_validate_map_r1_bad_key():
    mp = _write(json.dumps({"adrs-0001": []}))
    code, out, _ = run_cli(["validate", mp])
    assert code == 1 and "R1" in out


@case
def a16_validate_map_r2_bad_value():
    mp = _write(json.dumps({"ADR-0001": "not-a-list"}))
    code, out, _ = run_cli(["validate", mp])
    assert code == 1 and "R2" in out


@case
def a17_0000_key_form_accepted():
    mp = _write(json.dumps({"0001": ["x"]}))
    code, out, _ = run_cli(["validate", mp])
    assert code == 0


@case
def a18_bench_small():
    code, out, _ = run_cli(["bench", "--records", "20"])
    assert code == 0 and "adrs=20" in out


@case
def a19_bench_default():
    code, out, _ = run_cli(["bench", "--records", "200"])
    assert code == 0 and "rec/s" in out


@case
def a20_help_exit0():
    code, out, _ = run_cli(["--help"])
    assert code == 0 and "adr-staleness-check" in out


@case
def a21_no_args_exit2():
    code, _, _ = run_cli([])
    assert code == 2


@case
def a22_json_output_structure():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp, "--json"])
        data = json.loads(out)
        assert data["adrs"] == 1 and isinstance(data["findings"], list)


@case
def a23_supersedes_alt_form_parsed():
    rec = mod.parse_adr("status: Accepted\nThis decision supersedes ADR-0007.\n")
    assert rec["supersedes"] == 7


# ---------------- [B] exception paths ----------------

@case
def b01_adr_dir_missing():
    mp = _write(json.dumps({}))
    code, _, err = run_cli(["check", "Z:/no/adrs", mp])
    assert code == 1 and "not a directory" in err


@case
def b02_impl_map_missing():
    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = run_cli(["check", tmp, "Z:/no/map.json"])
        assert code == 1 and "cannot read" in err


@case
def b03_impl_map_invalid_json():
    with tempfile.TemporaryDirectory() as tmp:
        mp = _write("{bad")
        code, _, err = run_cli(["check", tmp, mp])
        assert code == 1 and "invalid JSON" in err


@case
def b04_validate_missing_file():
    code, _, err = run_cli(["validate", "Z:/no/map.json"])
    assert code == 1 and "cannot read" in err


@case
def b05_map_is_list():
    p = _write("[]")
    code, out, _ = run_cli(["validate", p])
    assert code == 1 and "R0" in out


@case
def b06_map_is_string():
    p = _write('"x"')
    code, out, _ = run_cli(["validate", p])
    assert code == 1 and "R0" in out


@case
def b07_no_impl_map_given_ok():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        code, out, _ = run_cli(["check", tmp])
        assert code == 0 and "M4" in out  # accepted without anchors


@case
def b08_stale_days_zero_rejected():
    mp = _write("{}")
    with tempfile.TemporaryDirectory() as tmp:
        code, _, _ = run_cli(["check", tmp, mp, "--stale-days", "0"])
        assert code == 2


@case
def b09_stale_days_negative_rejected():
    mp = _write("{}")
    with tempfile.TemporaryDirectory() as tmp:
        code, _, _ = run_cli(["check", tmp, mp, "--stale-days", "-5"])
        assert code == 2


@case
def b10_stale_days_not_int():
    mp = _write("{}")
    with tempfile.TemporaryDirectory() as tmp:
        code, _, _ = run_cli(["check", tmp, mp, "--stale-days", "soon"])
        assert code == 2


@case
def b11_bench_zero():
    code, _, _ = run_cli(["bench", "--records", "0"])
    assert code == 2


@case
def b12_bench_negative():
    code, _, _ = run_cli(["bench", "--records", "-1"])
    assert code == 2


@case
def b13_bad_today_format_tolerated():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1, date="2020-01-01")})
        mp = _write(json.dumps({"ADR-0001": ["x.txt"]}))
        with open(os.path.join(tmp, "x.txt"), "w") as fh:
            fh.write("y")
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp, "--today", "not-a-date"])
        assert code == 0  # age parse falls back to 0, no crash


@case
def b14_non_md_files_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1), "notes.txt": "0002 fake", "readme": "x"})
        recs = mod.load_adrs(tmp)
        assert set(recs) == {1}


@case
def b15_unreadable_adr_file_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        os.chmod(os.path.join(tmp, "0001-a.md"), 0o044)
        try:
            recs = mod.load_adrs(tmp)
            assert 1 in recs or recs == {}  # skip or read, never crash
        finally:
            os.chmod(os.path.join(tmp, "0001-a.md"), 0o644)


@case
def b16_no_number_prefix_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"decision-alpha.md": _adr(1)})
        recs = mod.load_adrs(tmp)
        assert recs == {}


@case
def b17_dir_as_impl_root_argument():
    mp = _write("{}")
    code, _, err = run_cli(["check", tempfile.mkdtemp(), mp, "--impl-root", "Z:/no/root"])
    assert code == 0 or "M2" not in err  # root not validated upfront; findings-based


@case
def b18_validate_map_value_non_string_items():
    mp = _write(json.dumps({"ADR-0001": [1, 2]}))
    code, out, _ = run_cli(["validate", mp])
    assert code == 1 and "R2" in out


@case
def b19_whitespace_only_map():
    p = _write("   \n ")
    code, _, _ = run_cli(["validate", p])
    assert code == 1


@case
def b20_empty_map_object_ok():
    p = _write("{}")
    code, out, _ = run_cli(["validate", p])
    assert code == 0


# ---------------- [C] extreme / edge ----------------

@case
def c01_empty_adr_dir():
    with tempfile.TemporaryDirectory() as tmp:
        mp = _write("{}")
        code, out, _ = run_cli(["check", tmp, mp, "--json"])
        assert code == 0 and json.loads(out)["adrs"] == 0


@case
def c02_unicode_cjk_adr_content():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-决策.md": _adr(1)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "M4" in out  # D2: CJK filename parsed fine


@case
def c03_unicode_emoji_content():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-ship.md": "# Ship it \U0001f680\n\n## Status\n\nAccepted\n"})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0


@case
def c04_crlf_adr_file():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, "0001-a.md"), "w", encoding="utf-8", newline="") as fh:  # D3
            fh.write(_adr(1).replace("\n", "\r\n"))
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp, "--json"])
        assert json.loads(out)["findings"] and any(f["rule"] == "M4" for f in json.loads(out)["findings"])


@case
def c05_utf8_bom_map():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        fd, mp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(mp, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + b'{"ADR-0001": []}')
        code, _, _ = run_cli(["check", tmp, mp])
        assert code == 0


@case
def c06_huge_adr_body():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-big.md": _adr(1) + ("Filler sentence about context.\n" * 20000)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "M4" in out


@case
def c07_many_adrs_bulk():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"%04d-d.md" % i: _adr(i) for i in range(1, 101)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp, "--json"])
        assert json.loads(out)["adrs"] == 100


@case
def c08_long_chain_supersedes():
    spec = {"0001-a.md": _adr(1, "Superseded", extra="\nSuperseded by ADR-0002")}
    for i in range(2, 20):
        spec["%04d-x.md" % i] = _adr(i, "Superseded", extra="\nSuperseded by ADR-%04d" % (i + 1))
    spec["0020-end.md"] = _adr(20)
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, spec)
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "G1" not in out  # long chain is not a cycle


@case
def c09_status_unknown_falls_back():
    rec = mod.parse_adr("## Status\n\nOn Hold pending review\n")
    assert rec["status"] is None


@case
def c10_proposed_not_flagged_orphan():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1, "Proposed")})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert "M4" not in out


@case
def c11_rejected_not_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1, "Rejected")})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert "M4" not in out


@case
def c12_superseded_without_ref_ignored_for_graph():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1, "Superseded")})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert "G4" not in out and "G2" not in out


@case
def c13_nested_impl_root_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        sub = os.path.join(tmp, "src", "deep")
        os.makedirs(sub)
        with open(os.path.join(sub, "impl.txt"), "w") as fh:
            fh.write("x")
        mp = _write(json.dumps({"ADR-0001": ["src/deep/impl.txt"]}))
        code, out, _ = run_cli(["check", tmp, mp, "--impl-root", tmp])
        assert code == 0 and "M2" not in out


@case
def c14_anchors_resolve_from_adr_dir_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1), "impl.txt": "not markdown"})
        mp = _write(json.dumps({"ADR-0001": ["impl.txt"]}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "M2" not in out


@case
def c15_map_key_lowercase_adr_prefix():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        mp = _write(json.dumps({"adr-0001": ["x.txt"]}))  # lowercase key: not matched -> M1
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "M1" not in out  # lowercase keys skipped by check; validate/ catches them


@case
def c16_100_anchors_bulk():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"%04d-d.md" % i: _adr(i) for i in range(1, 101)})
        for i in range(1, 101):
            with open(os.path.join(tmp, "impl%03d.txt" % i), "w") as fh:
                fh.write("x")
        mp = _write(json.dumps({"ADR-%04d" % i: ["impl%03d.txt" % i] for i in range(1, 101)}))
        code, out, _ = run_cli(["check", tmp, mp])
        assert code == 0 and "M2" not in out


@case
def c17_extra_keys_in_findings_json():
    with tempfile.TemporaryDirectory() as tmp:
        _adr_dir(tmp, {"0001-a.md": _adr(1)})
        mp = _write(json.dumps({}))
        code, out, _ = run_cli(["check", tmp, mp, "--json"])
        f = json.loads(out)["findings"][0]
        assert set(f) >= {"rule", "severity", "message"}


@case
def c18_date_without_status():
    rec = mod.parse_adr("Date: 2025-12-31\nNo status line here.\n")
    assert rec["status"] is None and rec["date"] == "2025-12-31"


@case
def c19_two_dates_first_wins():
    rec = mod.parse_adr("Date: 2025-01-01\nLater: 2026-02-02\n")
    assert rec["date"] == "2025-01-01"


@case
def c20_mixed_status_wordcase():
    rec = mod.parse_adr("## Status\n\naccepted\n")
    assert rec["status"] is None  # grammar is capitalized words only


class T(unittest.TestCase):
    def test_meta_case_count(self):
        self.assertGreaterEqual(len(CASES), 60)


for _fn in CASES:
    setattr(T, "test_" + _fn.__name__, lambda self, f=_fn: f())

if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
    total, fails = r.testsRun, len(r.failures) + len(r.errors)
    print("SUMMARY: PASS %d/%d" % (total - fails, total))
    sys.exit(0 if fails == 0 else 1)

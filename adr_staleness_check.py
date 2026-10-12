#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adr-staleness-check — detects drift between architecture decision records
and their declared implementations: an ADR marked Superseded whose files are
still anchored to it, accepted decisions with no implementation evidence,
broken supersedes graphs, and date-based staleness.

This is a decision-vs-implementation drift checker. It deliberately does NOT
check ADR *format* health (layout, status words, link syntax, numbering gaps) —
that is the job of format checkers such as adr-health-check.
Pure standard library, single file, offline.
"""
import argparse, json, os, re, sys, tempfile, time

FILE_NUM_RE = re.compile(r"^(\d{4})[-_]")
STATUS_RE = re.compile(r"^\s*[-*]?\s*(Accepted|Proposed|Superseded|Rejected|Deprecated)\b", re.M)
SUPERSEDED_BY_RE = re.compile(r"[Ss]uperseded by\s+ADR[- ]?(\d{4})")
SUPERSEDES_RE = re.compile(r"[Ss]upersedes\s+ADR[- ]?(\d{4})")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def parse_adr(text):
    """Extract decision-relevant fields from ADR markdown text."""
    m = STATUS_RE.search(text)
    status = m.group(1) if m else None
    sb = SUPERSEDED_BY_RE.search(text)
    sp = SUPERSEDES_RE.search(text)
    d = DATE_RE.search(text)
    return {
        "status": status,
        "superseded_by": int(sb.group(1)) if sb else None,
        "supersedes": int(sp.group(1)) if sp else None,
        "date": d.group(1) if d else None,
    }


def load_adrs(adr_dir):
    """Scan an ADR directory. Returns records keyed by 4-digit number."""
    records = {}
    for fn in sorted(os.listdir(adr_dir)):
        if not fn.lower().endswith((".md", ".markdown")):
            continue
        m = FILE_NUM_RE.match(fn)
        if not m:
            continue
        num = int(m.group(1))
        try:
            with open(os.path.join(adr_dir, fn), "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        rec = parse_adr(text)
        rec["file"] = fn
        records.setdefault(num, []).append(rec)
    return records


def validate_map(impl_map):
    """Structural validation of the implementation map."""
    findings = []
    if not isinstance(impl_map, dict):
        findings.append({"rule": "R0", "severity": "error", "message": "impl map must be a JSON object"})
        return findings
    for k, v in impl_map.items():
        if not re.match(r"^(?:ADR-)?\d{4}$", k):
            findings.append({"rule": "R1", "severity": "error", "message": "key %r is not ADR-NNNN or NNNN" % k})
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            findings.append({"rule": "R2", "severity": "error", "message": "value for %s must be a list of path strings" % k})
    return findings


def _has_error(findings):
    return any(f["severity"] == "error" for f in findings)


def check(adr_dir, impl_map, impl_root=None, stale_days=365, today="2026-10-13"):
    """Drift detection core. Returns (findings, n_adrs)."""
    findings = []
    records = load_adrs(adr_dir)
    numbers = {n for n, lst in records.items() for _ in lst}
    for n, lst in sorted(records.items()):
        if len(lst) > 1:
            findings.append({"rule": "G3", "severity": "error",
                             "message": "ADR number %04d used by %d files" % (n, len(lst)), "ref": lst[0]["file"]})

    def latest(num):
        return records[num][0] if records.get(num) else None

    # map-side checks
    anchored = {}
    for k, paths in (impl_map or {}).items():
        m = re.match(r"^(?:ADR-)?(\d{4})$", k)
        if not m:
            continue
        num = int(m.group(1))
        if num not in numbers:
            findings.append({"rule": "M1", "severity": "error",
                             "message": "map references ADR-%04d which does not exist" % num, "ref": k})
            continue
        anchored.setdefault(num, []).extend(paths)
        rec = latest(num)
        if rec and rec["status"] == "Superseded":
            findings.append({"rule": "M3", "severity": "error",
                             "message": "ADR-%04d is Superseded but the impl map still anchors %d file(s) to it"
                                        % (num, len(paths)), "ref": rec["file"]})
        for p in paths:
            full = os.path.join(impl_root or adr_dir, p.replace("/", os.sep))
            if not os.path.exists(full):
                findings.append({"rule": "M2", "severity": "error",
                                 "message": "anchored path missing on disk: %s" % p, "ref": k})

    # adr-side checks
    edges = {}  # old -> new
    for num, lst in sorted(records.items()):
        rec = lst[0]
        if rec["status"] == "Superseded":
            target = rec["superseded_by"]
            if target is not None:
                if target not in numbers:
                    findings.append({"rule": "G4", "severity": "error",
                                     "message": "ADR-%04d superseded by ADR-%04d which does not exist"
                                                % (num, target), "ref": rec["file"]})
                else:
                    if target <= num:
                        findings.append({"rule": "G2", "severity": "warning",
                                         "message": "ADR-%04d superseded by non-later ADR-%04d (numbering not monotonic)"
                                                    % (num, target), "ref": rec["file"]})
                    edges[num] = target
        if rec["status"] == "Accepted" and num not in anchored:
            findings.append({"rule": "M4", "severity": "warning",
                             "message": "ADR-%04d is Accepted with no implementation anchor" % num,
                             "ref": rec["file"]})
        if (rec["status"] == "Accepted" and rec["date"] and num in anchored
                and not any(os.path.exists(os.path.join(impl_root or adr_dir, p.replace("/", os.sep)))
                            for p in anchored[num])):
            try:
                age = (int(today[:4]) - int(rec["date"][:4])) * 365 + \
                      (int(today[5:7]) - int(rec["date"][5:7])) * 30 + \
                      (int(today[8:10]) - int(rec["date"][8:10]))
            except ValueError:
                age = 0
            if age > stale_days:
                findings.append({"rule": "S1", "severity": "warning",
                                 "message": "ADR-%04d accepted %s is %d days old and every anchor is missing (possibly stale)"
                                            % (num, rec["date"], age), "ref": rec["file"]})

    # cycle detection on supersedes graph (old -> new)
    for start in edges:
        seen, cur = set(), start
        while cur in edges:
            if cur in seen:
                findings.append({"rule": "G1", "severity": "error",
                                 "message": "supersedes cycle detected involving ADR-%04d" % start,
                                 "ref": records[start][0]["file"]})
                break
            seen.add(cur)
            cur = edges[cur]
    return findings, len(numbers)


def _load(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _print(findings, n_adrs, as_json):
    if as_json:
        print(json.dumps({"adrs": n_adrs, "findings": findings}, ensure_ascii=False, indent=2))
    else:
        print("scanned %d ADR(s), %d finding(s)" % (n_adrs, len(findings)))
        for f in findings:
            ref = " [%s]" % f["ref"] if f.get("ref") else ""
            print("%-7s %-4s%s %s" % (f["severity"], f["rule"], ref, f["message"]))


def _positive_int(text):
    try:
        v = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("not an integer: %r" % text)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def bench(n):
    root = tempfile.mkdtemp(prefix="adr-bench-")
    for i in range(n):
        with open(os.path.join(root, "%04d-decision.md" % i), "w",
                  encoding="utf-8", newline="") as fh:
            fh.write("# ADR-%04d\n\n## Status\n\nAccepted\n\nDate: 2026-01-01\n" % i)
    t0 = time.perf_counter()
    records = load_adrs(root)
    dt = time.perf_counter() - t0
    for fn in os.listdir(root):
        os.remove(os.path.join(root, fn))
    os.rmdir(root)
    return len(records), dt


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="adr-staleness-check",
        description="Detect drift between ADRs and their declared implementations.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="drift-check an ADR dir against an implementation map")
    pc.add_argument("adr_dir", help="directory of ADR markdown files")
    pc.add_argument("impl_map", nargs="?", help="implementation map JSON (adr -> file list)")
    pc.add_argument("--impl-root", help="root against which anchored paths resolve (default: adr_dir)")
    pc.add_argument("--stale-days", type=_positive_int, default=365)
    pc.add_argument("--today", default="2026-10-13", help="as-of date YYYY-MM-DD (for tests/repro)")
    pc.add_argument("--json", action="store_true")

    pv = sub.add_parser("validate", help="structural validation of an implementation map")
    pv.add_argument("impl_map")
    pv.add_argument("--json", action="store_true")

    pb = sub.add_parser("bench", help="time ADR parsing on synthetic records")
    pb.add_argument("--records", type=_positive_int, default=200)

    args = ap.parse_args(argv)
    if args.cmd == "bench":
        n, dt = bench(args.records)
        print("adrs=%d parsed in %.4fs (%.0f rec/s)" % (n, dt, n / dt if dt else 0))
        sys.exit(0)

    impl_map = {}
    if args.cmd in ("check", "validate") and args.impl_map:
        try:
            impl_map = _load(args.impl_map)
        except OSError as exc:
            print("error: cannot read %s: %s" % (args.impl_map, exc), file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as exc:
            print("error: invalid JSON in %s: %s" % (args.impl_map, exc), file=sys.stderr)
            sys.exit(1)

    if args.cmd == "validate":
        findings = validate_map(impl_map)
        if args.json:
            print(json.dumps({"findings": findings}, ensure_ascii=False, indent=2))
        else:
            if not findings:
                print("OK: no findings")
            for f in findings:
                print("%-7s %-4s %s" % (f["severity"], f["rule"], f["message"]))
        sys.exit(1 if _has_error(findings) else 0)

    if not os.path.isdir(args.adr_dir):
        print("error: adr_dir is not a directory: %s" % args.adr_dir, file=sys.stderr)
        sys.exit(1)

    findings, n = check(args.adr_dir, impl_map, args.impl_root, args.stale_days, args.today)
    _print(findings, n, args.json)
    sys.exit(1 if _has_error(findings) else 0)


if __name__ == "__main__":
    main()

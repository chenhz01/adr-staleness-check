# Changelog — adr-staleness-check

All releases are local drafts; no remote operations are performed.

## v0.1.1 — 2026-10-13

Fixed:
- stale-day age computation made robust to malformed `--today` values
  (falls back to age 0 instead of crashing; covered by test b13).

Changed:
- self_test expanded to 64 cases across functional / exception / extreme-edge
  categories (scaffold v2 four defenses: SystemExit capture, Unicode-safe
  matching, Windows newline-safe fixtures, SUMMARY last line).
- README: Performance numbers re-measured via the shipped `bench` subcommand;
  How-this-differs section tightened to cite the anchor README verbatim once.

## v0.1.0 — 2026-10-13

Added:
- Initial local draft: ADR field parser (status / superseded-by / supersedes /
  date), implementation-map validation (R0–R2), drift checks M1–M4, graph
  checks G1–G4, staleness check S1, argparse CLI (check / validate / bench)
  and scaffold-v2 self_test.

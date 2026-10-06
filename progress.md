# Progress

## 2026-10-06 — v1.0.3 bounded impact propagation
- Real counterexamples: maxdepth2 highscore2-hop a→x→b suppresses weaker1-hop a→b needed for b→c; maxdepth3 similar pattern missesd. New7 test methods failed72 assertions including oracle subtests and explicitly changed bounded tie policy before the fix. Layered relaxation preserves shallow alternatives, original unbounded heap unchanged.
- Final43source tests Windows42pass/1POSIXskip and compile/diff checks passed; new corpus has240graphs×6depth=1440 independent simple-path comparisons with exact powers-of-two weights. Paths, evidence, classifications, origin, ordering, cycle simplicity and actual CLI JSON/Markdown/input preservation checked. Added single-node/invalid-depth/all-changed/legacy tie compatibility; root5maintenance tests passed. Installed-wheel validation and publication results recorded separately in root maintenance report, avoiding documentation-only SHA loops.
- Benchmarks Python3.12.10 with tracemalloc on this machine: 10000fanout unbounded0.992s/13649190peakB; explicitdepth1fanout0.449s/14006704B; 500chain depth1000.063s/2648722B. No broad speedup/SLA or real-world graph accuracy claim. Worst-case bounded work scales with depth×edges, output-path size still matters.
- Source package1.0.3/store format1; wheel fresh-env/isolatedsource-independent oracle+CLI/pipcheck and exactSHA publicremote/CI verification required. No browser/UI changes, no real auditlog/customer input, no paidAI, no other repo service/profile/Release changes. Remaining: extreme score numeric behavior, broader scale/resource limits, actual change-review cases and hosted deployment outsidev1 scope.

## 2026-10-06 — v1.0.1 encrypted recovery hardening
- Crafted authenticated synthetic ZIPs reproduced17 failing boundary assertions and3 unhandled malformed-type errors across5 new methods before implementation. Encryption authentication does not make archive path data safe.
- Strict raw ZIP names, portable paths, special modes, case collisions including directories and file-parent conflicts checked before destination creation. Envelope field types/salt/nonce lengths, file-count and expansion limits checked. Refuse symlink/junction source roots/entries and restore targets.
- Windows ZipInfo normalizes backslashes, so initial corrected run still missed that spelling: preserve raw test entry spelling and validate orig_filename. No unsafe fixture is taken from a user file.
- Added entry-count/expansion and POSIX link tests; final cross-platform/package checks follow. Existing valid archive format remains version1; package1.0.1 does not promise atomic snapshots, malicious-race isolation or recovery of empty directories/metadata.

## 2026-10-06 — v1.0.2 bounded source reads
- Replace rglob with explicit traversal that checks links/junctions before descending. Bound each copied source to its predeclared size and compare stat/fstat identity/size/mtime; growing/changing sources fail before encrypted output publication.
- Added a source-growth injection before file reading.33 tests on Windows32 passed/1 POSIX skipped; store format remains version1. Whole-directory atomic consistency and malicious metadata-preserving writes remain out of scope.

## 2026-09-30
- Selected TraceCascade as the next flagship: an evidence-backed change-impact simulator.
- Defined R0–R5 and R0 acceptance criteria. Implementation started; nothing beyond R0 is claimed complete.
- Implemented strict version-1 graph/scenario validation, local evidence checking with optional source hashes, deterministic cycle-safe propagation, uncertainty classification, JSON/Markdown reports and CLI commands.
- Added a five-node customer-tier example with a real cycle and a mixture of confirmed/inferred relations. Initial local test suite covers malformed inputs, evidence drift, cycles, depth limits, path selection and CLI failure behavior.
- Hardened output safety (cannot overwrite graph/scenario/evidence), rejected boolean schema versions and negative depth, and covered parallel equal edges. 10 local tests pass; source compiles.
- Built `tracecascade-0.1.0-py3-none-any.whl`, installed it into a clean virtual environment and verified the installed console command/import from outside the repository. Public Git/CI release is pending.
- Published public repository at https://github.com/azaz2288/tracecascade. First CI run 36628396269 passed Ubuntu but exposed a real cross-platform issue: Windows line-ending conversion invalidated the pinned evidence hash. Added repository line-ending policy; replacement CI pending.
- Commit `48021d03ccd54b3cb96bedc9e4a899806e892cf4` passed Windows/Ubuntu CI run 36628662783. R0 is now a public, installable and cross-platform-verified vertical slice; R1–R5 remain roadmap work.
- Completed v1 implementation: multi-format ingestion, reversible entity alignment, graph/report diffs, role-gated loopback review UI, hash-chained optional-HMAC audit, Python/GitHub read-only connectors, ReproForge export, encrypted backup/restore, security hardening and operational documentation.
- Expanded the suite to 25 passing tests, including concurrent review writers, graph-bound UI state, connector mocking/bounds, relative Python imports, failed-ingestion output preservation, ciphertext modification, unsafe archive paths and restore target safety.
- Executed the complete example from Markdown ingestion through review application and ReproForge export; the resulting two-task plan validated and ran successfully in the local ReproForge checkout.
- Recorded scale observations: 10,000-node fan-out in 0.924 seconds / 13,649,246 traced bytes; 1,000-node deep chain in 5.833 seconds / 233,143,644 traced bytes, with the full-path output-size limitation documented.
- Built `tracecascade-1.0.0-py3-none-any.whl`, installed it with dependencies into a fresh virtual environment, verified metadata with `pip check`, imported it from `site-packages`, and exercised every local CLI workflow from outside the source tree (including exact undo, diffs, review application, source scan and encrypted recovery).
- Published complete v1 commit `fd8bded9aa78d5fd9fac1143fd431c45fdfb8afd`; GitHub Actions run 36634399038 passed the full suite, benchmark, package build and installed-CLI smoke test on both Windows and Ubuntu.

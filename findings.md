# Findings

v1.0.3: single-settled-node heap labels can miss reachable descendants with a hop bound; highscore deep prefix cannot dominate lowscore shallow prefix because remaining hop budgets differ. Layered relaxation retains these alternatives, prunes only when a strictly shallower prefix has at least the score, and updates best after each whole layer. Unit-weight cycles are dominated by shorter prefixes; explicit bound picks shortest equal-score path before edgeIDs/origin, without changing legacy unbounded tie semantics.240small synthetic graphs×6depth independent simple-path enumeration passed after a real first72failures (not72 distinct bugs); powers-of-two scores are not an extreme floating-point oracle. Installation verification uses source-independent-I imports and actual installed CLI, never fallback to old installed package. Benchmarks remain topology/depth-specific observations.

- Most knowledge tools answer retrieval questions; TraceCascade focuses on prospective change impact across heterogeneous artifacts.
- Real dependency graphs can contain cycles, so rejecting all cycles would hide valid mutual dependencies. Propagation must be cycle-safe and bounded instead.
- An influence score alone is not explainable. A report needs the selected path, relation types, evidence quotes and confidence/status for every hop.
- “Confirmed” is a human/evidence state, not a model confidence synonym. Reports must show both independently.
- Exact GitHub name search was repeated before release: zero repositories named `tracecascade`, and `azaz2288/tracecascade` was available at that time.
- The R0 example source is pinned by SHA-256 `d0746740b04f3414c9a9d8a3bd471d5d6375421382d1bf3f9095fea74d164878`, so changing the evidence document makes simulation fail closed until the graph is reviewed.
- Human decisions must be bound to the exact graph digest; otherwise an old confirmation can be shown against a changed graph even when application code filters it later.
- A persistent predecessor chain removes quadratic working-state copies in deep propagation, but a report that repeats every complete evidence path still has quadratic output size on a linear chain. The benchmark now exposes fan-out and chain topologies separately.
- The v1 ReproForge export was validated by the sibling ReproForge parser and executed as a real two-task dependency DAG, not merely checked as JSON.

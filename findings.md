# Findings

- Most knowledge tools answer retrieval questions; TraceCascade focuses on prospective change impact across heterogeneous artifacts.
- Real dependency graphs can contain cycles, so rejecting all cycles would hide valid mutual dependencies. Propagation must be cycle-safe and bounded instead.
- An influence score alone is not explainable. A report needs the selected path, relation types, evidence quotes and confidence/status for every hop.
- “Confirmed” is a human/evidence state, not a model confidence synonym. Reports must show both independently.
- Exact GitHub name search was repeated before release: zero repositories named `tracecascade`, and `azaz2288/tracecascade` was available at that time.
- The R0 example source is pinned by SHA-256 `d0746740b04f3414c9a9d8a3bd471d5d6375421382d1bf3f9095fea74d164878`, so changing the evidence document makes simulation fail closed until the graph is reviewed.

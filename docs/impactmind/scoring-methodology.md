# Structural Exposure Scoring Methodology

## 1. Metric Definition & Non-Goals

### What It Is
The **Blast Radius & Structural Exposure Score** (0.0 to 100.0) is a deterministic, heuristic metric reflecting the breadth and sensitivity of the codebase touched by a proposed code modification. It synthesizes AST change categories, contract-breaking signals, graph topology, public API exposure, and test coverage into a transparent, actionable score.

### What It Is NOT (Non-Goals)
- It is **NOT an empirical defect prediction model**.
- It does **NOT guarantee that a change is bug-free** if the score is low.
- It does **NOT replace code review, static analysis, or end-to-end integration testing**.

---

## 2. Component Scoring Formula

The structural exposure score is bounded between `0.0` and `100.0` and calculated additively:

$$\text{Exposure Score} = \min(100.0, \max(0.0, S_{\text{direct}} + S_{\text{indirect}} + S_{\text{breaking}} + S_{\text{exposure}} + S_{\text{test}}))$$

### 2.1 Direct Dependents ($S_{\text{direct}}$) — Max 25.0
Each direct dependent component (depth 1 caller, importer, or implementor) in the repository knowledge graph adds `5.0` points:
$$S_{\text{direct}} = \min(25.0, N_{\text{direct}} \times 5.0)$$

### 2.2 Indirect Downstream Dependents ($S_{\text{indirect}}$) — Max 15.0
Each multi-hop downstream component (depth 2+) reached via BFS traversal adds `2.5` points:
$$S_{\text{indirect}} = \min(15.0, N_{\text{indirect}} \times 2.5)$$

### 2.3 Breaking Contract Alterations ($S_{\text{breaking}}$) — Max 20.0
Each detected breaking contract change (added non-optional parameters, deleted symbols, altered return types) adds `10.0` points:
$$S_{\text{breaking}} = \min(20.0, N_{\text{breaking}} \times 10.0)$$

### 2.4 Public API & Database Model Exposure ($S_{\text{exposure}}$) — Max 20.0
Exposing or modifying public HTTP endpoints or database tables adds `10.0` points per exposed resource:
$$S_{\text{exposure}} = \min(20.0, (N_{\text{api}} \times 10.0) + (N_{\text{database}} \times 10.0))$$

### 2.5 Automated Test Coverage & Verification ($S_{\text{test}}$) — [-10.0, +20.0]
- **Zero Test Coverage Penalty**: If direct dependents or public endpoints are impacted but no automated tests cover the modified code path, a `+20.0` penalty is assessed.
- **Passing Regression Test Credit**: When approved regression tests are executed and pass in the controlled runner, a `-10.0` credit is applied.
- **Failing Regression Test Penalty**: If approved tests fail, a `+15.0` penalty is assessed.

---

## 3. Exposure Tiers

| Score Range | Tier | Definition | Recommended Engineering Action |
| :--- | :--- | :--- | :--- |
| **0.0 – 19.9** | `LOW` | Localized, non-breaking changes with minimal downstream impact | Standard code review and CI verification |
| **20.0 – 44.9** | `MEDIUM` | Moderate ripple effect across internal modules; no breaking public contracts | Review downstream call sites; run unit test suite |
| **45.0 – 69.9** | `HIGH` | Breaking internal contracts, multi-hop callers, or API modifications | Cross-team review; mandatory regression testing before merge |
| **70.0 – 100.0** | `CRITICAL` | Breaking public API routes, core schema migrations, or zero test coverage | Engineering lead sign-off; full regression validation |

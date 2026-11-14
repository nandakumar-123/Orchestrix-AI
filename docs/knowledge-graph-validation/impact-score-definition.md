# Blast Radius & Structural Exposure Score: Metric Definition & Architecture

## 1. Metric Overview

The **Blast Radius & Structural Exposure Score** is a heuristic, graph-topological metric (0.0 to 100.0) designed to quantify the structural surface area impacted when a specific code symbol, function, class, or file is modified.

### Crucial Clarification & Non-Goals

> [!IMPORTANT]
> The Blast Radius & Structural Exposure Score is **not** an empirical regression risk model or a statistical prediction of bug probability.
> 
> Predicting true regression risk requires historical defect logs, production incident telemetry, code churn frequency, and author commit statistics. In contrast, this metric measures **structural exposure**: *how widely coupled a given component is across the codebase graph, how deeply downstream modules depend on it, and whether automated tests exist to verify it.*

---

## 2. Structural Exposure Tiers

The score maps to four standard exposure tiers:

| Tier | Score Range | Description & Architectural Implication |
| :--- | :--- | :--- |
| **`LOW`** | `0.0 – 19.9` | **Isolated Component**: Few or no incoming callers; changes are localized within a leaf module. Low blast radius. |
| **`MEDIUM`** | `20.0 – 44.9` | **Bounded Exposure**: Modest number of direct callers or imports within the same subsystem. Standard peer review and focused testing recommended. |
| **`HIGH`** | `45.0 – 69.9` | **Significant Exposure**: Widely imported utility, multi-hop caller chains, or modification to a public API endpoint or database entity. Comprehensive integration tests required. |
| **`CRITICAL`** | `70.0 – 100.0` | **Architectural Nexus**: Highly coupled core symbol directly impacting multiple public API routes, shared persistent database models, deep transitive dependents, and lacking adequate test coverage. Requires strict review and regression verification. |

---

## 3. Mathematical & Heuristic Scoring Formula

The structural exposure score \(S\) is computed dynamically over the Knowledge Graph traversal DAG starting from the target entity \(v_0\) up to depth \(d \le 3\):

$$S = \min\left(100.0, \; S_{\text{direct}} + S_{\text{indirect}} + S_{\text{api}} + S_{\text{database}} + S_{\text{test}}\right)$$

### Component Weights & Caps

| Component | Heuristic Contribution | Max Cap | Rationality |
| :--- | :--- | :--- | :--- |
| **Direct Dependents** (\(S_{\text{direct}}\)) | \(+6.0 \times \min(5, N_{\text{direct}})\) | **30.0** | Direct callers, subclassing classes, and importing files are immediately affected by signature or contract mutations. |
| **Indirect Dependents** (\(S_{\text{indirect}}\)) | \(+3.0 \times \min(7, N_{\text{indirect}})\) | **20.0** | Transitive callers (depth 2–3) risk cascading runtime breakages or semantic drift. |
| **Public API Endpoints** (\(S_{\text{api}}\)) | \(+10.0 \times \min(2, N_{\text{endpoints}})\) | **25.0** | Public REST / GraphQL handlers expose internal changes directly to external clients and frontend applications. |
| **Database Models** (\(S_{\text{database}}\)) | \(+10.0 \times \min(2, N_{\text{models}})\) | **20.0** | Changes to database tables or ORM schemas jeopardize persistent data integrity and schema migrations. |
| **Test Verification** (\(S_{\text{test}}\)) | \(+15.0\) penalty if \(N_{\text{tests}} = 0\) and \(N_{\text{dependents}} > 0\) | **15.0** | If a widely coupled symbol has no automated test coverage, its structural exposure cannot be verified prior to deployment. |

---

## 4. Subgraph & Reasoning Output

Each evaluation returns an actionable `ImpactPreviewResponse` containing both quantitative and explanatory evidence:

```json
{
  "target_id": "sym:snap-1:app/services/auth.py:function:authenticate_user",
  "target_name": "authenticate_user",
  "target_type": "Function",
  "risk_level": "HIGH",
  "risk_score": 55.0,
  "score_type": "heuristic_structural_exposure",
  "score_label": "Blast Radius & Structural Exposure Score",
  "reasons": [
    "2 direct dependent(s) (callers/importers/subclasses) affected",
    "Exposes or modifies 1 public API endpoint(s)",
    "1 test case(s) verify this code path"
  ],
  "affected_endpoints": [
    {"name": "POST /login", "path": "/login", "method": "POST"}
  ],
  "affected_tests": [
    {"name": "test_authenticate_user", "file_path": "tests/test_auth.py"}
  ],
  "subgraph": {
    "total_nodes": 4,
    "total_edges": 3
  }
}
```

---

## 5. Guidelines for Multi-Agent Systems & Developers

1. **Autonomous PR & Plan Generation**: Agents should prioritize generating test cases for components in `HIGH` or `CRITICAL` tiers before proposing refactorings.
2. **Review Triage**: Human reviewers can immediately identify whether a change touches public API boundaries or shared database models.
3. **Audit Trail**: Every score computation is fully reproducible and verifiable using the underlying Cypher traversal in Neo4j Aura or MockGraphProvider.

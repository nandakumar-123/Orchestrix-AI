# Regression Test Selection Methodology

## 1. Overview

Blindly running an entire enterprise repository's test suite for every commit or pull request leads to test suite bloat, slow feedback loops, and resource exhaustion. ImpactMind's `RegressionTestSelector` intelligently selects and ranks test suites by synthesizing multiple corroborating intelligence sources:
1. Knowledge graph `TESTS` edges.
2. Downstream callers and dependency chains.
3. Public API route decorators and handlers.
4. Direct symbol and module naming conventions.
5. Phase 9 hybrid semantic similarity.

---

## 2. Priority Ranking Tiers

ImpactMind assigns every recommended regression test to one of four priority tiers:

### 2.1 CRITICAL
- **Criteria**:
  - Direct `TESTS` edge in the knowledge graph targeting a modified symbol.
  - Test suites covering an exposed public API endpoint that was directly modified or exposed by modified code.
  - Tests covering functions with detected breaking signature or schema alterations.
- **Action**: Must be executed before staging or production merges.

### 2.2 HIGH
- **Criteria**:
  - Direct callers (depth 1) in the knowledge graph that are marked as test cases (`TestCase`).
  - Unit tests matching changed module naming conventions (`test_<module>.py`, `<module>.test.ts`, `<module>_test.go`) when breaking alterations or schema changes exist.
  - Tests exercising modified database models or ORM classes.
- **Action**: Strongly recommended for pull request pre-merge verification.

### 2.3 MEDIUM
- **Criteria**:
  - Indirect downstream callers (depth 2+) identified through BFS graph traversal.
  - Convention-matched test files for non-breaking, logic-only modifications.
  - Semantically matched test suites surfaced via FastEmbed cosine similarity (>0.55 similarity).
- **Action**: Recommended for nightly regression passes or optional developer validation.

### 2.4 LOW
- **Criteria**:
  - Test suites in the repository that share loose namespace or directory alignment but lack direct structural call paths.
- **Action**: Executed as part of full release regression cycles.

---

## 3. Automated Framework Detection

ImpactMind infers the target test execution binary automatically from file extensions and repository manifests:
- `.py` files -> `pytest` / `uv run pytest`
- `.ts`, `.tsx`, `.js`, `.jsx` -> `vitest` / `npm test`
- `.go` -> `go test`
- Other -> `generic` allowlisted runner

# ImpactMind Architecture

## 1. Overview & Vision

**ImpactMind** is the intelligent change impact analysis and regression testing engine of Orchestrix AI. When engineers propose code changes across multi-language enterprise repositories, ImpactMind evaluates the modification holistically—not by running every test blindly, but by determining the exact structural blast radius, downstream callers, exposed API endpoints, and database models affected by the change.

ImpactMind combines five key intelligence layers:
1. **Git Diff & Commit Delta Analysis**: Precise line hunk parsing, addition/deletion metrics, file rename detection, and GitHub compare API ingestion.
2. **Multi-Language Tree-Sitter AST Classification**: AST symbol resolution across 40+ supported languages to classify changes into 13 discrete categories and detect contract-breaking modifications.
3. **Knowledge Graph Traversal**: Multi-hop directed dependency tracing over Phase 10 Neo4j/Mock graphs (`CALLS`, `IMPORTS`, `EXTENDS`, `IMPLEMENTS`, `EXPOSES`, `TESTS`, `DEFINES`, `DEPENDS_ON`).
4. **Hybrid Semantic & Lexical Retrieval**: Phase 9 FastEmbed (`all-MiniLM-L6-v2`) retrieval over pgvector code chunks to identify conceptually related error handling, validation, and domain logic.
5. **Controlled Regression Test Selection & Execution**: Multi-source test ranking (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) coupled with a permissioned, safeguarded subprocess runner requiring explicit user approval.

```
                           +---------------------------+
                           |   Git Diff / PR Commit    |
                           +-------------+-------------+
                                         |
                                         v
                           +-------------+-------------+
                           |       GitDiffParser       |
                           +-------------+-------------+
                                         |
                                         v
                         +---------------+---------------+
                         |      ASTChangeClassifier      |
                         |   (Tree-sitter 40+ Languages) |
                         +---------------+---------------+
                                         |
                     +-------------------+-------------------+
                     |                                       |
                     v                                       v
         +-----------+-----------+               +-----------+-----------+
         |  GraphImpactAnalyzer  |               | SemanticImpactAnalyzer|
         | (Multi-hop BFS Graph) |               | (Hybrid FastEmbed/vec)|
         +-----------+-----------+               +-----------+-----------+
                     |                                       |
                     +-------------------+-------------------+
                                         |
                                         v
                         +---------------+---------------+
                         |    RegressionTestSelector     |
                         |   (Ranked Test Prioritization)|
                         +---------------+---------------+
                                         |
                                         v
                         +---------------+---------------+
                         |   StructuralExposureScorer    |
                         |  (0–100 Blast Radius Metric)  |
                         +---------------+---------------+
                                         |
                                         v
                         +---------------+---------------+
                         |    ControlledTestRunner       |
                         | (Approval Gate + Redaction)   |
                         +-------------------------------+
```

---

## 2. Core Components

### 2.1 GitDiffParser
- Implemented in `backend/app/services/impactmind/diff_parser.py`.
- Parses standard unified diff format (e.g. `git diff` outputs) and GitHub Compare API JSON payloads.
- Extracts individual `DiffHunk` structures, tracking `old_start`, `old_count`, `new_start`, `new_count`, added lines, deleted lines, and hunk headers.
- Handles added, modified, deleted, and renamed files with path tracking.

### 2.2 ASTChangeClassifier
- Implemented in `backend/app/services/impactmind/ast_classifier.py`.
- Resolves file extensions to registered Tree-sitter parsers (`Python`, `JavaScript`, `TypeScript`, `Java`, `Go`, `Rust`, `C#`, etc.).
- Categorizes modifications into 13 formal change categories:
  - `LOGIC_CHANGE`
  - `SIGNATURE_CHANGE`
  - `PUBLIC_API_CHANGE`
  - `IMPORT_CHANGE`
  - `CLASS_STRUCTURE_CHANGE`
  - `INHERITANCE_CHANGE`
  - `DATABASE_SCHEMA_CHANGE`
  - `API_ROUTE_CHANGE`
  - `DEPENDENCY_CHANGE`
  - `TEST_CHANGE`
  - `CONFIGURATION_CHANGE`
  - `DOCUMENTATION_CHANGE`
  - `UNKNOWN_CHANGE`
- Performs breaking change detection by comparing parameter counts, non-default arguments, parameter deletions, and return types.

### 2.3 GraphImpactAnalyzer
- Implemented in `backend/app/services/impactmind/graph_analyzer.py`.
- Performs bounded Breadth-First Search (BFS) starting at changed symbol and file nodes up to a configurable maximum hop depth (default 2, max 3).
- Traces incoming edges to discover direct dependents (depth 1) and indirect dependents (depth 2+).
- Traces outgoing edges (`EXPOSES`, `DEFINES`, `READS_FROM`, `WRITES_TO`) to locate public API routes (`APIEndpoint`) and database models (`DatabaseTable`, `DatabaseModel`).
- Tracks edge confidence and flags unresolved or low-confidence dependencies as `uncertain_dependents`.
- Operates in degraded mode if graph provider is offline without interrupting the analysis pipeline.

### 2.4 SemanticImpactAnalyzer
- Implemented in `backend/app/services/impactmind/semantic_analyzer.py`.
- Formulates targeted search queries for modified symbols and categories (e.g. `process_payment implementation logic and error handling`).
- Executes hybrid vector + lexical retrieval using FastEmbed and pgvector.
- Filters out already-visited graph files and changed files to surface hidden conceptual overlaps that lack explicit AST imports or direct call edges.

### 2.5 RegressionTestSelector
- Implemented in `backend/app/services/impactmind/test_selector.py`.
- Prioritizes test execution across 4 tiers:
  - **CRITICAL**: Direct `TESTS` edges in knowledge graph, tests covering breaking API route modifications, or tests explicitly verifying broken signatures.
  - **HIGH**: Direct caller tests (depth 1), convention-based matches for breaking changes (`test_<module>.py`), or tests exercising modified database models.
  - **MEDIUM**: Indirect caller tests (depth 2+), convention-based matches for non-breaking changes, or semantic similarity matches.
  - **LOW**: General repository test suites not directly linked to modified components.
- Automatically infers test runner (`pytest`, `vitest`, `go test`).

### 2.6 StructuralExposureScorer
- Implemented in `backend/app/services/impactmind/exposure_scorer.py`.
- Calculates the **Blast Radius & Structural Exposure Score** (0.0 to 100.0) and assigns an Exposure Tier (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- Clearly documented and presented as a heuristic structural exposure metric based on graph topology and change surface; NOT an empirical prediction of defect probability.

### 2.7 ControlledTestRunner
- Implemented in `backend/app/services/impactmind/test_runner.py`.
- Enforces strict execution safeguards: explicit user approval gate (`run_approved=true`), binary allowlisting, shell metacharacter rejection, working directory isolation, 60s timeout, 50KB output truncation, and automated secret redaction.

---

## 3. Data Flow & Persistence

All assessments are tenant-isolated in Neon PostgreSQL via SQLAlchemy:
- `impact_assessments`: Top-level assessment records.
- `impact_change_classifications`: Individual classified symbol changes.
- `impact_affected_entities`: Downstream impacted graph nodes.
- `impact_test_recommendations`: Ranked regression tests.
- `impact_test_executions`: Subprocess execution logs and pass/fail metrics.

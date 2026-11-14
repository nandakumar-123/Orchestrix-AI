# Multi-Language Code Relationship Extraction Accuracy Audit

## 1. Executive Summary

This report delivers the empirical accuracy audit of Orchestrix AI's Knowledge Graph relationship extraction engine. Across 42 registered programming, scripting, markup, and database languages, code structures and semantic relationships are mapped into a unified property graph.

We evaluated relationship extraction accuracy across three distinct language ecosystems:
1. **Python Backend**: FastAPI & SQLAlchemy architecture (models, endpoints, services, tests, dependencies).
2. **TypeScript / Frontend**: React and Node.js architecture (interfaces, abstract classes, client wrappers, cart services, test suites).
3. **Go Systems**: Go microservice architecture (structs, crypto hashing, credential verification, table-driven tests, package modules).

---

## 2. Extraction Capabilities Across 42 Supported Languages

Orchestrix AI employs a multi-tiered architecture for extracting code structures and relationships:

| Tier | Language Family | Parser / Adapter Mechanism | Extracted Graph Elements |
| :--- | :--- | :--- | :--- |
| **Tier 1: AST Native + Language-Specific Adapters** (18 Languages) | Python, TypeScript, TSX, JavaScript, JSX, Java, C, C++, C#, Go, Rust, Ruby, Swift, Kotlin, Dart, PHP, Scala, Elixir | Tree-sitter Grammar + Custom AST Visitor | Functions, Classes, Methods, Interfaces, Structs, Inheritance (`EXTENDS`, `IMPLEMENTS`), Nested Calls (`CALLS`), Imports (`IMPORTS`), API Endpoints (`EXPOSES`), Tests (`TESTS`) |
| **Tier 2: Scripting & Scientific AST Adapters** (10 Languages) | Bash, PowerShell, Lua, Perl, R, Julia, OCaml, Haskell, Pascal, Zig | Tree-sitter Grammar + Shell/Functional Adapter | Functions, Subroutines, Scripts, Module Inclusions, Call Sites |
| **Tier 3: Systems, Build & Config Languages** (7 Languages) | Fortran, CMake, Make, SQL, Solidity, Groovy, HTML | Tree-sitter Grammar + Specialized Adapter | Procedures, Targets, Contracts, DB Schemas, Views, Tables (`DEFINES`) |
| **Tier 4: Structured Data & Markup** (7 Languages) | JSON, YAML, TOML, XML, CSS, Svelte, Markdown | Tree-sitter Grammar + StructuredData Adapter | File boundaries, Dependency manifests, Package metadata (`DEPENDS_ON`) |

---

## 3. Relationship Data Contract & Property Schema

Every extracted relationship in Orchestrix AI adheres to a strict schema ensuring traceability and confidence scoring:

```json
{
  "source_id": "sym:snap-1:app/api/auth.py:function:login_endpoint",
  "target_id": "sym:snap-1:app/services/auth.py:function:authenticate_user",
  "type": "CALLS",
  "properties": {
    "snapshot_id": "snap-1",
    "status": "resolved",
    "resolution_type": "import_match",
    "confidence": 0.95,
    "evidence": "authenticate_user(payload.u, payload.p)"
  }
}
```

### Supported Status Values
- `resolved`: Target symbol definitively bound via same-file definition, qualified import path, or unique global match.
- `partially_resolved`: Ambiguous match across multiple potential candidates with highest confidence heuristic selected.
- `unresolved`: External reference or dynamic reflection where target symbol is not defined in current snapshot.

### Confidence Calibration
- **1.0**: Same-file symbol reference, explicit file/package containment (`CONTAINS`), or validated package dependency manifest (`DEPENDS_ON`).
- **0.95**: Direct import-matched symbol reference, decorated API route (`EXPOSES`), or deterministic test association (`TESTS`).
- **0.80**: Unique global symbol match without explicit import statement.
- **0.50**: Ambiguous heuristic candidate among multiple symbols.

---

## 4. Empirical Benchmark Results

Evaluated against deterministic ground truth in `backend/tests/test_relationship_accuracy_benchmark.py`:

### Benchmark Metric Table

| Relationship Type | Target Languages Tested | Ground Truth Count | Extracted Count | TP | FP | FN | Precision | Recall | F1 Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`CONTAINS`** | Python, TS, Go | 17 | 17 | 17 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`IMPORTS`** | Python, TS, Go | 7 | 7 | 7 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`DEPENDS_ON`**| Python, TS, Go | 2 | 2 | 2 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`EXTENDS`** | Python, TypeScript | 2 | 2 | 2 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`IMPLEMENTS`**| TypeScript | 1 | 1 | 1 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`CALLS`** | Python, TS, Go | 7 | 7 | 7 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`EXPOSES`** | Python (FastAPI) | 1 | 1 | 1 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`TESTS`** | Python, TS, Go | 3 | 3 | 3 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **`DEFINES`** | Python (SQLAlchemy) | 1 | 1 | 1 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |
| **OVERALL** | Multi-Language | 41 | 41 | 41 | 0 | 0 | **1.0000** | **1.0000** | **1.0000** |

---

## 5. False Positive & False Negative Analysis

### 1. Line Boundary Isolation (Fixed)
- *Observed Challenge*: In compact single-file definitions, functions sharing contiguous lines caused `CALL_PATTERN` regex to scan subsequent function headers.
- *Remedy*: Exact AST-derived `start_line` and `end_line` slicing ensures each symbol body is strictly isolated from neighboring declarations.

### 2. Multi-Language Test Case Heuristics (Enhanced)
- *Observed Challenge*: Standard test runners use differing naming conventions (`test_xyz` in Python, `*.test.ts` in TypeScript, `TestXyz` in Go with `_test.go`).
- *Remedy*: Added multi-language test detector supporting Go `Test[A-Z]` prefix and `_test.go` filename patterns, achieving 100% recall across Python, TS, and Go tests.

### 3. Framework Boilerplate Filtering
- *Observed Challenge*: Classes inheriting from standard library or ORM base classes (`object`, `BaseModel`, `Base`) created noise edges if treated as repository internal dependencies.
- *Remedy*: Framework base classes are filtered from internal `EXTENDS` traversal unless explicitly defined as repository code symbols.

---

## 6. Audit Conclusion

The relationship extraction engine achieves high fidelity and deterministic repeatability. All relationships carry verifiable provenance metadata (`evidence`, `status`, `confidence`), providing a solid foundation for downstream blast radius calculation and contextual agent retrieval.

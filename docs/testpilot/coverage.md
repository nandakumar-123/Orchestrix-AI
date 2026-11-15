# TestPilot Coverage Intelligence

## Overview

The `CoverageAnalyzer` (`app.services.testpilot.coverage`) parses code coverage reports from `coverage.py` (Python) and `c8` / Istanbul / Vitest (Node.js/TypeScript).

## Critical Metric Integrity: Preserving Null Branch Coverage

Many repositories track statement/line coverage without enabling branch instrumentation (e.g. `pytest --cov` without `--cov-branch`).

- **Antipattern**: Setting `branch_coverage = 0.0` when unmeasured falsely signals 0% branch testing.
- **Orchestrix Standard**: When branch coverage is not instrumented or unmeasured, `branch_coverage` is explicitly set to `None`. It is never defaulted to `0.0`.

## Coverage Aggregation

- **Line Coverage**: Ratio of covered statements to total executable statements.
- **Branch Coverage**: Ratio of covered conditional branches to total possible branches (or `None`).
- **Uncovered Lines Mapping**: Granular per-file mapping of missing line numbers and uncovered branches.
- **Persistence**: Summary stored in `TestPilotCoverageReport` with structured JSON details in `file_coverages`.

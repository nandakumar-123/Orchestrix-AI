# DevPilot Multi-Stage Quality Validation

DevPilot guarantees code quality through a 3-stage validation coordinator before completing any task.

## Validation Stages

### Stage 1: Syntactic AST Verification (`SYNTAX_AND_AST`)
- Feeds each generated or modified file into Tree-sitter parsers corresponding to the file's extension.
- Confirms the resulting AST contains no `ERROR` or `MISSING` nodes.
- Flags malformed syntax or unclosed blocks as validation failures.

### Stage 2: ImpactMind Regression Blast Radius (`IMPACTMIND_REGRESSION`)
- Generates a synthetic diff of all modifications.
- Runs Phase 11 `ImpactMindEngine.analyze_impact()` on the diff.
- Recalculates the heuristic structural exposure score (0 - 100) and exposure tier (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- Categorizes modified symbols and verifies no unexpected public contracts were broken.

### Stage 3: Controlled Test Run (`CONTROLLED_TEST_RUN`)
- Discovers and executes targeted test suites.
- Validates that test commands conform to the command allowlist (`pytest`, `npm test`, `cargo test`, `go test`).
- Enforces execution timeouts and captures structured exit codes, stdout, stderr, and pass/fail statistics.

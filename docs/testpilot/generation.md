# TestPilot AI Test Generation & Quality Gates

## Overview

The `TestGenerator` (`app.services.testpilot.generator`) leverages repository context, AST intelligence, and LLM reasoning to synthesize targeted test cases.

## Test Categorization

Test cases are classified into distinct testing facets:
- **Unit**: Isolated verification of individual functions, methods, or classes.
- **Edge Case**: Boundary limits, off-by-one conditions, large inputs, unicode sequences.
- **Negative / Exception**: Explicit error triggering, parameter type mismatches, unauthorized access, invalid states.
- **Integration**: Component interactions, database query execution, API contract conformance.
- **Regression**: Validation for recently modified code paths to guard against unintended breakage.

## Strict Quality Gates

Every generated test case must pass rigorous static validation filters before ingestion:
1. **Tautology Rejection**: Rejects assertions that cannot fail:
   - `assert True`
   - `assert 1 == 1`
   - `expect(true).toBe(true)`
2. **Placeholder Rejection**: Rejects incomplete or stubbed test functions containing:
   - `TODO`
   - `FIXME`
   - Unhandled `pass` bodies without assertions
3. **Execution Guard**: Generated test suites are saved in database with status `GENERATED`. No test file is written to the repository and no process is spawned until a user explicitly approves the suite.

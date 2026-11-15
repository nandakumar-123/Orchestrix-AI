# TestPilot Architecture & Execution Flow

## Overview

**TestPilot** is Orchestrix AI's autonomous software testing agent. It operates as a repository-aware verification and test automation engine capable of detecting project testing conventions, synthesizing idiomatic test suites, executing tests in isolated sandboxes, diagnosing execution failures, analyzing branch and line coverage, and selecting targeted regression tests via ImpactMind.

## Key Architectural Principles

1. **Strict Human Approval Gate**: Generated tests are never committed or executed without explicit human approval. Newly synthesized suites remain in `GENERATED` status until reviewed.
2. **Environment & Sandbox Isolation**: Test executions run inside ephemeral workspace copies or sandboxed subdirectories bounded by Windows Job Objects (or POSIX process groups), CPU limits, and strict wall-clock timeouts.
3. **Command Security & Path Traversal Protection**: Commands are verified against strict allowlists (e.g., `pytest`, `npm test`, `npx vitest`) and disallowed from command chaining (`&&`, `||`, `;`, `|`), subshell execution, or executing outside the designated workspace.
4. **Pre-LLM Secret Redaction**: Stack traces, error logs, and source snippets are scrubbed of secrets, bearer tokens, and API credentials before submission to LLMs for diagnosis or test generation.
5. **Accurate Coverage Metrics**: Coverage analysis preserves `None` for unmeasured branch coverage, preventing false 0.0% metrics from misrepresenting actual testing rigor.

## Core Component Diagram

```
+---------------------------------------------------------------------------------+
|                                 TestPilotService                                |
+---------------------------------------------------------------------------------+
       |                  |                |                  |            |
       v                  v                v                  v            v
+-------------+   +---------------+   +------------+   +------------+ +-----------+
|  Framework  |   | AI Test       |   | Controlled |   | Failure    | | Coverage  |
|  Detector   |   | Generator     |   | Runner     |   | Diagnoser  | | Analyzer  |
+-------------+   +---------------+   +------------+   +------------+ +-----------+
       |                  |                |                  |            |
       |                  v                v                  |            |
       |          [Human Approval]  [Job Object/Env]          |            |
       |                  |                |                  |            |
       +------------------+----------------+------------------+------------+
                                  |
                                  v
                    +---------------------------+
                    |  PostgreSQL Database      |
                    |  (TestPilotSuite/Case/    |
                    |   Execution/Coverage)     |
                    +---------------------------+
```

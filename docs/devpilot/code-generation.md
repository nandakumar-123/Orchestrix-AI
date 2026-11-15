# DevPilot Code Generation & Sandbox Management

DevPilot isolates all code generation activities inside dedicated workspace sandboxes before any code can touch the repository.

## Isolated Workspace Sandbox

- **Directory Isolation**: Created under `.task_workspaces/<task_id>/`.
- **Path Traversal Protection**: Every file path is validated via `TaskWorkspaceManager.validate_relative_path()`. Attempting to reference `..`, absolute drives, or symbolic links escaping the sandbox raises `ValueError("Directory traversal detected")`.
- **Conflict Detection**: Prior to modifying any file, the manager compares baseline file timestamps and hashes to prevent overwrite collisions.
- **Unified Diff Generation**: Differences between the base repository snapshot and modified files are computed using standard unified diff format with line addition and deletion counts.

## LLM Provider Hierarchy & Fallback

```
1. Gemini Provider (Primary)
   └── Model: gemini-1.5-flash / gemini-1.5-pro
   └── Fast completion, structured JSON formatting

2. Mistral Provider (Secondary Fallback)
   └── Model: mistral-large-latest / codestral-latest
   └── Code-specialized completions if primary quota is exhausted

3. Deterministic Fallback Engine (Reliability Guarantee)
   └── Produces production-compliant templates and test skeletons
   └── Guarantees agent availability during upstream cloud API disruptions
```

## Secret Scrubbing

All inputs and generated code undergo automated credential scrubbing:
- Regex redaction of GitHub PATs, JWT tokens, AWS keys, database connection strings, and private keys.
- Replaces matches with `[REDACTED_SECRET]` before database persistence or API exposure.

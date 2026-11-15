# DevPilot Context Retrieval & Assembly

DevPilot avoids generic prompt stuffing by assembling an evidence-based multi-layer context from Orchestrix AI's preceding intelligence engines.

## 3-Tier Context Architecture

### 1. Phase 8 AST & Symbol Intelligence
- Parses repository source code across 40+ supported languages using Tree-sitter.
- Extracts symbol definitions (functions, classes, methods, interfaces, and signatures).
- Indexes files and detects active framework conventions (FastAPI, React, Django, Express, etc.).

### 2. Phase 9 Hybrid Semantic Search
- Uses FastEmbed (`all-MiniLM-L6-v2`) to embed user queries and match relevant code chunks stored in PostgreSQL (`pgvector`).
- Merges semantic similarity scores with lexical AST symbol matches.
- Filters search results to repository snapshot boundaries, preventing cross-tenant leakage.

### 3. Phase 10 Knowledge Graph Caller Traversal
- Queries Neo4j / graph providers for upstream callers and downstream dependencies of identified symbols.
- Identifies indirect blast radius up to 3 hops deep.
- Surfaces caller signatures to ensure proposed changes maintain backward compatibility.

## Ambiguity and Intent Verification

The context builder inspects the incoming user prompt:
- **Short Prompts (< 15 characters)**: Marked as `NEEDS_CLARIFICATION` with suggestions to provide concrete requirements.
- **Destructive Commands**: Prompts requesting `rm -rf`, `DROP DATABASE`, or mass code deletion are rejected with safety violations.
- **Context Budgeting**: Context items are dynamically ranked and capped at token budgets to prevent prompt dilution and truncation.

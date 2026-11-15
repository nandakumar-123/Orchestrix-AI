# TestPilot Framework & Convention Detection

## Purpose

The `FrameworkDetector` (`app.services.testpilot.detector`) inspects repository manifests, directory structures, and file naming patterns to determine the primary test framework and conventions without executing untrusted code.

## Supported Frameworks

| Language | Framework | Typical Config Files | Default Test Directory | Naming Convention |
| :--- | :--- | :--- | :--- | :--- |
| Python | `pytest` | `pytest.ini`, `pyproject.toml`, `setup.cfg` | `tests`, `test` | `test_*.py`, `*_test.py` |
| Python | `unittest` | `pyproject.toml`, standard library fallback | `tests`, `test` | `test_*.py` |
| TypeScript / JavaScript | `vitest` | `vitest.config.ts`, `vite.config.ts` | `tests`, `__tests__`, `src` | `*.test.ts`, `*.spec.ts` |
| TypeScript / JavaScript | `jest` | `jest.config.js`, `jest.config.ts` | `tests`, `__tests__` | `*.test.js`, `*.spec.js` |
| JavaScript | `mocha` | `.mocharc.json`, `.mocharc.yml` | `test`, `tests` | `*.test.js` |

## Confidence Scoring Heuristics

1. **Manifest Direct Declaration (+0.50)**: Presence of explicit framework settings in configuration manifests (e.g. `[tool.pytest.ini_options]` in `pyproject.toml`).
2. **Directory Conventions (+0.25)**: Dedicated testing directories (`tests/`, `__tests__/`).
3. **Naming Patterns (+0.15)**: Files following framework naming conventions (`test_*.py`, `*.spec.ts`).
4. **Runner Availability (+0.10)**: Verification that the framework executable exists in the runtime environment.
5. **Fallback Behavior**: When no recognized framework or test configuration is detected, raises `FrameworkNotSupportedError` with diagnostic recommendations.

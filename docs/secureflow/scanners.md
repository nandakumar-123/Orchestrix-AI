# SecureFlow Scanners & Tool Integrations

## 1. pip-audit (Python Dependencies)

- **Tool**: `pip-audit`
- **Manifests Inspected**: `requirements.txt`, `pyproject.toml`, `Pipfile.lock`, `setup.py`
- **Output Format**: Structured JSON parsed into `NormalizedFinding`
- **Severity Mapping**: Mapped from advisory score or severity ratings (Critical, High, Medium, Low)
- **Remediation**: Recommends upgrading to patched versions listed in advisory

## 2. npm audit (Node.js Dependencies)

- **Tool**: `npm audit --json`
- **Manifests Inspected**: `package.json`, `package-lock.json`
- **Output Format**: Structured JSON parsed into `NormalizedFinding`
- **Severity Mapping**: Direct mapping from npm vulnerability severities
- **Remediation**: Specific patch versions or `npm audit fix` advisories

## 3. Semgrep (Static Application Security Testing)

- **Tool**: `semgrep scan --json`
- **Rulesets**: OWASP Top 10 rulesets covering:
  - `A01:2021` - Broken Access Control / Path Traversal
  - `A02:2021` - Cryptographic Failures
  - `A03:2021` - Injection (SQLi, Command Injection, XSS)
  - `A07:2021` - Identification & Authentication Failures
  - `A08:2021` - Software & Data Integrity Failures (Insecure Deserialization / Pickle)
- **Unavailability Guarantee**: If the Semgrep binary is absent from the host, the scanner status is explicitly reported as `UNAVAILABLE`. The scan will never report 0 findings as clean.

## 4. OSV API (Universal Advisory Querying)

- **Endpoint**: `https://api.osv.dev/v1/query`
- **Timeout**: 30.0 seconds with graceful fallback
- **Usage**: Enriches package vulnerabilities with unified CVE, GHSA, and commit fix ranges.

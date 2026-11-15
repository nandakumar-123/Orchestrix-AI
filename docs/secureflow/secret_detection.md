# SecureFlow Secret Detection & Pre-LLM Redaction

## Secret Detection Rules

The `SecretScanner` (`app.services.secureflow.secret_scanner`) and `redaction` engine (`app.services.secureflow.redaction`) identify credentials matching high-precision compiled regular expressions and Shannon entropy:

1. **GitHub Tokens**:
   - Classic Personal Access Tokens (`ghp_[a-zA-Z0-9]{36}`)
   - OAuth Access Tokens (`gho_[a-zA-Z0-9]{36}`)
   - Fine-grained Personal Access Tokens (`github_pat_[a-zA-Z0-9_]{82}`)
2. **Google Cloud / Gemini API Keys**:
   - Key strings starting with `AIza` (`AIza[0-9A-Za-z\-_]{35}`)
3. **Amazon Web Services (AWS)**:
   - AWS Access Key IDs (`AKIA...`, `ASIA...`, `AROA...`)
   - AWS Secret Access Keys (`aws_secret_access_key` assignment patterns)
4. **Private Cryptographic Keys**:
   - PEM blocks (`-----BEGIN [A-Z ]*PRIVATE KEY-----`)
5. **Database Connection Strings**:
   - URLs containing embedded plaintext passwords (`postgres://user:password@host/db`)
6. **Authentication Tokens**:
   - JSON Web Tokens (`eyJ...`)
   - Slack bot and user tokens (`xoxb-...`, `xoxp-...`)
   - Bearer token headers

## File Eligibility & Entropy Bounds

- **Excluded Extensions**: Binaries, media, fonts, archives, and lockfiles (`.lock`, `.png`, `.exe`, etc.).
- **Size Bounds**: Files strictly bounded to 1 MB maximum scan size.
- **Shannon Entropy Check**: High-entropy strings (> 4.5 bits/char) assigned to variable declarations are scrutinized to detect novel API keys while ignoring UUIDs, git hashes, and standard base64 identifiers.

## Pre-LLM Redaction Standard

**CRITICAL MANDATE**: Raw credentials must NEVER be sent to an LLM provider, stored in plain database evidence, or logged to application standard streams.
- `sanitize_evidence_line`: Replaces captured secret bytes with `[REDACTED_SECRET]` while preserving line code context.
- `redact_data_structure`: Recursively sanitizes dicts and lists before serialization.

# SecureFlow Finding Lifecycle & Deduplication

## Deterministic Fingerprinting

Every security finding is indexed by a deterministic SHA-256 fingerprint hash:
$$\text{fingerprint} = \text{SHA256}(\text{rule\_id} + ":" + \text{file\_path} + ":" + \text{line\_start} + ":" + \text{line\_end} + ":" + \text{title})$$

This fingerprint remains constant across repeated scans when the underlying vulnerability remains unaddressed.

## Repository-Scoped Deduplication

When recurrent scans run against a repository:
1. If a finding with matching `(repository_id, fingerprint)` already exists:
   - The existing finding entity is updated in place.
   - `last_seen_at` is updated to the current timestamp.
   - `scan_id` is updated to point to the latest scan session.
   - No duplicate record is inserted.
2. If the finding is new:
   - A new row is inserted into `secureflow_findings` with `status = OPEN`.

## Status Lifecycle Transitions

Findings advance through an audited lifecycle managed by `FindingManager`:
- **OPEN**: Default state upon initial detection.
- **CONFIRMED**: Validated by security engineer or team lead.
- **FALSE_POSITIVE**: Triaged as safe or intentional code pattern.
- **ACCEPTED_RISK**: Acknowledged risk with deliberate business justification.
- **RESOLVED**: Remediated through code modification or package upgrade.

All state transitions emit an immutable audit event recorded in `SecureFlowScanEvent`.

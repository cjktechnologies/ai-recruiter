# Security Model

## Assets and trust boundaries

Assets: candidate PII and documents, interview transcripts, evaluations, compensation data, credentials, audit trail.
Boundaries: the internet → WAF/ALB → web BFF → API → data stores; API → third parties (LLMs, calendars, messaging,
HRIS); inbound webhooks. Candidate-supplied content (CVs, answers, chat) is **untrusted everywhere**, including inside
AI prompts.

## Controls mapped to OWASP ASVS / API Security Top 10

| Risk (OWASP API Top 10 2023) | Controls | Evidence |
|---|---|---|
| API1 Broken object-level authorization | Every tenant row is fetched through `get_scoped` (org match, else 404); panel-only interview access; candidates see only their own applications | `test_tenant_isolation`, portal tests |
| API2 Broken authentication | Argon2id hashing; 12+ char password policy; lockout after 5 failures; 15-min JWT (issuer, audience, exp, typ checked); rotating refresh tokens stored as HMAC digests with **family revocation on reuse**; OIDC with state + nonce + JWKS verification; httpOnly cookies in the browser | `test_login_refresh_rotation_and_reuse_detection`, `test_account_lockout_after_failed_logins`, `test_jwt_roundtrip_and_tampering` |
| API3 Broken object-property authorization | Explicit response schemas; answer keys never in candidate schemas; phone hidden without `candidates:read_pii`; secrets write-only | Lifecycle test asserts no `correct_answer` leaks |
| API4 Unrestricted resource consumption | Per-user and per-IP rate limits, WAF rate rule, upload size limits, page-size cap (200), PDF page and DOCX expansion limits, LLM max tokens | `test_public_rate_limit` |
| API5 Broken function-level authorization | 72 permissions × 8 roles; `require()` on every route; privilege-escalation guard (you can't grant what you don't hold); super-admin-only tenant provisioning | `test_rbac_matrix`, `test_privilege_escalation_prevented` |
| API6 Unrestricted access to sensitive business flows | Human gates in the state machine; segregation of duties on approvals, selection and offers; idempotency keys | Lifecycle tests |
| API7 SSRF | No user-supplied URLs are fetched; integration endpoints are admin-configured; calendar/HRIS hosts are fixed per adapter | Code review |
| API8 Security misconfiguration | Strict security headers (CSP, HSTS, XFO, nosniff), CORS allow-list, production refuses default secrets, non-root read-only containers, restricted pod security, NetworkPolicies | `test_security_headers_and_problem_details`, `test_production_requires_real_secrets` |
| API9 Improper inventory management | URI versioning; OpenAPI exported and diffed in CI | CI `OpenAPI drift` step |
| API10 Unsafe consumption of APIs | LLM outputs validated against strict JSON schemas; refusal/truncation handled; webhook signatures (HMAC + timestamp tolerance) verified | `test_anthropic_provider_structured_output_and_refusal` |

## Input and output validation

- Pydantic models with lengths, ranges and patterns on every input; unknown sort fields rejected; SQL is always
  parameterised by SQLAlchemy.
- Output: typed response models; problem+json errors without stack traces; HTML is never rendered from user content.

## Secure document processing

1. Size limit (`MAX_UPLOAD_MB`), filename sanitisation (no path traversal).
2. Magic-byte type detection; the extension and declared type must match the real type.
3. Rejects DOCX with macros (`vbaProject.bin`), PDFs with JavaScript/Launch/EmbeddedFile, encrypted PDFs, zip bombs.
4. Malware scan: ClamAV `INSTREAM` in deployed environments (`REQUIRE_MALWARE_SCAN=true` blocks processing if the
   scanner is unavailable); EICAR detection in all environments. Infected files are deleted and quarantined in the audit
   log; downloads of pending or infected files are refused.
5. Text is sanitised and injection-checked before any AI processing.
6. Stored in a private, KMS-encrypted, versioned bucket; served only through authorised, audited downloads with
   `Content-Disposition: attachment` and `nosniff`.

## Encryption

- In transit: TLS 1.2+ at the ALB (TLS 1.3 policy), `rds.force_ssl=1`, Redis TLS, S3 `aws:SecureTransport` deny.
- At rest: KMS CMKs with rotation for RDS, ElastiCache, S3, ECR, EKS secrets, Secrets Manager, SNS; app-level Fernet for
  phone numbers, CV text, transcripts and integration credentials (`DATA_ENCRYPTION_KEY`, rotated via re-encryption job).

## Secrets management

No secrets in source control (gitleaks in CI). Runtime secrets live in AWS Secrets Manager and are synced by External
Secrets Operator. CI/CD uses GitHub OIDC, so there are no stored cloud keys. Logs redact e-mails, phone numbers, bearer
tokens and API keys (`app/core/logging.py`), verified by `test_logs_never_contain_candidate_pii`.

## Supply chain

Pinned dependencies; pip-audit and npm audit; CodeQL (security-extended); Trivy image scans (fail on fixable
HIGH/CRITICAL); SBOM and provenance attached to images; immutable ECR tags with scan-on-push.

## Audit

Append-only `audit_logs` (DB trigger) captures actor type (user, agent, system, candidate), action, entity, redacted
diff, IP, user agent and request ID. That covers logins, failed logins, PII views, downloads, exports, erasures, every
decision and every AI action.

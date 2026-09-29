# Administrator Guide

## Getting a tenant running (Org Admin)

1. **Sign in** with the credentials from your provisioning e-mail, or SSO if configured.
2. **Administration → Departments:** add departments.
3. **Administration → Users:** invite users with roles:
   - HR Manager, Recruiter, Hiring Manager, Interviewer, Finance/Approver.
   - Custom roles (API `POST /roles`) can combine any permissions you hold.
4. **Administration → Compensation:** define approved bands per job level. The Offer agent stays within them;
   out-of-band offers automatically require Finance approval.
5. **Administration → Integrations:**
   - Calendar: Google Calendar or Microsoft Graph (`config.organizer_email`, secret `access_token`).
   - HRIS: `hris_webhook` (`config.url`, secret `signing_secret`). The platform posts HMAC-signed `employee.hired`
     events.
   - Background checks: `background_check` (secret `signing_secret`). Providers post results to
     `/api/v1/webhooks/background-checks/{id}` with `X-Timestamp` and `X-Signature: sha256=<hmac>`.
   - Secrets are encrypted and never shown again; rotate by saving a new secret.
6. **Administration → AI governance:** choose whether AI screening runs automatically, whether consent is required,
   interview summaries, the adverse-impact threshold (default 0.8) and data retention days. Add FAQ entries for the
   candidate assistant through `PUT /governance/policy` (`faq: [{q, a}]`).
7. **Question bank and interview templates:** Assessments page and `POST /interview-templates`.

## SSO (OIDC)

Set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` and `OIDC_REDIRECT_URI=https://<host>/api/session/oidc`.
Users are matched by verified e-mail or subject. Unknown users are provisioned only into `OIDC_DEFAULT_ORG_SLUG` with the
least-privileged role (Interviewer); an admin then assigns roles.

## Data protection duties (HR Manager)

- **Erasure requests** arrive as notifications. Open the candidate and choose *Erase data* (irreversible).
- **Access requests:** *Export (DSAR)* on the candidate profile.
- **Retention:** runs nightly; *Apply retention now* runs it on demand.
- **Fairness:** review Analytics → Fairness monitoring weekly. Investigate criteria when a group falls below the
  threshold; alerts also appear as critical insights.

## Monitoring AI

AI agents page: failures, guardrail flags (e.g. `injection:*`, `protected_attribute_reference`), human–AI agreement
and workflows waiting on each human gate. A low agreement rate is a signal to revisit requirements and thresholds.

# Security policy

## Reporting a vulnerability

Do not publish passwords, API keys, router credentials, customer information or exploit details in public issues. Contact the RIS project maintainer privately and include the affected release, impact and reproducible steps. Rotate any credential that may have been exposed.

## Deployment requirements

- Never commit or distribute `.env`, database files, backups or runtime logs.
- Use unique production secrets for every deployment. Keep `RIS_SECRET_KEY`, `RIS_PASSWORD_PEPPER`, `RIS_OTP_PEPPER` and `RIS_CREDENTIALS_KEY` in a secrets manager where possible.
- Put production traffic behind HTTPS and a trusted reverse proxy.
- Disable development OTP previews and simulated payments in production.
- Restrict database, router-management and FreeRADIUS ports to trusted networks.
- Use least-privilege database and router accounts; do not reuse administrator credentials.
- Back up databases and encryption keys separately, encrypt backups, and test restoration.
- Do not treat application-level tenant filters as a substitute for database-level tenant isolation and an independent security review.

## Scope

RIS v1.0.0 is an initial public release, not a production security certification. See `CODE-AUDIT-AND-ROADMAP.md` for known gaps and required validation.

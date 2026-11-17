# Security and access model

## Authorization matrix

| Resource or workflow | Public | Viewer / Auditor | Engineer / Operator | Administrator |
|---|---:|---:|---:|---:|
| Static landing page, dashboard shell, API and ML liveness/health | Read | Read | Read | Read |
| Workbench statistics, vendor catalog, saved runs, run details and HTML reports | No | Read | Read | Read |
| Saved suites and stored meter profiles | No | Read | Read | Read |
| Generate payloads, execute validation/transformation, compare, roundtrip, create/run suites | No | No | Use | Use |
| ML validation, batch validation and explanations | No | No | Use | Use |
| User listing/creation, role and active-state changes, password reset | No | No | No | Manage |
| Audit events and operational/user-journey aggregates | No | No | No | Read |

Health endpoints intentionally disclose only service status and dependency readiness. API
data, stored payload previews, meter history, and reports are never public. The Viewer
role can inspect stored validation outputs but cannot submit readings or trigger workflows
that write data.

## Authentication modes

- `demo`: local password authentication. On an empty database only, the first
  administrator is initialized from `VIDYUTSETU_INITIAL_ADMIN_PASSWORD`; if omitted,
  a cryptographically random one-time password is printed to the local server console.
- `password`: controlled deployments use the same local account store and must provide
  `VIDYUTSETU_INITIAL_ADMIN_PASSWORD` for first initialization. Do not use the demo
  mode's console bootstrap in production.
- `disabled`: development/test compatibility only; startup refuses this mode when
  `VIDYUTSETU_ENV=production`.

Sessions use random, opaque, server-stored tokens in `HttpOnly`, `SameSite=Strict`
cookies. Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes. Cookie-authenticated
write requests require a CSRF header; API clients may instead send a session token as
an explicit Bearer token. Sessions expire and logout revokes the active token.

The authentication boundary is provider-oriented, but no BESCOM SSO, identity provider,
or access proxy is configured or claimed. A production BESCOM deployment must obtain
the approved identity integration, TLS termination, secrets management, and operational
security requirements before enabling that integration.

## Audit and data handling

Application request logs contain a request identifier, route template, status, and
duration, never request bodies, passwords, session values, or raw meter payloads.
Authentication and protected API accesses are recorded without payload contents.
Meter payloads remain in the configured SQLite database; restrict its file and volume
permissions and include it in protected backups.

Rate limiting is applied to login attempts in the application. It is not a substitute
for a centrally shared limiter when running multiple application workers; controlled
deployments should also configure rate limiting at the approved reverse proxy.

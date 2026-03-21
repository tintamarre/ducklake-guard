# Security Policy

This is an early-access hobby project, not a production-grade product. It is shared publicly for learning and collaboration. That said, any security reports are appreciated and an effort will be made to integrate them.

If you discover a vulnerability, **do not open a public issue.** Instead, use [GitHub's private vulnerability reporting](https://github.com/berndsen-io/ducklake-guard/security/advisories/new) or email the maintainer directly.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Impact assessment (what an attacker could achieve)
- Suggested fix, if you have one

### Response timeline

This is a side project maintained by one person. I'll do my best to respond promptly, but there are no guaranteed SLAs. Expect best-effort responses.

## Scope

Security issues relevant to this project include:

- Policy bypass (S3 or RLS enforcement failures)
- Privilege escalation through the CLI or database layer
- Credential leakage through logs, error messages, or generated files
- SQL injection or other injection attacks

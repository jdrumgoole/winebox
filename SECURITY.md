# WineBox Security Documentation

## Architecture

### Single-Tenant Design

WineBox is designed as a **personal wine cellar management application**. It follows a single-tenant architecture where:

- One instance serves one user (or household)
- All wines and transactions are shared within that instance
- There is no user-level data isolation by design

This design decision is intentional for several reasons:

1. **Simplicity**: A personal cellar doesn't require complex multi-user permissions
2. **Performance**: No per-query user filtering overhead
3. **Use Case**: Households typically share a wine collection

**Important**: If deploying WineBox for multiple separate users, each should have their own instance with separate databases.

### Authentication

- JWT-based authentication with 2-hour token lifetime
- Argon2 password hashing (industry standard)
- Token revocation via blacklist
- Account lockout after failed login attempts
- Rate limiting on authentication endpoints

### Security Headers

The application sets comprehensive security headers:

- `Content-Security-Policy` with nonces for inline scripts
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security` (when HTTPS enforced)
- `Permissions-Policy` restricting browser features

### API Security

- All API endpoints require authentication (except health check)
- Rate limiting: 60 requests/minute globally, 30/minute for auth
- File upload size limits (10 MB default)
- Input validation via Pydantic models

## Configuration Security

### Secrets Management

Secrets are loaded from environment variables or `secrets.env`:

- `WINEBOX_SECRET_KEY` - JWT signing key (required in production)
- `WINEBOX_ANTHROPIC_API_KEY` - Claude API key (optional)
- `WINEBOX_AWS_ACCESS_KEY_ID` - AWS credentials for SES (optional)
- `WINEBOX_AWS_SECRET_ACCESS_KEY` - AWS secret (optional)

**Never commit secrets to version control**. The `.gitignore` excludes `.env` and `secrets.env`.

### Production Checklist

1. Set a strong `WINEBOX_SECRET_KEY` (minimum 32 characters)
2. Enable `enforce_https = true` in config
3. Use MongoDB Atlas or authenticated MongoDB instance
4. Set `debug = false`
5. Configure CORS origins explicitly if needed

## Dependency Security

Run regular security audits:

```bash
uv run pip-audit
```

## Reporting Security Issues

If you discover a security vulnerability, please report it responsibly by contacting the maintainers directly rather than opening a public issue.

# Daily Security Review — Scheduled Agent Prompt

Copy this prompt into the scheduled agent at https://claude.ai/code/scheduled

---

You are a security reviewer for the WineBox project (a FastAPI + MongoDB wine cellar app). Perform a comprehensive daily security audit and report all findings.

## 1. Dependency Vulnerability Check
- Read pyproject.toml and uv.lock to identify all dependencies with exact versions
- Use WebSearch to check each major dependency for known CVEs or security advisories published in the last 90 days. Search for: "[package name] CVE 2026", "[package name] security advisory", "[package name] vulnerability"
- Key packages to check: fastapi, uvicorn, pymongo, pydantic, pyjwt, cryptography, anthropic, pillow, httpx, jinja2, python-multipart, slowapi, openpyxl
- Flag any dependency that is more than 2 major versions behind the latest release
- Check if any dependency has been yanked or compromised (supply chain attacks)

## 2. Hardcoded Secrets Scan
- Search the entire codebase (excluding .env, secrets.env, and node_modules) for patterns:
  - API keys: `sk-`, `pk_`, `phc_`, `api_key = "`, `token = "`, `AKIA`
  - Connection strings: `mongodb://`, `mongodb+srv://`, `postgres://`, `redis://`
  - Passwords: `password = "`, `passwd = "`, `secret = "` (excluding test fixtures using obvious dummy values like "testpassword")
  - Private keys: `BEGIN RSA`, `BEGIN EC`, `BEGIN PRIVATE`
  - JWTs: `eyJ` followed by base64 characters
- Check if any sensitive files are tracked in git: `git ls-files | grep -iE '\.env|\.key|\.pem|secret|credential|\.p12|\.pfx'`
- Verify .gitignore covers: .env, secrets.env, *.pem, *.key, *.p12

## 3. Authentication & Authorization Audit
- Read winebox/main.py to find all registered routers and their URL prefixes
- For EVERY endpoint in winebox/routers/ (including sub-modules like winebox/routers/wines/):
  - Check that endpoints handling user data require authentication (RequireAuth or RequireAdmin)
  - Verify that database queries for user-owned data filter by owner_id
  - Flag any endpoint that returns data without owner_id scoping
- Check that admin endpoints use RequireAdmin, not just RequireAuth
- Verify that password change/reset invalidates existing tokens
- Check that user registration validates email format and password strength
- Verify constant-time password comparison is used (not == for passwords)

## 4. NoSQL Injection & Query Safety
- Search for any place where user input from request parameters, form data, or JSON body is interpolated directly into MongoDB query filters
- Check for unsafe operators that could be injected: $where, $expr, $function, $accumulator
- Look for regex patterns built from user input — verify re.escape() is used
- Verify that all ObjectId parsing from URL parameters is wrapped in try/except
- Check that $in queries don't accept unbounded arrays from user input
- Look for any raw pymongo collection access that bypasses the MongoDocument model's safety

## 5. Input Validation & Injection
- Check that all API inputs use Pydantic models for validation
- Look for any endpoint that accepts raw dict or untyped JSON body
- Verify file upload endpoints validate file type, size, and content
- Check for any HTML/JS injection vectors in responses (especially in Jinja templates or HTML generation)
- Verify that user input used in filenames is sanitised (path traversal prevention)
- Check search endpoints for regex injection (user input in re.compile without re.escape)

## 6. Rate Limiting & DoS Prevention
- Check that ALL auth endpoints have rate limits (login, register, password reset, token refresh)
- Verify search and expensive computation endpoints are rate-limited
- Check for any endpoint that could trigger unbounded database queries (missing pagination limits)
- Look for any endpoint that accepts a user-controlled limit/skip parameter without a maximum cap
- Check that file upload sizes are bounded
- Verify database query timeouts are configured

## 7. Session & Token Security
- Check JWT token configuration: algorithm, expiry time, secret key handling
- Verify tokens include a jti (JWT ID) for revocation support
- Check that token revocation actually works (revoked tokens are rejected)
- Verify that password changes invalidate all existing tokens for that user
- Check for any token leakage in logs, error messages, or API responses
- Verify HTTPS is enforced in production (redirect HTTP to HTTPS)

## 8. Security Headers
- Check that responses include security headers: X-Content-Type-Options, X-Frame-Options, Content-Security-Policy, Strict-Transport-Security
- Verify no inline scripts (CSP compliance)
- Check CORS configuration — ensure it's not set to allow all origins

## 9. Data Exposure
- Check API responses for any fields that should not be exposed (hashed passwords, internal IDs, system metadata)
- Verify that error messages don't leak internal details (stack traces, database names, file paths)
- Check that debug mode / verbose error responses are disabled in production configuration
- Look for any logging of sensitive data (passwords, tokens, API keys)

## 10. Git History & Recent Changes
- Run: git log --oneline -30 to review recent commits
- Check the last 30 commits for any that might have introduced security issues
- Run: git log --all --oneline -10 --diff-filter=A -- '*.env' '*.key' '*.pem' '*secret*' '*credential*' to check for accidentally committed secrets
- Check if any security-related files were recently modified (auth.py, settings.py, middleware)

## 11. Infrastructure & Configuration
- Check winebox/config/settings.py for secure defaults
- Verify that production settings differ from development (debug=False, HTTPS enforced, etc.)
- Check nginx configuration if accessible for security headers and SSL settings
- Verify MongoDB connection uses authentication (not unauthenticated localhost in production)
- Check for any hardcoded hostnames or IPs that might indicate environment leakage

## 12. Third-Party Integration Security
- Check Anthropic API key handling — verify it's loaded from environment, not hardcoded
- Check PostHog integration — verify API key is not exposed in client-side code beyond what's necessary
- Verify that webhook endpoints (if any) validate request signatures
- Check for any external API calls without timeout configuration

## Report & PR

Write your full report to `docs/security-reports/YYYY-MM-DD.md` (using today's date).

Summarise ALL findings using this structure:

### 🔴 CRITICAL (Immediate action required)
Issues that represent active security vulnerabilities or data exposure risks.

### 🟠 WARNING (Address within 1 week)
Issues that could become vulnerabilities or represent defence-in-depth gaps.

### 🟡 INFO (Best practice recommendations)
Suggestions to improve security posture.

### 🟢 CLEAN (Passed review)
Areas that were reviewed and found to be secure.

### 📊 Summary
- Date of review
- Total issues found by severity
- Comparison with previous review (if context available)
- Top 3 priorities for the development team

If the codebase is clean, report a clean bill of health with the date and what was checked.

## File a PR

After writing the report:
1. Create a branch named `security-review/YYYY-MM-DD`
2. Commit the report file to the branch
3. Open a PR with:
   - Title: "Security Review — YYYY-MM-DD"
   - Body: A short summary of findings (number of critical/warning/info issues, or "Clean bill of health")
   - Label the PR severity based on the worst finding:
     - CRITICAL findings: add "security-critical" in the PR title
     - WARNING findings: add "security-warning" in the PR title
     - Clean: add "security-clean" in the PR title

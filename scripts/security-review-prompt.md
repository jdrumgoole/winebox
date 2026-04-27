# Daily Security Review — Scheduled Agent Prompt

Copy this prompt into the scheduled agent at https://claude.ai/code/scheduled

---

You are a security reviewer for the WineBox project (a FastAPI + MongoDB wine cellar app). Perform a comprehensive daily security audit and report all findings.

The project ships **two FastAPI apps from a single PyPI wheel**:
- `winebox.main:app` — the user-facing wine app, served at `booze.winebox.app` (production) and `oat.winebox.app` (OAT) on port 8000.
- `winebox.admin.main:app` — the operator admin panel, served at `admin.winebox.app` (production) and `oatadmin.winebox.app` (OAT) on port 8001, with an nginx-level IP allowlist sourced from `deploy/winebox-admin.toml`.

Both apps share the same secrets, database connection, and `winebox/services/auth.py` primitives. **Every section below applies to both apps unless explicitly noted** — when reviewing routers, models, settings, or middleware, walk both `winebox/routers/` and `winebox/admin/routers/`. Section 15 covers admin-specific concerns (allowlist, dedicated endpoints, isolation between the two apps).

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
- Read `winebox/main.py` AND `winebox/admin/main.py` to find all registered routers and their URL prefixes for both apps.
- For EVERY endpoint in `winebox/routers/` (including sub-modules like `winebox/routers/wines/`) AND in `winebox/admin/routers/`:
  - Check that endpoints handling user data require authentication (`RequireAuth` or `RequireAdmin`).
  - Verify that database queries for user-owned data filter by `owner_id`.
  - Flag any endpoint that returns data without `owner_id` scoping.
- **Every endpoint in `winebox/admin/routers/` MUST use `RequireAdmin`**, never `RequireAuth` alone. The admin app is fronted by an nginx IP allowlist, but defence-in-depth requires app-level admin gating too — flag any admin endpoint that relies solely on the network layer.
- Verify that password change/reset invalidates existing tokens (via `User.tokens_invalidated_after`).
- Check that user registration validates email format and password strength.
- Verify constant-time password comparison is used (not `==` for passwords).

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
- Check `winebox/config/settings.py` for secure defaults.
- Verify that production settings differ from development (debug=False, HTTPS enforced, etc.).
- Check the nginx configurations (`deploy/nginx-winebox.conf`, `deploy/nginx-winebox-oat.conf`) for security headers and SSL settings. Both files now include `admin.winebox.app` / `oatadmin.winebox.app` server blocks proxying to the admin uvicorn worker on `127.0.0.1:8001` — verify those blocks ship the same security headers (HSTS, X-Content-Type-Options, X-Frame-Options) as the main app blocks.
- Verify MongoDB connection uses authentication (not unauthenticated localhost in production).
- Check for any hardcoded hostnames or IPs that might indicate environment leakage. The operator IP `109.255.27.13` is expected only inside `deploy/winebox-admin.toml` and possibly historical tasks/docs — flag any new appearance elsewhere.
- Verify that the systemd units `deploy/winebox.service`, `deploy/winebox-oat.service`, `deploy/winebox-admin.service`, and `deploy/winebox-admin-oat.service` have the same hardening flags (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`). The two admin units in particular share secrets and DB access with the main app — any drift is a defence-in-depth gap.

## 12. Third-Party Integration Security
- Check Anthropic API key handling — verify it's loaded from environment, not hardcoded
- Check PostHog integration — verify API key is not exposed in client-side code beyond what's necessary
- Verify that webhook endpoints (if any) validate request signatures
- Check for any external API calls without timeout configuration

## 13. GitHub Actions Workflow Security

Review every file in `.github/workflows/*.yml` (currently: ci.yml, deploy-oat.yml, nightly.yml, publish.yml, cert-check.yml, email-dns-check.yml). Confirm the list against the live filesystem at review time — flag any new workflow not enumerated here so the next reviewer picks it up.

### 13a. Third-party action pinning
- List every `uses:` directive. Flag any that reference a version tag (e.g. `actions/checkout@v4`) rather than a commit SHA. Tag references can be rewritten by the action author (malicious or otherwise) — SHA pinning defends against supply-chain swaps.
- Specifically check `astral-sh/setup-uv`, `anthropics/claude-code-action`, and any action not maintained by GitHub itself. These third-party actions run with access to the repo and `secrets.*`.

### 13b. Untrusted input injection
- Search for `${{ github.event.* }}` interpolations inside `run:` blocks. Anything from `pull_request.title`, `pull_request.body`, `issue.title`, `issue.body`, `head_ref`, `head.ref`, `comment.body`, `review.body` is attacker-controlled and must NOT be expanded inline into a shell command.
- Safe pattern: read via an env var, e.g. `env: { PR_TITLE: ${{ github.event.pull_request.title }} }` then use `$PR_TITLE` in the script.
- Reference: https://securitylab.github.com/research/github-actions-untrusted-input/

### 13c. Workflow permissions and GITHUB_TOKEN scope
- Every workflow and job should declare `permissions:` at workflow or job level. Absence means default permissions, which are too broad.
- Look for `permissions: write-all` or jobs that grant `contents: write` / `pull-requests: write` without needing them.
- `deploy-oat.yml` and `publish.yml` are the highest-value targets — verify their permissions match what they actually do.

### 13d. `pull_request_target` trigger
- This trigger runs workflows in the context of the target repo with read/write secrets access and checks out the PR head by default — a known exploit vector. Flag any workflow using `pull_request_target`. If one exists, confirm it never checks out the untrusted PR head before validating authorship.

### 13e. Self-hosted runner hardening
- `nightly.yml` uses `runs-on: [self-hosted, oat]` (runner lives on the OAT droplet). Flag if:
  - A self-hosted runner is attached to a public repo without `environment:` gating or a branch filter (`if: github.ref == 'refs/heads/main'`). Forks could otherwise run arbitrary code on the droplet.
  - The runner service runs as root or with sudo NOPASSWD access.
- Verify `nightly.yml` still has its main-branch guard on the deploy job.

### 13f. Secrets exposure
- List every `secrets.*` usage. Each should be justified — confirm that e.g. `WINEBOX_MONGODB_URL` and `WINEBOX_SECRET_KEY` are never logged, echoed, or passed to third-party actions that could exfiltrate them.
- Check for `echo "::add-mask::"` usage when secrets flow into outputs.
- Flag any `if: secrets.X != ''` patterns — those leak the existence of a secret.

### 13g. Cache poisoning
- Look for `actions/cache` usage that keys on user-controlled input (e.g. branch name). A poisoned cache can inject files into subsequent runs.

### 13h. Deploy authorisation
- `publish.yml` pushes to PyPI on tag push. Verify the trigger is `on: { push: { tags: [...] } }` and that only maintainers can push tags (branch/tag protection).
- `deploy-oat.yml` / the self-hosted nightly deploy — check any `environment:` gate (e.g. `oat-deploy`) is still present and that its reviewers list is current.

## 14. PyPI Package Integrity

The project publishes as `winebox` on PyPI via `.github/workflows/publish.yml`. Review the published package surface.

### 14a. Sdist/wheel contents
- Read `pyproject.toml` `[tool.setuptools]` or `[tool.hatch]` / `[build-system]` sections and any `MANIFEST.in` to understand what files ship in the package.
- Run `uv build` locally into a temp dir and list the sdist + wheel contents. Verify NONE of these end up in the package:
  - `.env`, `secrets.env`, `.env.*`
  - `tests/` (unless intentionally included for `winebox --test` style usage)
  - `docs/`, `artifacts/`, `.playwright-mcp/`, `.pytest_cache/`, `.venv/`
  - `deploy/` (contains nginx configs and infra — may leak operator IP allowlists)
  - `tasks.py` (contains production IPs and droplet names)
  - Any `.DS_Store`, `.idea/`, `.vscode/`
- Flag any file that looks like an artifact, screenshot, or secret bleeding into the wheel.

### 14b. Hardcoded environment leaks
- Grep the built wheel for `booze.winebox.app`, `oat.winebox.app`, `104.248.46.96`, `46.101.134.8`, `2t22cum.mongodb.net` (the cluster subdomain), and the operator admin IP `109.255.27.13`. These should not appear in user-facing code that ships to PyPI.
- It's fine for these to appear in infrastructure configs under `deploy/` IF deploy/ is correctly excluded from the sdist.

### 14c. Dependency pinning in the shipped metadata
- Read the `dependencies = [...]` block in pyproject.toml. Each entry should have a lower bound for known-CVE-fixed versions. Flag any dependency pinned to a version with an open advisory (cross-reference with section 1).
- Check that optional/dev-only deps are NOT in the main `dependencies` list — they'd be forced on every downstream consumer.

### 14d. Publication path
- `publish.yml` should use PyPI Trusted Publishing via OpenID Connect (`pypa/gh-action-pypi-publish` without an API token input), not a long-lived `PYPI_API_TOKEN` secret. Token-based publishing is a standing theft risk.
- Confirm the publishing job has `permissions: { id-token: write }` and nothing else.
- Verify the workflow is triggered by tag push, not branch push, and that the tag pattern matches the release naming (e.g. `v*`).

### 14e. Supply-chain bill of materials
- Check whether the wheel or sdist includes a SBOM (`pyproject.toml` `project.urls` → `BOM` or similar). Not required but increasingly expected.
- Check whether releases are signed with sigstore (`pypa/gh-action-pypi-publish` can do this with `attestations: true`). If not signed, note it as INFO.

### 14f. Installed package surface
- Verify what `pip install winebox` actually lets a consumer execute:
  - Console scripts (`[project.scripts]` in pyproject.toml) — list them and confirm none are admin-only tools accidentally exposed.
  - Post-install hooks — Python doesn't run arbitrary post-install scripts like npm does, but any `setup.py` with imperative code is a supply-chain concern. The project uses PEP 621 / `pyproject.toml` so this is typically a non-issue; verify.
- If the package exposes CLI tools that default to production databases or production hostnames, flag that — a dev who pip-installs and runs the CLI should not be able to accidentally hit prod.

### 14g. Version history review
- `pip index versions winebox` or check PyPI directly. Any yanked versions? Note them.
- Compare the latest PyPI version against `winebox/__init__.py` `__version__` and `pyproject.toml` `version`. A mismatch in git is harmless but flag if PyPI has a higher version than git's tag (would imply an out-of-band publish).

## 15. Admin Panel & Allowlist

The admin panel (`winebox.admin.main:app`, source under `winebox/admin/`) runs on its own subdomain and its own systemd unit. It shares secrets, the database connection, and auth helpers with the main app, but its attack surface and access controls are distinct. Audit it as a first-class component, not an extension of the main app.

### 15a. Allowlist file integrity
- Read `deploy/winebox-admin.toml`. Both `[oat]` and `[production]` sections must contain at least one entry — empty sections are rejected by `deploy/common.py:_load_admin_allowlist`, but verify the file hasn't been recently emptied or commented out.
- For each entry, confirm the IP/CIDR is operator-controlled and intentional. Flag:
  - Wildcards or `0.0.0.0/0` (would defeat the allowlist).
  - Public cloud ranges that don't belong to the operator (sign of a copy-paste mistake).
  - Long inactive entries (cross-reference with git log on the file — anything untouched for >90 days deserves a review).
- Confirm the file is committed to git and not in `.gitignore` (it MUST be tracked — it is the source of truth, not a secret).

### 15b. Nginx allowlist rendering
- Verify both nginx configs contain at least one standalone `# __ADMIN_ALLOWLIST__` line. Each gets substituted at deploy time with `allow ...; deny all;` directives.
  - `deploy/nginx-winebox.conf`: should have placeholders in the legacy `/admin` location on `booze.winebox.app` AND in the server-level block of `admin.winebox.app`.
  - `deploy/nginx-winebox-oat.conf`: same, for `oat.winebox.app/admin` and `oatadmin.winebox.app`.
- Run `uv run python -c "from pathlib import Path; from deploy.common import render_nginx_config; print(render_nginx_config(Path('deploy/nginx-winebox.conf'), 'production').read_text())"` to inspect the production render. Flag any rendered output that:
  - Contains `__ADMIN_ALLOWLIST__` outside of prose comments (means a placeholder didn't substitute).
  - Lacks a final `deny all;` after the `allow` directives.
  - Renders a different IP set than `deploy/winebox-admin.toml [production]` shows.
- Repeat for the `oat` section against `deploy/nginx-winebox-oat.conf`.

### 15c. App-level admin gating
- Every route in `winebox/admin/routers/` must use `RequireAdmin` (NOT `RequireAuth`). The nginx allowlist is the perimeter; app-level enforcement is the defence-in-depth backstop. Walk `admin.py` and `auth.py` and flag any route that doesn't have `RequireAdmin` injected.
- Check `winebox/admin/main.py`:
  - Confirm it includes `SecurityHeadersMiddleware` (currently imported from `winebox.main`).
  - Confirm rate limiting (`slowapi`) is wired up at app level AND on the auth router.
  - The `/health` endpoint should NOT require auth (it's used by the deploy task and the cert-check workflow), but it must NOT leak deployment-internal data — verify it returns only `status`, `version`, `app_name`.

### 15d. Static assets surface
- The admin SPA shell (`winebox/admin/static/admin.html`) and its JS/CSS are the only static files served by the admin app. Verify:
  - `admin.js` does not contain hardcoded admin tokens, user IDs, or production data fixtures.
  - `admin.html` has no inline `<script>` tags (CSP compliance) — all JS lives in `static/js/admin.js`.
  - The admin static mount is namespaced under `/static/` and does not shadow paths the app uses for API routes.

### 15e. Cross-app secret/data isolation
- Both apps use the same `WINEBOX_DATABASE` env var. The OAT admin defaults to `winebox_oat` (set in `winebox/admin/main.py` BEFORE the `winebox` import); production admin's systemd unit (`deploy/winebox-admin.service`) hard-pins `WINEBOX_DATABASE=winebox`. Verify those two enforcement points still exist.
- Confirm the production check in `winebox/config/settings.py:_check_database_safety` (or equivalent) still blocks the admin from connecting to the production DB unless running on the production droplet's FQDN. A regression here would let the admin script in OAT touch prod data.

### 15f. Admin systemd units
- `deploy/winebox-admin.service` (production) and `deploy/winebox-admin-oat.service` (OAT) should be byte-similar except for the `WINEBOX_DATABASE` env line, the `Description=`, and (for OAT) `After=`/`Wants=`. Diff them and flag any drift in the security-hardening flags or `ExecStart` arguments.
- Both must run as the `winebox` user (NOT root), and `ExecStart` must reference `winebox.admin.main:app`, not the old `admin_app.main:app` (which would point at a deleted module).

### 15g. Admin smoke tests
- Confirm `tests/test_oat_admin_smoke.py` and `tests/test_production_admin_smoke.py` exist and assert against `oatadmin.winebox.app` and `admin.winebox.app` respectively. Both modules should auto-skip when the host isn't reachable (the allowlist is enforced before the tests run, so non-allowlisted CI environments must not see a hard failure).

### 15h. Cert coverage
- `scripts/check_certs.py` should include `admin.winebox.app` and `oatadmin.winebox.app` in its `DEFAULT_HOSTS` tuple alongside `booze.winebox.app` and `oat.winebox.app`. Flag any cert added or removed without matching changes in `.github/workflows/cert-check.yml` cadence.

### 15i. Admin URL leakage in the user-facing app
- Grep `winebox/static/`, `winebox/main.py`, and `winebox/routers/` for `admin.winebox.app`, `oatadmin.winebox.app`, or `127.0.0.1:8001`. Those should not appear in the user-facing app — leaking the admin URL invites IP-bypass probing. Acceptable locations: `deploy/`, `tests/test_*_admin_smoke.py`, `docs/`, `tasks.py`, and the security-review prompt itself.

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

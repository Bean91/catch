.PHONY: check check-python check-frontend audit

# Mirrors .github/workflows/ci.yml step for step — CI calls these same underlying commands
# (not this Makefile itself, to keep each runner's own caching/working-directory setup
# native to its action), so "green locally" and "green on GitHub" can't drift apart.
check: check-python check-frontend

check-python:
	uv sync --locked --all-groups --all-extras
	uv run ruff check .
	uv run pytest

check-frontend:
	cd web && npm ci
	cd web && npm run typecheck
	cd web && npm run lint
	cd web && npm run test
	cd web && npm run build
	! grep -rIl -e 'sb_secret_' -e 'service_role' catch/api/static
	node --check catch/api/static/sw.js
	cd web && npm run check:bundle-size
	cd web && CI=1 npx playwright test

# Dependency vulnerability audit (needs network; kept out of `check` so that stays offline-safe). CI runs the same in
# .github/workflows/security.yml, plus gitleaks over the full history.
audit:
	f=$$(mktemp) && uv export --locked --all-groups --all-extras --no-hashes --no-emit-project --format requirements-txt -o $$f && uvx pip-audit --requirement $$f --no-deps --disable-pip --strict; s=$$?; rm -f $$f; exit $$s
	cd web && npm audit --omit=dev --audit-level=high

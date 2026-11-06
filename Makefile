.PHONY: check check-python check-frontend

# Mirrors .github/workflows/ci.yml step for step — CI calls these same underlying commands
# (not this Makefile itself, to keep each runner's own caching/working-directory setup
# native to its action), so "green locally" and "green on GitHub" can't drift apart.
check: check-python check-frontend

check-python:
	uv sync --locked --all-groups
	uv run ruff check .
	uv run pytest

check-frontend:
	cd web && npm ci
	cd web && npm run typecheck
	cd web && npm run lint
	cd web && npm run test
	cd web && npm run build
	cd web && npm run check:bundle-size
	cd web && npx playwright test

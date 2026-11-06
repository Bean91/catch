from __future__ import annotations

from datetime import datetime, timezone

# Evaluated at first import, which happens during catch.main's module-level router imports —
# close enough to "process start" for a human-readable uptime figure on the Status page. A
# separate module (not just a constant in catch/main.py) so routes_status.py can import it
# without a main.py <-> routes_status.py circular import.
START_TIME = datetime.now(timezone.utc)

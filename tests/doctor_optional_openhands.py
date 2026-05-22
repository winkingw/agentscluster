from __future__ import annotations

from unittest.mock import patch

from agents_cluster.core.doctor import _integration_checks
from agents_cluster.core.integrations import IntegrationStatus


def main() -> None:
    # Ensure OpenHands being missing never causes doctor to fail.
    statuses = [
        IntegrationStatus(
            name="openhands",
            installed=False,
            detail="command not found: openhands",
            install_hint="(optional) uv tool install openhands --python 3.12",
            use_for="pure optional",
        )
    ]
    with patch("agents_cluster.core.doctor.list_integrations", return_value=statuses):
        checks = _integration_checks()
    check = next(item for item in checks if item.name == "optional openhands")
    assert check.ok is True
    print("doctor optional openhands ok")


if __name__ == "__main__":
    main()


from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_external_hub_app_never_starts_a_package_install() -> None:
    from hermes_cli.apps.errors import AppDomainError
    from hermes_cli.apps.hub import AppHubOperations

    class ExternalAppClient:
        def get_app(self, app_id: str, *, version: str | None = None):
            assert app_id == "ai.stocksense.external-terminal"
            assert version == "1.0.0"
            return SimpleNamespace(
                data={
                    "item": {
                        "delivery": {
                            "type": "external",
                            "message": "外部安装，请联系运维人员。",
                        }
                    }
                }
            )

    operations = AppHubOperations(client=ExternalAppClient())

    with pytest.raises(AppDomainError, match="请联系运维人员") as exc_info:
        operations.start_install("ai.stocksense.external-terminal", version="1.0.0")

    assert exc_info.value.code == "HUB_EXTERNAL_INSTALL_REQUIRED"

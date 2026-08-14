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


def test_hub_preview_image_is_resolved_through_the_local_hub_client() -> None:
    from hermes_cli.apps.hub import AppHubOperations

    class PreviewAppClient:
        def get_app(self, app_id: str, *, version: str | None = None):
            assert app_id == "ai.stocksense.watchlist"
            assert version == "1.0.0"
            return SimpleNamespace(
                data={
                    "item": {
                        "preview_image_url": "https://cdn.stocksense.work/previews/watchlist.webp"
                    }
                },
                cache_state="fresh",
                stored_at=None,
            )

        def fetch_preview_image(self, value: str):
            assert value.endswith("watchlist.webp")
            return b"preview", "image/webp"

    content, content_type = AppHubOperations(client=PreviewAppClient()).get_preview_image(
        "ai.stocksense.watchlist", version="1.0.0"
    )

    assert content == b"preview"
    assert content_type == "image/webp"


def test_hub_preview_refreshes_metadata_before_fetching_a_signed_image() -> None:
    from hermes_cli.apps.hub import AppHubOperations

    calls: list[str] = []

    class PreviewAppClient:
        def get_app(self, app_id: str, *, version: str | None = None):
            raise AssertionError("preview loading should use refresh_app")

        def refresh_app(self, app_id: str, *, version: str | None = None):
            calls.append(f"refresh:{app_id}:{version}")
            return SimpleNamespace(
                data={
                    "item": {
                        "preview_image_url": "https://cdn.stocksense.work/previews/fresh.webp"
                    }
                }
            )

        def fetch_preview_image(self, value: str):
            calls.append(f"fetch:{value}")
            return b"fresh-preview", "image/webp"

    content, content_type = AppHubOperations(client=PreviewAppClient()).get_preview_image(
        "ai.stocksense.watchlist", version="1.0.0"
    )

    assert calls == [
        "refresh:ai.stocksense.watchlist:1.0.0",
        "fetch:https://cdn.stocksense.work/previews/fresh.webp",
    ]
    assert content == b"fresh-preview"
    assert content_type == "image/webp"

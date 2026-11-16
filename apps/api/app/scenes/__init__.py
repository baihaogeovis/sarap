"""Scene plugin registry for the platform API.

Concrete algorithms live in the engine. This package only holds manifests
so the shell can register scenes without hardcoding flood in generic tables.
"""

from app.scenes.registry import FLOOD_MANIFEST, get_manifest

__all__ = ["FLOOD_MANIFEST", "get_manifest"]

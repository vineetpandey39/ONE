"""OpenJarvis — modular AI assistant backend with composable intelligence primitives."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# This machine's antivirus (Avast) intercepts all outbound HTTPS with its own
# root CA (see NODE_EXTRA_CA_CERTS, which is how Node already trusts it) --
# Windows itself trusts that CA, but Python's bundled certifi list does not,
# so every httpx-based cloud call (Anthropic, OpenAI -- anything the
# `anthropic`/`openai` SDKs touch) failed with "CERTIFICATE_VERIFY_FAILED:
# unable to get local issuer certificate" / "Connection error." -- confirmed
# live (2026-08-11) chasing a "Ghost Agent connection error" report from a
# JARVIS Voice Mode "play a song" request. truststore delegates Python's SSL
# verification to the OS certificate store instead of the bundled list, so
# Python ends up trusting exactly what Windows (and therefore every browser
# and Node) already trusts -- no weakening of verification, just parity.
# Applied here, at package import time, so it's in effect for every entry
# point (server, CLI, scripts) with no per-caller wiring needed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 -- absence shouldn't block startup
    pass

from openjarvis.sdk import Jarvis, JarvisSystem, MemoryHandle, SystemBuilder

try:
    __version__ = _pkg_version("openjarvis")
except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
    __version__ = "0.0.0+unknown"

__all__ = ["Jarvis", "JarvisSystem", "MemoryHandle", "SystemBuilder", "__version__"]

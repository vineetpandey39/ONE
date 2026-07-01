"""Process-wide startup hooks for the ONE local runtime.

Windows machines can sit behind antivirus/proxy TLS inspection that installs
its root CA into the Windows certificate store, not into Python's bundled
certifi store. Importing this module at interpreter startup lets httpx,
requests, OpenAI, NVIDIA, and other HTTPS clients trust the same certificates
Chrome/Edge already trust.
"""

from __future__ import annotations


try:
    from pip_system_certs.wrapt_requests import inject_truststore

    inject_truststore()
except Exception:
    # Optional hardening only. If the package is absent, Python's default SSL
    # behavior remains unchanged and individual network calls surface errors.
    pass

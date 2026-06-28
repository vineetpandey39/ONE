"""Compatibility shim for IA prompt checks.

The real prompt implementation lives in ``ia_prompts.py``. This file
exists only because an interrupted edit left a truncated duplicate behind.
Keeping this shim lets any old imports continue to work without maintaining
two copies of the same prompt library.
"""

from __future__ import annotations

from openjarvis.agents.ia_prompts import *  # noqa: F401,F403


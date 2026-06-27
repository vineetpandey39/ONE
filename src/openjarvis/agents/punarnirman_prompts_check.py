"""Compatibility shim for Punarnirman prompt checks.

The real prompt implementation lives in ``punarnirman_prompts.py``. This file
exists only because an interrupted edit left a truncated duplicate behind.
Keeping this shim lets any old imports continue to work without maintaining
two copies of the same prompt library.
"""

from __future__ import annotations

from openjarvis.agents.punarnirman_prompts import *  # noqa: F401,F403


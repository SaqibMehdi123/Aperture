"""Aperture: a composable, cache-aware, observable context-engineering runtime for AI agents.

Public entry points:
    aperture.wrap(agent_loop, ...) - wrap any loop that calls an LLM (spec Section 7.4).
    aperture.Aperture / aperture.Session - the runtime facade.
"""

from aperture.runtime import Aperture, Session, wrap

__version__ = "0.1.0"

__all__ = ["Aperture", "Session", "__version__", "wrap"]

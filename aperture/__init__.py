"""Aperture: a composable, cache-aware, observable context-engineering runtime for AI agents.

Public entry points:
    aperture.Aperture / aperture.ChatSession - the runtime + one-liner chat API.
    aperture.wrap(agent_loop, ...) - wrap any loop that calls an LLM (spec Section 7.4).
"""

from aperture.chat import ChatSession
from aperture.runtime import Aperture, Session, wrap

__version__ = "0.4.2"

__all__ = ["Aperture", "ChatSession", "Session", "__version__", "wrap"]

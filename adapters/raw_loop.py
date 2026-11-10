"""Raw-loop adapter: the minimal framework integration (spec weeks 1-2,
"pip-installable skeleton wraps a toy loop end to end").

Any loop shaped `def loop(session)` works unchanged; `complete()` is the
single pre-call hook every adapter reduces to.
"""

from __future__ import annotations

from collections.abc import Callable

from aperture.runtime import Aperture, Session


class RawLoopAdapter:
    def __init__(self, loop_fn: Callable[[Session], object]) -> None:
        self.loop_fn = loop_fn

    def run(self, runtime: Aperture, session_id: str, token_budget: int = 32768) -> object:
        return runtime.wrap(self.loop_fn, session_id=session_id, token_budget=token_budget)

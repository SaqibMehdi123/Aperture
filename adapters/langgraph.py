"""LangGraph adapter: aperture-managed graph nodes (spec Table 6, P1).

LangGraph accumulates conversation history in `state["messages"]` and merges
each node's returned messages back into it. The adapter keeps the Aperture
window and that state in lockstep, per thread:

    from aperture import Aperture
    from adapters.langgraph import LangGraphAdapter

    ap = Aperture(model="openai/gpt-4o-mini")
    lg = LangGraphAdapter(ap)

    @lg.wrap_node
    def chatbot(state):
        reply = state["aperture"].complete()      # full decision loop
        return {"messages": [{"role": "assistant", "content": reply}]}

    graph.add_node("chatbot", chatbot)

Responsibilities per invocation: ingest new state messages as spans (roles
mapped, system messages protected + cache-headed), run the node, sync back
returned messages that the runtime did not already record, and advance the
ingestion cursor so nothing is ever added twice. No `langgraph` import is
required - messages are duck-typed (dicts or LangChain-style objects).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aperture.chat import ChatSession
from aperture.runtime import Aperture

_ROLE_BY_TYPE = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}


def _role_and_content(message: Any) -> tuple[str, str]:
    """Dict messages and LangChain-style objects -> (role, content)."""
    if isinstance(message, dict):
        role = str(message.get("role", "user"))
        content = str(message.get("content", "") or "")
        return role, content
    mtype = str(getattr(message, "type", "") or "")
    role = _ROLE_BY_TYPE.get(mtype, "user")
    content = str(getattr(message, "content", "") or "")
    return role, content


def _thread_id(config: Any) -> str:
    """LangGraph RunnableConfig -> thread id (best effort, no import)."""
    if config is None:
        return "default"
    configurable = None
    if hasattr(config, "get"):
        configurable = config.get("configurable", None)
    elif hasattr(config, "configurable"):
        configurable = config.configurable
    if configurable is None:
        return "default"
    if hasattr(configurable, "get"):
        tid = configurable.get("thread_id", None)
    else:
        tid = getattr(configurable, "thread_id", None)
    return str(tid) if tid else "default"


class _ChatProxy:
    """The handle injected as `state["aperture"]`.

    The user turn already arrived via state sync, so nodes call
    `state["aperture"].complete()` - the full decision loop, reply text out.
    """

    def __init__(self, chat: ChatSession, reply_holder: dict) -> None:
        self._chat = chat
        self._holder = reply_holder

    def complete(self) -> str:
        resp = self._chat.raw.complete()
        self._holder["text"] = resp.text
        return resp.text

    def stats(self) -> dict:
        return self._chat.stats()

    @property
    def raw(self):
        return self._chat.raw


class LangGraphAdapter:
    """Per-thread aperture sessions for LangGraph nodes."""

    def __init__(self, runtime: Aperture, token_budget: int = 32768) -> None:
        self._runtime = runtime
        self._token_budget = token_budget
        self._chats: dict[str, ChatSession] = {}
        self._ingested: dict[str, int] = {}

    def session_for(self, thread_id: str = "default") -> ChatSession:
        """The ChatSession backing a thread (create if missing)."""
        if thread_id not in self._chats:
            self._chats[thread_id] = ChatSession(
                self._runtime, f"lg-{thread_id}", self._token_budget
            )
            self._ingested[thread_id] = 0
        return self._chats[thread_id]

    def reset(self, thread_id: str = "default") -> None:
        """Forget a thread: the next invocation starts a fresh session."""
        self._chats.pop(thread_id, None)
        self._ingested.pop(thread_id, None)

    def wrap_node(self, node_fn: Callable) -> Callable:
        """Decorate a graph node; injects `state["aperture"]` (a _ChatProxy)."""

        def wrapped(state, config=None, *args, **kwargs):
            thread_id = _thread_id(config)
            chat = self.session_for(thread_id)
            messages = list(state.get("messages", []) or [])
            cursor = self._ingested.get(thread_id, 0)

            # 1. State -> spans: everything the state gained since last time.
            for message in messages[cursor:]:
                role, content = _role_and_content(message)
                if content:
                    chat.ingest(content, role=role)

            # 2. Run the node with the aperture handle injected.
            reply_holder: dict[str, str] = {}
            run_state = dict(state)
            run_state["aperture"] = _ChatProxy(chat, reply_holder)
            result = node_fn(run_state, *args, **kwargs) or {}

            # 3. Sync back returned messages the runtime did not record.
            returned = list(result.get("messages", [])) if isinstance(result, dict) else []
            reply = reply_holder.get("text")
            for message in returned:
                role, content = _role_and_content(message)
                if role == "assistant" and reply is not None and content == reply:
                    continue  # already recorded by complete()
                if content:
                    chat.ingest(content, role=role)

            # 4. Advance the cursor: state now contains everything above.
            self._ingested[thread_id] = len(messages) + len(returned)
            return result

        wrapped.__name__ = getattr(node_fn, "__name__", "aperture_node")
        wrapped.__doc__ = node_fn.__doc__
        return wrapped

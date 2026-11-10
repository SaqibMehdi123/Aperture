"""The three-line integration (run: python examples/quickstart.py).

No API keys needed: without `model=`, Aperture uses a deterministic synthetic
gateway so you can feel the loop end to end. Pass a LiteLLM model string
(`pip install 'aperture-runtime[litellm]'`) to go live:

    ap = Aperture(model="openai/gpt-4o-mini")
"""

from aperture import Aperture

ap = Aperture()  # try: Aperture(model="openai/gpt-4o-mini", profile="lean")

with ap.chat("quickstart") as chat:
    chat.system("You are a careful support agent for an e-commerce team.")
    chat.constraints(
        [
            "Never approve refunds above 500 USD without escalation.",
            "Always cite the order ID when discussing a shipment.",
        ]
    )

    reply = chat.send("Where is my order 1234?")
    print("agent:", reply)

    # A bulky tool output: the runtime may archive it and keep a stub.
    reply = chat.send(
        "[order 1234] " + "shipment log line for the warehouse batch job " * 60,
        role="tool",
    )
    print("agent:", reply)

    print("stats:", chat.stats())

print("history classes:", [c for c, _ in chat.history()])

"""agentveto veto layer: calls blocked *before* they run.

Run this with:

    python examples/veto_demo.py

It records a refund agent whose runtime refuses three calls - emailing a
customer, a refund above the approval line, and a full PII export - then
writes a self-contained HTML report. Open the file and look for the red
rows with the purple "veto" tag.

No API key, no account, no network. That is the whole point.
"""

from agentveto import demo_veto

if __name__ == "__main__":
    path = demo_veto(out="agentveto-veto-demo.html")
    print(f"report written to {path} - open it in any browser")

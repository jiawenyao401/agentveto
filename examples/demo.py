"""Run this to see what agentveto captures. No API key, no network, no account.

    python examples/demo.py
"""

import agentveto

path = agentveto.demo()
print(f"\nReport written to: {path}")
print("Open it in a browser - it is a single self-contained HTML file.")

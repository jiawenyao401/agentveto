"""Command line entry point: agentveto <command>"""

from __future__ import annotations

import argparse
import sys

from ._version import __version__


def _open(path: str) -> None:
    import webbrowser

    webbrowser.open("file://" + path if not path.startswith("http") else path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentveto",
        description="Replay it. Prove it. Veto it. Runtime control for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"agentveto {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_demo = sub.add_parser("demo", help="Generate an example run and open its report (no API key needed)")
    p_demo.add_argument("-o", "--out", help="Output HTML path")
    p_demo.add_argument("--veto", action="store_true",
                        help="Generate the runtime-policy demo instead (calls blocked before they run)")
    p_demo.add_argument("--open", action="store_true", help="Open the report in a browser")

    p_report = sub.add_parser("report", help="Write a self-contained HTML report for a run")
    p_report.add_argument("--db", help="Path to the trace database")
    p_report.add_argument("--run", help="Run id (defaults to the most recent run)")
    p_report.add_argument("-o", "--out", help="Output HTML path")
    p_report.add_argument("--open", action="store_true")

    p_list = sub.add_parser("list", help="List recorded runs")
    p_list.add_argument("--db")
    p_list.add_argument("-n", "--limit", type=int, default=20)

    p_serve = sub.add_parser("serve", help="Serve the local viewer (needs agentveto[serve])")
    p_serve.add_argument("--db")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8420)
    p_serve.add_argument("--open", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "demo":
        if args.veto:
            from .demo import demo_veto

            path = demo_veto(out=args.out, open=args.open)
        else:
            from .demo import demo

            path = demo(out=args.out, open=args.open)
        print(path)
        return 0

    if args.cmd == "report":
        from .report import report

        path = report(args.run, out=args.out, db=args.db)
        print(path)
        if args.open:
            _open(path)
        return 0

    if args.cmd == "list":
        from .store import Store

        runs = Store(args.db).list_runs(limit=args.limit)
        if not runs:
            print("No runs recorded yet.")
            return 0
        print(f"{'RUN ID':<26}{'STATUS':<9}{'STEPS':>6}{'COST':>12}  NAME")
        for r in runs:
            print(
                f"{r['id']:<26}{r['status']:<9}{r['span_count']:>6}"
                f"{'$' + format(r['total_cost'], '.5f'):>12}  {r['name']}"
            )
        return 0

    if args.cmd == "serve":
        from .serve import serve

        serve(db=args.db, host=args.host, port=args.port, open=args.open)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

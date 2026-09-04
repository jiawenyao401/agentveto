"""Command line entry point: agentveto <command>"""

from __future__ import annotations

import argparse
import json
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

    # --- policy: explain / validate / format ---------------------------------
    p_policy = sub.add_parser("policy", help="Inspect a policy file without running anything")
    psp = p_policy.add_subparsers(dest="policy_cmd")

    p_show = psp.add_parser("show", help="Summarize a policy file (default, rule count, action set)")
    p_show.add_argument("file", help="Path to a JSON policy file")

    p_validate = psp.add_parser("validate", help="Validate a policy file; exit 0 if valid")
    p_validate.add_argument("file")
    p_validate.add_argument("--strict", action="store_true",
                            help="Warn on rules without a name or reason")

    p_explain = psp.add_parser("explain", help="Explain which rule would fire for a given action")
    p_explain.add_argument("file", help="Policy JSON file")
    p_explain.add_argument("--action", required=True, help="Action name, e.g. send_email")
    p_explain.add_argument("--payload", default="{}",
                           help="Payload as a JSON object (string or @file.json)")
    p_explain.add_argument("--format", choices=("text", "json"), default="text")

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

    if args.cmd == "policy":
        from .policy_io import explain, load_policy

        if args.policy_cmd == "show":
            policy = load_policy(args.file)
            rules = policy.get("rules") or []
            actions = sorted({str(r.get("action", "*")) for r in rules if isinstance(r, dict)})
            print(f"policy: {args.file}")
            print(f"  default     : {policy.get('default', 'allow')}")
            print(f"  rules       : {len(rules)}")
            print(f"  actions     : {', '.join(actions) if actions else '(none)'}")
            effects: dict[str, int] = {}
            for r in rules:
                if isinstance(r, dict):
                    effects[r.get("effect", "deny")] = effects.get(r.get("effect", "deny"), 0) + 1
            for k, v in sorted(effects.items()):
                print(f"    {k:<7}: {v}")
            return 0

        if args.policy_cmd == "validate":
            try:
                policy = load_policy(args.file)
            except Exception as exc:
                print(f"invalid: {exc}", file=sys.stderr)
                return 2
            warnings: list[str] = []
            if args.strict:
                for i, r in enumerate(policy.get("rules") or []):
                    if isinstance(r, dict):
                        if not r.get("name"):
                            warnings.append(f"rule #{i} has no name")
                        if not r.get("reason"):
                            warnings.append(f"rule #{i} ({r.get('name', i)}) has no human-readable reason")
            for w in warnings:
                print(f"warning: {w}", file=sys.stderr)
            if warnings:
                return 1
            print(f"ok: {len(policy.get('rules') or [])} rules")
            return 0

        if args.policy_cmd == "explain":
            policy = load_policy(args.file)
            payload_str = args.payload
            if payload_str.startswith("@"):
                with open(payload_str[1:], encoding="utf-8") as fh:
                    payload_str = fh.read()
            try:
                payload = json.loads(payload_str) if payload_str.strip() else {}
            except json.JSONDecodeError as exc:
                print(f"invalid --payload JSON: {exc}", file=sys.stderr)
                return 2
            explanation = explain(policy, args.action, payload)
            if args.format == "json":
                print(json.dumps(explanation.as_dict(), indent=2, ensure_ascii=False))
                return 0
            print(f"action  : {args.action}")
            print(f"payload : {json.dumps(payload, ensure_ascii=False)}")
            print(f"default : {explanation.default}")
            print()
            for r in explanation.rules:
                tag = "MATCH" if r.matched else "skip "
                head = f"  [{tag}] {r.action:<14} -> {r.effect:<6}"
                head += f"  ({r.name})" if r.name else ""
                print(head)
                for p in r.paths:
                    print(f"          {'OK' if p.matched else 'X'} {p.detail}")
            print()
            d = explanation.decision
            print(f"decision: {d}")
            return 0

        parser.print_help()
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Command line entry point: agentveto <command>"""

from __future__ import annotations

import argparse
import json
import os
import sys

from ._version import __version__


def _open(path: str) -> None:
    import webbrowser

    webbrowser.open("file://" + path if not path.startswith("http") else path)


def _read_key(path: str | None) -> bytes | None:
    if not path:
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _read_pub(path: str | None) -> str | None:
    """Read a public key (base64) file. Tolerates surrounding whitespace."""
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def _resolve_and_verify(target: str, public_b64: str | None):
    """Pick the right verifier for ``target``: a directory/db -> the store,
    anything else -> a portable .evd evidence file."""
    from . import prove
    from .store import default_db_path

    if os.path.isdir(target):
        candidates = [f for f in os.listdir(target) if f.lower().endswith(".db")]
        if not candidates:
            dbpath = default_db_path()
            if os.path.dirname(dbpath) != os.path.abspath(target):
                raise SystemExit(f"no .db file found in {target}")
        else:
            dbpath = os.path.join(target, candidates[0])
        return prove.verify_db(dbpath, public_b64_override=public_b64)
    low = target.lower()
    if low.endswith(".db"):
        return prove.verify_db(target, public_b64_override=public_b64)
    if not os.path.exists(target):
        raise SystemExit(f"file not found: {target}")
    return prove.verify_evidence_file(target, public_b64)


def _print_verification(v) -> None:
    print(("OK    " if v.ok else "FAILED") + "  " + v.summary())
    for name, ok, detail in v.checks:
        mark = "ok" if ok else "XX"
        print(f"  [{mark}] {name:<18} {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentveto",
        description="Replay it. Prove it. Veto it. Runtime control for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"agentveto {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_demo = sub.add_parser("demo", help="Generate an example run and open its report (no API key needed)")
    p_demo.add_argument("-o", "--out", help="Output HTML path")
    p_demo.add_argument(
        "--veto",
        action="store_true",
        help="Generate the runtime-policy demo instead (calls blocked before they run)",
    )
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
    p_validate.add_argument("--strict", action="store_true", help="Warn on rules without a name or reason")

    p_explain = psp.add_parser("explain", help="Explain which rule would fire for a given action")
    p_explain.add_argument("file", help="Policy JSON file")
    p_explain.add_argument("--action", required=True, help="Action name, e.g. send_email")
    p_explain.add_argument("--payload", default="{}", help="Payload as a JSON object (string or @file.json)")
    p_explain.add_argument("--format", choices=("text", "json"), default="text")

    # --- prove: tamper-evident, signed evidence -----------------------------
    p_prove = sub.add_parser("prove", help="Turn recorded runs into verifiable evidence")
    pp = p_prove.add_subparsers(dest="prove_cmd")

    p_keygen = pp.add_parser("keygen", help="Create an Ed25519 signing keypair (needs agentveto[sign])")
    p_keygen.add_argument("-o", "--out", default=".", help="Directory for the .key/.pub files")

    p_sign = pp.add_parser("sign", help="Build the hash chain and sign it, persisting to the db")
    p_sign.add_argument("--db", help="Path to the trace database")
    p_sign.add_argument("--run", help="Limit the attestation to this run and everything before it")
    p_sign.add_argument("--key", help="Private key file (agentveto.key); omit to stay unsigned")

    p_export = pp.add_parser("export", help="Write a portable .evd evidence file")
    p_export.add_argument("--db", help="Path to the trace database")
    p_export.add_argument("--run", required=True, help="Run id to export")
    p_export.add_argument("-o", "--out", help="Output .evd path (default: <run>.evd)")
    p_export.add_argument("--key", help="Private key file to sign the evidence with")

    p_verify = sub.add_parser("verify", help="Verify evidence: a .evd file or a trace db")
    p_verify.add_argument("target", help="An .evd evidence file, a .db file, or a directory holding a db")
    p_verify.add_argument("--pub", help="Public key file (agentveto.pub) for signature checks")

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

    if args.cmd == "prove":
        from . import prove

        if args.prove_cmd == "keygen":
            private_pem, public_b64 = prove.keygen()
            os.makedirs(args.out, exist_ok=True)
            priv_path = os.path.join(args.out, "agentveto.key")
            pub_path = os.path.join(args.out, "agentveto.pub")
            with open(priv_path, "wb") as fh:
                fh.write(private_pem)
            try:
                os.chmod(priv_path, 0o600)
            except OSError:
                pass
            with open(pub_path, "w", encoding="utf-8") as fh:
                fh.write(public_b64)
            print(f"wrote private key: {priv_path}")
            print(f"wrote public key : {pub_path}")
            print(f"public key: {public_b64}")
            return 0

        if args.prove_cmd == "sign":
            res = prove.sign_db(args.db, _read_key(args.key), run_id=args.run)
            print(f"blocks   : {res['blocks']}")
            print(f"head run : {res['head_run_id']}")
            print(f"head hash: {res['head_hash']}")
            print(f"signed   : {'yes' if res['signed'] else 'no (unsigned integrity chain)'}")
            return 0

        if args.prove_cmd == "export":
            path = prove.export_evidence(args.db, args.run, _read_key(args.key), out=args.out)
            print(path)
            return 0

        p_prove.print_help()
        return 1

    if args.cmd == "verify":
        v = _resolve_and_verify(args.target, _read_pub(args.pub))
        _print_verification(v)
        return 0 if v.ok else 1

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

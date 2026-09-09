"""Prove: tamper-evident, signed evidence for agent runs.

Why this exists
---------------
A trace in SQLite is only as trustworthy as the person who controls the file.
"Prove it" turns a run into *evidence*: a canonical digest that is chained
across runs, optionally signed, and exportable to a single portable file an
auditor can verify offline -- without holding your database or your secret.

Two layers, kept deliberately small (restraint over features):

* **Integrity** -- stdlib only, always available. Every run gets a canonical
  SHA-256 digest of its stored rows; runs are linked into a hash chain anchored
  at a genesis hash. Any byte change to a covered run or span is detected and
  pinned to the specific run.
* **Authenticity** -- optional, needs ``cryptography``. An Ed25519 key signs the
  head of the chain, so a third party who does not hold your key can still verify
  the whole history. The chain is a *deliberate attestation*, not ambient tracing:
  you sign or export explicitly. That keeps the tracing hot path fast and
  stdlib-only even when no crypto package is installed.

What is covered
---------------
A run's digest hashes the run row **plus every span row, ordered by seq**, exactly
as stored (including any truncation markers). What you recorded is what you prove.

Known limitations (honest scope, v2):
* The chain is linear (not a Merkle tree). For one process's run history that is
  the right size; a Merkle tree only buys log-time verification for huge datasets.
* It proves integrity of the recorded store -- it is not a hardware root of trust.
  Anyone who can edit the database *before* you sign can edit the evidence too.
  Sign at the moment you want to lock in the record.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .store import Store

FORMAT_VERSION = 1
GENESIS = "0" * 64
_SIGN_HINT = "signing needs the 'cryptography' package: pip install agentveto[sign]"


class ProverError(Exception):
    """Raised for invalid input (unknown run, bad key, malformed evidence)."""


# ---------------------------------------------------------------------------
# Canonical hashing (stdlib, deterministic)
# ---------------------------------------------------------------------------


def canonical(obj: Any) -> bytes:
    """Deterministic serialization: sorted keys, compact, UTF-8.

    Digests are only meaningful if the same data always serializes the same way,
    so we sort keys and use fixed separators. ``ensure_ascii=False`` keeps
    non-ASCII stable *and* readable.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def run_digest(run: dict, spans: list[dict]) -> str:
    """Digest of a run's stored rows. ``spans`` must be ordered by seq."""
    return sha256_hex(canonical({"run": run, "spans": spans}))


def block_hash(pos: int, run_id: str, prev_hash: str, run_digest: str) -> str:
    """Hash of a single chain block. Depends on the previous hash, so the whole
    history flows into every block after the first."""
    return sha256_hex(
        canonical({"pos": pos, "run_id": run_id, "prev_hash": prev_hash, "run_digest": run_digest})
    )


def build_chain(items: list[tuple[dict, list[dict]]]) -> list[dict]:
    """Build the hash chain from ``(run, spans)`` in chain order (oldest first)."""
    prev = GENESIS
    blocks: list[dict] = []
    for i, (run, spans) in enumerate(items):
        rd = run_digest(run, spans)
        h = block_hash(i, run["id"], prev, rd)
        blocks.append({"pos": i, "run_id": run["id"], "prev_hash": prev, "run_digest": rd, "hash": h})
        prev = h
    return blocks


# ---------------------------------------------------------------------------
# Ed25519 (optional; lazy import so the core stays stdlib-only)
# ---------------------------------------------------------------------------


def _require_crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - depends on install
        raise ProverError(_SIGN_HINT) from exc
    return InvalidSignature, serialization, Ed25519PrivateKey, Ed25519PublicKey


def keygen() -> tuple[bytes, str]:
    """Generate an Ed25519 keypair. Returns ``(private_pem, public_b64)``."""
    _invalid, serialization, Ed25519PrivateKey, _pub = _require_crypto()
    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub = priv.public_key()
    public_b64 = base64.b64encode(
        pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode("ascii")
    return private_pem, public_b64


def _load_private(private_pem: bytes | str):
    if isinstance(private_pem, str):
        private_pem = private_pem.encode("utf-8")
    _invalid, serialization, _priv_cls, _pub_cls = _require_crypto()
    return serialization.load_pem_private_key(private_pem, password=None)


def public_b64_from_private(private_pem: bytes | str) -> str:
    _invalid, serialization, _priv_cls, _pub_cls = _require_crypto()
    priv = _load_private(private_pem)
    pub = priv.public_key()
    return base64.b64encode(
        pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode("ascii")


def sign_head(private_pem: bytes | str, head_hash: str) -> tuple[str, str]:
    """Sign a chain head hash. Returns ``(signature_b64, public_b64)``."""
    priv = _load_private(private_pem)
    sig = priv.sign(bytes.fromhex(head_hash))
    return base64.b64encode(sig).decode("ascii"), public_b64_from_private(private_pem)


def verify_signature(signature_b64: str, head_hash: str, public_b64: str) -> bool:
    """Verify an Ed25519 signature over a head hash. Never raises; returns bool."""
    if not signature_b64 or not public_b64:
        return False
    try:
        _invalid, _serialization, _priv_cls, Ed25519PublicKey = _require_crypto()
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64))
        pub.verify(base64.b64decode(signature_b64), bytes.fromhex(head_hash))
        return True
    except Exception:
        # Wrong key, corrupt signature, missing crypto: all are "not verified".
        return False


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------


@dataclass
class Verification:
    ok: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append((name, ok, detail))

    def __bool__(self) -> bool:
        return self.ok

    def summary(self) -> str:
        if not self.checks:
            return "no checks performed"
        return "ok" if self.ok else "FAILED" + " (" + ", ".join(n for n, o, _ in self.checks if not o) + ")"


# ---------------------------------------------------------------------------
# Building & exporting evidence
# ---------------------------------------------------------------------------


def _ordered_runs_up_to(store: Store, run_id: str) -> list[dict]:
    """The genesis-to-``run_id`` slice of the chain, oldest first."""
    runs = store.list_runs_asc()
    ids = [r["id"] for r in runs]
    if run_id not in ids:
        raise ProverError(f"unknown run: {run_id}")
    return runs[: ids.index(run_id) + 1]


def _items_for(store: Store, runs: list[dict]) -> list[tuple[dict, list[dict]]]:
    return [(store.get_run(r["id"]), store.get_spans(r["id"])) for r in runs]


def build_evidence(store: Store, run_id: str, private_pem: bytes | str | None = None) -> dict:
    """Assemble a portable evidence document for ``run_id`` (and the chain to it).

    The document embeds only the *target* run's full data; earlier runs are
    represented by their digests so the chain is fully re-verifiable from the
    file alone while staying small.
    """
    runs = _ordered_runs_up_to(store, run_id)
    blocks = build_chain(_items_for(store, runs))
    head = blocks[-1]

    signature = None
    public_b64 = None
    if private_pem is not None:
        signature, public_b64 = sign_head(private_pem, head["hash"])

    return {
        "agentveto_evidence": FORMAT_VERSION,
        "created_at": time.time(),
        "run_id": run_id,
        "public_key": public_b64,
        "anchor": {
            "genesis": GENESIS,
            "head_hash": head["hash"],
            "head_run_id": head["run_id"],
            "block_count": len(blocks),
        },
        "blocks": blocks,
        "data": {"run": store.get_run(run_id), "spans": store.get_spans(run_id)},
        "signature": signature,
    }


def export_evidence(
    db: str | None,
    run_id: str,
    private_pem: bytes | str | None = None,
    out: str | None = None,
) -> str:
    """Write a self-contained ``.evd`` evidence file. Returns the file path."""
    from .store import default_db_path

    store = Store(db or default_db_path())
    doc = build_evidence(store, run_id, private_pem)
    if out is None:
        out = run_id + ".evd"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    return os.path.abspath(out)


def sign_db(
    db: str | None,
    private_pem: bytes | str | None = None,
    run_id: str | None = None,
) -> dict:
    """Build and (optionally) sign the chain, persisting it to the DB's evidence
    table. ``run_id`` limits the attestation to that run and everything before it;
    omitted means the entire history. Returns a summary dict."""
    from .store import default_db_path

    store = Store(db or default_db_path())
    if run_id is None:
        runs = store.list_runs_asc()
    else:
        runs = _ordered_runs_up_to(store, run_id)
    if not runs:
        raise ProverError("no runs to sign")

    blocks = build_chain(_items_for(store, runs))
    head = blocks[-1]
    signature = None
    public_b64 = None
    if private_pem is not None:
        signature, public_b64 = sign_head(private_pem, head["hash"])

    store.save_evidence(blocks, signature=signature, public_key=public_b64, signed_at=time.time())
    return {
        "blocks": len(blocks),
        "head_hash": head["hash"],
        "head_run_id": head["run_id"],
        "signed": signature is not None,
        "public_key": public_b64,
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _recompute_chain(blocks: list[dict], genesis: str = GENESIS) -> tuple[bool, int | None]:
    """Recompute the chain from stored digests. Returns ``(ok, broken_index)``."""
    prev = genesis
    for b in blocks:
        h = block_hash(b["pos"], b["run_id"], b["prev_hash"], b["run_digest"])
        if h != b["hash"] or b["prev_hash"] != prev:
            return False, b["pos"]
        prev = h
    return True, None


def verify_evidence(doc: dict, public_b64_override: str | None = None) -> Verification:
    """Verify a portable evidence document (as loaded from an ``.evd`` file)."""
    v = Verification(ok=False)
    try:
        blocks = doc["blocks"]
        data = doc["data"]
        anchor = doc.get("anchor", {})
    except (KeyError, TypeError) as exc:
        return Verification(ok=False, checks=[("format", False, f"malformed evidence: {exc}")])

    # 1. Target run's data must match the digest its block claims.
    target = None
    for b in blocks:
        if b["run_id"] == data["run"]["id"]:
            target = b
            break
    if target is None:
        v.add("target_run", False, "target run not present in the evidence chain")
    else:
        rd = run_digest(data["run"], data["spans"])
        match = target["run_digest"] == rd
        v.add(
            "target_run_digest",
            match,
            "data matches attested digest"
            if match
            else "run data does not match its attested digest (tampered?)",
        )

    # 2. The whole chain must recompute to the attested head.
    ok, broken = _recompute_chain(blocks, anchor.get("genesis", GENESIS))
    v.add(
        "chain",
        ok,
        "ok" if ok else f"broken at block index {broken} (run {blocks[broken]['run_id']})",
    )
    head_ok = bool(blocks) and blocks[-1]["hash"] == anchor.get("head_hash")
    v.add("head_anchor", head_ok, "ok" if head_ok else "head hash does not match anchor")

    # 3. Signature (if present) over the attested head hash.
    signature = doc.get("signature")
    public_b64 = public_b64_override or doc.get("public_key")
    if signature:
        if not public_b64:
            v.add("signature", False, "signed but no public key available to verify")
        else:
            good = verify_signature(signature, anchor.get("head_hash", ""), public_b64)
            v.add("signature", good, "valid" if good else "INVALID (not produced by this key)")
    else:
        v.add("signature", True, "unsigned -- integrity check only")

    v.ok = all(c[1] for c in v.checks)
    return v


def verify_evidence_file(path: str, public_b64_override: str | None = None) -> Verification:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return verify_evidence(doc, public_b64_override)


def verify_db(
    db: str | None,
    run_id: str | None = None,
    public_b64_override: str | None = None,
) -> Verification:
    """Verify the evidence chain stored in a live database against its own rows.

    This is the "did someone edit the file?" check: it recomputes every covered
    run's digest from the *current* rows and compares to what was attested.
    """
    from .store import default_db_path

    store = Store(db or default_db_path())
    rows = store.evidence_rows()
    if not rows:
        return Verification(
            ok=False,
            checks=[("evidence", False, "no signed evidence in db -- run 'agentveto prove sign' first")],
        )
    blocks = [
        {
            "pos": r["pos"],
            "run_id": r["run_id"],
            "prev_hash": r["prev_hash"],
            "run_digest": r["run_digest"],
            "hash": r["hash"],
        }
        for r in rows
    ]
    v = Verification(ok=False)

    # 1. Each covered run's live data must match its attested digest.
    all_runs_ok = True
    for b in blocks:
        if run_id is not None and b["run_id"] != run_id:
            continue
        run = store.get_run(b["run_id"])
        if run is None:
            v.add(f"run[{b['pos']}]", False, f"run {b['run_id']} missing from db")
            all_runs_ok = False
            continue
        rd = run_digest(run, store.get_spans(b["run_id"]))
        if rd != b["run_digest"]:
            v.add(
                f"run[{b['pos']}]",
                False,
                f"run {b['run_id']} data does not match attested digest (tampered?)",
            )
            all_runs_ok = False
    if all_runs_ok:
        v.add("runs", True, f"{len(blocks)} run(s) match attested digests")

    # 2. Chain recomputes to the head.
    ok, broken = _recompute_chain(blocks)
    v.add("chain", ok, "ok" if ok else f"broken at block index {broken}")

    # 3. Signature, if stored.
    head = rows[-1]
    signature = head.get("signature")
    public_b64 = public_b64_override or head.get("public_key")
    head_hash = head["hash"]
    if signature:
        if not public_b64:
            v.add("signature", False, "signed but no public key available to verify")
        else:
            good = verify_signature(signature, head_hash, public_b64)
            v.add("signature", good, "valid" if good else "INVALID (not produced by this key)")
    else:
        v.add("signature", True, "unsigned -- integrity check only")

    v.ok = all(c[1] for c in v.checks)
    return v

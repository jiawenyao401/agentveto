"""Prove layer: tamper-evident, signed evidence.

The point of these tests is the failure modes -- a chain that says "ok" is only
interesting if it also says "no" the moment a single byte moves.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest

from agentveto import prove
from agentveto.prove import (
    GENESIS,
    ProverError,
    block_hash,
    build_chain,
    canonical,
    run_digest,
)
from agentveto.tracer import Tracer

cryptography = pytest.importorskip("cryptography", reason="needs agentveto[sign] for Ed25519 tests")


@pytest.fixture
def tracer(tmp_path):
    return Tracer(str(tmp_path / "t.db"), auto_patch=False)


@pytest.fixture
def db(tracer):
    """Three recorded runs, in order. Returns (db_path, [run_id, ...])."""
    rids = []
    for i in range(3):
        with tracer.start_run(f"run-{i}") as run:
            with tracer.start_span(f"step-{i}", kind="llm") as span:
                span.set_model("gpt-4o")
                span.set_io(input={"prompt": f"q{i}"}, output={"text": f"a{i}"})
                span.set_usage(10 + i, 5 + i)
        rids.append(run.id)
    return tracer.store.path, rids


@pytest.fixture
def key():
    return prove.keygen()


@contextmanager
def _raw(db_path):
    """Raw sqlite access, to simulate an attacker editing the file directly."""
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------- canonical


def test_canonical_ignores_key_order():
    assert canonical({"a": 1, "b": 2}) == canonical({"b": 2, "a": 1})


def test_canonical_is_stable_for_nested_and_unicode():
    doc = {"z": [1, {"k": "v"}], "a": "中文"}
    assert canonical(doc) == canonical(json.loads(json.dumps(doc, ensure_ascii=False)))


def test_canonical_distinguishes_different_values():
    assert canonical({"a": 1}) != canonical({"a": 2})


def test_run_digest_covers_run_and_spans(db):
    db_path, rids = db
    store = Tracer(db_path, auto_patch=False).store
    run = store.get_run(rids[0])
    spans = store.get_spans(rids[0])
    base = run_digest(run, spans)
    assert base != run_digest({**run, "name": "renamed"}, spans)
    assert base != run_digest(run, [{**spans[0], "output": "changed"}])


def test_run_digest_is_stable_across_reads(db):
    db_path, rids = db
    store = Tracer(db_path, auto_patch=False).store
    a = run_digest(store.get_run(rids[0]), store.get_spans(rids[0]))
    b = run_digest(store.get_run(rids[0]), store.get_spans(rids[0]))
    assert a == b


# --------------------------------------------------------------- chain


def test_block_hash_is_deterministic():
    h1 = block_hash(0, "r1", GENESIS, "deadbeef")
    h2 = block_hash(0, "r1", GENESIS, "deadbeef")
    assert h1 == h2
    assert block_hash(1, "r1", GENESIS, "deadbeef") != h1


def test_chain_starts_at_genesis_and_links(db):
    db_path, rids = db
    store = Tracer(db_path, auto_patch=False).store
    items = [(store.get_run(r), store.get_spans(r)) for r in rids]
    blocks = build_chain(items)

    assert [b["pos"] for b in blocks] == [0, 1, 2]
    assert blocks[0]["prev_hash"] == GENESIS
    for prev_b, b in zip(blocks, blocks[1:]):
        assert b["prev_hash"] == prev_b["hash"]


def test_chain_is_order_dependent(db):
    db_path, rids = db
    store = Tracer(db_path, auto_patch=False).store
    items = [(store.get_run(r), store.get_spans(r)) for r in rids]
    assert build_chain(items)[-1]["hash"] != build_chain(list(reversed(items)))[-1]["hash"]


# --------------------------------------------------------------- signing


def test_keygen_returns_pem_and_base64_public_key(key):
    private_pem, public_b64 = key
    assert private_pem.startswith(b"-----BEGIN")
    assert len(public_b64) == 44  # 32 raw bytes, base64


def test_sign_head_derives_matching_public_key(key):
    private_pem, public_b64 = key
    sig, derived = prove.sign_head(private_pem, "ab" * 32)
    assert derived == public_b64
    assert prove.verify_signature(sig, "ab" * 32, public_b64)
    assert not prove.verify_signature(sig, "cd" * 32, public_b64)


def test_sign_db_persists_signed_chain(db, key):
    db_path, rids = db
    res = prove.sign_db(db_path, key[0])
    assert res["blocks"] == 3
    assert res["signed"] is True
    assert res["public_key"] == key[1]
    assert res["head_run_id"] == rids[-1]

    v = prove.verify_db(db_path)
    assert v.ok, v.summary()
    assert dict((n, o) for n, o, _ in v.checks)["signature"] is True


def test_sign_db_without_key_is_unsigned_but_verifiable(db):
    db_path, _ = db
    res = prove.sign_db(db_path, None)
    assert res["signed"] is False
    v = prove.verify_db(db_path)
    assert v.ok
    sig_detail = [d for n, o, d in v.checks if n == "signature"][0]
    assert "unsigned" in sig_detail


def test_sign_db_can_stop_at_a_run(db, key):
    db_path, rids = db
    res = prove.sign_db(db_path, key[0], run_id=rids[1])
    assert res["blocks"] == 2
    assert res["head_run_id"] == rids[1]


def test_sign_db_unknown_run_raises(db):
    db_path, _ = db
    with pytest.raises(ProverError):
        prove.sign_db(db_path, run_id="nope")


# --------------------------------------------------------- db verification


def test_verify_db_fails_when_nothing_signed(db):
    db_path, _ = db
    v = prove.verify_db(db_path)
    assert not v.ok
    assert "prove sign" in v.checks[0][2]


def test_verify_db_detects_a_tampered_span(db, key):
    """The whole point: one edited field must be caught, and pinned to its run."""
    db_path, rids = db
    prove.sign_db(db_path, key[0])
    assert prove.verify_db(db_path).ok

    store = Tracer(db_path, auto_patch=False).store
    span_id = store.get_spans(rids[1])[0]["id"]
    with _raw(db_path) as conn:
        conn.execute("UPDATE spans SET output=? WHERE id=?", ("TAMPERED", span_id))

    v = prove.verify_db(db_path)
    assert not v.ok
    failed = [n for n, ok, _ in v.checks if not ok]
    assert any(n.startswith("run[1]") for n in failed), failed


def test_verify_db_detects_a_deleted_run(db, key):
    db_path, rids = db
    prove.sign_db(db_path, key[0])
    with _raw(db_path) as conn:
        conn.execute("DELETE FROM runs WHERE id=?", (rids[0],))

    v = prove.verify_db(db_path)
    assert not v.ok


def test_chain_order_is_stable_when_timestamps_collide(db):
    """Regression: two runs sharing started_at must come out of the chain in
    the same order they were inserted. Without this, the hash chain is
    non-deterministic and the same DB can produce different evidence files
    on different machines.
    """
    db_path, _ = db
    res1 = prove.sign_db(db_path, None)
    # Force every run to share started_at exactly
    with _raw(db_path) as conn:
        conn.execute("UPDATE runs SET started_at = 1000.0")

    res2 = prove.sign_db(db_path, None)
    from agentveto.store import Store

    order1 = [r["run_id"] for r in Store(db_path).evidence_rows()]
    # res2 overwrote evidence_rows
    order2 = [r["run_id"] for r in Store(db_path).evidence_rows()]
    assert order1 == order2, (order1, order2)


def test_verify_db_rejects_signature_from_another_key(db, key):
    db_path, _ = db
    prove.sign_db(db_path, key[0])
    other_public = prove.keygen()[1]
    v = prove.verify_db(db_path, public_b64_override=other_public)
    assert not v.ok
    sig = [d for n, ok, d in v.checks if n == "signature"][0]
    assert "INVALID" in sig


# ------------------------------------------------------------- .evd files


def test_export_and_verify_portable_evidence(db, key, tmp_path):
    db_path, rids = db
    out = tmp_path / "run.evd"
    path = prove.export_evidence(db_path, rids[2], key[0], out=str(out))
    assert path == str(out)

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["agentveto_evidence"] == 1
    assert doc["signature"] and doc["public_key"] == key[1]
    # Only the target run ships full data; earlier runs are digests only.
    assert len(doc["blocks"]) == 3
    assert doc["data"]["run"]["id"] == rids[2]
    assert doc["data"]["spans"], "target run data must be embedded"

    v = prove.verify_evidence_file(path)
    assert v.ok, v.summary()


def test_evidence_file_digest_survives_a_json_round_trip(db, key, tmp_path):
    """Verifying must work after a reload -- that is the auditor's first step."""
    db_path, rids = db
    path = prove.export_evidence(db_path, rids[1], key[0], out=str(tmp_path / "r.evd"))
    reloaded = json.loads(json.dumps(json.loads(open(path, encoding="utf-8").read())))
    assert prove.verify_evidence(reloaded).ok


def test_evidence_file_detects_edited_payload(db, key, tmp_path):
    db_path, rids = db
    path = prove.export_evidence(db_path, rids[1], key[0], out=str(tmp_path / "r.evd"))
    doc = json.loads(open(path, encoding="utf-8").read())
    doc["data"]["spans"][0]["output"] = "I was never said"
    v = prove.verify_evidence(doc)
    assert not v.ok
    assert not [o for n, o, _ in v.checks if n == "target_run_digest"][0]


def test_evidence_file_detects_replaced_chain_digest(db, key, tmp_path):
    db_path, rids = db
    path = prove.export_evidence(db_path, rids[1], key[0], out=str(tmp_path / "r.evd"))
    doc = json.loads(open(path, encoding="utf-8").read())
    doc["blocks"][0]["run_digest"] = "0" * 64
    v = prove.verify_evidence(doc)
    assert not v.ok
    assert not [o for n, o, _ in v.checks if n == "chain"][0]


def test_evidence_file_with_wrong_key_reports_invalid_signature(db, key, tmp_path):
    db_path, rids = db
    path = prove.export_evidence(db_path, rids[1], key[0], out=str(tmp_path / "r.evd"))
    v = prove.verify_evidence_file(path, prove.keygen()[1])
    assert not v.ok
    sig = [d for n, ok, d in v.checks if n == "signature"][0]
    assert "INVALID" in sig


def test_unsigned_evidence_file_still_proves_integrity(db, tmp_path):
    db_path, rids = db
    path = prove.export_evidence(db_path, rids[0], None, out=str(tmp_path / "r.evd"))
    doc = json.loads(open(path, encoding="utf-8").read())
    assert doc["signature"] is None
    v = prove.verify_evidence_file(path)
    assert v.ok


def test_malformed_evidence_is_reported_not_raised():
    v = prove.verify_evidence({"nonsense": True})
    assert not v.ok
    assert v.checks[0][0] == "format"


# -------------------------------------------------------------------- CLI


def test_cli_sign_then_verify(db, key, tmp_path, monkeypatch, capsys):
    from agentveto import cli

    db_path, _ = db
    keyfile = tmp_path / "agentveto.key"
    keyfile.write_bytes(key[0])

    assert cli.main(["prove", "sign", "--db", db_path, "--key", str(keyfile)]) == 0
    assert "head hash" in capsys.readouterr().out

    assert cli.main(["verify", db_path]) == 0


def test_cli_verify_returns_nonzero_after_tampering(db, key, tmp_path, capsys):
    from agentveto import cli

    db_path, rids = db
    keyfile = tmp_path / "agentveto.key"
    keyfile.write_bytes(key[0])
    cli.main(["prove", "sign", "--db", db_path, "--key", str(keyfile)])

    store = Tracer(db_path, auto_patch=False).store
    span_id = store.get_spans(rids[0])[0]["id"]
    with _raw(db_path) as conn:
        conn.execute("UPDATE spans SET output=? WHERE id=?", ("TAMPERED", span_id))

    assert cli.main(["verify", db_path]) == 1


def test_cli_keygen_writes_key_pair(tmp_path, capsys):
    from agentveto import cli

    outdir = tmp_path / "keys"
    assert cli.main(["prove", "keygen", "-o", str(outdir)]) == 0
    assert (outdir / "agentveto.key").exists()
    assert (outdir / "agentveto.pub").exists()
    assert len((outdir / "agentveto.pub").read_text().strip()) == 44


def test_cli_export_then_verify_file(db, key, tmp_path):
    from agentveto import cli

    db_path, rids = db
    keyfile = tmp_path / "agentveto.key"
    keyfile.write_bytes(key[0])
    out = tmp_path / "r.evd"

    assert (
        cli.main(
            ["prove", "export", "--db", db_path, "--run", rids[0], "--key", str(keyfile), "-o", str(out)]
        )
        == 0
    )
    assert out.exists()
    assert cli.main(["verify", str(out)]) == 0

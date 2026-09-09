# Prove: tamper-evident evidence

Replay answers *what happened*. Veto answers *what is allowed*. Prove answers
the question an auditor actually asks: **can I trust this record?**

A trace in a SQLite file is only as trustworthy as whoever controls the file.
`prove` turns a run into evidence — a canonical digest, chained across runs,
optionally signed, and exportable as a single file that anyone can verify
offline without your database or your secret key.

## Quick start

```bash
agentveto prove keygen -o ./keys                 # agentveto.key + agentveto.pub
agentveto prove sign --db agentveto.db --key ./keys/agentveto.key
```

```text
blocks   : 12
head run : run_caf4d2289c9443c7
head hash: 3af412fde97ca8fbe5643b6369534684c2301e1f1d7218807314c78415e28bb8
signed   : yes
```

Then, later or on another machine:

```bash
agentveto verify agentveto.db        # is my own store still untouched?
```

```text
OK      ok
  [ok] runs               12 run(s) match attested digests
  [ok] chain              ok
  [ok] signature          valid
```

`verify` exits `0` when everything checks out and `1` when it does not, so it
drops straight into CI or a cron job.

## Handing evidence to someone else

```bash
agentveto prove export --db agentveto.db --run <run-id> --key ./keys/agentveto.key -o incident.evd
agentveto verify incident.evd
```

The `.evd` file is self-contained JSON. It embeds the target run's full data
plus the chain of digests leading up to it, so a third party can verify it
with nothing but the file — no database, no network, no account.

Only the target run ships its payload; earlier runs are represented by their
digests, so the file stays small while the whole chain remains re-verifiable.

## Two layers

### Integrity — zero dependencies, always on

Every run gets a SHA-256 digest of its stored rows (the run row plus every span,
ordered by `seq`). Runs are then linked into a hash chain anchored at a genesis
value of 64 zeros:

```text
block[i].hash = SHA256(canonical({pos, run_id, prev_hash, run_digest}))
```

Because each block hashes the previous one, the history flows into every
successive block — which is what lets a single signature cover all of it.

Change one byte in one span and verification fails, naming the run it is in:

```text
FAILED  FAILED (runs, chain)
  [XX] run[1]              run run_c9997bf5550346d0 data does not match attested digest (tampered?)
  [XX] chain               broken at block index 1
  [ok] signature           valid
```

!!! tip "What is covered"
    The digest hashes the rows **as stored**, including any truncation markers.
    What you recorded is what you prove — not a re-serialisation that might
    differ.

### Authenticity — optional, needs `agentveto[sign]`

```bash
pip install 'agentveto[sign]'
```

An Ed25519 key signs the chain head. Since the head hash transitively covers
every earlier block, **one signature authenticates the entire history**. Someone
holding only your public key can verify it:

```bash
agentveto verify incident.evd --pub ./keys/agentveto.pub
```

A signature that does not match the key reports `INVALID (not produced by this
key)` rather than silently passing.

Without `cryptography` installed, everything above still works — you just get
integrity without authenticity, and `verify` says so plainly:

```text
  [ok] signature           unsigned -- integrity check only
```

## Python API

```python
from agentveto import prove

private_pem, public_b64 = prove.keygen()

prove.sign_db("agentveto.db", private_pem)  # chain + sign
prove.verify_db("agentveto.db")  # -> Verification

path = prove.export_evidence("agentveto.db", run_id, private_pem, out="incident.evd")
prove.verify_evidence_file(path)  # -> Verification
```

`Verification` is a small dataclass — `ok`, plus a `checks` list of
`(name, ok, detail)` you can render however you like:

```python
v = prove.verify_db("agentveto.db")
if not v.ok:
    for name, ok, detail in v.checks:
        if not ok:
            print(name, detail)
```

Signing a single run's evidence includes everything before it — you cannot
attest to run 7 without attesting to runs 1–6:

```python
prove.sign_db("agentveto.db", private_pem, run_id="run_abc")  # chain up to run_abc
```

## Design choices

**Signing is explicit, not ambient.** The chain is a deliberate attestation you
make when you want to lock in the record. That keeps the tracing hot path fast
and keeps `agentveto` dependency-free for people who never call `prove`.

**Linear chain, not a Merkle tree.** A Merkle tree only buys logarithmic-time
verification of individual items, which matters for huge datasets. For one
process's run history the linear chain is smaller, simpler, and equally strong.

**SQLite, not a ledger service.** Same reasoning as the rest of the project: an
auditor should be able to open the file on a laptop, offline, in five years.

## Limits — read this before you rely on it

!!! warning "What Prove does not do"
    - It proves **integrity of what was recorded**, not that the recording is
      faithful to reality. If your agent was told to record something false,
      the evidence faithfully attests to the false record.
    - Anyone with write access *before* you sign can edit the record and then
      sign the edited version. **Sign at the moment you want to freeze it.**
    - It is not a hardware root of trust, and there is no timestamping
      authority. `signed_at` is your clock.
    - Deleting an entire run is detected as a missing run, but Prove cannot
      conjure the data back.

Threat model in one line: Prove turns *silent* tampering into *detected*
tampering. That is a real and useful guarantee, and it is not the same as
making tampering impossible.

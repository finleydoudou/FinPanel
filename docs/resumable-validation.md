# Resumable offline validation

Use a pinned local evidence store. Acquisition is a separate operation and never
runs as a fallback during validation.

```bash
finpanel validate broad --store output/corpus/evidence --snapshot SNAPSHOT_ID \
  --universe src/finpanel/validation/release-universe.json --output output/audit
# After an interruption, repeat the identical semantic request with --resume:
finpanel validate broad --store output/corpus/evidence --snapshot SNAPSHOT_ID \
  --universe src/finpanel/validation/release-universe.json --output output/audit --resume
```

`--issuer 0000012659` can be repeated for a subset. `--limit` selects the first
sorted CIKs. `--checkpoint PATH` relocates the checkpoint; pass the same path when
resuming. `--workers 1` is explicit: this implementation bounds memory with one
serial worker per job and rejects larger counts. Separate disjoint jobs may run
concurrently, with separate outputs and checkpoints; report their resource usage
as multiple processes, not a multiworker timing for one job.

The job identity includes the universe hash, sorted selected CIKs, metrics, periods,
fiscal years, cutoffs, policies, exact snapshot and manifest hashes, software identity,
and validation contract. Equivalent ordering and duplicate query dimensions are
normalized. No private local absolute path participates in the public job identity.

After each complete issuer, the checkpoint atomically records completed units,
cumulative semantic results, receipt identities, counters, and SHA-256 hashes of
all unit exports and sidecars. Resume verifies the checkpoint checksum, job identity,
full pinned evidence integrity, and completed output hashes before skipping work.
Changed software, evidence, query, missing output, corruption, and unknown formats
fail explicitly. A checksum is accidental-corruption detection, not a signature
against an adversary who can rewrite both the data and its hashes.

An OS writer lock prevents concurrent writes to the same job and releases when the
process exits. The small lock file remains intentionally. An interrupted issuer is
recomputed from immutable inputs; its partial files are preserved under
`.interrupted/`. Completed issuers are not recomputed. Never manually edit a
checkpoint to force compatibility.

Preparation, parser, and source-verification exceptions become explicit failed
units without deleting earlier work. A recorded failure is terminal for that job;
create a new job after correcting its cause. Invariant failures remain unexpected
findings and make the CLI exit nonzero. A corrupt pinned snapshot fails closed
before computation; previously saved checkpoint/output files remain preserved.

The tests compare uninterrupted and interrupted/resumed reports **and receipts**,
verify which issuers were skipped, reject changed inputs and damaged files, preserve
partial output, and isolate an injected parser failure. Performance durations,
process peak memory, and the `resumed` flag are operational measurements and can differ.

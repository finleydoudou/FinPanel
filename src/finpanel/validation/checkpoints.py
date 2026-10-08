"""Verified issuer-boundary checkpoints for offline validation jobs.

Hashes detect accidental corruption, not an attacker who can rewrite the entire
checkpoint and its hashes. Only one process may write a job at a time.
"""

import shutil
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from finpanel.cache.file import atomic_write
from finpanel.errors import ValidationError
from finpanel.serialization import dumps, loads
from finpanel.snapshots.store import digest

FORMAT = "finpanel-validation-checkpoint-v1"
CONTRACT = "broad-invariants-v2"


def file_hashes(folder: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValidationError("Checkpoint output cannot contain symlinks")
        if path.is_file():
            hashes[path.relative_to(folder).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return hashes


class Checkpoint:
    def __init__(self, output, path, job, *, resume=False):
        self.output = Path(output)
        self.path = Path(path) if path is not None else self.output / "checkpoint.json"
        if self.path.resolve().is_relative_to(self.output.resolve()):
            relative = self.path.resolve().relative_to(self.output.resolve())
            if len(relative.parts) != 1 or relative.name in {
                "report.json",
                "receipt.json",
                "findings.json",
                "performance.json",
                *job["issuers"],
            }:
                raise ValidationError("Checkpoint path overlaps benchmark output")
        self.job = loads(dumps(job))
        self.job_id = digest(self.job)
        self.completed = {}
        self.state = {}
        if resume:
            try:
                value = loads(self.path.read_bytes())
                checksum = value.pop("checksum")
                if digest(value) != checksum:
                    raise ValidationError("Checkpoint checksum mismatch")
                if (
                    value["format"] != FORMAT
                    or value["job_id"] != self.job_id
                    or value["job"] != self.job
                ):
                    raise ValidationError("Incompatible validation checkpoint")
                self.completed = value["completed"]
                if set(self.completed) - set(job["issuers"]):
                    raise ValidationError("Checkpoint contains unknown issuers")
                self.state = value["state"]
                for cik, hashes in self.completed.items():
                    if file_hashes(self.output / cik) != hashes:
                        raise ValidationError("Checkpoint output missing or corrupt: " + cik)
            except ValidationError:
                raise
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise ValidationError("Unreadable validation checkpoint") from exc
        else:
            if self.output.exists() or self.path.exists():
                raise ValidationError("Benchmark output must be a new directory")
            self.output.mkdir(parents=True)
            self.save({})

    def prepare(self, cik):
        """Preserve incomplete output; never reuse an unverified partial batch."""
        folder = self.output / cik
        if folder.exists():
            archive = self.output / ".interrupted"
            archive.mkdir(exist_ok=True)
            shutil.move(str(folder), archive / (cik + "-" + uuid4().hex))

    def complete(self, cik, state):
        self.completed[cik] = file_hashes(self.output / cik)
        self.save(state)

    def save(self, state):
        value = dict(
            format=FORMAT, job_id=self.job_id, job=self.job, completed=self.completed, state=state
        )
        atomic_write(self.path, dumps(dict(value, checksum=digest(value))).encode())
        self.state = state


# An OS advisory lock is released even when the process is terminated. The empty
# lock file is deliberately retained to avoid two processes locking different inodes.


@contextmanager
def job_lock(path):
    lock = Path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        import os

        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValidationError("Validation job is already running") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

"""Build a variant: copy base data -> apply ops -> validate -> emit (or refuse)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import UnsupportedFormat, get_adapter
from .ops import apply_op
from .spec import VariantSpec
from .validator import CheckResult, validate


@dataclass
class BuildResult:
    name: str
    emitted: bool
    checks: list[CheckResult] = field(default_factory=list)
    error: str = ""

    @property
    def all_passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


def _preflight_formats(spec: VariantSpec, base_data: Path) -> None:
    """Fail fast if any op targets a file we have no adapter for."""
    for op in spec.ops:
        rel = op.params.get("file")
        if not rel:           # file-level op (e.g. anonymize_filenames) — no single target
            continue
        get_adapter(base_data / rel)  # raises UnsupportedFormat


def _dir_fingerprint(root: Path) -> str:
    """Hash the set of file paths under root — detects file-level ops (rename /
    delete) that change which files exist, not their contents."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(Path(root).rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(root)).encode())
    return h.hexdigest()


def _op_fingerprint(op, out_data: Path) -> str:
    """Value-level fingerprint of what an op affects: the target file's cell
    values, or (for file-level ops) the directory's file set."""
    rel = op.params.get("file")
    if not rel:
        return _dir_fingerprint(out_data)
    return get_adapter(out_data / rel).fingerprint()


def build_variant(spec: VariantSpec, base_data: Path, out_data: Path,
                  overwrite: bool = True) -> BuildResult:
    """Construct spec's variant from base_data into out_data, gated on validation.

    The variant data is written ONLY if every required_signal check passes; on
    failure the partial output is removed so a broken variant can never be used.
    """
    base_data, out_data = Path(base_data), Path(out_data)
    try:
        _preflight_formats(spec, base_data)
    except UnsupportedFormat as e:
        return BuildResult(spec.name, emitted=False, error=f"unsupported_format: {e}")

    if out_data.exists():
        if not overwrite:
            return BuildResult(spec.name, emitted=False, error="output exists (overwrite=False)")
        shutil.rmtree(out_data)
    out_data.parent.mkdir(parents=True, exist_ok=True)
    # HARDLINK the base tree instead of copying bytes: a variant that drops one
    # column from one file must not duplicate an 11GB sibling matrix. Hardlinks
    # share inodes (≈0 disk). We then COPY-ON-WRITE only the files an op touches
    # (below), so writes never corrupt the shared base inode. Falls back to a
    # real copy across filesystems where hardlinks aren't possible.
    def _link_tree(src: Path, dst: Path):
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            d = dst / item.name
            if item.is_dir():
                _link_tree(item, d)
            else:
                try:
                    os.link(item, d)
                except OSError:
                    shutil.copy2(item, d)
    _link_tree(base_data, out_data)

    # Break the hardlink for every file an op will modify (copy-on-write), so
    # the op edits a private copy, never the shared base inode.
    for op in spec.ops:
        rel = op.params.get("file")
        if not rel:
            continue
        target = out_data / rel
        if target.exists():
            tmp = target.with_suffix(target.suffix + ".cow")
            shutil.copy2(target, tmp)
            target.unlink()
            tmp.rename(target)

    try:
        for op in spec.ops:
            # EFFECT ASSERTION: an op that changes nothing is a silent build bug
            # (wrong header_row, a pattern that matched no column, a keep_value
            # that was already the only value). It would otherwise emit green
            # while the answer-critical signal stays fully intact. Catch it here,
            # generically, so no spec has to anticipate the failure.
            before = _op_fingerprint(op, out_data)
            apply_op(op, out_data)
            after = _op_fingerprint(op, out_data)
            if before == after:
                shutil.rmtree(out_data, ignore_errors=True)
                tgt = op.params.get("file", "<files>")
                return BuildResult(spec.name, emitted=False,
                                   error=f"op_no_effect: {op.kind} on {tgt!r} changed nothing "
                                         f"(likely wrong header_row / non-matching pattern)")
    except Exception as e:
        shutil.rmtree(out_data, ignore_errors=True)
        return BuildResult(spec.name, emitted=False, error=f"op_failed: {type(e).__name__}: {e}")

    checks = validate(spec, out_data)
    if not all(c.passed for c in checks):
        shutil.rmtree(out_data, ignore_errors=True)
        return BuildResult(spec.name, emitted=False, checks=checks,
                           error="validation_failed: variant is NOT unanswerable")
    return BuildResult(spec.name, emitted=True, checks=checks)

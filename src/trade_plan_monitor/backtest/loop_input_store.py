"""Result-owned immutable copies of reviewed inputs and cutoff market evidence."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Literal, Self

from pydantic import model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import LoopFrozenSymbolDay
from trade_plan_monitor.backtest.jobs.models import LoopInputReference
from trade_plan_monitor.backtest.loop_dataset import LoopDatasetManifest, loop_dataset_requirements
from trade_plan_monitor.backtest.loop_input import (
    MAX_LOOP_RECORDS,
    MAX_SOURCE_BYTES,
    MonitorLoopInput,
)
from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.preparation_review import FrozenPreparedPlan
from trade_plan_monitor.backtest.research_input import ResearchValue

if TYPE_CHECKING:
    from trade_plan_monitor.backtest.market_store import BacktestMarketStore

_BUNDLE_DOMAIN = "monitor-loop-stored-input-v1"
_DAY_DOMAIN = "monitor-loop-copied-day-v1"
# Derived from existing artifact/source limits, not a new admission quota.
_MAX_OBJECT_BYTES = MAX_LOOP_RECORDS * 4096 + MAX_SOURCE_BYTES
_HASH = re.compile(r"^[0-9a-f]{64}$")
_OWNER = b'{"schema_version":"monitor-loop-result-input-directory-v1"}'


def _digest(domain: str, payload: bytes) -> str:
    return sha256(domain.encode() + b"\0" + payload).hexdigest()


class StoredLoopInput(ResearchValue):
    schema_version: Literal["monitor-loop-stored-input-v1"] = _BUNDLE_DOMAIN
    prepared: FrozenPreparedPlan
    run_input: MonitorLoopInput
    dataset: LoopDatasetManifest
    day_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (
            self.run_input.schedule != self.prepared.schedule
            or self.run_input.initial_account != self.prepared.account
            or self.run_input.dataset_hash != self.dataset.dataset_hash
            or self.run_input.boundary != self.dataset.boundary
            or self.dataset.plan_hash != self.prepared.version.plan_hash
            or self.dataset.plan_version_id != self.prepared.version.version_id
            or self.dataset.requirements
            != loop_dataset_requirements(self.prepared.version.snapshot)
            or self.dataset.scope.symbols != (self.prepared.version.snapshot.symbol,)
            or len(self.day_hashes) != len(self.dataset.days)
        ):
            raise ValueError("stored loop input must bind exact reviewed plan/account/dataset")
        return self

    @property
    def reference(self) -> LoopInputReference:
        return LoopInputReference(
            run_id=self.run_input.run_id,
            input_hash=self.run_input.input_hash,
            dataset_hash=self.dataset.dataset_hash,
            bundle_hash=_digest(_BUNDLE_DOMAIN, canonical_json(self).encode()),
        )


def _verify_day(dataset: LoopDatasetManifest, index: int, day: LoopFrozenSymbolDay) -> None:
    """Bind copied values back to every original immutable market artifact."""
    import json

    from trade_plan_monitor.backtest.market_store import _content_hash, _minute_artifact_row

    selection = dataset.days[index]
    if (
        day.symbol != dataset.scope.symbols[0]
        or day.trade_date != selection.trade_date
        or day.state != selection.state
        or day.evidence_cutoff != dataset.boundary.evidence_cutoff
    ):
        raise RuntimeError("copied loop day does not match frozen selection")

    def market_hash(value, item):
        return _content_hash(
            {
                "kind": item.kind,
                "provider": "TUSHARE",
                "contract_version": "normalized-market-v1",
                "natural_key": item.natural_key,
                "content": json.loads(canonical_json(value)),
            }
        )

    if market_hash(day.trading_day, selection.calendar) != selection.calendar.artifact_hash:
        raise RuntimeError("copied loop calendar does not match artifact")
    if len(day.minutes) != len(selection.minutes):
        raise RuntimeError("copied loop minute membership is incomplete")
    for bar, ref in zip(day.minutes, selection.minutes, strict=True):
        if (
            _minute_artifact_row(bar, dataset.scope.historical_profile)[0] != ref.artifact_hash
            or bar.bar_end != ref.bar_end
            or bar.received_at != ref.available_at
        ):
            raise RuntimeError("copied loop minute does not match artifact")
    for values, refs in ((day.daily_limits, selection.limits), (day.daily_bars, selection.daily)):
        if len(values) != len(refs):
            raise RuntimeError("copied loop daily membership is incomplete")
        for value, ref in zip(values, refs, strict=True):
            if (
                market_hash(value, ref.item) != ref.item.artifact_hash
                or value.received_at != ref.available_at
            ):
                raise RuntimeError("copied loop daily evidence does not match artifact")


class LoopInputStore:
    """Inert handle; explicit writes atomically publish immutable content files."""

    def __init__(self, result_database: Path):
        self._root = result_database.parent / (result_database.name + ".loop-inputs")

    @property
    def root(self) -> Path:
        return self._root

    def _owned_root(self, *, create: bool) -> None:
        if self.root.is_symlink() or self.root.is_junction():
            raise RuntimeError("loop input directory cannot be a link")
        if create:
            self.root.mkdir(exist_ok=True)
        marker = self.root / "owner.json"
        if not marker.exists():
            if not create or any(self.root.iterdir()):
                raise RuntimeError("loop input directory ownership is missing")
            self._publish(marker, _OWNER)
        if (
            marker.is_symlink()
            or marker.is_junction()
            or marker.stat().st_size != len(_OWNER)
            or marker.read_bytes() != _OWNER
        ):
            raise RuntimeError("loop input directory ownership is invalid")

    def _object_path(self, prefix: str, digest: str) -> Path:
        if type(digest) is not str or _HASH.fullmatch(digest) is None:
            raise ValueError("loop input object requires a SHA-256 identity")
        return self.root / f"{prefix}-{digest}.json"

    def bundle_path(self, reference: LoopInputReference) -> Path:
        return self._object_path("bundle", reference.bundle_hash)

    def day_path(self, digest: str) -> Path:
        return self._object_path("day", digest)

    def _publish(self, path: Path, payload: bytes) -> None:
        if len(payload) > _MAX_OBJECT_BYTES:
            raise ValueError("loop input object exceeds existing evidence bounds")
        temporary = None
        try:
            with NamedTemporaryFile(dir=self.root, prefix=".writing-", delete=False) as file:
                temporary = Path(file.name)
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if (
                    path.is_symlink()
                    or path.is_junction()
                    or path.stat().st_size != len(payload)
                    or path.read_bytes() != payload
                ):
                    raise RuntimeError("existing immutable loop input is damaged") from None
            if os.name != "nt":
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _read(self, path: Path, domain: str, digest: str) -> bytes:
        if path.is_symlink() or path.is_junction():
            raise RuntimeError("loop input object cannot be a link")
        try:
            if path.stat().st_size > _MAX_OBJECT_BYTES:
                raise RuntimeError("loop input object exceeds existing evidence bounds")
            with path.open("rb") as file:
                payload = file.read(_MAX_OBJECT_BYTES + 1)
        except FileNotFoundError:
            raise RuntimeError("immutable loop input object is missing") from None
        if len(payload) > _MAX_OBJECT_BYTES or _digest(domain, payload) != digest:
            raise RuntimeError("immutable loop input content hash is invalid")
        return payload

    def persist(
        self,
        *,
        prepared: FrozenPreparedPlan,
        run_input: MonitorLoopInput,
        dataset: LoopDatasetManifest,
        market_source: BacktestMarketStore,
    ) -> StoredLoopInput:
        # Validate all authority bindings before creating the directory or copying evidence.
        candidate = StoredLoopInput(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            day_hashes=tuple("0" * 64 for _ in dataset.days),
        )
        self._owned_root(create=True)
        hashes = []
        with market_source.open_frozen_loop_dataset(dataset) as reader:
            for index, day in enumerate(reader):
                if index >= len(dataset.days):
                    raise RuntimeError("loop market source contains extra days")
                _verify_day(dataset, index, day)
                payload = canonical_json(day).encode()
                digest = _digest(_DAY_DOMAIN, payload)
                self._publish(self.day_path(digest), payload)
                hashes.append(digest)
        stored = candidate.model_copy(update={"day_hashes": tuple(hashes)})
        self._publish(self.bundle_path(stored.reference), canonical_json(stored).encode())
        return self.load(stored.reference)

    def load(self, reference: LoopInputReference, *, verify_days: bool = True) -> StoredLoopInput:
        reference = LoopInputReference.model_validate(reference.model_dump(mode="python"))
        self._owned_root(create=False)
        payload = self._read(self.bundle_path(reference), _BUNDLE_DOMAIN, reference.bundle_hash)
        stored = StoredLoopInput.model_validate_json(payload)
        if canonical_json(stored).encode() != payload or stored.reference != reference:
            raise RuntimeError("immutable loop input reference is inconsistent")
        if verify_days:
            for index in range(len(stored.day_hashes)):
                self._read_day(stored, index)
        return stored

    def _read_day(self, stored: StoredLoopInput, index: int) -> LoopFrozenSymbolDay:
        digest = stored.day_hashes[index]
        payload = self._read(self.day_path(digest), _DAY_DOMAIN, digest)
        day = LoopFrozenSymbolDay.model_validate_json(payload)
        if canonical_json(day).encode() != payload:
            raise RuntimeError("copied loop day is not canonical")
        _verify_day(stored.dataset, index, day)
        return day

    @contextmanager
    def open_dataset(
        self, reference: LoopInputReference
    ) -> Iterator[Iterator[LoopFrozenSymbolDay]]:
        stored = self.load(reference, verify_days=False)
        yield (self._read_day(stored, index) for index in range(len(stored.day_hashes)))

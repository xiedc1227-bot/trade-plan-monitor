"""Result-owned immutable copies of reviewed inputs and cutoff market evidence."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import LoopFrozenSymbolDay
from trade_plan_monitor.backtest.jobs.models import LoopInputReference
from trade_plan_monitor.backtest.loop_dataset import (
    LoopDatasetManifest,
    LoopDatasetPlanBinding,
    ScheduledLoopDatasetManifest,
    loop_dataset_requirements,
    open_frozen_scheduled_loop_dataset,
    relevant_schedule_entries,
    scheduled_dataset_requirements,
)
from trade_plan_monitor.backtest.loop_input import (
    MAX_LOOP_RECORDS,
    MAX_SOURCE_BYTES,
    MonitorLoopInput,
    ScheduledLoopInput,
    WorkbenchLoopInput,
)
from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.preparation_review import (
    FrozenPreparedCollection,
    FrozenPreparedPlan,
)
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchPlanSelection,
)

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


def _validate_linked_source(schedule, dataset):
    linked = [
        row.version.snapshot for row in schedule.entries
        if row.version.snapshot.schema_version in {6, 7, 8}
    ]
    source = dataset.linked_index_source
    if linked and source is None:
        raise ValueError("LINKED_INDEX_REPLAY_HISTORY_MISSING")
    if source is not None:
        if not linked or any(plan.reference_market != source.reference_market for plan in linked):
            raise ValueError("LINKED_INDEX_REPLAY_BINDING_MISMATCH")
        source.validate_scope(binding=linked[0].reference_market,
            session_dates=tuple(day.trade_date for day in dataset.days if day.state != "CLOSED"),
            started_at=dataset.boundary.started_at, cutoff=dataset.boundary.evidence_cutoff)


class StoredLoopInput(ResearchValue):
    schema_version: Literal["monitor-loop-stored-input-v1"] = _BUNDLE_DOMAIN
    prepared: FrozenPreparedPlan
    run_input: MonitorLoopInput
    dataset: LoopDatasetManifest
    day_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def bound(self) -> Self:
        _validate_linked_source(self.run_input.schedule, self.dataset)
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
            bundle_hash=_digest(self.schema_version, canonical_json(self).encode()),
        )


class ScheduledStoredLoopInput(ResearchValue):
    schema_version: Literal["monitor-loop-stored-input-v2"] = "monitor-loop-stored-input-v2"
    prepared: FrozenPreparedCollection
    run_input: ScheduledLoopInput
    dataset: ScheduledLoopDatasetManifest
    day_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def bound(self):
        _validate_linked_source(self.run_input.schedule, self.dataset)
        bindings = tuple(LoopDatasetPlanBinding(
            effective_trade_date=row.effective_trade_date,
            version_id=row.version.version_id, plan_hash=row.version.plan_hash,
        ) for row in relevant_schedule_entries(self.prepared.schedule, self.run_input.boundary))
        if (self.run_input.schedule != self.prepared.schedule
            or self.run_input.initial_account != self.prepared.account
            or self.run_input.dataset_hash != self.dataset.dataset_hash
            or self.run_input.boundary != self.dataset.boundary
            or self.dataset.plan_bindings != bindings
            or self.dataset.requirements != scheduled_dataset_requirements(
                self.prepared.schedule, self.run_input.boundary,
            )
            or self.dataset.scope.symbols != (self.prepared.schedule.symbol,)
            or len(self.day_hashes) != len(self.dataset.days)):
            raise ValueError("stored collection must bind the exact chain/account/dataset")
        return self

    @property
    def reference(self):
        return StoredLoopInput.reference.fget(self)


class WorkbenchStoredLoopInput(StoredLoopInput):
    schema_version: Literal["monitor-loop-stored-input-v3"] = "monitor-loop-stored-input-v3"
    prepared: WorkbenchPlanSelection
    run_input: WorkbenchLoopInput

    @model_validator(mode="after")
    def selection_bound(self):
        if self.run_input.selection_hash != self.prepared.manifest_hash:
            raise ValueError("workbench input differs from its complete research declaration")
        return self


_STORED_LOOP_CODEC = TypeAdapter(
    Annotated[
        StoredLoopInput | ScheduledStoredLoopInput | WorkbenchStoredLoopInput,
        Field(discriminator="schema_version"),
    ]
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

    def report_path(self, digest: str) -> Path:
        return self._object_path("report", digest)

    def persist_report(self, report):
        """Publish a typed immutable header without enlarging SQLite row bounds."""
        from trade_plan_monitor.backtest.loop_report import decode_loop_report

        report = decode_loop_report(report.model_dump_json())
        self._owned_root(create=False)
        payload = canonical_json(report.model_dump(mode="python", exclude={"report_hash"})).encode()
        self._publish(self.report_path(report.report_hash), payload)
        return self.load_report(report.report_hash)

    def load_report(self, digest: str):
        from trade_plan_monitor.backtest.loop_report import (
            LOOP_REPORT_VERSION,
            SCHEDULED_LOOP_REPORT_VERSION,
            decode_loop_report,
        )

        self._owned_root(create=False)
        payload = self._read(
            self.report_path(digest), (LOOP_REPORT_VERSION, SCHEDULED_LOOP_REPORT_VERSION), digest,
        )
        import json

        report = decode_loop_report(
            canonical_json(json.loads(payload) | {"report_hash": digest})
        )
        if (
            canonical_json(report.model_dump(mode="python", exclude={"report_hash"})).encode()
            != payload
        ):
            raise RuntimeError("immutable loop report is not canonical")
        return report

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

    def _read(self, path: Path, domain: str | tuple[str, ...], digest: str) -> bytes:
        if path.is_symlink() or path.is_junction():
            raise RuntimeError("loop input object cannot be a link")
        try:
            if path.stat().st_size > _MAX_OBJECT_BYTES:
                raise RuntimeError("loop input object exceeds existing evidence bounds")
            with path.open("rb") as file:
                blocks = []
                remaining = _MAX_OBJECT_BYTES + 1
                while remaining:
                    block = file.read(min(65_536, remaining))
                    if not block:
                        break
                    blocks.append(block)
                    remaining -= len(block)
                payload = b"".join(blocks)
        except FileNotFoundError:
            raise RuntimeError("immutable loop input object is missing") from None
        domains = (domain,) if isinstance(domain, str) else domain
        if len(payload) > _MAX_OBJECT_BYTES or not any(
            _digest(value, payload) == digest for value in domains
        ):
            raise RuntimeError("immutable loop input content hash is invalid")
        return payload

    def persist(
        self,
        *,
        prepared: FrozenPreparedPlan | FrozenPreparedCollection,
        run_input: MonitorLoopInput | ScheduledLoopInput,
        dataset: LoopDatasetManifest | ScheduledLoopDatasetManifest,
        market_source: BacktestMarketStore | None = None,
        frozen_source: LoopInputReference | None = None,
    ) -> StoredLoopInput | ScheduledStoredLoopInput:
        # Validate all authority bindings before creating the directory or copying evidence.
        if (market_source is None) == (frozen_source is None):
            raise ValueError("choose one verified market source")
        scheduled = isinstance(prepared, FrozenPreparedCollection)
        stored_type = (WorkbenchStoredLoopInput if isinstance(prepared, WorkbenchPlanSelection)
                       else ScheduledStoredLoopInput if scheduled else StoredLoopInput)
        candidate = stored_type(
            prepared=prepared,
            run_input=run_input,
            dataset=dataset,
            day_hashes=tuple("0" * 64 for _ in dataset.days),
        )
        self._owned_root(create=True)
        hashes = []
        if frozen_source is not None:
            stream = self.open_dataset(frozen_source)
        else:
            stream = (open_frozen_scheduled_loop_dataset(market_source, dataset) if scheduled
                      else market_source.open_frozen_loop_dataset(dataset))
        with stream as reader:
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

    def load(
        self, reference: LoopInputReference, *, verify_days: bool = True,
    ) -> StoredLoopInput | ScheduledStoredLoopInput:
        reference = LoopInputReference.model_validate(reference.model_dump(mode="python"))
        self._owned_root(create=False)
        payload = self._read(
            self.bundle_path(reference),
            (_BUNDLE_DOMAIN, "monitor-loop-stored-input-v2", "monitor-loop-stored-input-v3"),
            reference.bundle_hash,
        )
        stored = _STORED_LOOP_CODEC.validate_json(payload)
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

    def prune_unreferenced(
        self,
        inputs: Iterable[StoredLoopInput],
        reports: Iterable[str],
        *,
        remaining_budget: int,
    ) -> tuple[int, bool]:
        """Remove individual owned objects only; caller serializes with publication."""
        if type(remaining_budget) is not int or not 0 <= remaining_budget <= 1000:
            raise ValueError("remaining_budget must be between 0 and 1000")
        if not self.root.exists():
            return 0, False
        self._owned_root(create=False)
        keep = {"owner.json"}
        for stored in inputs:
            keep.add(self.bundle_path(stored.reference).name)
            keep.update(self.day_path(digest).name for digest in stored.day_hashes)
        keep.update(self.report_path(digest).name for digest in reports)
        deleted = 0
        with os.scandir(self.root) as entries:
            for entry in entries:
                if entry.name in keep or not (
                    re.fullmatch(r"(?:bundle|day|report)-[0-9a-f]{64}\.json", entry.name)
                    or entry.name.startswith(".writing-")
                ):
                    continue
                path = Path(entry.path)
                if (
                    path.is_symlink()
                    or path.is_junction()
                    or not entry.is_file(follow_symlinks=False)
                ):
                    raise RuntimeError("loop cleanup object must be an owned regular file")
                if path.parent.resolve() != self.root.resolve():
                    raise RuntimeError("loop cleanup path escapes its owned directory")
                if deleted == remaining_budget:
                    return deleted, True
                path.unlink()
                deleted += 1
        return deleted, False

    @contextmanager
    def open_dataset(
        self, reference: LoopInputReference
    ) -> Iterator[Iterator[LoopFrozenSymbolDay]]:
        stored = self.load(reference, verify_days=False)
        yield (self._read_day(stored, index) for index in range(len(stored.day_hashes)))

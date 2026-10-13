from __future__ import annotations

import struct

import numpy as np
import pytest

from aoe2mr.backends.fake import FakeProcess, FakeProcessBackend
from aoe2mr.backends.win32 import constants as c
from aoe2mr.concurrency import CancellationToken, OperationCancelledError
from aoe2mr.config import RegionsConfig, SamplingConfig
from aoe2mr.process_discovery.models import ProcessEntry
from aoe2mr.snapshot_analysis.analysis import (
    compare_snapshots,
    read_current,
    refine_from_snapshot,
    scan_value,
)
from aoe2mr.snapshot_analysis.capture import CHUNK_SIZE, CaptureSelection, SnapshotCapturer
from aoe2mr.snapshot_analysis.models import DataType, FilterKind, ValueFilter
from aoe2mr.snapshot_analysis.session import ResearchSession, SessionStateError
from tests.conftest import region

PID = 5000
HEAP = 0x100000
HEAP_SIZE = 3 * 4096
IMAGE = 0x400000


class Game:
    """A fake process whose 'heap' holds a few int32/float32 values at known offsets."""

    WOOD = HEAP + 0x10
    FOOD = HEAP + 0x20
    DECOY = HEAP + 0x1010  # second copy of wood that lags behind (like a UI cache)
    TIME = HEAP + 0x2000

    def __init__(self) -> None:
        self.heap = bytearray(HEAP_SIZE)
        self.proc = FakeProcess(
            entry=ProcessEntry(PID, 1, "AoE2DE_s.exe", 10),
            regions=[
                region(HEAP, HEAP_SIZE),
                region(IMAGE, 4096, protect=c.PAGE_READONLY, type_=c.MEM_IMAGE),
                region(0x900000, 4096, protect=c.PAGE_READWRITE | c.PAGE_GUARD),
            ],
        )
        self.proc.memory[IMAGE] = struct.pack("<i", 200) * 1024
        self.set_i32(self.WOOD, 200)
        self.set_i32(self.FOOD, 200)
        self.set_i32(self.DECOY, 200)
        self.set_f32(self.TIME, 1.5)
        self.backend = FakeProcessBackend([self.proc])

    def _sync(self) -> None:
        self.proc.memory[HEAP] = bytes(self.heap)

    def set_i32(self, address: int, value: int) -> None:
        struct.pack_into("<i", self.heap, address - HEAP, value)
        self._sync()

    def set_f32(self, address: int, value: float) -> None:
        struct.pack_into("<f", self.heap, address - HEAP, value)
        self._sync()


@pytest.fixture
def game() -> Game:
    return Game()


def capturer(game: Game, max_bytes: int = 1 << 30) -> SnapshotCapturer:
    return SnapshotCapturer(game.backend, RegionsConfig(min_region_size=0),
                            SamplingConfig(max_snapshot_bytes=max_bytes))


def session(game: Game) -> ResearchSession:
    return ResearchSession(game.backend, PID, RegionsConfig(min_region_size=0), SamplingConfig())


# --- models ---------------------------------------------------------------------------------


def test_data_type_sizes_and_coerce() -> None:
    assert [d.size for d in DataType] == [1, 1, 2, 2, 4, 4, 8, 8, 4, 8]
    assert all(d.np_dtype.itemsize == d.size for d in DataType)
    assert DataType.INT32.coerce("0x10") == 16
    assert DataType.FLOAT32.coerce("1.5") == 1.5
    with pytest.raises(ValueError):
        DataType.UINT8.coerce("256")
    with pytest.raises(ValueError):
        DataType.INT8.coerce("-129")
    with pytest.raises(ValueError):
        DataType.INT32.coerce("abc")


@pytest.mark.parametrize(
    ("kind", "operand", "old", "new", "expected"),
    [
        (FilterKind.EQUALS, 5, None, 5, True),
        (FilterKind.DISPLAYED, 207, None, 207.0, True),
        (FilterKind.DISPLAYED, 207, None, 207.93, True),   # truncated display
        (FilterKind.DISPLAYED, 207, None, 206.6, True),    # rounded display
        (FilterKind.DISPLAYED, 207, None, 208.0, False),
        (FilterKind.DISPLAYED, 207, None, 206.4, False),
        (FilterKind.CHANGED, None, 1, 2, True),
        (FilterKind.CHANGED, None, 1, 1, False),
        (FilterKind.UNCHANGED, None, 1, 1, True),
        (FilterKind.INCREASED, None, 1, 2, True),
        (FilterKind.INCREASED, None, 2, 1, False),
        (FilterKind.DECREASED, None, 2, 1, True),
        (FilterKind.INCREASED_BY, 25, 200, 225, True),
        (FilterKind.INCREASED_BY, 25, 200, 226, False),
        (FilterKind.DECREASED_BY, 50, 200, 150, True),
    ],
)
def test_filters(kind: FilterKind, operand: float | None, old: float | None, new: float,
                 expected: bool) -> None:
    assert ValueFilter(kind, operand).matches(old, new) is expected


def test_filter_needs_operand_and_rejects_nan() -> None:
    with pytest.raises(ValueError):
        ValueFilter(FilterKind.EQUALS)
    assert not ValueFilter(FilterKind.CHANGED).matches(1.0, float("nan"))
    assert not ValueFilter(FilterKind.DISPLAYED, 5).matches(None, float("inf"))
    assert ValueFilter(FilterKind.EQUALS, 1.0, tolerance=0.01).matches(None, 1.005)


# --- capture --------------------------------------------------------------------------------


def test_capture_selects_private_writable_by_default(game: Game) -> None:
    snap = capturer(game).capture(PID, "start")
    assert [r.base_address for r in snap.regions] == [HEAP]  # image + guard page excluded
    assert snap.total_bytes == HEAP_SIZE == snap.planned_bytes and not snap.truncated
    assert snap.read_value(Game.WOOD, DataType.INT32) == 200
    assert snap.read_value(0x5, DataType.INT32) is None
    with_image = capturer(game).capture(PID, selection=CaptureSelection(image=True,
                                                                        writable_only=False))
    assert {r.base_address for r in with_image.regions} == {HEAP, IMAGE}


def test_capture_respects_byte_cap_smallest_first(game: Game) -> None:
    game.proc.regions.append(region(0x800000, 2 * 4096))
    snap = capturer(game, max_bytes=2 * 4096).capture(PID)
    assert [r.base_address for r in snap.regions] == [0x800000]  # smaller region first
    assert snap.truncated and snap.planned_bytes == HEAP_SIZE + 2 * 4096


def test_capture_cancel_and_progress(game: Game) -> None:
    seen: list[tuple[int, int]] = []
    capturer(game).capture(PID, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (HEAP_SIZE, HEAP_SIZE)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        capturer(game).capture(PID, cancel=token)


def test_capture_splits_around_unreadable_chunk(game: Game) -> None:
    big = 3 * CHUNK_SIZE
    game.proc.regions = [region(HEAP, big)]
    game.proc.memory[HEAP] = b"\x01" * CHUNK_SIZE  # only the first chunk is readable
    snap = capturer(game).capture(PID)
    assert snap.failed_chunks == 2
    assert [(r.base_address, r.size) for r in snap.regions] == [(HEAP, CHUNK_SIZE)]


def test_whole_region_is_captured_without_copy(game: Game) -> None:
    snap = capturer(game).capture(PID)
    assert isinstance(snap.regions[0].data, bytearray)


# --- scans ----------------------------------------------------------------------------------


def test_exact_scan_finds_aligned_matches(game: Game) -> None:
    snap = capturer(game).capture(PID)
    cand = scan_value(snap, DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    assert set(cand.addresses.tolist()) == {Game.WOOD, Game.FOOD, Game.DECOY}
    assert cand.values.tolist() == [200, 200, 200]


def test_displayed_scan_finds_float_resource(game: Game) -> None:
    game.set_f32(Game.WOOD, 207.4)  # the game shows 207
    snap = capturer(game).capture(PID)
    cand = scan_value(snap, DataType.FLOAT32, ValueFilter(FilterKind.DISPLAYED, 207))
    assert cand.addresses.tolist() == [Game.WOOD]
    assert cand.values[0] == pytest.approx(207.4, abs=1e-4)
    exact = scan_value(snap, DataType.FLOAT32, ValueFilter(FilterKind.EQUALS, 207))
    assert len(exact) == 0  # why an exact search fails on the real game


def test_float_scan_tolerance(game: Game) -> None:
    snap = capturer(game).capture(PID)
    near = scan_value(snap, DataType.FLOAT32, ValueFilter(FilterKind.EQUALS, 1.49, 0.02))
    assert near.addresses.tolist() == [Game.TIME]


def test_scan_cap(game: Game) -> None:
    snap = capturer(game).capture(PID)
    zeros = scan_value(snap, DataType.INT32, ValueFilter(FilterKind.EQUALS, 0), max_candidates=10)
    assert len(zeros) == 10 and zeros.truncated


def test_scan_requires_value_filter(game: Game) -> None:
    snap = capturer(game).capture(PID)
    with pytest.raises(ValueError):
        scan_value(snap, DataType.INT32, ValueFilter(FilterKind.CHANGED))


def test_scan_is_cancellable(game: Game) -> None:
    snap = capturer(game).capture(PID)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        scan_value(snap, DataType.FLOAT32, ValueFilter(FilterKind.EQUALS, 1.0, 0.5),
                   cancel=token)


def test_compare_unknown_initial_value(game: Game) -> None:
    cap = capturer(game)
    before = cap.capture(PID)
    game.set_i32(Game.WOOD, 225)
    game.set_f32(Game.TIME, 2.5)
    after = cap.capture(PID)
    inc = compare_snapshots(before, after, DataType.INT32, ValueFilter(FilterKind.INCREASED))
    # the float's bit pattern also "increases" when read as int32; that is expected noise
    assert Game.WOOD in set(inc.addresses.tolist())
    by25 = compare_snapshots(before, after, DataType.INT32,
                             ValueFilter(FilterKind.INCREASED_BY, 25))
    assert by25.addresses.tolist() == [Game.WOOD]
    f = compare_snapshots(before, after, DataType.FLOAT32,
                          ValueFilter(FilterKind.INCREASED_BY, 1.0))
    assert f.addresses.tolist() == [Game.TIME]
    same = compare_snapshots(before, after, DataType.INT32, ValueFilter(FilterKind.UNCHANGED))
    assert Game.FOOD in set(same.addresses.tolist())
    assert Game.WOOD not in set(same.addresses.tolist())


def test_read_current_batches_and_marks_unreadable(game: Game) -> None:
    addresses = np.array([Game.DECOY, Game.WOOD, 0x5, Game.FOOD], dtype=np.uint64)
    game.set_i32(Game.WOOD, 321)
    with game.backend.open_read_only(PID) as proc:
        values, ok = read_current(proc, DataType.INT32, addresses)
    assert ok.tolist() == [True, True, False, True]
    assert values[ok].tolist() == [200, 321, 200]


def test_refine_from_snapshot_rejects_lagging_decoy(game: Game) -> None:
    cap = capturer(game)
    cand = scan_value(cap.capture(PID), DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    game.set_i32(Game.WOOD, 225)
    cand = refine_from_snapshot(cand, cap.capture(PID), ValueFilter(FilterKind.INCREASED_BY, 25))
    assert cand.addresses.tolist() == [Game.WOOD]
    assert cand.values.tolist() == [225]
    assert len(cand.history) == 2


# --- session --------------------------------------------------------------------------------


def test_session_known_value_workflow(game: Game) -> None:
    s = session(game)
    with pytest.raises(SessionStateError):
        s.next_scan(ValueFilter(FilterKind.CHANGED))
    game.set_f32(Game.WOOD, 200.25)
    found = s.new_scan(DataType.FLOAT32, ValueFilter(FilterKind.DISPLAYED, 200))
    assert found is not None and Game.WOOD in set(found.addresses.tolist())
    assert s.baseline is None  # the snapshot is not kept once candidates exist

    game.set_f32(Game.WOOD, 225.75)  # no new snapshot needed: next scan reads live
    s.next_scan(ValueFilter(FilterKind.DISPLAYED, 225))
    assert s.candidates is not None and s.candidates.addresses.tolist() == [Game.WOOD]
    game.set_f32(Game.WOOD, 230.75)
    s.next_scan(ValueFilter(FilterKind.INCREASED_BY, 5))
    assert s.candidates is not None and len(s.candidates) == 1
    s.annotate("villager dropped 5 wood")
    assert [e.kind for e in s.timeline] == ["snapshot", "scan", "filter", "filter",
                                            "annotation"]
    assert s.timeline[2].candidate_count == 1

    game.set_f32(Game.WOOD, 240.0)
    live = s.read_live()
    assert live[0].address == Game.WOOD and live[0].value == 240.0

    record = s.to_record()
    assert record["candidates"]["items"] == [{"address": f"0x{Game.WOOD:X}", "value": 230.75}]
    s.reset()
    assert s.candidates is None and s.timeline[-1].kind == "reset"


def test_session_unknown_value_workflow(game: Game) -> None:
    s = session(game)
    assert s.new_scan(DataType.INT32, ValueFilter(FilterKind.CHANGED)) is None
    assert s.baseline is not None and s.awaiting_next_scan
    game.set_i32(Game.FOOD, 150)
    with pytest.raises(SessionStateError):
        s.next_scan(ValueFilter(FilterKind.DECREASED))  # no data type
    s.next_scan(ValueFilter(FilterKind.DECREASED_BY, 50), data_type=DataType.INT32)
    assert s.candidates is not None and s.candidates.addresses.tolist() == [Game.FOOD]
    assert s.baseline is None


def test_session_snapshot_limit_and_truncation_note(game: Game) -> None:
    s = session(game)
    s.set_snapshot_limit(4096)
    s.new_scan(DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    assert "TRUNCATED" in s.timeline[0].message


def test_live_read_marks_unreadable(game: Game) -> None:
    s = session(game)
    s.new_scan(DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    game.proc.regions = []
    assert all(v.value is None for v in s.read_live())
    s.next_scan(ValueFilter(FilterKind.UNCHANGED))
    assert s.candidates is not None and len(s.candidates) == 0  # stale addresses dropped
    with pytest.raises(SessionStateError):
        s.next_scan(ValueFilter(FilterKind.CHANGED))

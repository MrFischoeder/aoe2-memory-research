from __future__ import annotations

import struct

import pytest

from aoe2mr.backends.fake import FakeProcess, FakeProcessBackend
from aoe2mr.backends.win32 import constants as c
from aoe2mr.concurrency import CancellationToken, OperationCancelledError
from aoe2mr.config import RegionsConfig, SamplingConfig
from aoe2mr.process_discovery.models import ProcessEntry
from aoe2mr.snapshot_analysis.analysis import compare_snapshots, refine, scan_value
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
def test_filters(kind: FilterKind, operand: int | None, old: int | None, new: int,
                 expected: bool) -> None:
    assert ValueFilter(kind, operand).matches(old, new) is expected


def test_filter_needs_operand_and_rejects_nan() -> None:
    with pytest.raises(ValueError):
        ValueFilter(FilterKind.EQUALS)
    assert not ValueFilter(FilterKind.CHANGED).matches(1.0, float("nan"))
    assert ValueFilter(FilterKind.EQUALS, 1.0, tolerance=0.01).matches(None, 1.005)


# --- capture --------------------------------------------------------------------------------


def test_capture_selects_private_writable_by_default(game: Game) -> None:
    snap = capturer(game).capture(PID, "start")
    assert [r.base_address for r in snap.regions] == [HEAP]  # image + guard page excluded
    assert snap.total_bytes == HEAP_SIZE and not snap.truncated
    assert snap.read_value(Game.WOOD, DataType.INT32) == 200
    assert snap.read_value(0x5, DataType.INT32) is None
    with_image = capturer(game).capture(PID, selection=CaptureSelection(image=True,
                                                                        writable_only=False))
    assert {r.base_address for r in with_image.regions} == {HEAP, IMAGE}


def test_capture_respects_byte_cap(game: Game) -> None:
    snap = capturer(game, max_bytes=4096).capture(PID)
    assert snap.total_bytes == 4096 and snap.truncated


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


# --- scans ----------------------------------------------------------------------------------


def test_exact_scan_finds_aligned_matches(game: Game) -> None:
    snap = capturer(game).capture(PID)
    cand = scan_value(snap, DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    assert set(cand.addresses) == {Game.WOOD, Game.FOOD, Game.DECOY}
    assert list(cand.values) == [200, 200, 200]


def test_float_scan_exact_and_tolerance(game: Game) -> None:
    snap = capturer(game).capture(PID)
    exact = scan_value(snap, DataType.FLOAT32, ValueFilter(FilterKind.EQUALS, 1.5))
    assert list(exact.addresses) == [Game.TIME]
    near = scan_value(snap, DataType.FLOAT32, ValueFilter(FilterKind.EQUALS, 1.49, 0.02))
    assert list(near.addresses) == [Game.TIME]


def test_scan_cap(game: Game) -> None:
    snap = capturer(game).capture(PID)
    zeros = scan_value(snap, DataType.INT32, ValueFilter(FilterKind.EQUALS, 0), max_candidates=10)
    assert len(zeros) == 10 and zeros.truncated


def test_scan_requires_equals(game: Game) -> None:
    snap = capturer(game).capture(PID)
    with pytest.raises(ValueError):
        scan_value(snap, DataType.INT32, ValueFilter(FilterKind.CHANGED))


def test_compare_unknown_initial_value(game: Game) -> None:
    cap = capturer(game)
    before = cap.capture(PID)
    game.set_i32(Game.WOOD, 225)
    game.set_f32(Game.TIME, 2.5)
    after = cap.capture(PID)
    inc = compare_snapshots(before, after, DataType.INT32, ValueFilter(FilterKind.INCREASED))
    # the float's bit pattern also "increases" when read as int32; that is expected noise
    assert Game.WOOD in set(inc.addresses)
    by25 = compare_snapshots(before, after, DataType.INT32,
                             ValueFilter(FilterKind.INCREASED_BY, 25))
    assert list(by25.addresses) == [Game.WOOD]
    f = compare_snapshots(before, after, DataType.FLOAT32,
                          ValueFilter(FilterKind.INCREASED_BY, 1.0))
    assert list(f.addresses) == [Game.TIME]


def test_refine_rejects_lagging_decoy(game: Game) -> None:
    cap = capturer(game)
    cand = scan_value(cap.capture(PID), DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    game.set_i32(Game.WOOD, 225)
    cand = refine(cand, cap.capture(PID), ValueFilter(FilterKind.INCREASED_BY, 25))
    assert list(cand.addresses) == [Game.WOOD]
    assert list(cand.values) == [225]
    assert len(cand.history) == 2


# --- session --------------------------------------------------------------------------------


def test_session_workflow_and_timeline(game: Game) -> None:
    s = session(game)
    with pytest.raises(SessionStateError):
        s.scan_value(DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    s.capture("start")
    s.scan_value(DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    assert s.candidates is not None and len(s.candidates) == 3
    with pytest.raises(SessionStateError):  # same snapshot: a change filter makes no sense
        s.apply_filter(ValueFilter(FilterKind.CHANGED))
    game.set_i32(Game.WOOD, 225)
    s.capture("gathered 25 wood")
    s.apply_filter(ValueFilter(FilterKind.INCREASED_BY, 25))
    assert s.candidates is not None and list(s.candidates.addresses) == [Game.WOOD]
    s.annotate("villager gathered exactly 25 wood")
    assert [e.kind for e in s.timeline] == ["snapshot", "scan", "snapshot", "filter",
                                            "annotation"]
    assert s.timeline[3].candidate_count == 1

    game.set_i32(Game.WOOD, 230)
    live = s.read_live()
    assert live[0].address == Game.WOOD and live[0].value == 230

    record = s.to_record()
    assert record["candidates"]["items"] == [{"address": f"0x{Game.WOOD:X}", "value": 225}]
    s.reset()
    assert s.candidates is None and s.timeline[-1].kind == "reset"


def test_session_compare_without_candidates(game: Game) -> None:
    s = session(game)
    s.capture()
    with pytest.raises(SessionStateError):
        s.apply_filter(ValueFilter(FilterKind.CHANGED), data_type=DataType.INT32)
    game.set_i32(Game.FOOD, 150)
    s.capture()
    with pytest.raises(SessionStateError):
        s.apply_filter(ValueFilter(FilterKind.DECREASED))  # no data type
    s.apply_filter(ValueFilter(FilterKind.DECREASED_BY, 50), data_type=DataType.INT32)
    assert s.candidates is not None and list(s.candidates.addresses) == [Game.FOOD]


def test_session_keeps_bounded_snapshots(game: Game) -> None:
    s = session(game)
    for _ in range(5):
        s.capture()
    assert len(s.snapshots) == 2 and s.snapshots[-1].snapshot_id == 5


def test_live_read_marks_unreadable(game: Game) -> None:
    s = session(game)
    s.capture()
    s.scan_value(DataType.INT32, ValueFilter(FilterKind.EQUALS, 200))
    game.proc.regions = []
    assert all(v.value is None for v in s.read_live())

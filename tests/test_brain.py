from dataclasses import replace
from pathlib import Path
import threading
import time

import numpy as np

from flybrain.brain import BrainState, BrainWorker, NeuralModel
from flybrain.data import normalized_weights
from flybrain.game import Action


def model(seed=64):
    return NeuralModel(Path("/unused"), kind="demo", seed=seed)


def wait_until(predicate, timeout=2):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("Worker did not reach expected state")


def test_normalization_uses_incoming_rows_and_preserves_inhibition():
    matrix = normalized_weights(np.array([0, 1, 0]), np.array([2, 2, 1]),
                                np.array([2, 6, 3]), np.array([1, -1, 1]), 3)
    np.testing.assert_allclose(np.asarray(abs(matrix).sum(axis=1)).ravel(), [0, 1, 1])
    assert matrix[2, 1] < 0 and matrix[2, 0] > 0


def test_seeded_spikes_and_controls_are_reproducible():
    a, b = model(), model()
    frame = np.random.default_rng(1).integers(0, 255, (64, 48, 3), dtype=np.uint8)
    for _ in range(35):
        sa, sb = a.step(frame), b.step(frame)
        np.testing.assert_array_equal(a.spikes, b.spikes)
        assert sa.action == sb.action


def test_visual_input_changes_downstream_motor_activity():
    a, b = model(), model()
    black = np.zeros((64, 48, 3), np.uint8)
    stimulus = black.copy()
    stimulus[:, :24, 0] = 255
    trace_a, trace_b = [], []
    for _ in range(70):
        trace_a.append(a.step(black).action.x)
        trace_b.append(b.step(stimulus).action.x)
    assert not np.allclose(trace_a, trace_b)


class BlockedModel:
    dt = .025
    draw_nodes = np.arange(1)

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def step(self, frame):
        self.entered.set()
        self.release.wait(2)
        return BrainState(tick=1, action=Action(x=1, fire=True))


def test_handoff_discards_an_inflight_neural_command():
    blocked = BlockedModel()
    worker = BrainWorker(blocked)
    try:
        worker.set_enabled(True)
        worker.submit(np.zeros((64, 48, 3), np.uint8))
        assert blocked.entered.wait(1)
        worker.set_enabled(False)
        assert worker.action() == Action()
        worker.set_enabled(True)
        blocked.release.set()
        time.sleep(.05)
        assert worker.snapshot().tick == 0
        assert worker.action() == Action()  # Reconnect without a fresh frame stays neutral.
        worker.submit(np.zeros((64, 48, 3), np.uint8))
        wait_until(lambda: worker.snapshot().tick == 1)
        assert worker.action().fire
    finally:
        blocked.release.set()
        worker.close()


def test_stale_commands_release_control_and_bomb_is_one_shot():
    worker = BrainWorker(model())
    try:
        worker.set_enabled(True)
        now = time.monotonic()
        with worker.lock:
            worker.frame_time = now
            worker.state = BrainState(timestamp=now, epoch=worker.epoch,
                                       action=Action(x=.5, fire=True, bomb=True))
        assert worker.action().bomb
        assert not worker.action().bomb
        assert worker.action(now=now+1) == Action()
        worker.set_enabled(False)
        assert worker.action() == Action()
    finally:
        worker.close()


def test_control_handoff_keeps_sensing_and_rejects_inflight_actuation():
    class PhasedModel(BlockedModel):
        def __init__(self):
            super().__init__()
            self.second_entered = threading.Event()
            self.second_release = threading.Event()
            self.calls = 0

        def step(self, frame):
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                self.release.wait(2)
            elif self.calls == 2:
                self.second_entered.set()
                self.second_release.wait(2)
            return BrainState(tick=self.calls, action=Action(x=1, fire=True, bomb=True))

    blocked = PhasedModel()
    worker = BrainWorker(blocked)
    try:
        worker.set_enabled(True)
        worker.submit(np.zeros((64, 48, 3), np.uint8))
        assert blocked.entered.wait(1)
        worker.set_control(False)
        worker.set_control(True)
        blocked.release.set()
        assert blocked.second_entered.wait(1)
        # The real first result is published for telemetry while the fresh
        # computation is blocked. It cannot cross the control boundary.
        assert worker.snapshot().tick == 1
        assert worker.action() == Action()
        assert worker.enabled
        blocked.second_release.set()
        wait_until(lambda: worker.snapshot().control_epoch == worker.control_epoch)
        assert worker.action().fire
        worker.set_control(False)
        assert worker.action() == Action() and worker.enabled
    finally:
        blocked.release.set()
        blocked.second_release.set()
        worker.close()


def test_reward_and_punishment_drive_distinct_neurons_and_decay():
    frame = np.zeros((64, 48, 3), np.uint8)
    baseline, rewarded, punished = model(), model(), model()
    rewarded.stimulate(reward=1)
    punished.stimulate(punishment=1)
    for _ in range(3):
        baseline.step(frame)
        rs, ps = rewarded.step(frame), punished.step(frame)
    assert rewarded.spikes[rewarded.reward_nodes].sum() > baseline.spikes[baseline.reward_nodes].sum()
    assert punished.spikes[punished.punishment_nodes].sum() > baseline.spikes[baseline.punishment_nodes].sum()
    assert rs.reward_events == 1 and rs.punishment_events == 0
    assert ps.punishment_events == 1 and ps.reward_events == 0
    for _ in range(25):
        rs, ps = rewarded.step(frame), punished.step(frame)
    assert rs.reward == ps.punishment == 0
    np.testing.assert_array_equal(baseline.w.data, rewarded.w.data)
    np.testing.assert_array_equal(baseline.w.data, punished.w.data)


def test_feedback_accumulates_without_live_control_and_handles_terminal_event():
    worker = BrainWorker(model())
    frame = np.zeros((64, 48, 3), np.uint8)
    try:
        # Final damage can arrive after the application disables the worker.
        worker.feedback(frame, reward=3, punishment=1)
        worker.feedback(frame, reward=2, punishment=1)
        wait_until(lambda: worker.snapshot().reward_events == 5)
        state = worker.snapshot()
        assert state.punishment_events == 2
        assert worker.action() == Action() and state.action == Action()
        tick = state.tick
        time.sleep(.08)
        assert worker.snapshot().tick == tick  # Events are never replayed.
        worker.reset_feedback()
        wait_until(lambda: worker.model.reward == worker.model.punishment == 0)
    finally:
        worker.close()

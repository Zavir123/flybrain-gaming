"""Connectome-derived LIF dynamics and a cancellable latest-frame worker.

The model receives a 48x64 RGB image and event-triggered stimulation.
No enemy coordinates, health or game strategy enter its motor calculation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
import time

import numpy as np
from scipy import sparse

from .data import SCHEMA
from .game import Action


@dataclass(frozen=True)
class BrainState:
    tick: int = 0
    active: int = 0
    total_spikes: int = 0
    mean_hz: float = 0.0
    left_hz: float = 0.0
    right_hz: float = 0.0
    forward_hz: float = 0.0
    escape_hz: float = 0.0
    luminance: float = 0.0
    contrast: float = 0.0
    latency_ms: float = 0.0
    realtime_factor: float = 0.0
    action: Action = Action()
    timestamp: float = 0.0
    epoch: int = 0
    control_epoch: int = 0
    reward: float = 0.0
    punishment: float = 0.0
    reward_events: int = 0
    punishment_events: int = 0
    activity: np.ndarray = field(default_factory=lambda: np.zeros(1, np.float32))
    sensory: np.ndarray = field(default_factory=lambda: np.zeros((64, 48), np.float32))


class NeuralModel:
    dt = .025
    tau = .12
    tonic = .18
    gain = 1.5

    def __init__(self, cache: Path, kind="auto", seed=64):
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.real = False
        if kind != "demo" and (cache / "manifest.json").exists():
            manifest = json.loads((cache / "manifest.json").read_text("utf-8"))
            if manifest.get("schema") != SCHEMA:
                raise ValueError("MaleCNS cache version mismatch; run prepare again")
            self.w = sparse.load_npz(cache / "weights.npz").astype(np.float32).tocsr()
            with np.load(cache / "nodes.npz", allow_pickle=False) as nodes:
                for name in ("visual", "pixels", "left", "right", "forward", "escape", "positions", "position_known"):
                    setattr(self, name, nodes[name])
                types = nodes["types"]
                self.reward_nodes = np.flatnonzero(np.char.startswith(types, "PAM"))
                self.punishment_nodes = np.flatnonzero(np.char.startswith(types, "PPL1"))
                if not len(self.reward_nodes) or not len(self.punishment_nodes):
                    raise ValueError("PAM/PPL1 stimulation annotations missing; rebuild brain cache")
            self.real = True
            self.label = "MaleCNS v1.0"
            self.manifest = manifest
        elif kind == "malecns":
            raise FileNotFoundError("MaleCNS cache missing. Run: python main.py prepare")
        else:
            self._demo_graph()
        self.n = self.w.shape[0]
        self.edges = self.w.nnz
        self.v = np.zeros(self.n, np.float32)
        self.spikes = np.zeros(self.n, np.float32)
        self.activity = np.zeros(self.n, np.float32)
        self.previous = np.zeros(len(self.visual), np.float32)
        self.history = deque(maxlen=10)
        self.tick = self.total_spikes = 0
        self.control_x = self.control_y = 0.0
        self.last_bomb = -100.0
        self.reward = self.punishment = 0.0
        self.reward_events = self.punishment_events = 0
        known = np.flatnonzero(self.position_known)
        selection = np.random.default_rng(100).choice(known, min(len(known), 1800), replace=False)
        self.draw_nodes = selection
        self.draw_positions = self.positions[selection]
        self.output_nodes = np.concatenate((self.left, self.right, self.forward, self.escape))
        self.splits = np.cumsum([len(self.left), len(self.right), len(self.forward)])

    def _demo_graph(self):
        """Explicitly synthetic fixture, including authored visual-motor paths."""
        self.label = "DEMO / synthetic"
        n = 4096
        rng = self.rng
        self.visual = np.arange(1536)
        self.pixels = np.column_stack((np.arange(1536) % 48, (np.arange(1536)//48)*2))
        self.left, self.right = np.arange(3400, 3440), np.arange(3440, 3480)
        self.forward, self.escape = np.arange(3480, 3520), np.arange(3520, 3560)
        # Synthetic stimulus pools; these indices are not anatomical labels.
        self.reward_nodes = np.arange(3560, 3600)
        self.punishment_nodes = np.arange(3600, 3640)
        pre = rng.integers(0, n, 28000)
        post = rng.integers(0, n, 28000)
        weights = rng.uniform(.008, .055, len(pre)).astype(np.float32)
        weights *= np.where(pre % 5 == 0, -1, 1)
        # Synthetic circuitry: bright left-eye activity excites the right pool.
        for source, target in ((self.visual[self.pixels[:, 0] < 24], self.right),
                               (self.visual[self.pixels[:, 0] >= 24], self.left),
                               (self.visual, self.forward),
                               (self.visual[self.pixels[:, 1] > 42], self.escape)):
            count = len(source)*3
            pre = np.concatenate((pre, np.repeat(source, 3)))
            post = np.concatenate((post, rng.choice(target, count)))
            weights = np.concatenate((weights, np.full(count, .045, np.float32)))
        self.w = sparse.csr_matrix((weights, (post, pre)), shape=(n, n), dtype=np.float32)
        sums = np.asarray(abs(self.w).sum(axis=1)).ravel()
        self.w.data *= np.repeat(1/np.maximum(sums, 1), np.diff(self.w.indptr))
        # Schematic positions, never presented as measured anatomy.
        groups = rng.choice([-1, 0, 1], n, p=[.32, .36, .32])
        self.positions = rng.normal(0, .29, (n, 3)).astype(np.float32)
        self.positions[:, 0] += groups*.75
        self.positions[:, 1] *= np.where(groups == 0, 1.1, 1.5)
        self.position_known = np.ones(n, bool)
        self.manifest = dict(dataset=self.label, synthetic=True, learning=False)

    def stimulate(self, reward=0, punishment=0):
        """Authored 500 ms current pulses, never direct motor commands or learning."""
        self.reward_events += reward
        self.punishment_events += punishment
        self.reward = min(1.0, self.reward + .5*reward)
        self.punishment = min(1.0, self.punishment + .5*punishment)

    def clear_stimulation(self):
        self.reward = self.punishment = 0.0

    def step(self, frame: np.ndarray) -> BrainState:
        started = time.perf_counter()
        rgb = np.asarray(frame, np.float32)/255
        sampled = rgb[self.pixels[:, 1], self.pixels[:, 0]]
        luminance = sampled @ np.array([.2126, .7152, .0722], np.float32)
        temporal = np.abs(luminance-self.previous)
        # RGB approximation: red contrast emphasizes rendered red threats.
        red = np.maximum(sampled[:, 0] - (sampled[:, 1]+sampled[:, 2])*.5, 0)
        drive = np.clip(.45*luminance + 1.5*temporal + .6*red, 0, 1)
        self.previous = luminance

        current = self.w @ self.spikes
        self.v *= np.exp(-self.dt/self.tau)
        self.v += self.gain*current + self.tonic
        self.v += (self.rng.random(self.n) < 1.2*self.dt)*.22
        self.v[self.visual] += drive*.8
        reward, punishment = self.reward, self.punishment
        self.v[self.reward_nodes] += .35*min(1, reward/.5)
        self.v[self.punishment_nodes] += .35*min(1, punishment/.5)
        self.reward = max(0, reward-self.dt)
        self.punishment = max(0, punishment-self.dt)
        fired = self.v >= 1.0
        self.v[fired] = 0
        self.spikes[:] = fired
        self.activity *= .86
        self.activity[fired] = 1
        self.history.append(fired[self.output_nodes].astype(np.float32))
        rates = np.mean(self.history, axis=0)
        left, right, forward, escape = [float(a.mean()) for a in np.split(rates, self.splits)]
        # These game-action meanings are authored mappings, not fly behavior.
        raw_x = float(np.clip((right-left)*9, -1, 1))
        raw_y = float(np.clip((.12-forward)*3, -.6, .6))
        self.control_x = .65*self.control_x + .35*raw_x
        self.control_y = .8*self.control_y + .2*raw_y
        sim_time = self.tick*self.dt
        bomb = escape > .42 and sim_time-self.last_bomb > 10 and self.tick > 30
        if bomb:
            self.last_bomb = sim_time
        action = Action(self.control_x if abs(self.control_x) > .06 else 0,
                        self.control_y if abs(self.control_y) > .06 else 0,
                        forward > .025 and self.tick > 6, bomb)
        self.tick += 1
        count = int(fired.sum())
        self.total_spikes += count
        full_lum = rgb @ np.array([.2126, .7152, .0722], np.float32)
        return BrainState(tick=self.tick, active=count, total_spikes=self.total_spikes,
                          mean_hz=count/self.n/self.dt, left_hz=left/self.dt,
                          right_hz=right/self.dt, forward_hz=forward/self.dt,
                          escape_hz=escape/self.dt, luminance=float(luminance.mean()),
                          reward=reward, punishment=punishment,
                          reward_events=self.reward_events, punishment_events=self.punishment_events,
                          contrast=float(temporal.mean()), latency_ms=(time.perf_counter()-started)*1000,
                          action=action, activity=self.activity[self.draw_nodes].copy(), sensory=full_lum)


class BrainWorker:
    """One model owner; epochs discard in-flight outputs across handoffs.

    The UI never waits for inference. Sensing and control ownership are separate:
    a human can drive while the model keeps observing and computing.
    """

    def __init__(self, model: NeuralModel):
        self.model = model
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.enabled = False
        self.epoch = 0
        self.control_epoch = 0
        self.control_enabled = True
        self.frame = None
        self.frame_time = 0.0
        self.pending_reward = self.pending_punishment = 0
        self.feedback_frame = None
        self.clear_feedback = False
        self.state = BrainState(activity=np.zeros(len(model.draw_nodes), np.float32))
        self.error = ""
        self.epoch_started = time.monotonic()
        self.epoch_ticks = 0
        self.thread = threading.Thread(target=self._run, name="flybrain-model", daemon=True)
        self.thread.start()

    def set_enabled(self, enabled: bool):
        with self.lock:
            self.enabled = enabled
            self.epoch += 1
            self.frame = None
            self.frame_time = 0
            self.epoch_started = time.monotonic()
            self.epoch_ticks = 0
        self.wake.set()

    def submit(self, frame: np.ndarray):
        with self.lock:
            if self.enabled:
                self.frame = frame.copy()
                self.frame_time = time.monotonic()
        self.wake.set()

    def feedback(self, frame: np.ndarray, *, reward=0, punishment=0):
        """Accumulate events separately from replaceable visual frames.

        Also accepts the final lethal hit after sensing has stopped.
        Only the worker thread mutates neural state.
        """
        with self.lock:
            self.pending_reward += reward
            self.pending_punishment += punishment
            self.feedback_frame = frame.copy()
        self.wake.set()

    def reset_feedback(self):
        with self.lock:
            self.pending_reward = self.pending_punishment = 0
            self.feedback_frame = None
            self.clear_feedback = True
        self.wake.set()

    def set_control(self, enabled: bool):
        """Gate actuation without interrupting sensory input or neural state."""
        with self.lock:
            if self.control_enabled != enabled:
                self.control_enabled = enabled
                self.control_epoch += 1

    def snapshot(self) -> BrainState:
        with self.lock:
            return self.state

    def action(self, now=None) -> Action:
        now = time.monotonic() if now is None else now
        with self.lock:
            if (not self.enabled or not self.control_enabled or self.error or
                    self.state.control_epoch != self.control_epoch or
                    now-self.frame_time > .3 or self.state.epoch != self.epoch or
                    now-self.state.timestamp > .3):
                return Action()
            # Bomb is an event: consume it once, not once per rendered frame.
            result = self.state.action
            if result.bomb:
                from dataclasses import replace
                self.state = replace(self.state, action=Action(result.x, result.y, result.fire, False))
            return result

    def _run(self):
        from dataclasses import replace
        while not self.stop_event.is_set():
            started = time.monotonic()
            with self.lock:
                epoch = self.epoch
                control_epoch = self.control_epoch
                frame = self.frame
                valid = self.enabled and frame is not None and started-self.frame_time < .3
                reward, punishment = self.pending_reward, self.pending_punishment
                clear_feedback = self.clear_feedback
                self.clear_feedback = False
                if reward or punishment:
                    frame = self.feedback_frame
                    valid = True
                    self.pending_reward = self.pending_punishment = 0
                    self.feedback_frame = None
                enabled = self.enabled
            if clear_feedback:
                self.model.clear_stimulation()
            if not valid:
                self.wake.wait(.05)
                self.wake.clear()
                continue
            try:
                if reward or punishment:
                    self.model.stimulate(reward, punishment)
                state = self.model.step(frame)
                with self.lock:
                    if epoch == self.epoch and (self.enabled or reward or punishment):
                        self.epoch_ticks += 1
                        rtf = self.epoch_ticks*self.model.dt / max(time.monotonic()-self.epoch_started, .001)
                        self.state = replace(state, epoch=epoch, control_epoch=control_epoch,
                                             action=state.action if enabled else Action(),
                                             timestamp=time.monotonic(), realtime_factor=rtf)
            except Exception as exc:
                with self.lock:
                    self.error = f"{type(exc).__name__}: {exc}"
                    self.enabled = False
                break
            self.stop_event.wait(max(0, self.model.dt-(time.monotonic()-started)))

    def close(self):
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=3)

"""A repeatable sensory-to-motor intervention, not a gameplay benchmark."""
from __future__ import annotations

import json
from pathlib import Path
import platform

import numpy as np

from .brain import NeuralModel


def validate(cache: Path, kind="malecns", output=Path("artifacts/validation.json"), ticks=80):
    black = np.zeros((64, 48, 3), np.uint8)
    red = black.copy()
    red[:, :24, 0] = 255
    traces = []
    for name, frame in (("dark", black), ("stimulus", red), ("repeat_dark", black)):
        model = NeuralModel(cache, kind=kind, seed=64)
        trace = []
        print(f"验证 {name}: {model.label}, {model.n:,} cells", flush=True)
        for _ in range(ticks):
            state = model.step(frame)
            trace.append([state.active, state.left_hz, state.right_hz, state.forward_hz,
                          state.action.x, state.action.y, float(state.action.fire), float(state.action.bomb)])
        traces.append(np.asarray(trace))
        identity = dict(model=model.label, neurons=model.n, edges=model.edges)
        del model
    dark, stimulus, repeated = traces
    reproducible = bool(np.array_equal(dark, repeated))
    changed_ticks = int(np.any(dark[:, 4:] != stimulus[:, 4:], axis=1).sum())
    report = dict(**identity, ticks=ticks, seed=64, python=platform.python_version(),
                  repeated_dark_identical=reproducible,
                  stimulus_changes_motor_output=changed_ticks > 0,
                  changed_motor_ticks=changed_ticks,
                  max_pool_hz_difference=float(np.max(np.abs(dark[:, 1:4]-stimulus[:, 1:4]))),
                  limitation="Engineered visual intervention; does not validate natural fly behavior, learning or gameplay skill.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not reproducible or changed_ticks == 0:
        raise RuntimeError("Sensory intervention validation failed; inspect the saved report")

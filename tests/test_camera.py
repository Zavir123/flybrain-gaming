import numpy as np

from flybrain.camera import Camera3D


def test_camera_has_perspective_and_drag_changes_both_axes():
    camera = Camera3D(yaw=0, pitch=0)
    positions = np.array([[1, 1, -1], [1, 1, 1], [-1, -1, 0]])
    first, depth = camera.project(positions, center=(0, 0))
    assert first[0, 0] > first[1, 0] and depth[0] < depth[1]
    camera.orbit(40, 30)
    second, _ = camera.project(positions, center=(0, 0))
    assert not np.allclose(first, second)
    assert np.isfinite(second).all()

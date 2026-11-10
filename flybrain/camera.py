"""Small CPU 3D camera for measured neuron positions; no graphics dependency."""
from dataclasses import dataclass
import math

import numpy as np


@dataclass
class Camera3D:
    yaw: float = .35
    pitch: float = -.2
    zoom: float = 1.0

    def orbit(self, dx, dy):
        self.yaw = (self.yaw+dx*.012) % math.tau
        self.pitch = float(np.clip(self.pitch+dy*.012, -1.45, 1.45))

    def dolly(self, steps):
        self.zoom = float(np.clip(self.zoom*1.12**steps, .55, 2.5))

    def reset(self):
        self.yaw, self.pitch, self.zoom = .35, -.2, 1.0

    def project(self, positions, center=(718, 228), scale=73):
        """Yaw/pitch rotation, perspective division and depth for painter order."""
        positions = np.asarray(positions)
        x = positions[:, 0]*math.cos(self.yaw) + positions[:, 2]*math.sin(self.yaw)
        z = -positions[:, 0]*math.sin(self.yaw) + positions[:, 2]*math.cos(self.yaw)
        y = positions[:, 1]*math.cos(self.pitch) - z*math.sin(self.pitch)
        depth = positions[:, 1]*math.sin(self.pitch) + z*math.cos(self.pitch)
        perspective = 4.5/np.maximum(4.5+depth, .3)
        points = np.column_stack((center[0]+x*scale*self.zoom*perspective,
                                  center[1]+y*scale*self.zoom*perspective))
        return points, depth

"""Resolution-independent Pygame rendering; no gameplay or control decisions."""
from __future__ import annotations

from collections import deque
import math
from pathlib import Path
import random

import numpy as np
import pygame

from .camera import Camera3D
from .game import HEALTH_LIFETIME, HEALTH_RESTORE, HEIGHT, MAX_HP, PICKUP_NAMES, WIDTH

SIZE = (1400, 900)
BG = (9, 15, 25)
CARD = (15, 24, 38)
LINE = (35, 49, 67)
TEXT = (226, 237, 247)
MUTED = (132, 153, 174)
TEAL = (76, 230, 194)
BLUE = (90, 180, 255)
GOLD = (255, 198, 102)
RED = (255, 113, 129)
BRAIN_RECT = pygame.Rect(564, 159, 308, 142)
PAUSE_RECT = pygame.Rect(936, 32, 158, 40)
SKILL_COLORS = {"shield": BLUE, "super": GOLD, "clones": (196, 154, 255),
                "rapid": TEAL, "health": TEAL, "power": GOLD, "bomb": RED}


class Renderer:
    def __init__(self, model):
        self.model = model
        self.canvas = pygame.Surface(SIZE)
        self.field = pygame.Surface((WIDTH, HEIGHT))
        self.fonts = {}
        self.font_path = Path(__file__).parent / "assets/fonts/NotoSansCJKsc-Regular.otf"
        self.mono_path = pygame.font.match_font("menlo,consolas,dejavusansmono")
        rng = random.Random(82)
        self.stars = [(rng.randrange(WIDTH), rng.randrange(HEIGHT), rng.uniform(.3, 1)) for _ in range(95)]
        self.rates = deque(maxlen=160)
        self.last_tick = -1
        self.camera = Camera3D()

    def font(self, size, mono=False):
        key = (size, mono)
        if key not in self.fonts:
            path = self.mono_path if mono else str(self.font_path) if self.font_path.exists() else pygame.font.match_font("pingfangsc,microsoftyahei,notosanscjksc,arial")
            self.fonts[key] = pygame.font.Font(path, size)
        return self.fonts[key]

    def text(self, text, x, y, size=16, color=TEXT, mono=False, width=None, target=None):
        font = self.font(size, mono)
        if width is not None:
            while font.size(str(text))[0] > width and len(str(text)) > 1:
                text = str(text)[:-2] + "…"
        image = font.render(str(text), True, color)
        (target or self.canvas).blit(image, (x, y))
        return image.get_width()

    def card(self, rect, number, title, tag=""):
        pygame.draw.rect(self.canvas, CARD, rect, border_radius=12)
        pygame.draw.rect(self.canvas, LINE, rect, 1, border_radius=12)
        x, y, w, _ = rect
        self.text(number, x+17, y+15, 12, TEAL, True)
        self.text(title, x+47, y+11, 17)
        if tag:
            tag_width = self.font(11, True).size(tag)[0]
            self.text(tag, x+w-17-tag_width, y+15, 11, MUTED, True)
        pygame.draw.line(self.canvas, LINE, (x+16, y+44), (x+w-16, y+44))

    def pill(self, text, rect, color=TEAL):
        pygame.draw.rect(self.canvas, tuple(int(c*.12+8) for c in color), rect, border_radius=7)
        pygame.draw.rect(self.canvas, tuple(int(c*.36) for c in color), rect, 1, border_radius=7)
        self.text(text, rect[0]+12, rect[1]+7, 14, color)

    def draw_field(self, game):
        s = self.field
        s.fill((8, 18, 31))
        for x in range(0, WIDTH, 48):
            pygame.draw.line(s, (13, 28, 43), (x, 0), (x, HEIGHT))
        for y in range(-48, HEIGHT+48, 48):
            yy = int(y + (game.elapsed*24)%48)
            pygame.draw.line(s, (13, 28, 43), (0, yy), (WIDTH, yy))
        for x, y, depth in self.stars:
            yy = int((y+game.elapsed*(18+depth*30)) % HEIGHT)
            pygame.draw.circle(s, (int(55+depth*65), int(73+depth*65), int(91+depth*65)), (x, yy), 1)
        # A faint center flight corridor lends depth without hiding bullets.
        pygame.draw.line(s, (19, 41, 56), (WIDTH//2-90, 0), (WIDTH//2-130, HEIGHT))
        pygame.draw.line(s, (19, 41, 56), (WIDTH//2+90, 0), (WIDTH//2+130, HEIGHT))

        for pickup in game.pickups:
            x, y = int(pickup.x), int(pickup.y)
            color = SKILL_COLORS[pickup.kind]
            pygame.draw.circle(s, tuple(int(v*.18) for v in color), (x, y), 16)
            pygame.draw.circle(s, color, (x, y), 16, 2)
            label = {"shield": "盾", "super": "超", "clones": "影", "rapid": "速",
                     "health": "+", "power": "P", "bomb": "B"}[pickup.kind]
            self.text(label, x-7, y-12, 16, color, target=s)
            if pickup.kind == "health":
                if pickup.remaining <= 2 and int(game.elapsed*8) % 2:
                    pygame.draw.circle(s, GOLD, (x, y), 20, 2)
                self.text(f"+{HEALTH_RESTORE}HP {pickup.remaining:.1f}s", max(0, min(WIDTH-100, x-45)),
                          y+19, 11, TEAL, target=s)
        for b in game.bullets:
            x, y = int(b.x), int(b.y)
            if b.friendly:
                color = GOLD if b.supercharged else (145, 246, 255)
                glow = (94, 63, 25) if b.supercharged else (30, 81, 101)
                pygame.draw.line(s, glow, (x, y+11), (x, y-6), 10 if b.supercharged else 7)
                pygame.draw.line(s, color, (x, y+6), (x, y-6), 5 if b.supercharged else 3)
            else:
                pygame.draw.circle(s, (83, 34, 50), (x, y), 7)
                pygame.draw.circle(s, RED, (x, y), 4)
                pygame.draw.circle(s, (255, 224, 190), (x, y), 2)
        for enemy in game.enemies:
            x, y, r = int(enemy.x), int(enemy.y), enemy.radius
            color = (RED, GOLD, (202, 149, 255))[enemy.kind]
            points = [(x, y+r), (x-r//3, y+4), (x-r, y+9), (x-r+3, y-r//2),
                      (x-5, y-r//3), (x, y-r), (x+5, y-r//3), (x+r-3, y-r//2),
                      (x+r, y+9), (x+r//3, y+4)]
            pygame.draw.polygon(s, tuple(int(v*.22) for v in color), points)
            pygame.draw.polygon(s, color, points, 2)
            pygame.draw.line(s, color, (x, y-r//2), (x, y+r//2), 3)
            if enemy.kind:
                total = (2, 6, 18)[enemy.kind]
                pygame.draw.rect(s, (41, 47, 62), (x-r, y-r-9, r*2, 3))
                pygame.draw.rect(s, color, (x-r, y-r-9, int(r*2*enemy.hp/total), 3))
        for p in game.particles:
            color = tuple(int(v*min(1, p.life*3)) for v in p.color)
            pygame.draw.circle(s, color, (int(p.x), int(p.y)), max(1, int(p.life*5)))
        if not game.over:
            for clone_x, clone_y in game.clone_positions:
                ghost = pygame.Surface((64, 76), pygame.SRCALPHA)
                points = [(32, 6), (24, 28), (9, 49), (10, 57), (27, 50),
                          (32, 55), (37, 50), (54, 57), (55, 49), (40, 28)]
                pygame.draw.polygon(ghost, (114, 76, 176, 85), points)
                pygame.draw.polygon(ghost, (202, 170, 255, 195), points, 2)
                pygame.draw.polygon(ghost, (163, 122, 255, 160), [(28, 53), (32, 70), (36, 53)])
                s.blit(ghost, (int(clone_x)-32, int(clone_y)-32))
        if not game.over and (game.invincible <= 0 or int(game.elapsed*12) % 2 == 0):
            x, y = int(game.x), int(game.y)
            flame = 15+int(5*math.sin(game.elapsed*40))
            pygame.draw.polygon(s, (30, 116, 160), [(x-7,y+15),(x,y+flame+18),(x+7,y+15)])
            pygame.draw.polygon(s, (135, 233, 255), [(x-3,y+16),(x,y+flame+9),(x+3,y+16)])
            points = [(x,y-26),(x-7,y-6),(x-22,y+13),(x-22,y+20),(x-6,y+14),
                      (x,y+19),(x+6,y+14),(x+22,y+20),(x+22,y+13),(x+7,y-6)]
            pygame.draw.polygon(s, (23, 75, 97), points)
            pygame.draw.polygon(s, (115, 229, 255), points, 2)
            pygame.draw.polygon(s, (217, 252, 255), [(x,y-15),(x-3,y+1),(x+3,y+1)])
            if game.invincible > 0:
                pygame.draw.circle(s, (66, 125, 148), (x, y), 34, 1)
        if not game.over and game.effects["shield"] > 0:
            x, y = int(game.x), int(game.y)
            pygame.draw.circle(s, (39, 82, 115), (x, y), 40, 5)
            pygame.draw.circle(s, BLUE, (x, y), 42, 2)
        if game.bomb_flash > 0:
            flash = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            flash.fill((99, 219, 255, int(game.bomb_flash*160)))
            s.blit(flash, (0, 0))
        return s

    def render(self, app, fps):
        s = self.canvas
        s.fill(BG)
        state = app.worker.snapshot()
        if state.tick != self.last_tick:
            self.rates.append((state.left_hz, state.right_hz, state.forward_hz))
            self.last_tick = state.tick
        self.text("FLYBRAIN  /  ARCADE", 26, 18, 13, TEAL, True)
        self.text("果蝇 · 飞行实验室", 24, 38, 29)
        self.text("01  经典飞机大战     /     02  连接组实时控制", 345, 53, 14, MUTED)
        mode_color = TEAL if app.neural else BLUE
        mode_label = "果蝇接管" if app.neural else "人工驾驶"
        self.pill("SPACE  /  " + mode_label, (1110, 32, 266, 40), mode_color)
        self.pill("P  /  " + ("继续" if app.paused else "暂停"), PAUSE_RECT, GOLD if app.started else MUTED)
        pygame.draw.line(s, LINE, (24, 88), (1376, 88))
        game = app.game
        resolved = max(0, game.stage_spawned-len(game.enemies))
        self.card((24, 104, 504, 740), "01", f"飞行区域 · 第 {game.level} 关", f"{resolved:02d} / {game.stage_quota:02d}")
        s.blit(self.field, (36, 152))
        # HUD is outside the image delivered to the neural model.
        hud = pygame.Surface((480, 79), pygame.SRCALPHA)
        hud.fill((9, 20, 34, 235))
        s.blit(hud, (36, 152))
        self.text(f"{game.score:07d}", 50, 159, 23, TEXT, True)
        self.text("SCORE", 50, 186, 9, MUTED, True)
        # Fixed-width bar: each of the ten segments represents ten percent HP.
        for i in range(10):
            rect = pygame.Rect(253+i*9, 167, 6, 12)
            pygame.draw.rect(s, LINE, rect, border_radius=2)
            fraction = min(1, max(0, game.hp/MAX_HP*10-i))
            if fraction > 0:
                pygame.draw.rect(s, TEAL, (rect.x, rect.y, max(1, round(rect.w*fraction)), rect.h), border_radius=2)
        self.text(f"HP {game.hp:03d}/{MAX_HP}", 253, 184, 10, TEAL, True)
        self.text(f"BOMB {game.bombs}   火力 {game.weapon}", 367, 169, 12, GOLD)
        buffs = [(kind, left) for kind, left in game.effects.items() if left > 0]
        if buffs:
            for i, (kind, left) in enumerate(buffs):
                self.text(f"{PICKUP_NAMES[kind]} {left:.0f}s", 50+i*111, 207, 12, SKILL_COLORS[kind])
        elif game.stage_break > 0:
            self.text(f"本关通过 · 休整 {game.stage_break:.1f}s", 50, 207, 12, GOLD)
        else:
            self.text(f"血包投放 {game.health_cooldown:.0f}s · 拾取 +{HEALTH_RESTORE} HP / {HEALTH_LIFETIME:g}s 到期", 50, 207, 12, MUTED)

        if not app.started or app.paused or game.over:
            shade = pygame.Surface((480, 680), pygame.SRCALPHA)
            shade.fill((5, 11, 22, 208))
            s.blit(shade, (36, 152))
            if game.over:
                title, subtitle, button = "飞行结束", f"本次得分  {game.score:,}    /    击落  {game.kills}", "R  /  再次起飞"
            elif app.paused:
                title, subtitle, button = "飞行暂停", "游戏与神经仿真均已暂停", "P  /  继续飞行"
            else:
                title, subtitle, button = "准备好起飞了吗", "人类与果蝇，共用一架战机。", "ENTER  /  开始飞行"
            self.text("FLIGHT / 01", 79, 363, 14, TEAL, True)
            self.text(title, 76, 397, 34)
            self.text(subtitle, 79, 457, 16, MUTED)
            self.pill(button, (79, 505, 390, 48))
            self.text("空格随时切换人工与果蝇控制", 79, 579, 15, MUTED)
            self.text("WASD / 方向键移动 · J 射击 · K 炸弹", 79, 610, 13, MUTED)

        self.card((548, 104, 340, 240), "02", "神经活动 · 3D", "LIVE" if app.brain_live else "FROZEN")
        self.brain_map(state, app.brain_live)
        caption = "实测胞体位置 · 抽样显示" if self.model.real else "演示网络 · 示意位置"
        self.text("拖动旋转 · 滚轮缩放 · 右键复位", 566, 303, 12, MUTED)
        self.text(caption + " · 奖惩为人工刺激映射", 566, 325, 10, MUTED)

        self.card((904, 104, 472, 240), "03", "脑模型运行状态", "LIF / FIXED")
        self.text("数据来源", 922, 162, 12, MUTED)
        self.text(self.model.label, 1046, 158, 18, TEAL if self.model.real else GOLD, True)
        self.metric("神经元", f"{self.model.n:,}", 922, 190)
        self.metric("加权连接", f"{self.model.edges:,}", 1148, 190)
        self.metric("当前放电", f"{state.active:,}", 922, 239)
        self.metric("累计脉冲", f"{state.total_spikes:,}", 1148, 239)
        self.text(f"奖励 {state.reward:.2f}s / {state.reward_events}次", 922, 291, 11,
                  TEAL if state.reward > 0 else MUTED)
        self.text(f"惩罚 {state.punishment:.2f}s / {state.punishment_events}次", 1148, 291, 11,
                  RED if state.punishment > 0 else MUTED)
        status = app.brain_status
        self.text(status, 922, 314, 12, mode_color if app.brain_live else MUTED, width=434)

        self.card((548, 360, 250, 218), "04", "视觉输入", "48 x 64")
        image = pygame.surfarray.make_surface(np.transpose(app.sensor, (1, 0, 2)))
        image = pygame.transform.scale(image, (94, 125))
        s.blit(image, (567, 418))
        pygame.draw.rect(s, LINE, (567, 418, 94, 125), 1)
        self.text("亮度", 677, 422, 12, MUTED)
        self.text(f"{state.luminance:.3f}", 677, 444, 18, TEXT, True)
        self.text("时间对比度", 677, 481, 11, MUTED)
        self.text(f"{state.contrast:.3f}", 677, 503, 18, GOLD, True)
        self.text("近似网格投射 · 非实测视轴", 566, 552, 11, MUTED)

        self.card((814, 360, 562, 218), "05", "神经建议与实际动作", "AUTHORED MAP")
        self.bar("左侧群", state.left_hz/40, 834, 421, BLUE, f"{state.left_hz:4.1f} Hz")
        self.bar("右侧群", state.right_hz/40, 834, 457, TEAL, f"{state.right_hz:4.1f} Hz")
        self.bar("前进群", state.forward_hz/40, 834, 493, GOLD, f"{state.forward_hz:4.1f} Hz")
        action = app.applied
        self.text(f"脑建议 X {state.action.x:+.2f}  Y {state.action.y:+.2f}", 834, 526, 11, MUTED)
        self.text(f"实际 X {action.x:+.2f}  Y {action.y:+.2f}", 834, 548, 12, TEXT)
        for key, active, x in (("FIRE", action.fire, 1110), ("BOMB", action.bomb, 1234)):
            self.pill(key, (x, 536, 102, 29), TEAL if active else MUTED)

        self.card((548, 594, 440, 250), "06", "群体放电时间线", "0 - 40 Hz")
        self.chart((566, 655, 404, 115))
        for label, color, x in (("LEFT", BLUE, 566), ("RIGHT", TEAL, 681), ("FORWARD", GOLD, 799)):
            pygame.draw.circle(s, color, (x+4, 791), 3)
            self.text(label, x+16, 783, 11, MUTED, True)
        self.text(f"{state.latency_ms:5.1f} ms / tick     RTF {state.realtime_factor:.2f}x", 566, 816, 12, MUTED, True)

        self.card((1004, 594, 372, 250), "07", "事件与控制记录", "LIVE LOG")
        for i, (stamp, label, color) in enumerate(list(app.events)[-6:]):
            self.text(f"{stamp:6.1f}s", 1021, 652+i*29, 11, MUTED, True)
            self.text(label, 1091, 647+i*29, 13, color, width=267)

        self.text("WASD / ↑↓←→  移动    J  射击    K  炸弹", 25, 862, 12, MUTED)
        self.text("SPACE  切换控制    P  暂停    R  重开    ESC  退出", 548, 862, 12, MUTED)
        self.text(f"{fps:02.0f} FPS", 1305, 862, 12, TEAL, True)
        # Explicit provenance is always visible, including when real data is absent.
        if not self.model.real:
            self.text("离线演示网络 · 不是真实果蝇连接组", 25, 881, 10, GOLD)
        else:
            self.text("MaleCNS v1.0 / CC BY 4.0 · 学习关闭 · 工程近似动力学", 25, 881, 10, MUTED)
        return s

    def metric(self, label, value, x, y):
        self.text(label, x, y, 12, MUTED)
        self.text(value, x, y+21, 23, TEXT, True)

    def bar(self, label, value, x, y, color, number):
        self.text(label, x, y-5, 13, MUTED)
        pygame.draw.rect(self.canvas, (29, 43, 58), (x+74, y+2, 315, 8), border_radius=4)
        if value > 0:
            pygame.draw.rect(self.canvas, color, (x+74, y+2, max(3, int(315*min(1, value))), 8), border_radius=4)
        self.text(number, x+408, y-5, 13, color, True)

    def brain_map(self, state, live):
        positions = self.model.draw_positions
        if not len(positions):
            self.text("无可用位置数据", 585, 220, 14, MUTED)
            return
        points, depth = self.camera.project(positions)
        points = points.astype(int)
        self.canvas.set_clip(BRAIN_RECT)
        for gx in range(572, 870, 24):
            pygame.draw.line(self.canvas, (22, 35, 48), (gx, 160), (gx, 298))
        for gy in range(164, 299, 24):
            pygame.draw.line(self.canvas, (22, 35, 48), (565, gy), (870, gy))
        activity = state.activity if len(state.activity) == len(points) else np.zeros(len(points))
        visible_activity = activity if live else activity*.32
        shades = np.clip(.88-depth*.14, .45, 1)
        colors = ((np.array([38, 79, 91]) + visible_activity[:, None]*np.array([180, 150, 102])) * shades[:, None]).astype(np.uint8)
        # Draw back to front. Near points are brighter/larger, preserving depth
        # independently from their actual firing activity.
        for index in np.argsort(depth)[::-1]:
            px, py = points[index]
            v = visible_activity[index]
            color = tuple(int(c) for c in colors[index])
            radius = 2 if v > .65 and depth[index] < .6 else 1
            pygame.draw.circle(self.canvas, color, (int(px), int(py)), radius)
        axis = np.array([[0, 0, 0], [.5, 0, 0], [0, .5, 0], [0, 0, .5]])
        axes, _ = self.camera.project(axis, center=(838, 274), scale=37/self.camera.zoom)
        for i, (color, name) in enumerate(((RED, "X"), (TEAL, "Y"), (BLUE, "Z")), 1):
            pygame.draw.aaline(self.canvas, color, axes[0], axes[i])
            self.text(name, axes[i, 0]+2, axes[i, 1]-6, 9, color, True)
        self.canvas.set_clip(None)

    def chart(self, rect):
        x, y, width, height = rect
        for j in range(5):
            yy = y+j*height/4
            pygame.draw.line(self.canvas, LINE, (x, yy), (x+width, yy))
        for series, color in enumerate((BLUE, TEAL, GOLD)):
            points = [(x+i*width/159, y+height-min(40, rates[series])/40*height)
                      for i, rates in enumerate(self.rates)]
            if len(points) > 1:
                pygame.draw.aalines(self.canvas, color, False, points)

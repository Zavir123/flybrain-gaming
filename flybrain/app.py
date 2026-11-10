"""Window, control ownership and recording. Space owns the handoff boundary."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import json
from pathlib import Path
import signal
import time

import numpy as np
import pygame

from .brain import BrainWorker, NeuralModel
from .game import Action, Game
from .ui import BLUE, BRAIN_RECT, GOLD, MUTED, PAUSE_RECT, RED, SIZE, TEAL, Renderer


class Application:
    def __init__(self, model: NeuralModel, *, headless=False, autostart=False,
                 manual=False, seed=42, log_dir: Path | None = None):
        pygame.display.init()
        pygame.font.init()
        self.headless = headless
        self.seed = seed
        self.game = Game(seed)
        self.neural = not manual
        self.started = autostart
        self.paused = False
        self.running = True
        self.bomb_pending = False
        self.brain_dragging = False
        self.brain_drag_position = (0.0, 0.0)
        self.applied = Action()
        self.last_action_keys = ()
        self.sensor = np.zeros((64, 48, 3), np.uint8)
        self.worker = BrainWorker(model)
        self.renderer = Renderer(model)
        self.events = deque(maxlen=64)
        self.log = None
        self.last_log = 0.0
        self.last_sensor = 0.0
        self._brain_requested = False
        self._closed = False
        size = SIZE
        if not headless:
            desktop = pygame.display.get_desktop_sizes()[0]
            scale = min(1, (desktop[0]-96)/SIZE[0], (desktop[1]-160)/SIZE[1])
            size = (max(840, int(SIZE[0]*scale)), max(540, int(SIZE[1]*scale)))
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption("Flybrain Arcade | 果蝇 · 飞行实验室")
        pygame.key.set_repeat()
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".jsonl"
            self.log_path = log_dir / name
            self.log = self.log_path.open("w", encoding="utf-8")
            self.record(dict(type="session", seed=seed, brain_seed=model.seed,
                             model=model.manifest, dt=model.dt, tonic=model.tonic,
                             synaptic_gain=model.gain, learning=False))
            self.record(dict(type="stimulation_config", reward_pool="PAM" if model.real else "synthetic reward",
                             punishment_pool="PPL1" if model.real else "synthetic punishment",
                             reward_nodes=len(model.reward_nodes), punishment_nodes=len(model.punishment_nodes),
                             pulse_seconds=.5, current=.35, learning=False))
        self.announce("MaleCNS 数据已载入" if model.real else "离线演示网络（非真实连接组）", TEAL if model.real else GOLD)
        self.announce("空格切换控制权 · Enter 起飞", MUTED)
        self.sync_worker()

    @property
    def brain_live(self):
        state = self.worker.snapshot()
        return (self._brain_requested and not self.worker.error and
                state.epoch == self.worker.epoch and time.monotonic()-state.timestamp <= .3)

    @property
    def brain_status(self):
        if self.worker.error:
            return "脑线程错误：" + self.worker.error
        if not self.started:
            return "等待起飞 · Enter 开始 / 空格选择控制方"
        if self.game.over:
            return "本局结束 · 神经仿真已停止"
        if self.paused:
            return "暂停中 · 感觉输入与动作输出均暂停"
        if not self.neural:
            return "人工驾驶 · 脑持续感知 / 仅屏蔽操作"
        if not self.brain_live:
            return "等待新指令 · 过期输出不执行"
        return "实时连接 · 奖惩刺激开启 / 学习关闭"

    def record(self, value):
        if self.log:
            self.log.write(json.dumps(value, ensure_ascii=False) + "\n")

    def announce(self, label, color=TEAL, key=None):
        if key:
            label = f"{key} {label}"
        self.events.append((self.game.elapsed, label, color))
        self.record(dict(type="event", game_time=self.game.elapsed, message=label, key=key))

    def log_action(self, action):
        """Log actual action transitions, with canonical controls for either driver."""
        mapping = (("W", action.y < -.06, "前进"), ("S", action.y > .06, "后退"),
                   ("A", action.x < -.06, "左移"), ("D", action.x > .06, "右移"),
                   ("J", action.fire, "射击"))
        keys = tuple(key for key, active, _ in mapping if active)
        if keys == self.last_action_keys:
            return
        if keys:
            description = " / ".join(label for _, active, label in mapping if active)
            self.announce(description, TEAL if self.neural else BLUE, key="+".join(keys))
        elif self.last_action_keys:
            self.announce("松开", MUTED, key="+".join(self.last_action_keys))
        self.last_action_keys = keys

    def sync_worker(self):
        desired = self.started and not self.paused and not self.game.over and not self.worker.error
        self.worker.set_control(self.neural)
        if desired != self._brain_requested:
            self._brain_requested = desired
            self.worker.set_enabled(desired)

    def toggle_control(self):
        self.neural = not self.neural
        self.applied = Action()
        self.last_action_keys = ()
        self.bomb_pending = False
        self.sync_worker()
        self.announce("果蝇接管 · 等待新指令" if self.neural else "人工接管 · 脑仍在感知", TEAL if self.neural else BLUE, key="SPACE")

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN and not getattr(event, "repeat", False):
            if event.key == pygame.K_ESCAPE:
                self.announce("退出", MUTED, key="ESC")
                self.running = False
            elif event.key == pygame.K_SPACE:
                self.toggle_control()
            elif event.key == pygame.K_RETURN and not self.started:
                self.started = True
                self.announce("已起飞 / NEURAL" if self.neural else "已起飞 / HUMAN", key="ENTER")
            elif event.key in (pygame.K_p, pygame.K_PAUSE) and self.started and not self.game.over:
                self.paused = not self.paused
                self.applied = Action()
                self.last_action_keys = ()
                self.bomb_pending = False
                self.announce("暂停" if self.paused else "继续飞行", GOLD, key="P" if event.key == pygame.K_p else "PAUSE")
            elif event.key == pygame.K_r:
                # Preserve the immutable graph; game restart invalidates all old commands.
                self.worker.set_enabled(False)
                self.worker.reset_feedback()
                self._brain_requested = False
                self.seed += 1
                self.game = Game(self.seed)
                self.renderer.rates.clear()
                self.applied = Action()
                self.last_action_keys = ()
                self.bomb_pending = False
                self.brain_dragging = False
                self.started, self.paused = True, False
                self.announce("新一局 · 神经状态保留", GOLD, key="R")
            elif event.key == pygame.K_k and not self.neural and self.started and not self.paused and not self.game.over:
                self.bomb_pending = True
        elif event.type == pygame.WINDOWFOCUSLOST and self.started and not self.game.over:
            self.paused = True
            self.applied = Action()
            self.last_action_keys = ()
            self.bomb_pending = False
            self.brain_dragging = False
            self.announce("窗口失焦 · 已自动暂停", GOLD)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = self.logical_mouse(event.pos)
            if BRAIN_RECT.collidepoint(pos):
                if event.button == 1:
                    self.brain_dragging = True
                    self.brain_drag_position = pos
                elif event.button == 3:
                    self.renderer.camera.reset()
            elif event.button == 1 and PAUSE_RECT.collidepoint(pos):
                self.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
            elif event.button == 1 and pygame.Rect(1110, 32, 266, 40).collidepoint(pos):
                self.toggle_control()
            elif event.button == 1 and pygame.Rect(79, 505, 390, 48).collidepoint(pos):
                key = pygame.K_r if self.game.over else pygame.K_p if self.paused else pygame.K_RETURN
                self.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.brain_dragging = False
        elif event.type == pygame.MOUSEMOTION and self.brain_dragging:
            pos = self.logical_mouse(event.pos)
            self.renderer.camera.orbit(pos[0]-self.brain_drag_position[0], pos[1]-self.brain_drag_position[1])
            self.brain_drag_position = pos
        elif event.type == pygame.MOUSEWHEEL:
            pos = self.logical_mouse(getattr(event, "pos", pygame.mouse.get_pos()))
            if BRAIN_RECT.collidepoint(pos):
                self.renderer.camera.dolly(event.y)
        self.sync_worker()

    def logical_mouse(self, position):
        width, height = self.screen.get_size()
        scale = min(width/SIZE[0], height/SIZE[1])
        return ((position[0]-(width-SIZE[0]*scale)/2)/scale,
                (position[1]-(height-SIZE[1]*scale)/2)/scale)

    def human_action(self, keys):
        mouse_fire = (not self.brain_dragging and pygame.Rect(36, 152, 480, 680).collidepoint(
            self.logical_mouse(pygame.mouse.get_pos())) and pygame.mouse.get_pressed()[0])
        action = Action(float(bool(keys[pygame.K_d] or keys[pygame.K_RIGHT]))-float(bool(keys[pygame.K_a] or keys[pygame.K_LEFT])),
                        float(bool(keys[pygame.K_s] or keys[pygame.K_DOWN]))-float(bool(keys[pygame.K_w] or keys[pygame.K_UP])),
                        bool(keys[pygame.K_j] or mouse_fire), self.bomb_pending)
        self.bomb_pending = False
        return action

    def step(self, dt):
        reward = punishment = 0
        if self.worker.error and self.neural:
            self.neural = False
            self.applied = Action()
            self.announce("脑线程异常 · 已交回人工", RED)
        active = self.started and not self.paused and not self.game.over
        if active:
            self.applied = self.worker.action() if self.neural else self.human_action(pygame.key.get_pressed())
            self.game.update(dt, self.applied)
            self.log_action(self.applied)
            for kind, label in self.game.events:
                reward += kind == "kill"
                punishment += kind == "damage"
                color = RED if kind in ("damage", "over") else GOLD if kind == "bomb" else TEAL
                label = {"damage": "受击 · 惩罚刺激 " + label, "kill": "击落 · 奖励刺激 " + label,
                         "bomb": "释放炸弹 " + label, "pickup": "获得补给 " + label,
                         "over": "飞行结束 " + label, "stage": label}.get(kind, label)
                self.announce(label, color, key="K" if kind == "bomb" else None)
        else:
            self.applied = Action()
        self.sync_worker()
        field = self.renderer.draw_field(self.game)
        # Main-thread pixel capture. Neither model nor worker touches Pygame.
        now = time.monotonic()
        if reward or punishment or (now-self.last_sensor >= .025 and (self._brain_requested or not self.started)):
            small = pygame.transform.smoothscale(field, (48, 64))
            self.sensor = np.transpose(pygame.surfarray.array3d(small), (1, 0, 2)).copy()
            self.worker.submit(self.sensor)
            if reward or punishment:
                self.worker.feedback(self.sensor, reward=reward, punishment=punishment)
                self.record(dict(type="stimulation", game_time=self.game.elapsed,
                                 reward=reward, punishment=punishment,
                                 controller="brain" if self.neural else "human"))
            self.last_sensor = now
        if now-self.last_log >= .1 and self.started:
            state = self.worker.snapshot()
            self.record(dict(type="tick", game_time=round(self.game.elapsed, 4),
                             controller="brain" if self.neural else "human", paused=self.paused,
                             connected=self.brain_live, tick=state.tick, active=state.active,
                             brain_controls=self.neural and self.brain_live,
                             brain_suggestion=dict(x=state.action.x, y=state.action.y, fire=state.action.fire, bomb=state.action.bomb),
                             mean_hz=state.mean_hz, latency_ms=state.latency_ms,
                             stimulation=dict(reward=state.reward, punishment=state.punishment,
                                              reward_events=state.reward_events,
                                              punishment_events=state.punishment_events),
                             action=dict(x=self.applied.x, y=self.applied.y, fire=self.applied.fire, bomb=self.applied.bomb),
                             game=dict(score=self.game.score, hp=self.game.hp, kills=self.game.kills,
                                       stage=self.game.stage, effects=self.game.effects.copy())))
            self.last_log = now

    def draw(self, fps):
        canvas = self.renderer.render(self, fps)
        width, height = self.screen.get_size()
        scale = min(width/SIZE[0], height/SIZE[1])
        target = (max(1, int(SIZE[0]*scale)), max(1, int(SIZE[1]*scale)))
        self.screen.fill((5, 10, 18))
        image = canvas if target == SIZE else pygame.transform.smoothscale(canvas, target)
        self.screen.blit(image, ((width-target[0])//2, (height-target[1])//2))
        pygame.display.flip()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.worker.close()
        if self.log:
            self.record(dict(type="end", score=self.game.score, elapsed=self.game.elapsed))
            self.log.close()
        pygame.quit()


def run(args, cache):
    model = NeuralModel(cache, kind=args.brain, seed=args.brain_seed)
    app = Application(model, headless=args.headless, autostart=args.start,
                      manual=args.manual, seed=args.seed,
                      log_dir=None if args.no_log else Path(args.log_dir))
    clock = pygame.time.Clock()
    count = 0
    previous_signals = {}
    for name in (signal.SIGINT, signal.SIGTERM):
        previous_signals[name] = signal.signal(name, lambda *_: setattr(app, "running", False))
    try:
        while app.running and (not args.frames or count < args.frames):
            dt = min(clock.tick(60)/1000, .05)
            for event in pygame.event.get():
                app.handle_event(event)
            app.step(1/60 if args.headless else dt)
            app.draw(clock.get_fps())
            count += 1
        if args.screenshot:
            path = Path(args.screenshot)
            path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(app.renderer.canvas, str(path))
        summary = dict(model=model.label, neurons=model.n, edges=model.edges,
                       frames=count, score=app.game.score, neural_ticks=app.worker.snapshot().tick,
                       worker_error=app.worker.error, controller="brain" if app.neural else "human")
        print(json.dumps(summary, ensure_ascii=False))
        if app.worker.error:
            raise RuntimeError(app.worker.error)
    finally:
        for name, handler in previous_signals.items():
            signal.signal(name, handler)
        app.close()

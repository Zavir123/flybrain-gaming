import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from collections import defaultdict
from pathlib import Path

import pygame
import time

from flybrain.app import Application
from flybrain.brain import NeuralModel
from flybrain.game import Action


def press(app, key):
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))


def test_space_pause_restart_and_human_play():
    app = Application(NeuralModel(Path("unused"), kind="demo"), headless=True)
    try:
        press(app, pygame.K_RETURN)
        assert app.worker.enabled
        press(app, pygame.K_SPACE)
        assert not app.neural and app.worker.enabled and not app.worker.control_enabled and app.applied == Action()
        keys = defaultdict(bool, {pygame.K_d: True, pygame.K_j: True})
        x = app.game.x
        app.game.update(.02, app.human_action(keys))
        assert app.game.x > x and any(b.friendly for b in app.game.bullets)
        press(app, pygame.K_SPACE)
        assert app.neural and app.worker.enabled and app.worker.control_enabled
        assert app.worker.action() == Action()
        press(app, pygame.K_p)
        assert app.paused and not app.worker.enabled
        elapsed = app.game.elapsed
        app.step(.02)
        assert app.game.elapsed == elapsed
        press(app, pygame.K_SPACE)
        press(app, pygame.K_p)
        assert not app.paused and not app.neural and app.worker.enabled
        app.game.hp = 1
        press(app, pygame.K_r)
        assert app.game.hp == 100 and app.started and not app.paused
        app.draw(60)
    finally:
        app.close()


def test_focus_loss_pauses_and_releases_neural_control():
    app = Application(NeuralModel(Path("unused"), kind="demo"), headless=True, autostart=True)
    try:
        app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        assert app.paused and not app.worker.enabled and app.applied == Action()
    finally:
        app.close()


def test_action_log_has_key_prefixes_and_does_not_repeat_held_inputs():
    app = Application(NeuralModel(Path("unused"), kind="demo"), headless=True,
                      autostart=True, manual=True)
    try:
        assert app.game.hp == 100
        app.log_action(Action(y=-1))
        assert app.events[-1][1] == "W 前进"
        count = len(app.events)
        app.log_action(Action(y=-1))
        assert len(app.events) == count
        app.log_action(Action(x=1, y=-1, fire=True))
        assert app.events[-1][1] == "W+D+J 前进 / 右移 / 射击"
        app.log_action(Action())
        assert app.events[-1][1] == "W+D+J 松开"
        press(app, pygame.K_p)
        assert app.events[-1][1] == "P 暂停"
        press(app, pygame.K_SPACE)
        assert app.events[-1][1].startswith("SPACE 果蝇接管")
        press(app, pygame.K_r)
        assert app.events[-1][1].startswith("R 新一局")
    finally:
        app.close()


def test_human_driving_keeps_brain_observing_but_does_not_execute_its_actions():
    app = Application(NeuralModel(Path("unused"), kind="demo"), headless=True,
                      autostart=True, manual=True)
    try:
        before = (app.game.x, app.game.y)
        for _ in range(25):
            app.step(.01)
            time.sleep(.012)
        assert app.worker.snapshot().tick > 3 and app.brain_live
        assert not app.worker.control_enabled and app.worker.action() == Action()
        assert before == (app.game.x, app.game.y)
        tick = app.worker.snapshot().tick
        press(app, pygame.K_SPACE)
        assert app.worker.action() == Action()  # No pre-handoff suggestion can actuate.
        deadline = time.monotonic()+1
        while app.worker.snapshot().tick <= tick+1 and time.monotonic() < deadline:
            app.step(.01)
            time.sleep(.01)
        assert app.worker.snapshot().tick > tick+1
        assert app.worker.snapshot().control_epoch == app.worker.control_epoch
    finally:
        app.close()


def test_mouse_orbits_3d_without_firing_and_pause_button_works(monkeypatch):
    app = Application(NeuralModel(Path("unused"), kind="demo"), headless=True,
                      autostart=True, manual=True)
    try:
        camera = app.renderer.camera
        yaw, pitch = camera.yaw, camera.pitch
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(650, 220)))
        app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(700, 250)))
        assert (camera.yaw, camera.pitch) != (yaw, pitch)
        monkeypatch.setattr(pygame.mouse, "get_pressed", lambda: (True, False, False))
        monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (700, 250))
        assert not app.human_action(defaultdict(bool)).fire
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(700, 250)))
        app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=2, pos=(700, 250)))
        assert camera.zoom > 1
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(700, 250)))
        assert camera.zoom == 1 and camera.yaw == yaw
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(970, 50)))
        assert app.paused and not app.worker.enabled
        press(app, pygame.K_PAUSE)
        assert not app.paused and app.worker.enabled
        press(app, pygame.K_k)
        assert app.bomb_pending
        press(app, pygame.K_p)
        assert not app.bomb_pending
        app.draw(60)
    finally:
        app.close()


def test_game_events_stimulate_brain_in_manual_mode_and_on_lethal_hit():
    from flybrain.game import Bullet, Enemy, MAX_HP
    app = Application(NeuralModel(Path("unused"), kind="demo"), headless=True,
                      autostart=True, manual=True)
    def wait_for(predicate):
        deadline = time.monotonic()+2
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.01)
        assert predicate()
    try:
        app.game.enemies = [Enemy(100, 200, 0, 1)]
        app.game.bullets = [Bullet(100, 200, 0, 0, True)]
        app.step(.001)
        wait_for(lambda: app.worker.snapshot().reward_events == 1)
        app.game.invincible = 0
        app.game.bullets = [Bullet(app.game.x, app.game.y, 0, 0, False) for _ in range(4)]
        app.step(.001)
        assert app.game.hp == MAX_HP-1
        wait_for(lambda: app.worker.snapshot().punishment_events == 1)
        app.game.bullets = [Bullet(app.game.x, app.game.y, 0, 0, False)]
        app.step(.001)
        time.sleep(.05)
        assert app.worker.snapshot().punishment_events == 1  # Invincible hits do not punish.
        app.game.hp, app.game.invincible = 1, 0
        app.game.bullets = [Bullet(app.game.x, app.game.y, 0, 0, False)]
        app.step(.001)
        assert app.game.over and not app.worker.enabled
        wait_for(lambda: app.worker.snapshot().punishment_events == 2)
        assert app.worker.action() == Action()
        app.draw(60)
    finally:
        app.close()

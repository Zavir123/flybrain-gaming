"""Deterministic, display-independent vertical shooter simulation."""
from __future__ import annotations

from dataclasses import dataclass
import math
import random

WIDTH, HEIGHT = 480, 680
MAX_HP = 100
HEALTH_RESTORE = 10
HEALTH_LIFETIME = 15.0
HEALTH_INTERVAL = 18.0
BUFF_DURATIONS = {"shield": 8.0, "super": 10.0, "clones": 12.0, "rapid": 8.0}
PICKUP_NAMES = {"shield": "保护罩", "super": "超级子弹", "clones": "影分身",
                "rapid": "极速射击", "health": "血包", "power": "火力升级", "bomb": "炸弹补充"}


@dataclass(frozen=True)
class Action:
    x: float = 0.0
    y: float = 0.0
    fire: bool = False
    bomb: bool = False


@dataclass
class Bullet:
    x: float
    y: float
    vx: float
    vy: float
    friendly: bool
    damage: int = 1
    supercharged: bool = False


@dataclass
class Enemy:
    x: float
    y: float
    kind: int
    hp: int
    age: float = 0.0
    cooldown: float = 1.0
    phase: float = 0.0

    @property
    def radius(self):
        return (15, 22, 32)[self.kind]


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple[int, int, int]


@dataclass
class Pickup:
    x: float
    y: float
    kind: str
    remaining: float | None = None

    def __post_init__(self):
        if self.kind == "health" and self.remaining is None:
            self.remaining = HEALTH_LIFETIME


class Game:
    """All time-based mechanics advance only by update(dt, action)."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.x, self.y = WIDTH / 2, HEIGHT - 92.0
        self.hp = MAX_HP
        self.bombs = 3
        self.weapon = 1
        self.score = 0
        self.kills = 0
        self.elapsed = 0.0
        self.stage = 1
        self.stage_spawned = 0
        self.stage_break = 0.0
        self.total_spawned = 0
        self.drop_count = 0
        self.health_cooldown = HEALTH_INTERVAL
        self.effects = {kind: 0.0 for kind in BUFF_DURATIONS}
        self.over = False
        self.invincible = 2.0
        self.shot_cooldown = 0.0
        self.bomb_cooldown = 0.0
        self.spawn_cooldown = 1.8
        self.bomb_flash = 0.0
        self.bullets: list[Bullet] = []
        self.enemies: list[Enemy] = []
        self.particles: list[Particle] = []
        self.pickups: list[Pickup] = []
        self.events: list[tuple[str, str]] = []

    @property
    def level(self):
        return self.stage

    @property
    def stage_quota(self):
        return 6 + (self.stage-1)*2

    @property
    def enemy_limit(self):
        return min(8, 2 + (self.stage-1)//2)

    @property
    def spawn_interval(self):
        return max(.6, 2.8/(1+.16*(self.stage-1)))

    @property
    def drop_chance(self):
        # Compensate for larger waves too: expected drops *per stage* decline,
        # rather than increasing simply because later stages have more enemies.
        return .72 * .8**(self.stage-1) * 6/self.stage_quota

    @property
    def clone_positions(self):
        if self.effects["clones"] <= 0:
            return []
        return [(max(18, self.x-48), self.y+14), (min(WIDTH-18, self.x+48), self.y+14)]

    def collect(self, kind: str):
        if kind in BUFF_DURATIONS:
            self.effects[kind] = max(self.effects[kind], BUFF_DURATIONS[kind])
        elif kind == "power":
            self.weapon = min(3, self.weapon+1)
        elif kind == "health":
            restored = min(HEALTH_RESTORE, MAX_HP-self.hp)
            self.hp += restored
            self.events.append(("pickup", f"血包 +{restored} HP"))
            return
        elif kind == "bomb":
            self.bombs = min(5, self.bombs+1)
        self.events.append(("pickup", PICKUP_NAMES.get(kind, kind)))

    def fire(self):
        supercharged = self.effects["super"] > 0
        offsets = (-18, -9, 0, 9, 18) if supercharged else ((0,) if self.weapon == 1 else (-9, 9) if self.weapon == 2 else (-16, 0, 16))
        for dx in offsets:
            self.bullets.append(Bullet(self.x+dx, self.y-24, dx*2, -700 if supercharged else -620,
                                       True, 3 if supercharged else 1, supercharged))
        for x, y in self.clone_positions:
            self.bullets.append(Bullet(x, y-22, 0, -650, True, 2 if supercharged else 1, supercharged))

    def explode(self, x, y, color=(255, 175, 85), count=18):
        for _ in range(count):
            a = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(30, 170)
            self.particles.append(Particle(x, y, math.cos(a)*speed,
                                           math.sin(a)*speed, self.rng.uniform(.2, .7), color))

    def destroy(self, enemy: Enemy):
        self.score += (100, 300, 800)[enemy.kind]
        self.kills += 1
        self.explode(enemy.x, enemy.y, count=15 + enemy.kind * 10)
        if self.kills == 1 or self.rng.random() < self.drop_chance:
            # Introduce all three signature skills early, then mix the loot pool.
            if self.drop_count < 3:
                kind = ("shield", "super", "clones")[self.drop_count]
            else:
                kind = self.rng.choices(tuple(PICKUP_NAMES), (3, 3, 3, 2, 2, 1, 1))[0]
            self.pickups.append(Pickup(enemy.x, enemy.y, kind))
            self.drop_count += 1
        self.events.append(("kill", f"+{(100, 300, 800)[enemy.kind]}"))

    def damage(self):
        if self.effects["shield"] > 0:
            return
        if self.invincible > 0 or self.over:
            return
        self.hp -= 1
        self.invincible = 1.8
        self.explode(self.x, self.y, (103, 217, 255), 22)
        self.events.append(("damage", f"HP {self.hp}/{MAX_HP}"))
        if self.hp <= 0:
            self.over = True
            self.events.append(("over", f"SCORE {self.score}"))

    def update(self, dt: float, action: Action):
        self.events = []
        if self.over:
            return
        self.elapsed += dt
        self.stage_break = max(0, self.stage_break-dt)
        for kind in self.effects:
            self.effects[kind] = max(0, self.effects[kind]-dt)
        self.invincible = max(0, self.invincible - dt)
        self.bomb_flash = max(0, self.bomb_flash - dt)
        self.shot_cooldown -= dt
        self.bomb_cooldown -= dt
        length = max(1, math.hypot(action.x, action.y))
        self.x = min(WIDTH-22, max(22, self.x + action.x/length * 285 * dt))
        self.y = min(HEIGHT-30, max(48, self.y + action.y/length * 285 * dt))

        if action.fire and self.shot_cooldown <= 0:
            self.fire()
            self.shot_cooldown = .075 if self.effects["rapid"] > 0 else .14
        if action.bomb and self.bombs > 0 and self.bomb_cooldown <= 0:
            self.bombs -= 1
            self.bomb_cooldown = .8
            self.bomb_flash = .5
            self.bullets = [b for b in self.bullets if b.friendly]
            for enemy in self.enemies[:]:
                enemy.hp -= 12
                if enemy.hp <= 0:
                    self.destroy(enemy)
                    self.enemies.remove(enemy)
            self.events.append(("bomb", f"BOMBS {self.bombs}"))

        self.spawn_cooldown -= dt
        if (self.spawn_cooldown <= 0 and self.stage_break <= 0
                and self.stage_spawned < self.stage_quota and len(self.enemies) < self.enemy_limit):
            kind = self.rng.choices((0, 1, 2), (8, min(4, max(0, self.stage-2)*.7), min(2, max(0, self.stage-4)*.4)))[0]
            self.enemies.append(Enemy(self.rng.uniform(40, WIDTH-40), -40,
                                      kind, (2, 6, 18)[kind],
                                      cooldown=self.rng.uniform(1.8, 3.2),
                                      phase=self.rng.uniform(0, math.tau)))
            self.stage_spawned += 1
            self.total_spawned += 1
            self.spawn_cooldown = self.spawn_interval * self.rng.uniform(.85, 1.15)

        for enemy in self.enemies[:]:
            enemy.age += dt
            enemy.y += ((68, 48, 32)[enemy.kind] + min((self.level-1)*4, 55)) * dt
            enemy.x += math.sin(enemy.age*2 + enemy.phase) * (22 if enemy.kind else 40) * dt
            enemy.x = min(WIDTH-enemy.radius, max(enemy.radius, enemy.x))
            enemy.cooldown -= dt
            if enemy.cooldown <= 0 and enemy.y > 25:
                speed = min(230, 90 + (self.level-1)*8)
                a = math.atan2(self.y-enemy.y, self.x-enemy.x)
                spread = (-.23, 0, .23) if enemy.kind == 2 else (0,)
                for da in spread:
                    self.bullets.append(Bullet(enemy.x, enemy.y+enemy.radius,
                                               math.cos(a+da)*speed, math.sin(a+da)*speed, False))
                enemy.cooldown = max(.6, (3.5, 2.8, 2.1)[enemy.kind] / (1 + .055*(self.level-1)))
            if math.hypot(enemy.x-self.x, enemy.y-self.y) < enemy.radius+10:
                self.damage()
                enemy.hp = 0
                self.explode(enemy.x, enemy.y)
                self.enemies.remove(enemy)
            elif enemy.y > HEIGHT+50:
                self.enemies.remove(enemy)

        survivors = []
        for b in self.bullets:
            b.x += b.vx*dt
            b.y += b.vy*dt
            if not (-30 < b.x < WIDTH+30 and -40 < b.y < HEIGHT+40):
                continue
            hit = False
            if b.friendly:
                for enemy in self.enemies[:]:
                    if math.hypot(b.x-enemy.x, b.y-enemy.y) < enemy.radius+4:
                        enemy.hp -= b.damage
                        hit = True
                        if enemy.hp <= 0:
                            self.destroy(enemy)
                            self.enemies.remove(enemy)
                        break
            elif math.hypot(b.x-self.x, b.y-self.y) < 12:
                self.damage()
                hit = True
            if not hit:
                survivors.append(b)
        self.bullets = survivors

        self.health_cooldown -= dt
        if not self.over and self.health_cooldown <= 0:
            self.pickups.append(Pickup(self.rng.uniform(40, WIDTH-40), 90, "health"))
            self.health_cooldown += HEALTH_INTERVAL
            self.events.append(("supply", f"限时血包出现 · {HEALTH_LIFETIME:g} 秒内拾取 +{HEALTH_RESTORE} HP"))
        for pickup in self.pickups[:]:
            if pickup.remaining is not None:
                pickup.remaining = max(0, pickup.remaining-dt)
                if pickup.remaining <= 0:
                    self.pickups.remove(pickup)
                    continue
            if self.over:
                continue
            pickup.y += (55 if pickup.kind == "health" else 100)*dt
            distance = math.hypot(pickup.x-self.x, pickup.y-self.y)
            if 0 < distance < 125:
                pickup.x += (self.x-pickup.x)/distance*200*dt
                pickup.y += (self.y-pickup.y)/distance*200*dt
            if math.hypot(pickup.x-self.x, pickup.y-self.y) < 30:
                self.collect(pickup.kind)
                self.pickups.remove(pickup)
            elif pickup.y > HEIGHT+30:
                self.pickups.remove(pickup)
        for p in self.particles:
            p.x += p.vx*dt
            p.y += p.vy*dt
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0][-450:]
        if not self.over and self.stage_spawned >= self.stage_quota and not self.enemies:
            self.stage += 1
            self.stage_spawned = 0
            self.stage_break = self.spawn_cooldown = 3.5
            self.bullets = [b for b in self.bullets if b.friendly]
            self.events.append(("stage", f"进入第 {self.stage} 关 · 休整 3.5 秒"))

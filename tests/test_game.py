from flybrain.game import Action, BUFF_DURATIONS, Bullet, Enemy, Game, MAX_HP, Pickup


def test_manual_input_moves_and_fires_without_brain():
    game = Game()
    before = game.x
    game.update(.02, Action(x=1, fire=True))
    assert game.x > before
    assert any(b.friendly for b in game.bullets)
    for _ in range(300):
        game.update(.02, Action(x=1, y=1))
    assert 22 <= game.x <= 458 and 48 <= game.y <= 650


def test_hit_kill_and_invulnerability():
    game = Game()
    game.enemies = [Enemy(100, 200, 0, 1)]
    game.bullets = [Bullet(100, 200, 0, 0, True)]
    game.update(.001, Action())
    assert game.kills == 1 and game.score == 100 and not game.enemies
    game.invincible = 0
    game.bullets = [Bullet(game.x, game.y, 0, 0, False) for _ in range(4)]
    game.update(.001, Action())
    assert game.hp == MAX_HP-1  # Simultaneous hits consume one life, not four.


def test_bomb_destroys_enemies_and_clears_hostile_bullets():
    game = Game()
    game.enemies = [Enemy(100, 150, 1, 6)]
    game.bullets = [Bullet(30, 40, 0, 0, False)]
    game.update(.01, Action(bomb=True))
    assert game.bombs == 2 and game.kills == 1
    assert not any(not b.friendly for b in game.bullets)
    game.update(.01, Action(bomb=True))
    assert game.bombs == 2


def test_same_seed_and_inputs_reproduce_game_state():
    first, second = Game(5), Game(5)
    for _ in range(500):
        for game in (first, second):
            game.update(1/60, Action(fire=True))
    assert first.enemies == second.enemies
    assert first.bullets == second.bullets
    assert (first.score, first.hp) == (second.score, second.hp)


def test_game_over_stops_progression():
    game = Game()
    game.hp, game.invincible = 1, 0
    game.damage()
    elapsed = game.elapsed
    game.update(1, Action(x=1, fire=True))
    assert game.over and game.elapsed == elapsed


def test_first_stage_limits_enemies_and_progress_requires_a_cleared_wave():
    game = Game()
    game.invincible = 1000
    for _ in range(1800):
        game.update(1/60, Action())
        assert len(game.enemies) <= 2
    assert game.total_spawned <= 6 and game.level == 1
    game.elapsed = 900  # Wall time does not advance a stage by itself.
    game.update(.01, Action())
    assert game.level == 1
    game.enemies.clear()
    game.stage_spawned = game.stage_quota
    game.bullets = [Bullet(20, 20, 0, 0, False)]
    game.update(.01, Action())
    assert game.level == 2 and game.stage_break > 0
    assert not any(not b.friendly for b in game.bullets)


def test_difficulty_rises_while_expected_drops_per_wave_fall():
    game = Game()
    previous = None
    for stage in range(1, 21):
        game.stage = stage
        current = (game.spawn_interval, game.drop_chance*game.stage_quota, game.enemy_limit)
        if previous is not None:
            assert current[0] <= previous[0]
            assert current[1] < previous[1]
            assert current[2] >= previous[2]
        previous = current


def test_shield_super_bullets_clones_and_skill_expiration():
    game = Game()
    game.spawn_cooldown = 1000
    game.invincible = 0
    game.collect("shield")
    game.damage()
    assert game.hp == MAX_HP
    game.collect("super")
    game.collect("clones")
    game.collect("rapid")
    game.update(.01, Action(fire=True))
    assert len(game.clone_positions) == 2
    assert len(game.bullets) == 7 and all(b.damage >= 2 for b in game.bullets)
    assert all(b.supercharged for b in game.bullets)
    assert game.shot_cooldown < .1
    for _ in range(800):
        game.update(.02, Action())
    assert not any(game.effects.values()) and not game.clone_positions
    game.damage()
    assert game.hp == MAX_HP-1
    game.fire()
    assert len(game.bullets) == 1 and game.bullets[0].damage == 1


def test_collecting_health_caps_at_ten_and_early_drops_introduce_skills():
    game = Game()
    for _ in range(20):
        game.destroy(Enemy(100, 100, 0, 0))
    assert [p.kind for p in game.pickups[:3]] == ["shield", "super", "clones"]
    game.hp = MAX_HP-1
    game.pickups = [Pickup(game.x, game.y, "health")]
    game.update(.01, Action())
    assert game.hp == MAX_HP


def test_health_pack_heals_ten_caps_hp_and_expires_before_collection():
    from flybrain.game import HEALTH_RESTORE, HEALTH_LIFETIME
    game = Game()
    game.hp = 35
    game.pickups = [Pickup(game.x, game.y, "health")]
    game.update(.01, Action())
    assert HEALTH_RESTORE == 10 and game.hp == 45
    assert ("pickup", "血包 +10 HP") in game.events
    game.hp = MAX_HP-2
    game.collect("health")
    game.collect("health")
    assert game.hp == MAX_HP
    expired = Pickup(game.x, game.y, "health", remaining=.01)
    assert HEALTH_LIFETIME == 15.0
    assert Pickup(40, 40, "health").remaining == HEALTH_LIFETIME
    game.hp = 10
    game.pickups = [expired]
    game.update(.02, Action())
    assert not game.pickups and game.hp == 10


def test_health_supply_appears_without_kills_on_game_clock():
    from flybrain.game import HEALTH_INTERVAL, HEALTH_LIFETIME
    game = Game()
    game.x = 22  # Stay away from the seeded supply so auto-collection cannot hide expiry.
    game.spawn_cooldown = 1000
    for _ in range(int(HEALTH_INTERVAL*10)+1):
        game.update(.1, Action())
    packs = [p for p in game.pickups if p.kind == "health"]
    assert len(packs) == 1 and 0 < packs[0].remaining <= HEALTH_LIFETIME
    assert game.kills == 0
    for _ in range(81):
        game.update(.1, Action())
    assert packs[0] in game.pickups  # Still available after eight seconds.
    for _ in range(31):
        game.update(.1, Action())
    assert not game.pickups
    assert packs[0].y > 710 and packs[0].remaining > 0  # Leaves the screen before timeout.

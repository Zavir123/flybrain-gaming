from __future__ import annotations

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="果蝇 · 飞行实验室 / Python 飞机大战")
    parser.add_argument("command", nargs="?", choices=["play", "prepare", "validate"], default="play")
    parser.add_argument("--brain-data", "--cache", dest="cache", type=Path, default=Path("brain_data"), help="MaleCNS 脑数据目录（默认 brain_data/；--cache 为兼容别名）")
    parser.add_argument("--brain", choices=["auto", "malecns", "demo"], default="auto", help="auto 优先真实缓存；demo 为明确标注的合成网络")
    parser.add_argument("--manual", action="store_true", help="以人工驾驶开始")
    parser.add_argument("--start", action="store_true", help="跳过起飞画面")
    parser.add_argument("--seed", type=int, default=42, help="游戏随机种子")
    parser.add_argument("--brain-seed", type=int, default=64, help="背景神经噪声种子")
    parser.add_argument("--log-dir", default="runs", help="JSONL 运行记录目录")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--headless", action="store_true", help="无窗口渲染验证")
    parser.add_argument("--frames", type=int, default=0, help="在指定帧数后退出；0 为不限")
    parser.add_argument("--screenshot", help="退出时保存逻辑画面 PNG")
    args = parser.parse_args()
    if args.frames < 0:
        parser.error("--frames 必须大于等于 0")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if args.command == "prepare":
        from .data import prepare
        prepare(args.cache)
    else:
        if args.headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ["SDL_AUDIODRIVER"] = "dummy"
        # Bound BLAS threads before importing NumPy/SciPy; the sparse worker
        # should leave cores available for the game and the operating system.
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        try:
            if args.command == "validate":
                from .validate import validate
                validate(args.cache, "malecns" if args.brain == "auto" else args.brain)
            else:
                from .app import run
                run(args, args.cache)
        except (FileNotFoundError, ValueError) as exc:
            parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()

"""Download official MaleCNS tables and build a versioned, local sparse cache.

Only measured connectivity is imported. Signs, normalization and the grid
projection are explicit modeling assumptions, not recovered physiology.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import urllib.request

import numpy as np
import pyarrow.feather as feather
from scipy import sparse

SCHEMA = 1
BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome"
SOURCES = {
    "annotations.feather": f"{BASE}/body-annotations-male-cns-v1.0-minconf-0.5.feather",
    "transmitters.feather": f"{BASE}/body-neurotransmitters-male-cns-v1.0.feather",
    "weights.feather": f"{BASE}/connectome-weights-male-cns-v1.0-minconf-0.5.feather",
}


def download(url: str, path: Path):
    """Resume interrupted public downloads; publish only complete files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as response:
        expected = int(response.headers["Content-Length"])
    if path.exists() and path.stat().st_size == expected:
        print(f"已存在 {path.name} ({expected/1e6:.1f} MB)", flush=True)
        return
    partial = path.with_suffix(".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset >= expected:
        partial.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
        if offset and response.status != 206:
            offset = 0
        received = offset
        last = 0.0
        with partial.open("ab" if offset else "wb") as output:
            while chunk := response.read(2**20):
                output.write(chunk)
                received += len(chunk)
                if time.monotonic()-last > 2:
                    print(f"下载 {path.name}: {received/expected:6.1%} ({received/1e6:.0f}/{expected/1e6:.0f} MB)", flush=True)
                    last = time.monotonic()
    if received != expected:
        raise IOError(f"Incomplete download: {path.name}, {received}/{expected}")
    partial.replace(path)


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(2**20):
            h.update(block)
    return h.hexdigest()


def normalized_weights(pre, post, count, sign, n):
    """W[post, pre]; normalize by the absolute sum of each *incoming row*."""
    matrix = sparse.csr_matrix((np.asarray(count, np.float32) * sign[pre],
                                (post, pre)), shape=(n, n), dtype=np.float32)
    matrix.sum_duplicates()
    incoming = np.asarray(abs(matrix).sum(axis=1)).ravel()
    # Index row scales by CSR row lengths; never confuse outgoing column sums.
    matrix.data *= np.repeat(1 / np.maximum(incoming, 1), np.diff(matrix.indptr))
    return matrix


def prepare(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text("utf-8"))
        if old.get("schema") == SCHEMA and all((cache / name).exists() for name in ("weights.npz", "nodes.npz")):
            print(f"缓存已准备好：{old['neurons']:,} 个神经元 / {old['edges']:,} 条连接。", flush=True)
            return
    for name, url in SOURCES.items():
        download(url, cache / "raw" / name)

    print("读取注释与递质表…", flush=True)
    table = feather.read_table(cache / "raw/annotations.feather").to_pydict()
    retained = [i for i, value in enumerate(table["superclass"]) if value]
    retained.sort(key=lambda i: table["bodyId"][i])
    ids = np.array([table["bodyId"][i] for i in retained], dtype=np.int64)
    if len(ids) != 166700:
        raise ValueError(f"Unexpected MaleCNS v1.0 neuron selection: {len(ids)}")
    types = np.array([table["flywireType"][i] or table["type"][i] or "" for i in retained])
    sides = np.array([table["somaSide"][i] or table["rootSide"][i] or
                      (table["instance"][i] or "").rsplit("_", 1)[-1] for i in retained])
    nt = feather.read_table(cache / "raw/transmitters.feather", columns=["body", "consensus_nt"]).to_pydict()
    transmitters = dict(zip(nt["body"], nt["consensus_nt"]))
    signs = np.array([-1 if (transmitters.get(int(i)) or "").lower() in
                      {"gaba", "glutamate", "histamine"} else 1 for i in ids], np.float32)
    print("分批读取连接表；仅保留两端均在所选神经元中的连接…", flush=True)
    edge_table = feather.read_table(cache / "raw/weights.feather", memory_map=True)
    pre_parts, post_parts, values_parts = [], [], []
    n = len(ids)
    processed = last_progress = 0
    for batch in edge_table.to_batches(max_chunksize=2_000_000):
        pre_ids = batch.column("body_pre").to_numpy()
        post_ids = batch.column("body_post").to_numpy()
        pre = np.searchsorted(ids, pre_ids)
        post = np.searchsorted(ids, post_ids)
        valid = (pre < n) & (post < n)
        valid &= (ids[np.minimum(pre, n-1)] == pre_ids) & (ids[np.minimum(post, n-1)] == post_ids)
        pre_parts.append(pre[valid].astype(np.int32))
        post_parts.append(post[valid].astype(np.int32))
        values_parts.append(batch.column("weight").to_numpy()[valid].astype(np.float32))
        processed += batch.num_rows
        if processed-last_progress >= 20_000_000 or processed == edge_table.num_rows:
            print(f"  已处理 {processed:,} / {edge_table.num_rows:,} 行", flush=True)
            last_progress = processed
    del edge_table
    pre, post, values = np.concatenate(pre_parts), np.concatenate(post_parts), np.concatenate(values_parts)
    del pre_parts, post_parts, values_parts
    matrix = normalized_weights(pre, post, values, signs, n)
    del pre, post, values

    visual = np.flatnonzero(np.isin(types, ["R1-6", "R7", "R8"]))
    left = np.flatnonzero(np.isin(types, ["DNa02", "DNg13"]) & (sides == "L"))
    right = np.flatnonzero(np.isin(types, ["DNa02", "DNg13"]) & (sides == "R"))
    forward = np.flatnonzero(types == "DNg100")
    escape = np.flatnonzero(np.isin(types, ["DNp01", "DNp10"]))
    if any(len(group) == 0 for group in (visual, left, right, forward, escape)):
        raise ValueError("Required sensory/motor cell annotations could not be resolved")

    # The optical axes are NOT known. A deterministic per-eye grid is an
    # engineered projection and is labeled as such in the app and manifest.
    pixels = np.zeros((len(visual), 2), np.int32)
    for side, x_start in (("L", 0), ("R", 24)):
        selected = np.flatnonzero(sides[visual] == side)
        rank = np.arange(len(selected))
        pixels[selected, 0] = rank % 24 + x_start
        pixels[selected, 1] = (rank // 24) % 64
    unknown = np.flatnonzero(~np.isin(sides[visual], ["L", "R"]))
    pixels[unknown] = np.column_stack((unknown % 48, (unknown // 48) % 64))

    positions = np.full((n, 3), np.nan, np.float32)
    for j, row in enumerate(retained):
        location = table["somaLocation"][row] or table["tosomaLocation"][row]
        if location is not None and len(location) == 3:
            positions[j] = location
    known = np.isfinite(positions).all(axis=1)
    low, high = np.nanpercentile(positions, [1, 99], axis=0)
    positions = (positions-(low+high)/2) / np.maximum((high-low)/2, 1)
    positions[:, 1] *= -1
    np.savez(cache / "nodes.npz", ids=ids, types=types, visual=visual, pixels=pixels,
             left=left, right=right, forward=forward, escape=escape,
             positions=positions, position_known=known)
    sparse.save_npz(cache / "weights.npz", matrix, compressed=False)
    manifest = dict(schema=SCHEMA, dataset="MaleCNS v1.0", neurons=n, edges=matrix.nnz,
                    sensory_cells=len(visual), measured_positions=int(known.sum()),
                    selection="nonempty superclass; includes tbc; no status filter",
                    normalization="W[post,pre], signed synapse count / incoming absolute row sum",
                    sign_assumption="GABA/glutamate/histamine negative; all other/unknown positive",
                    retina="approximate deterministic per-eye grid; not measured optical axes",
                    learning=False, license="CC BY 4.0", source="https://male-cns.janelia.org/download/",
                    files={name: dict(url=url, sha256=sha256(cache / 'raw' / name)) for name, url in SOURCES.items()})
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    print(f"准备完成：{n:,} 个神经元 / {matrix.nnz:,} 条加权连接 → {cache}", flush=True)

#!/usr/bin/env python3
"""构建 T0.3 自验语料：从 cloud/ 下的真实小说原文切出 ≥20MB 样例。

**不访问外网**：原文来自飞书云盘 projects/fix_text 目录，用
`lark-cli drive +download --file-token <token> --output ./cloud/<name>` 取回后放入 cloud/。

切取口径（可复现，无随机、无改写）：
1. `corpus_<key>.txt`：原文**逐字节复制**，不改写、不截断、不补足。
2. `corpus_20mb_slice.txt`：从体积最大的那部小说按**字节**切前 20 MiB，
   再把末尾回溯到最近的换行符之后，保证切点是完整行边界；
   记录实际切取字节数、起止偏移与 sha256。

所有统计值（字节 / 字符 / 行 / sha256）都是实测，写入 corpus/corpus_meta.json。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLOUD = PROJECT_ROOT / "cloud"
OUT = PROJECT_ROOT / "corpus"

# 云盘 projects/fix_text 中的三部真实小说：key -> (云盘文件名, file_token, 标题)
BOOKS: dict[str, tuple[str, str, str]] = {
    "guimie": (
        "鬼灭之刃：我的眼睛能看到弹幕 作者：陆要芝麻粒.txt",
        "TyKfbfpKaoXmGqxA8EicoOuKnDg",
        "鬼灭之刃：我的眼睛能看到弹幕",
    ),
    "quhun": (
        "雀魂：开局国士无双 作者：玄汐蓝.txt",
        "U97xbrR4bo7mo5xQgX4clWLDnmh",
        "雀魂：开局国士无双",
    ),
    "fanpai": (
        "反派少爷只想过佛系生活 作者：人之下.txt",
        "Hr23bsrK4o63OixCV2ucIbEFn94",
        "反派少爷只想过佛系生活",
    ),
}

SLICE_TARGET_BYTES = 20 * 1024 * 1024  # 20 MiB


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(path: Path) -> dict:
    """流式统计：字节 / 字符 / 行 / 乱码字符 / 章节行数。"""
    nbytes = nchars = nlines = nchap = nfffd = 0
    last = b""
    with open(path, "rb") as f:
        for raw in f:
            nbytes += len(raw)
            s = raw.decode("utf-8", errors="replace")
            nchars += len(s)
            nfffd += s.count("\ufffd")
            if s.endswith("\n"):
                nlines += 1
            head = s.lstrip()
            if head.startswith("第") and "章" in head[:20]:
                nchap += 1
            last = raw[-1:]
    if nbytes and last != b"\n":
        nlines += 1
    return {
        "bytes": nbytes,
        "chars": nchars,
        "lines": nlines,
        "chapters": nchap,
        "replacement_chars": nfffd,
    }


def slice_20mb(src: Path, dst: Path) -> dict:
    """按字节取 ≥20 MiB，末端**向前**延伸到最近换行符之后（完整行边界）。

    先读满 20 MiB，再从该位置往后读到下一个换行（含），因此实际切取必然 ≥ 20 MiB，
    既满足「≥20MB」要求，切点又落在完整行边界上。
    """
    block = 1 << 16
    cut = SLICE_TARGET_BYTES
    guard = 0
    with open(src, "rb") as f:
        f.read(SLICE_TARGET_BYTES)
        while True:
            extra = f.read(block)
            if not extra:
                break
            idx = extra.find(b"\n")
            if idx >= 0:
                cut += idx + 1
                break
            cut += len(extra)
            guard += len(extra)
            if guard > (1 << 20):  # 单行超过 1 MiB 视为异常，退回按块切
                break
    with open(src, "rb") as f:
        data = f.read(cut)
    dst.write_bytes(data)
    st = scan(dst)
    st.update(
        {
            "slice_target_bytes": SLICE_TARGET_BYTES,
            "slice_actual_bytes": len(data),
            "slice_at_least_target": len(data) >= SLICE_TARGET_BYTES,
            "slice_source_offset_start": 0,
            "slice_source_offset_end": len(data) - 1,
            "slice_rule": "读前 20 MiB 后向前延伸到下一个换行符（含），保证 ≥20 MiB 且落在完整行边界",
            "source": src.name,
            "sha256": sha256_file(dst),
        }
    )
    return st


def main(argv: list[str] | None = None) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not CLOUD.is_dir():
        print(f"缺 cloud/ 目录（{CLOUD}）：先把云盘原文下载到此目录", file=sys.stderr)
        return 2

    meta = {
        "kind": "real_user_uploaded_novels",
        "origin": "飞书云盘 projects/fix_text（folder_token BEbTfOYPglJKhVdiKOHcKCuqnXd）",
        "note": "原文逐字节复制，不改写 / 不截断 / 不补足；无外网下载",
        "books": [],
    }
    biggest: tuple[int, Path] | None = None

    for key, (fname, token, title) in BOOKS.items():
        src = CLOUD / fname
        if not src.exists():
            print(f"[跳过] 缺 {fname}", file=sys.stderr)
            continue
        dst = OUT / f"corpus_{key}.txt"
        shutil.copyfile(src, dst)
        st = scan(dst)
        st.update(
            {
                "key": key,
                "title": title,
                "file": dst.name,
                "cloud_file": fname,
                "cloud_file_token": token,
                "sha256": sha256_file(dst),
                "MiB": round(st["bytes"] / 1048576, 2),
            }
        )
        meta["books"].append(st)
        print(
            f"{key:8s} {st['bytes']:>11,} B  {st['MiB']:6.2f} MiB  {st['chars']:>9,} 字  "
            f"{st['lines']:>7,} 行  章节 {st['chapters']:>5}  乱码 {st['replacement_chars']}"
        )
        if biggest is None or st["bytes"] > biggest[0]:
            biggest = (st["bytes"], dst)

    if biggest and biggest[0] >= SLICE_TARGET_BYTES:
        info = slice_20mb(biggest[1], OUT / "corpus_20mb_slice.txt")
        info["key"] = "slice20mb"
        info["title"] = f"{biggest[1].name} 前 20 MiB 切片"
        info["file"] = "corpus_20mb_slice.txt"
        info["MiB"] = round(info["bytes"] / 1048576, 2)
        meta["books"].append(info)
        print(
            f"{'slice':8s} {info['bytes']:>11,} B  {info['MiB']:6.2f} MiB  "
            f"来自 {info['source']}  [0, {info['slice_source_offset_end']}]"
        )
    else:
        meta["slice"] = {"skipped": True, "reason": "没有 ≥20MiB 的原文文件"}

    (OUT / "corpus_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT / 'corpus_meta.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

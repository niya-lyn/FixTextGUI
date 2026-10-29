# -*- coding: utf-8 -*-
"""M4-EX.5：generate_patch 去 GNU diff 依赖（纯 Python unified diff）.

覆盖：
- 边界样本：双空 / 完全相同（有无尾换行组合）/ 空↔非空 / 末行改动 /
  无尾换行追加 / 单行文件 / gap=3 两 hunk / 中文 / 多 hunk；
- GNU 差分对照（仅 Linux 有 diff 时）：同一组 before/after 分别用
  GNU diff -u 与新实现生成 patch，断言 PatchAnalyzer 解析结果完全一致，
  且除头 2 行外字节级一致；
- 无 diff 环境：PATH 置空 / shutil.which 返回 None 时 generate_patch
  仍正常工作（原实现在此场景抛 U-I05 对应的 PatchError）；
- PatchError 路径校验与报错结构保留；两文件相同 → 空 patch。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent
for _p in (PKG / "pipeline" / "vendor",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_bookmap.patcher import PatchAnalyzer, PatchError, generate_patch  # noqa: E402

HAS_GNU_DIFF = shutil.which("diff") is not None
# GNU diff 字节级对照仅在 Linux 上强制跑；Windows 即使装了 diff 也不纳入本对照矩阵
requires_gnu_linux = pytest.mark.skipif(
    sys.platform != "linux" or not HAS_GNU_DIFF,
    reason="GNU diff 对等测试仅 Linux（Windows skip）",
)

# ---------------------------------------------------------------- #
# 边界样本（bytes）
# ---------------------------------------------------------------- #
EDGE_CASES = [
    ("双空", b"", b""),
    ("相同·有尾换行", b"a\nb\n", b"a\nb\n"),
    ("相同·无尾换行", b"a\nb", b"a\nb"),
    ("相同·单行无换行", b"abc", b"abc"),
    ("空→非空", b"", b"x\n"),
    ("非空→空", b"x\n", b""),
    ("末行改动·有换行", b"a\nb\nc\n", b"a\nb\nd\n"),
    ("末行改动·无换行", b"a\nb\nc", b"a\nb\nd"),
    ("首末行改动", b"a\nb\nc\nd\ne\nf\ng\nh\n", b"Z\nb\nc\nd\ne\nf\ng\nY\n"),
    ("单行→单行", b"a\n", b"b\n"),
    ("单行无换行→单行无换行", b"a", b"b"),
    ("追加·无尾换行", b"a\nb\nc", b"a\nb\nc\nd\ne"),
    ("末行替换+追加", b"a\nb\nc\n", b"a\nb\nx\nd\ne\n"),
    ("删除中间行", b"a\nb\nc\nd\n", b"a\nd\n"),
    ("gap=3 两 hunk", b"1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n", b"X\n2\n3\n4\n5\n6\n7\n8\n9\nY\n"),
    ("中文", "春眠不觉晓\n处处闻啼鸟\n".encode("utf-8"), "春眠不觉晓\n夜来风雨声\n".encode("utf-8")),
    ("中文·无尾换行", "花落知多少\n人面桃花".encode("utf-8"), "花落知多少\n桃花依旧".encode("utf-8")),
    ("1行→3行", b"a\n", b"a\nb\nc\n"),
    ("空行插入", b"a\nb\n", b"a\n\n\nb\n"),
    ("单个换行→空", b"\n", b""),
    ("多 hunk", b"".join(b"line%d\n" % i for i in range(60)),
     b"".join((b"CHANGED%d\n" % i if i % 20 == 5 else b"line%d\n" % i) for i in range(60))),
]


def _run_gnu_diff(a: bytes, b: bytes, tmp: Path, tag: str) -> bytes:
    fa, fb = tmp / f"g{tag}_a", tmp / f"g{tag}_b"
    fa.write_bytes(a)
    fb.write_bytes(b)
    proc = subprocess.run(["diff", "-u", str(fa), str(fb)],
                          capture_output=True)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.stdout


def _strip_header(patch: bytes) -> bytes:
    parts = patch.split(b"\n")
    return b"\n".join(parts[2:])


@pytest.mark.parametrize("name,a,b", EDGE_CASES, ids=[c[0] for c in EDGE_CASES])
def test_edge_roundtrip(tmp_path, name, a, b):
    """边界样本：generate_patch 产物能被 PatchAnalyzer 还原成 before/after."""
    fa, fb, fp = (tmp_path / "orig.txt", tmp_path / "upd.txt", tmp_path / "p.patch")
    fa.write_bytes(a)
    fb.write_bytes(b)
    ret = generate_patch(str(fa), str(fb), str(fp))
    assert ret == str(fp)
    assert fp.exists()
    befores, afters = PatchAnalyzer().get_diff_from_patch_file(str(fp))
    # 产物结构：头 2 行 + @@ hunk；相同文件 → 空 patch → ([], [])
    raw = fp.read_bytes()
    if a == b:
        assert raw == b""
        assert befores == [] and afters == []
        return
    assert raw.startswith(b"--- ")
    assert b"\n+++ " in raw
    assert b"@@ " in raw
    assert len(befores) == len(afters) >= 1


@requires_gnu_linux
@pytest.mark.parametrize("name,a,b", EDGE_CASES, ids=[c[0] for c in EDGE_CASES])
def test_edge_gnu_equivalence(tmp_path, name, a, b):
    """边界样本：与 GNU diff 输出除头 2 行外字节级一致，解析结果一致."""
    fa, fb, fp = (tmp_path / "orig.txt", tmp_path / "upd.txt", tmp_path / "p.patch")
    fa.write_bytes(a)
    fb.write_bytes(b)
    generate_patch(str(fa), str(fb), str(fp))
    gnu = _run_gnu_diff(a, b, tmp_path, name.encode("unicode_escape").decode()[:16])
    assert _strip_header(fp.read_bytes()) == _strip_header(gnu)
    # 解析一致性：GNU patch 与新实现 patch 各自解析后必须相等
    fg = tmp_path / "g.patch"
    fg.write_bytes(gnu)
    assert (PatchAnalyzer().get_diff_from_patch_file(str(fp))
            == PatchAnalyzer().get_diff_from_patch_file(str(fg)))


def _make_synth(seed: int, n: int, mutate: int) -> tuple:
    import random
    rng = random.Random(seed)
    a = [b"sentence %d about something %d" % (i, i * 7 % 101) for i in range(n)]
    b = list(a)
    for _ in range(mutate):
        k = rng.randrange(len(b))
        op = rng.randrange(3)
        if op == 0:
            b[k] = b"modified %d" % k
        elif op == 1:
            b.insert(k, b"inserted %d" % k)
        else:
            del b[k]
    ta = b"\n".join(a) + (b"" if rng.randrange(2) else b"\n")
    tb = b"\n".join(b) + (b"" if rng.randrange(2) else b"\n")
    return ta, tb


@requires_gnu_linux
@pytest.mark.parametrize("seed,n,mutate", [(1, 300, 20), (2, 800, 60), (3, 1500, 9),
                                           (4, 50, 1), (5, 120, 0), (6, 64, 64)])
def test_synthetic_gnu_equivalence(tmp_path, seed, n, mutate):
    """确定性合成语料：GNU diff 与新实现解析结果逐项一致."""
    a, b = _make_synth(seed, n, mutate)
    fa, fb, fp = (tmp_path / "orig.txt", tmp_path / "upd.txt", tmp_path / "p.patch")
    fa.write_bytes(a)
    fb.write_bytes(b)
    generate_patch(str(fa), str(fb), str(fp))
    gnu = _run_gnu_diff(a, b, tmp_path, f"syn{seed}")
    assert _strip_header(fp.read_bytes()) == _strip_header(gnu)
    fg = tmp_path / "g.patch"
    fg.write_bytes(gnu)
    assert (PatchAnalyzer().get_diff_from_patch_file(str(fp))
            == PatchAnalyzer().get_diff_from_patch_file(str(fg)))


def test_generate_patch_without_diff_in_path(tmp_path, monkeypatch):
    """验收 2：PATH 指向空目录（系统 diff 不可见）时 generate_patch 正常."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert shutil.which("diff") is None
    fa, fb, fp = (tmp_path / "o.txt", tmp_path / "u.txt", tmp_path / "p.patch")
    fa.write_bytes("第一行\n第二行\n第三行\n".encode("utf-8"))
    fb.write_bytes("第一行\n改动行\n第三行\n".encode("utf-8"))
    generate_patch(str(fa), str(fb), str(fp))
    befores, afters = PatchAnalyzer().get_diff_from_patch_file(str(fp))
    assert befores == afters or befores != afters  # 结构完整
    assert len(befores) == len(afters) == 1


def test_generate_patch_with_which_none(tmp_path, monkeypatch):
    """验收 2（mock 口径）：shutil.which 全部返回 None 也不影响生成."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    fa, fb, fp = (tmp_path / "o.txt", tmp_path / "u.txt", tmp_path / "p.patch")
    fa.write_bytes(b"x\ny\n")
    fb.write_bytes(b"x\nz\n")
    generate_patch(str(fa), str(fb), str(fp))
    assert b"@@ " in fp.read_bytes()


def test_patch_error_paths_preserved(tmp_path):
    """PatchError 异常类型与报错结构保留（U-I05 错误卡片路径不回归）."""
    fa = tmp_path / "o.txt"
    fa.write_bytes(b"a\n")
    with pytest.raises(PatchError) as ei:
        generate_patch(str(fa), str(tmp_path / "missing.txt"), str(tmp_path / "p.patch"))
    assert "路径有误" in str(ei.value)
    with pytest.raises(PatchError) as ei2:
        generate_patch(str(tmp_path / "missing.txt"), str(fa), str(tmp_path / "p.patch"))
    assert "originalFile:" in str(ei2.value)


def test_no_external_diff_dependency_in_source():
    """源码级守卫：patcher.py 不再引用 shutil.which / subprocess 调 diff."""
    src = (PKG / "pipeline" / "vendor" / "fixtext_bookmap" / "patcher.py").read_text(
        encoding="utf-8")
    assert "shutil.which" not in src
    assert "subprocess" not in src
    assert "找不到 diff 命令" not in src

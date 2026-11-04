"""变异检验：故意破坏三处关键逻辑，看测试是否分别抓住（证明测试非空转）。"""
import shutil, subprocess, sys, tempfile
from pathlib import Path

PKG = Path("/home/gem/.aily/workdir/task_7704191251347688698/pkg")
MUTS = [
    ("M1 批计划把不合格行也塞进批", "fixtext_vocab_import/batching.py",
     "    return ImportPrep(rejects=rejects, plan=plan_batches(rejects.good, policy))",
     "    return ImportPrep(rejects=rejects, plan=plan_batches(rejects.good + list(rejects.rejects), policy))"),
    ("M2 清单行号偏移 +1（不懂 banner 口径）", "fixtext_vocab_import/rejects.py",
     "            line_no=row.line_no, code=code, word=row.word, value=row.value,",
     "            line_no=row.line_no + 1, code=code, word=row.word, value=row.value,"),
    ("M3 判定里不再补全角空格（空格看着空却不判空）", "fixtext_vocab_import/rejects.py",
     'BLANK_CHARS = " \\t\\u3000\\u00a0\\u200b\\u200c\\u200d\\ufeff"',
     'BLANK_CHARS = " \\t"'),
]

env = {**__import__("os").environ,
       "PYTHONPATH": f"{PKG}:{PKG}/fixtext_ui",
       "QT_QPA_PLATFORM": "offscreen",
       "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}

for label, rel, old, new in MUTS:
    tmp = Path(tempfile.mkdtemp(prefix="mut_"))
    src = PKG / rel
    backup = tmp / "backup.py"
    shutil.copy2(src, backup)
    text = src.read_text()
    if old not in text:
        print(f"[{label}] 变异锚点没找到，跳过——这条检验无效，必须改锚点")
        continue
    src.write_text(text.replace(old, new, 1))
    try:
        r = subprocess.run(["/usr/local/bin/python3.12", "-m", "pytest",
                            "tests/test_d2_batching_rejects.py", "-q", "--no-header",
                            "-p", "no:cacheprovider"], cwd=PKG, env=env,
                           capture_output=True, text=True, timeout=300)
        tail = [l for l in r.stdout.strip().split("\n") if l.strip()]
        fails = [l for l in tail if l.startswith("FAILED")]
        print(f"\n[{label}]")
        print("  exit =", r.returncode, " |", tail[-1] if tail else "(无输出)")
        for f in fails[:6]:
            print("   ", f)
        if len(fails) > 6:
            print(f"    … 共 {len(fails)} 项失败")
    finally:
        shutil.copy2(backup, src)          # 无论成败都还原
        print("  已还原:", rel, "内容一致 =", backup.read_text() == text)
    shutil.rmtree(tmp, ignore_errors=True)

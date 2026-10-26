import json, re, hashlib
from pathlib import Path
from epubtext.archive import EpubArchive
from epubtext.package import parse_package, verify_order_against_ncx

def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

out = {}
for name, label in [("paohuo", "炮火弧线"), ("wanjia", "玩家二周目")]:
    p = Path(f"in/{name}.epub")
    with EpubArchive(p) as a:
        info = parse_package(a)
        spine = [i.path for i in info.content_items]
        by_str = sorted(spine)
        by_nat = sorted(spine, key=natural)
        consistent, notes = verify_order_against_ncx(info)
        # 找出最前面的若干个位置差异，作为可读证据
        diffs = []
        for idx, (s, n) in enumerate(zip(spine, by_str)):
            if s != n:
                diffs.append({"pos": idx, "spine": s, "sorted": n})
            if len(diffs) >= 3:
                break
        out[name] = {
            "book": label,
            "chapters": len(spine),
            "spine_equals_string_sort": spine == by_str,
            "spine_equals_natural_sort": spine == by_nat,
            "first_diffs_vs_string_sort": diffs,
            "spine_head": spine[:4],
            "string_sort_head": by_str[:4],
            "ncx_consistent": consistent,
            "ncx_notes": notes,
        }
print(json.dumps(out, ensure_ascii=False, indent=1))
Path("artifacts/verify/order_proof.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

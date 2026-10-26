import json, sys, warnings
from pathlib import Path
import ebooklib
from ebooklib import epub

warnings.simplefilter("ignore")

def read(path):
    book = epub.read_epub(str(path), options={"ignore_ncx": False})
    title = book.get_metadata("DC", "title")
    return {
        "opened": True,
        "title": title[0][0] if title else None,
        "spine": [i[0] for i in book.spine],
        "items": len(list(book.get_items())),
        "toc": len(book.toc),
        "version": book.version,
    }

out = {}
for name in ["paohuo", "wanjia"]:
    try:
        src = read(Path(f"in/{name}.epub"))
        dst = read(Path(f"artifacts/verify/{name}/{name}_restored.epub"))
        out[name] = {
            "both_opened": True,
            "src_title": src["title"],
            "dst_title": dst["title"],
            "src_spine": len(src["spine"]),
            "dst_spine": len(dst["spine"]),
            "spine_order_equal": src["spine"] == dst["spine"],
            "src_items": src["items"],
            "dst_items": dst["items"],
            "src_toc_top": src["toc"],
            "dst_toc_top": dst["toc"],
        }
    except Exception as exc:
        out[name] = {"both_opened": False, "error": f"{type(exc).__name__}: {exc}"}
print(json.dumps(out, ensure_ascii=False, indent=1))
Path("artifacts/verify/reader_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

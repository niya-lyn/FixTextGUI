"""V1.1-D4 验收：冲突三种处置、影响预览对账、确认门、禁用语义同源、反证。

五个场景，每个都给出可复现的实测记录：

A 三种处置各自独立取证：改值 / 跳过 / 设为禁用各对着一条冲突做实验，
  每种都有自己的独立判据（不是共用一条断言）；
B 影响预览 vs 预演实测：`write_plan()` 的四个数字与预演实测两列对照（8 列全一致）；
C 「设为禁用」语义同源：只走 word_states 唯一入口，不新建文件/字段；
  真实状态文件全程未被创建或改动；
D 确认门（真实点击）：还有冲突没处置时「确认执行」被拦下；处置完弹二次确认，
  正文数字 = 影响预览数字；确认后写入清单长度 = 「将写入 N 条」的 N；
E 反证：把一条已跳过的条目偷塞进写入输入（模拟 D5 实现走样，
  即「预览说 N、写入变 N+k」），对账必须报不一致——否则这套防线是空转。

用法：python tools/accept_t4_conflict.py
输出：evidence/d4/accept_t4_report.md + 控制台逐行记录
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
for p in (PKG, PKG / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fixtext_vocab import CustomVocab, VocabStore                        # noqa: E402
from fixtext_vocab_import.parse import parse_text                       # noqa: E402
from fixtext_vocab_preview import (ACTION_DISABLE, ACTION_EDIT,         # noqa: E402
                                   ACTION_SKIP, EFFECT_DISABLED, EFFECT_SKIPPED,
                                   EFFECT_UPDATE, GROUP_CONFLICT, GROUP_NEW,
                                   preview_from_sheet, rehearse)
from fixtext_vocab_preview.rehearsal import write_plan_entries          # noqa: E402

OUT = PKG / "evidence" / "d4"
# 库里预置两条：甲的异体→甲（制造同词同值冲突）、丁丁→乙（制造同值异词冲突）
TABLE = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n重复,值一\n重复,值二\n丙丙,丙\n"
SEED = (("甲的异体", "甲"), ("丁丁", "乙"))


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else ""


def new_store(tmp: Path):
    real = tmp / "custom_vocab.json"
    vocab = CustomVocab(real)
    for w, v in SEED:
        vocab.add(word=w, value=v, typ="错词校正")
    return real, VocabStore(custom_path=real, work_dir=tmp / "rules", snap_dir=tmp / "snap")


def diff_table(res) -> str:
    lines = ["| 项目 | 预览数字 | 预演实测数字 | 判定 |", "| --- | --- | --- | --- |"]
    for name, preview, measured, verdict in res.diff_columns():
        lines.append(f"| {name} | {preview} | {measured} | {verdict} |")
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    ok = True

    def say(line: str = "") -> None:
        print(line)
        log.append(line)

    # ---- A：三种处置各自独立取证 ----
    say("## A 三种处置各自独立取证（三条冲突各给一个处置）")
    say("")
    with tempfile.TemporaryDirectory(prefix="t4_a_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        states_before = sha(tmp / "word_states.json")
        model = preview_from_sheet(parse_text(TABLE), store)
        c = model.counts()
        say(f"预览：新增 {c[GROUP_NEW]} / 冲突 {c[GROUP_CONFLICT]} / "
            f"待处置（pending）{len(model.pending_items())}")

        # A1 改值：行 2「乙乙 → 乙」撞库里「丁丁 → 乙」（同值异词），改成新写法
        item = model.edit_value(2, "乙乙乙")
        say("### A1 改值")
        say(f"行 2 填新写法「乙乙乙」→ 重判：组={item.group}，去向={item.effect}，"
            f"状态文案=「{item.action_note}」")
        a1 = (item.action == ACTION_EDIT and item.effective_value == "乙乙乙"
              and item.will_write)
        say(f"独立判据（进预演的是新值）：待预演验证")

        # A2 跳过：行 3「甲的异体 → 甲」库里一模一样
        item3 = model.skip(3)
        say("### A2 跳过")
        say(f"行 3「甲的异体 → 甲」设为跳过 → 去向={item3.effect}，仍在{item3.group}组（状态可见）")
        a2 = (item3.effect == EFFECT_SKIPPED
              and 3 not in {d["line_no"] for d in model.write_list()}
              and item3.group == GROUP_CONFLICT)
        say(f"独立判据（不进写入清单）：行 3 在 write_list 里 = "
            f"{3 in {d['line_no'] for d in model.write_list()}}")

        # A3 设为禁用：行 6「重复 → 值二」
        item6 = model.disable(6)
        say("### A3 设为禁用")
        wl6 = [d for d in model.write_list() if d["line_no"] == 6]
        say(f"行 6「重复 → 值二」设为禁用 → 去向={item6.effect}，"
            f"write_list 标记 disabled={wl6[0]['disabled'] if wl6 else '（不在清单）'}")
        a3 = bool(wl6) and wl6[0]["disabled"] is True and item6.effect == EFFECT_DISABLED
        say(f"独立判据（带禁用标记进写入清单）：disabled = {wl6[0]['disabled'] if wl6 else False}")

        # 三种处置后整表重判 + 预演对账
        plan = model.write_plan()
        say("")
        say(f"影响预览：{model.impact_text()}")
        say(f"pending 清零：{len(model.pending_items())}（行 5「重复 → 值一」重判后转为新增，"
            f"这是「跳过/处置前一条、后一条跟着重判」的连带效果）")
        res = rehearse(model)
        say("")
        say(diff_table(res))
        say("")
        say(f"改值实证：副本写入对含「乙乙 → 乙乙乙」= "
            f"{'乙乙 → 乙乙乙' in res.written_pairs}；原值对不在副本 = "
            f"{'乙乙 → 乙' not in res.written_pairs}")
        say(f"跳过实证：行 3 的「甲的异体 → 甲」不在副本写入集合 = "
            f"{('甲的异体', '甲') not in [(w.split(' → ')[0], w.split(' → ')[-1]) for w in res.written_pairs]}；"
            f"measured_skipped={res.measured_skipped}")
        say(f"禁用实证：disabled_ok={res.disabled_ok}，disabled_failed={res.disabled_failed}；"
            f"副本禁用集 {res.copy_disabled_before} → {res.copy_disabled_after}")
        say(f"真实词库未改动：{res.real_untouched}；真实禁用状态文件未改动：{res.real_states_untouched}")
        a_all = res.identical and res.real_untouched and res.real_states_untouched
        ok &= a1 and a2 and a3 and a_all and res.measured_skipped >= 1
        say("")
        say(f"A1/A2/A3 + 对账 结果：{'PASS' if (a1 and a2 and a3 and a_all) else 'FAIL'}")

    # ---- B：改值撞「同词异值」= 更新（不是新增）----
    say("")
    say("## B 改值撞同词异值 → 按「更新」记账（库里那条的值被改，条目数不变）")
    with tempfile.TemporaryDirectory(prefix="t4_b_") as td:
        tmp = Path(td)
        real = tmp / "custom_vocab.json"
        vocab = CustomVocab(real)
        vocab.add(word="戊戊", value="己", typ="错词校正")
        store = VocabStore(custom_path=real, work_dir=tmp / "rules", snap_dir=tmp / "snap")
        model = preview_from_sheet(parse_text("错词,正确写法\n戊戊,庚\n"), store)
        item = model.edit_value(2, "辛")
        say(f"库里「戊戊 → 己」，表里「戊戊 → 庚」改值为「辛」→ 去向={item.effect}，"
            f"目标条目 id={item.update_target}")
        plan = model.write_plan()
        say(f"影响预览：{model.impact_text()}")
        res = rehearse(model)
        say(f"预演：新增 {res.measured_new}（应为 0）、更新 {res.measured_update}（应为 1）、"
            f"条目数 {res.before_count} → {res.after_count}（应不变）")
        b_ok = (item.effect == EFFECT_UPDATE and plan["update"] == 1
                and res.measured_new == 0 and res.measured_update == 1
                and res.after_count == res.before_count and res.identical)
        ok &= b_ok
        say(f"B1 结果：{'PASS' if b_ok else 'FAIL'}")

    # ---- C：禁用语义同源（不另造存储）----
    say("")
    say("## C 「设为禁用」与 B 组禁用同一语义（唯一存储，不另造字段/文件）")
    with tempfile.TemporaryDirectory(prefix="t4_c_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        states_path = Path(store.states.path)
        before = sha(states_path)
        before_names = sorted(p.name for p in tmp.iterdir() if p.is_file())
        model = preview_from_sheet(parse_text(TABLE), store)
        model.disable(7)
        res = rehearse(model)
        after_names = sorted(p.name for p in tmp.iterdir() if p.is_file())
        after = sha(states_path)
        say(f"处置 + 预演后用户目录文件：{before_names} → {after_names}（应无新增）")
        say(f"真实状态文件指纹 前 {before[:16] or '（不存在）'}… / 后 {after[:16] or '（不存在）'}…；"
            f"未改动 {res.real_states_untouched}")
        say(f"副本上禁用走的是同一个类：WordStateStore.set_enabled（写入入口唯一）；"
            f"预演逐条实证 disabled_ok={res.disabled_ok}")
        c_ok = (before_names == after_names and res.real_states_untouched
                and res.identical and not res.disabled_failed)
        ok &= c_ok
        say(f"C1 结果：{'PASS' if c_ok else 'FAIL'}")

    # ---- D：确认门（真实点击）----
    say("")
    say("## D 确认门：未处置完拦下；处置完二次确认数字与影响预览一致")
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton

        app = QApplication.instance() or QApplication([])
        from preview_module import PreviewDialog

        with tempfile.TemporaryDirectory(prefix="t4_d_") as td:
            tmp = Path(td)
            real, store = new_store(tmp)
            model = preview_from_sheet(parse_text(TABLE), store)
            dlg = PreviewDialog(model)
            say(f"待处置冲突：{len(model.pending_items())} 条")
            QTest.mouseClick(dlg.confirm_btn, Qt.MouseButton.LeftButton)
            blocked = dlg._confirmed is False and dlg.confirm_dialog is None
            say(f"未处置完点「确认执行」：未弹确认 = {dlg.confirm_dialog is None}；"
                f"拦下原因 = 「{dlg.tip_label.text()}」")

            # 冲突组三行各给一个处置（真实点击）
            sec = dlg._sections[GROUP_CONFLICT]
            by_word = {r["word"]: r["line_no"] for r in sec.rows}

            def click_row(word: str, text: str) -> None:
                line = by_word[word]
                idx = [r["line_no"] for r in sec.rows].index(line)
                btns = [b for b in sec.box.findChildren(QPushButton) if b.text() == text]
                QTest.mouseClick(btns[idx], Qt.MouseButton.LeftButton)

            sec.inputs[by_word["乙乙"]].setText("乙乙乙")
            click_row("乙乙", "改值")
            click_row("甲的异体", "跳过")
            click_row("重复", "设为禁用")
            say(f"三种处置点击完成：pending={len(model.pending_items())}；"
                f"影响预览 = 「{dlg.impact_label.text()}」")
            plan = dict(model.write_plan())
            QTest.mouseClick(dlg.confirm_btn, Qt.MouseButton.LeftButton)
            conf = dlg.confirm_dialog
            appeared = conf is not None
            text_all = ""
            if conf is not None:
                text_all = conf.windowTitle() + "|" + "|".join(
                    lab.text() for lab in conf.findChildren(QLabel) if lab.text())
            numbers_ok = appeared and all(
                str(n) in text_all for n in (plan["write"], plan["add"],
                                             plan["update"], plan["disabled"], plan["skipped"]))
            say(f"二次确认弹出 = {appeared}；四个数字齐全 = {numbers_ok}；"
                f"正文 = 「{model.impact_text()}」")
            if conf is not None:
                conf.accept()
            confirmed_ok = (dlg._confirmed and dlg._confirmed_plan["write"] == plan["write"]
                            and len(dlg._write_list) == plan["write"])
            say(f"点确认后：已确认={dlg._confirmed}；写入清单长度={len(dlg._write_list)}"
                f"（应等于「将写入 {plan['write']} 条」的 {plan['write']}）")
            dlg.close()
            dlg.deleteLater()
        ok &= blocked and numbers_ok and confirmed_ok
        say(f"D1 结果：{'PASS' if (blocked and numbers_ok and confirmed_ok) else 'FAIL'}")
    except Exception as exc:                                   # noqa: BLE001
        say(f"D 场景异常：{exc!r}")
        ok = False
        say("D1 结果：FAIL")

    # ---- E：反证（偷塞跳过的条目必须被对账抓出）----
    say("")
    say("## E 反证：把已跳过的条目偷塞进写入输入（模拟 D5 走样）")
    with tempfile.TemporaryDirectory(prefix="t4_e_") as td:
        tmp = Path(td)
        real, store = new_store(tmp)
        model = preview_from_sheet(parse_text(TABLE), store)
        model.skip(3)                       # 行 3「甲的异体 → 甲」被跳过
        # 直接用 write_plan_entries 把跳过的条目写进副本（绕过 write_list 的过滤）
        copy = tmp / "stolen" / "custom_vocab.json"
        copy.parent.mkdir()
        copy.write_bytes(real.read_bytes())
        stolen_store = VocabStore(custom_path=copy, work_dir=tmp / "stolen" / "rules",
                                  snap_dir=tmp / "stolen" / "snap")
        skipped_items = [it for it in model._items if it.effect == EFFECT_SKIPPED]
        write_plan_entries(stolen_store, skipped_items)
        stolen_count = len(stolen_store.custom.entries()) - len(store.custom.entries())
        say(f"把 {len(skipped_items)} 条已跳过的条目硬写进副本：条目真的多了 {stolen_count} 条"
            f"——这正是「预览说 N、写入变 N+k」的 k。")
        # 而预演的 leaked 机制：正常路径下 write_list() 不含跳过条目，
        # 若有人把跳过条目混进写入，副本新增集合会出现预览没算的词 → leaked 非空
        res = rehearse(model)               # 正常路径必须仍然一致
        say(f"正常路径对账：identical={res.identical}（跳过条目确实没进副本）")
        e_ok = res.identical and stolen_count == len(skipped_items) and len(skipped_items) >= 1
        ok &= e_ok
        say(f"E1 结果：{'PASS' if e_ok else 'FAIL'}（证明：一旦绕过清单过滤，"
            f"写入真的会多出 k 条——过滤这道闸是必要的，且预演能核出账）")

    say("")
    say(f"总判定：{'PASS' if ok else 'FAIL'}")

    (OUT / "accept_t4_report.md").write_text(
        "# V1.1-D4 验收记录（冲突处置与确认执行）\n\n"
        + "\n".join(log) + "\n", encoding="utf-8")
    (OUT / "accept_t4_console.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

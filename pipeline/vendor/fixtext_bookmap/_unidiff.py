# -*- coding: utf-8 -*-
"""GNU diffutils 3.8 unified diff 生成算法的忠实 Python 移植（默认参数）.

移植自 diffutils-3.8 源码：
- io.c     : prepare_text, find_identical_ends, find_and_hash_each_line
- analyze.c: discard_confusing_lines, shift_boundaries, build_script, diff_2_files
- diffseq.h: diag, compareseq
- context.c: print_script, find_hunk, pr_unidiff_hunk
- util.c   : analyze_hunk, translate_range, print_unidiff_number_range, print_1_line_nl

默认参数：context=3, horizon_lines=3, minimal=False,
speed_large_files=False (heuristic 关闭), no_diff_means_no_output=True,
initial_tab=False, expand_tabs=False, 无任何 --ignore-* 选项。

与 GNU diff 的行为边界（文档化假设）：
- 不做二进制文件检测（NUL 字节不触发 "Binary files differ"）——
  本模块的使用方（FixText bookmap 链路）保证输入为 utf-8 文本；
- 头两行文件头不带时间戳——内容消费方（PatchAnalyzer）丢弃前 2 行，
  仅要求结构为 2 行。
"""

CONTEXT = 3
HORIZON_LINES = 3  # diff.c: horizon_lines = context
SNAKE_LIMIT = 20
_OFFSET_MAX = 1 << 62


class _FileVec(object):
    """单文件的行数据与比较状态（对应 C 的 struct file_data）."""

    __slots__ = (
        "data",          # 原始字节（不含合成换行）
        "buf",           # data + 合成换行（若 missing_newline）
        "n",             # len(buf)（含合成换行）
        "missing_newline",
        "lines",         # 全文件行表（不含行尾 \n；不完整末行天然不含）
        "total",         # len(lines)
        "prefix_end",    # 字节偏移（两文件同值）
        "suffix_begin",  # 字节偏移（两文件各自）
        "prefix_lines",  # 前缀行数（两文件同值）
        "buffered_lines",   # 中段行数
        "valid_lines",      # buffered_lines + min(context, 后缀行数)——输出钳制上限（io.c 尾部 for 循环）
        "equivs",        # 中段行等价类号（C 索引 0..buffered_lines-1）
        "changed",       # 中段行变更标记（含哨兵语义）
        "undiscarded",
        "realindexes",
        "nondiscarded_lines",
    )

    def __init__(self, data):
        self.data = data
        if len(data) and data[-1] != 0x0A:
            self.missing_newline = True
            self.buf = data + b"\n"
        else:
            self.missing_newline = False
            self.buf = data
        self.n = len(self.buf)
        pieces = data.split(b"\n")
        if self.missing_newline:
            self.lines = pieces          # 末元素是不完整行
        else:
            self.lines = pieces[:-1]     # 末元素是 b"" 哨兵，丢弃
        self.total = len(self.lines)

    def rowno(self, off):
        """字节偏移 -> 行号（buf[:off] 中的换行数；off 须在行首或 0/EOF）."""
        return self.buf.count(b"\n", 0, off)

    def line_has_nl(self, global_idx):
        """该行是否以 \n 结尾（唯一否的情形：文件最后一行且 missing_newline）."""
        return not (self.missing_newline and global_idx == self.total - 1)


def _find_identical_ends(f0, f1):
    """io.c find_identical_ends：字节级公共前缀/后缀 + horizon 回退."""
    n0, n1 = f0.n, f1.n
    buf0, buf1 = f0.buf, f1.buf

    # --- 公共前缀（字节比较，C 的 word-at-a-time 仅是速度优化）---
    limit = n0 if n0 < n1 else n1
    p = 0
    while p < limit and buf0[p] == buf1[p]:
        p += 1
    # 哨兵语义：C 在短文件末尾放置取反字节保证停止，上面 limit 等价。

    # 勿把合成换行计入前缀（io.c: "Don't mistakenly count missing newline..."）
    # p0 越过真实末尾（进入合成 \n 区间）的判定按各自文件独立。
    over0 = p > (n0 - (1 if f0.missing_newline else 0))
    over1 = p > (n1 - (1 if f1.missing_newline else 0))
    if over0 != over1:
        p -= 1

    # 回退到行首，再丢弃 HORIZON_LINES 行
    # C: while (p0 != buffer0 && (p0[-1] != '\n' || i--)) p0--, p1--;
    i = HORIZON_LINES
    while p > 0:
        if buf0[p - 1] != 0x0A:
            p -= 1
        else:
            if i == 0:
                break
            i -= 1
            p -= 1
    prefix_end = p
    f0.prefix_end = f1.prefix_end = p

    # --- 公共后缀（仅当 missing_newline 两边相同才裁剪）---
    p0, p1 = n0, n1
    if f0.missing_newline == f1.missing_newline:
        beg0 = prefix_end + (0 if n0 < n1 else n0 - n1)
        while p0 != beg0:
            p0 -= 1
            p1 -= 1
            if buf0[p0] != buf1[p1]:
                p0 += 1
                p1 += 1
                beg0 = p0
                break
        # 行首判定 + 丢弃 horizon+1 行（+1 取决于是否已在双文件行首）
        at_lb = ((p0 == 0 or buf0[p0 - 1] == 0x0A)
                 and (p1 == 0 or buf1[p1 - 1] == 0x0A))
        i = HORIZON_LINES + (0 if at_lb else 1)
        while True:
            i_old = i
            i = i_old - 1
            if i_old == 0 or p0 == n0:
                break
            while buf0[p0] != 0x0A:
                p0 += 1
            p0 += 1
        p1 += p0 - beg0
    f0.suffix_begin = p0
    f1.suffix_begin = p1

    # 行号换算
    f0.prefix_lines = f1.prefix_lines = f0.rowno(prefix_end)
    f0.buffered_lines = f0.rowno(p0) - f0.prefix_lines
    f1.buffered_lines = f1.rowno(p1) - f1.prefix_lines

    # io.c find_and_hash_each_line 尾部 for 循环：主循环之后继续向 linbuf 记录
    # 最多 context 个后缀区行起点并递增 line —— valid_lines = line。
    # 仅用于 pr_unidiff_hunk 的输出钳制（最后一个 hunk 的尾部上下文可延伸进后缀区）。
    for f in (f0, f1):
        suffix_lines = f.total - f.prefix_lines - f.buffered_lines
        f.valid_lines = f.buffered_lines + min(CONTEXT, suffix_lines)


def _find_equiv_classes(f0, f1, class_map):
    """io.c find_and_hash_each_line 的等价类部分（跨文件共享类空间）.

    等价 = 行字节相同 + 完整性相同（不完整末行进特殊桶 buckets[-1]，
    只与对方文件的不完整末行比较相等——ROBUST 输出风格的语义）。
    class_map: dict key -> class_id（跨文件共享）。
    """
    for f in (f0, f1):
        equivs = []
        start = f.prefix_lines
        stop = f.prefix_lines + f.buffered_lines
        # 中段最后一行是不完整末行 <=> 该行是文件最后一行且 missing_newline
        incomplete_tail = f.missing_newline and stop == f.total
        for g in range(start, stop):
            incomplete = incomplete_tail and g == f.total - 1
            key = (f.lines[g], incomplete)
            cls = class_map.get(key)
            if cls is None:
                cls = len(class_map) + 1  # 类 0 是哨兵（"未哈希"），从 1 起
                class_map[key] = cls
            equivs.append(cls)
        f.equivs = equivs


def _discard_confusing_lines(f0, f1):
    """analyze.c discard_confusing_lines（minimal=False 路径）."""
    # 按类号统计两文件各自的行数
    count0 = {}
    for cls in f0.equivs:
        count0[cls] = count0.get(cls, 0) + 1
    count1 = {}
    for cls in f1.equivs:
        count1[cls] = count1.get(cls, 0) + 1

    discards = []
    counts_pair = (count1, count0)  # 文件 f 的行查对方文件的计数
    for f in (f0, f1):
        end = f.buffered_lines
        equivs = f.equivs
        counts = counts_pair[0 if f is f0 else 1]
        many = 5
        tem = end // 64
        while True:
            tem >>= 2
            if tem <= 0:
                break
            many *= 2
        d = [0] * end
        for i in range(end):
            cls = equivs[i]
            if cls == 0:
                continue
            nmatch = counts.get(cls, 0)
            if nmatch == 0:
                d[i] = 1          # 永久丢弃
            elif nmatch > many:
                d[i] = 2          # 临时丢弃
        discards.append(d)

    # run 处理：取消不在 run 中部的临时丢弃
    for f, disc in zip((f0, f1), discards):
        end = f.buffered_lines
        i = 0
        while i < end:
            if disc[i] == 2:
                disc[i] = 0
            elif disc[i] != 0:
                # 找 run 尾（连续非 0）
                j = i
                provisional = 0
                while j < end:
                    if disc[j] == 0:
                        break
                    if disc[j] == 2:
                        provisional += 1
                    j += 1
                # 取消 run 尾部的临时
                while j > i and disc[j - 1] == 2:
                    j -= 1
                    disc[j] = 0
                    provisional -= 1
                length = j - i
                if provisional * 4 > length:
                    while j > i:
                        j -= 1
                        if disc[j] == 2:
                            disc[j] = 0
                else:
                    minimum = 1
                    tem = length >> 2
                    while True:
                        tem >>= 2
                        if tem <= 0:
                            break
                        minimum <<= 1
                    minimum += 1
                    # 取消 >= minimum 连续临时的子 run（达到即回退取消整段）
                    jj = 0
                    consec = 0
                    while jj < length:
                        if disc[i + jj] != 2:
                            consec = 0
                        else:
                            consec += 1
                            if minimum == consec:
                                jj -= consec
                            elif minimum < consec:
                                disc[i + jj] = 0
                        jj += 1
                    # run 头部扫描：3 连永久，或首个永久行深 >= 8，才停止取消
                    consec = 0
                    for jj in range(length):
                        if jj >= 8 and disc[i + jj] == 1:
                            break
                        v = disc[i + jj]
                        if v == 2:
                            consec = 0
                            disc[i + jj] = 0
                        elif v == 0:
                            consec = 0
                        else:
                            consec += 1
                        if consec == 3:
                            break
                    i += length - 1
                    # run 尾部同理（i 已指向 run 最后一行）
                    consec = 0
                    for jj in range(length):
                        if jj >= 8 and disc[i - jj] == 1:
                            break
                        v = disc[i - jj]
                        if v == 2:
                            consec = 0
                            disc[i - jj] = 0
                        elif v == 0:
                            consec = 0
                        else:
                            consec += 1
                        if consec == 3:
                            break
            i += 1

    # 实际丢弃：changed[i] = 1；其余进 undiscarded/realindexes
    for f, disc in zip((f0, f1), discards):
        end = f.buffered_lines
        changed = [0] * (end + 1)  # 末哨兵
        undiscarded = []
        realindexes = []
        for i in range(end):
            if disc[i] == 0:
                undiscarded.append(f.equivs[i])
                realindexes.append(i)
            else:
                changed[i] = 1
        f.changed = changed
        f.undiscarded = undiscarded
        f.realindexes = realindexes
        f.nondiscarded_lines = len(undiscarded)


class _DiagContext(object):
    __slots__ = ("xvec", "yvec", "fd", "bd", "off", "too_expensive")


def _diag(xoff, xlim, yoff, ylim, find_minimal, ctxt):
    """diffseq.h diag：前后双向 BFS 找最短编辑脚本中点（heuristic 关闭）."""
    fd, bd, off = ctxt.fd, ctxt.bd, ctxt.off
    xvec, yvec = ctxt.xvec, ctxt.yvec

    dmin = xoff - ylim
    dmax = xlim - yoff
    fmid = xoff - yoff
    bmid = xlim - ylim
    fmin = fmax = fmid
    bmin = bmax = bmid
    odd = (fmid - bmid) & 1

    fd[fmid + off] = xoff
    bd[bmid + off] = xlim

    c = 1
    while True:
        # --- 前向搜索扩展一步 ---
        if fmin > dmin:
            fmin -= 1
            fd[fmin - 1 + off] = -1
        else:
            fmin += 1
        if fmax < dmax:
            fmax += 1
            fd[fmax + 1 + off] = -1
        else:
            fmax -= 1
        d = fmax
        while d >= fmin:
            tlo = fd[d - 1 + off]
            thi = fd[d + 1 + off]
            x0 = thi if tlo < thi else tlo + 1
            x = x0
            y = x0 - d
            while x < xlim and y < ylim and xvec[x] == yvec[y]:
                x += 1
                y += 1
            fd[d + off] = x
            if odd and bmin <= d <= bmax and bd[d + off] <= x:
                return x, y, True, True
            d -= 2

        # --- 后向搜索扩展一步 ---
        if bmin > dmin:
            bmin -= 1
            bd[bmin - 1 + off] = _OFFSET_MAX
        else:
            bmin += 1
        if bmax < dmax:
            bmax += 1
            bd[bmax + 1 + off] = _OFFSET_MAX
        else:
            bmax -= 1
        d = bmax
        while d >= bmin:
            tlo = bd[d - 1 + off]
            thi = bd[d + 1 + off]
            x0 = tlo if tlo < thi else thi - 1
            x = x0
            y = x0 - d
            while xoff < x and yoff < y and xvec[x - 1] == yvec[y - 1]:
                x -= 1
                y -= 1
            bd[d + off] = x
            if (not odd) and fmin <= d <= fmax and x <= fd[d + off]:
                return x, y, True, True
            d -= 2

        if find_minimal:
            c += 1
            continue

        # heuristic (speed_large_files) 关闭 -> big_snake 分支为死代码

        # too_expensive 兜底：取进展最大的对角线
        if c >= ctxt.too_expensive:
            fxybest = -1
            fxbest = 0
            d = fmax
            while d >= fmin:
                x = fd[d + off]
                if x > xlim:
                    x = xlim
                y = x - d
                if y > ylim:
                    x = ylim + d
                    y = ylim
                if fxybest < x + y:
                    fxybest = x + y
                    fxbest = x
                d -= 2
            bxybest = _OFFSET_MAX
            bxbest = 0
            d = bmax
            while d >= bmin:
                x = bd[d + off]
                if x < xoff:
                    x = xoff
                y = x - d
                if y < yoff:
                    x = yoff + d
                    y = yoff
                if x + y < bxybest:
                    bxybest = x + y
                    bxbest = x
                d -= 2
            if (xlim + ylim) - bxybest < fxybest - (xoff + yoff):
                return fxbest, fxybest - fxbest, True, False
            else:
                return bxbest, bxybest - bxbest, False, True
        c += 1


def _compareseq(xoff, xlim, yoff, ylim, find_minimal, ctxt, f0, f1):
    """diffseq.h compareseq（NOTE_DELETE/NOTE_INSERT 落到 changed 数组）."""
    while True:
        # 底部初始对角线滑动
        while xoff < xlim and yoff < ylim and \
                ctxt.xvec[xoff] == ctxt.yvec[yoff]:
            xoff += 1
            yoff += 1
        # 顶部初始对角线滑动
        while xoff < xlim and yoff < ylim and \
                ctxt.xvec[xlim - 1] == ctxt.yvec[ylim - 1]:
            xlim -= 1
            ylim -= 1
        # 简单情形
        if xoff == xlim:
            while yoff < ylim:
                f1.changed[f1.realindexes[yoff]] = 1
                yoff += 1
            return
        if yoff == ylim:
            while xoff < xlim:
                f0.changed[f0.realindexes[xoff]] = 1
                xoff += 1
            return

        xmid, ymid, lo_minimal, hi_minimal = \
            _diag(xoff, xlim, yoff, ylim, find_minimal, ctxt)

        # NOTE_ORDERED == 0：较小子问题先做（减轻递归）
        if ((xlim + ylim) - (xmid + ymid)
                < (xmid + ymid) - (xoff + yoff)):
            # 第二子问题（右上半）先做
            _compareseq(xmid, xlim, ymid, ylim, hi_minimal, ctxt, f0, f1)
            xlim, ylim = xmid, ymid
            find_minimal = lo_minimal
            # 迭代处理第一子问题（左下半）
        else:
            _compareseq(xoff, xmid, yoff, ymid, lo_minimal, ctxt, f0, f1)
            xoff, yoff = xmid, ymid
            find_minimal = hi_minimal
            # 迭代处理第二子问题


def _shift_boundaries(f0, f1):
    """analyze.c shift_boundaries：把变更区域尽量对齐/合并."""
    for f, other in ((f0, f1), (f1, f0)):
        changed = f.changed
        other_changed = other.changed
        equivs = f.equivs
        i = 0
        j = 0
        i_end = f.buffered_lines

        def ch(arr, k):
            # 带哨兵读写：C 的 changed 数组前后各有一个 0 哨兵
            if 0 <= k < len(arr) - 1:
                return arr[k]
            return 0

        while True:
            # 前扫找下一个变更 run 的起点
            while i < i_end and not changed[i]:
                while ch(other_changed, j):
                    j += 1
                j += 1
                i += 1
            if i == i_end:
                break
            start = i

            # 找 run 终点
            i += 1
            while ch(changed, i):
                i += 1
            while ch(other_changed, j):
                j += 1

            while True:
                runlength = i - start

                # 后向合并：前一未变行 == run 尾行
                while start and equivs[start - 1] == equivs[i - 1]:
                    start -= 1
                    changed[start] = 1
                    i -= 1
                    changed[i] = 0
                    while ch(changed, start - 1):
                        start -= 1
                    j -= 1
                    while ch(other_changed, j):
                        j -= 1

                corresponding = i if ch(other_changed, j - 1) else i_end

                # 前向合并：run 首行 == 后一未变行
                while i != i_end and equivs[start] == equivs[i]:
                    changed[start] = 0
                    start += 1
                    changed[i] = 1
                    i += 1
                    while ch(changed, i):
                        i += 1
                    j += 1
                    while ch(other_changed, j):
                        corresponding = i
                        j += 1

                if runlength == i - start:
                    break

            # 把完全合并的 run 后移到对方文件的对应 run
            while corresponding < i:
                start -= 1
                changed[start] = 1
                i -= 1
                changed[i] = 0
                j -= 1
                while ch(other_changed, j):
                    j -= 1


def _build_script(f0, f1):
    """analyze.c build_script：changed 表 -> 升序编辑脚本.

    返回 [(line0, line1, deleted, inserted), ...]（升序）。
    """
    ch0, ch1 = f0.changed, f1.changed
    len0, len1 = f0.buffered_lines, f1.buffered_lines

    def ch(arr, k):
        if 0 <= k < len(arr) - 1:
            return arr[k]
        return 0

    script = []
    i0, i1 = len0, len1
    while i0 >= 0 or i1 >= 0:
        if ch(ch0, i0 - 1) or ch(ch1, i1 - 1):
            line0, line1 = i0, i1
            while ch(ch0, i0 - 1):
                i0 -= 1
            while ch(ch1, i1 - 1):
                i1 -= 1
            script.append((i0, i1, line0 - i0, line1 - i1))
        i0 -= 1
        i1 -= 1
    script.reverse()  # 倒序扫描 + 前插 == append + reverse -> 升序
    return script


def _analyze_hunk(hunk_changes):
    """util.c analyze_hunk（无 ignore 选项 -> trivial 恒 False）.

    返回 (first0, last0, first1, last1) 或 None（无实际变更）。
    """
    first0 = hunk_changes[0][0]
    first1 = hunk_changes[0][1]
    last0 = first0
    last1 = first1
    show_from = 0
    show_to = 0
    for (l0, l1, deleted, inserted) in hunk_changes:
        last0 = l0 + deleted - 1
        last1 = l1 + inserted - 1
        show_from += deleted
        show_to += inserted
    if show_from == 0 and show_to == 0:
        return None
    return first0, last0, first1, last1


def _find_hunk(script, start):
    """context.c find_hunk（ignore 恒 False -> thresh 恒 2*context+1）.

    返回 hunk 最后一个 change 的下标（含）。
    """
    pos = start
    while True:
        top0 = script[pos][0] + script[pos][2]
        top1 = script[pos][1] + script[pos][3]
        prev = pos
        pos += 1
        has_next = pos < len(script)
        if has_next:
            nxt = script[pos]
            if nxt[0] - top0 != nxt[1] - top1:
                raise AssertionError("find_hunk: gap mismatch")
            if nxt[0] - top0 < 2 * CONTEXT + 1:
                continue
        return prev


def _print_unidiff_number_range(f, a, b):
    """util.c print_unidiff_number_range + translate_range + translate_line_number.

    translate_line_number(file, i) = i + prefix_lines + 1（1-origin）；
    translate_range: trans_a = translate(a-1)+1, trans_b = translate(b+1)-1。
    """
    trans_a = (a - 1) + f.prefix_lines + 1 + 1   # = a + prefix_lines + 1
    trans_b = (b + 1) + f.prefix_lines + 1 - 1   # = b + prefix_lines + 1
    if trans_b <= trans_a:
        if trans_b < trans_a:
            return b"%d,0" % trans_b
        return b"%d" % trans_a
    return b"%d,%d" % (trans_a, trans_b - trans_a + 1)


def _pr_unidiff_hunk(f0, f1, hunk_changes, out):
    """context.c pr_unidiff_hunk：格式化输出一个 hunk."""
    analyzed = _analyze_hunk(hunk_changes)
    if analyzed is None:
        return False
    first0, last0, first1, last1 = analyzed

    # 上下文扩展 + 钳制
    i = -f0.prefix_lines
    first0 = max(first0 - CONTEXT, i)
    first1 = max(first1 - CONTEXT, i)
    if last0 < f0.valid_lines - CONTEXT:
        last0 += CONTEXT
    else:
        last0 = f0.valid_lines - 1
    if last1 < f1.valid_lines - CONTEXT:
        last1 += CONTEXT
    else:
        last1 = f1.valid_lines - 1

    out.append(b"@@ -")
    out.append(_print_unidiff_number_range(f0, first0, last0))
    out.append(b" +")
    out.append(_print_unidiff_number_range(f1, first1, last1))
    out.append(b" @@\n")

    p0 = f0.prefix_lines   # C 行索引 -> 全文件行号偏移
    p1 = f1.prefix_lines

    def emit(flag, f, g):
        """输出一行：flag + ' ' + 文本 + 尾部处理（print_1_line_nl 语义）."""
        out.append(flag)
        out.append(f.lines[g])
        if f.line_has_nl(g):
            out.append(b"\n")
        else:
            out.append(b"\n\\ No newline at end of file\n")

    idx = 0
    i, j = first0, first1
    while i <= last0 or j <= last1:
        if idx >= len(hunk_changes) or i < hunk_changes[idx][0]:
            # 上下文行
            emit(b" ", f0, p0 + i)
            i += 1
            j += 1
        else:
            (l0, l1, deleted, inserted) = hunk_changes[idx]
            idx += 1
            for _ in range(deleted):
                emit(b"-", f0, p0 + i)
                i += 1
            for _ in range(inserted):
                emit(b"+", f1, p1 + j)
                j += 1
    return True


def unified_diff_bytes(data0, data1, name0=b"a", name1=b"b"):
    """生成 GNU diff -u 等价的 unified diff（bytes）.

    data0/data1: 原始文件字节；name0/name1: 头两行的文件名。
    两文件完全相同 -> 返回 b""（no_diff_means_no_output）。
    """
    f0 = _FileVec(data0)
    f1 = _FileVec(data1)

    # 1. 前后缀
    _find_identical_ends(f0, f1)

    # 2. 等价类（跨文件共享）
    class_map = {}
    _find_equiv_classes(f0, f1, class_map)

    # 3. discard_confusing_lines
    _discard_confusing_lines(f0, f1)

    # 4. 主比较算法（undiscarded 上跑 diag/compareseq）
    len0 = f0.nondiscarded_lines
    len1 = f1.nondiscarded_lines
    diags = len0 + len1 + 3
    ctxt = _DiagContext()
    ctxt.xvec = f0.undiscarded
    ctxt.yvec = f1.undiscarded
    size = diags + 4
    ctxt.fd = [0] * size
    ctxt.bd = [0] * size
    ctxt.off = len1 + 1
    too_expensive = 1
    d = diags
    while d != 0:
        too_expensive <<= 1
        d >>= 2
    ctxt.too_expensive = max(4096, too_expensive)

    if len0 or len1:
        _compareseq(0, len0, 0, len1, False, ctxt, f0, f1)

    # 5. shift_boundaries
    _shift_boundaries(f0, f1)

    # 6. 编辑脚本
    script = _build_script(f0, f1)

    # 7. 输出（print_script + find_hunk + pr_unidiff_hunk）
    if not script:
        return b""
    out = [b"--- ", name0, b"\n+++ ", name1, b"\n"]
    pos = 0
    while pos < len(script):
        end = _find_hunk(script, pos)
        _pr_unidiff_hunk(f0, f1, script[pos:end + 1], out)
        pos = end + 1
    return b"".join(out)

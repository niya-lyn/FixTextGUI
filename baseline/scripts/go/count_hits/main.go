// count_hits —— T0.4 回归基线集的「替换计数」度量工具（基线度量，非新引擎）
//
// 语义与上游 src/tools/replace_by_go.go 保持一致：
//   - 规则对按 before.json / after.json 的给定顺序进入替换器；
//   - 重复 before 取「先出现」的那条（Go strings.NewReplacer 的 trie 语义：先写入者优先）；
//   - 匹配为「最左、最长匹配」，命中后从替换结果之后继续；
//   - 整体执行 count 轮（生产口径 count=2）。
// 本工具在同样的规则上重放替换并统计每条规则的命中次数；
// 其替换结果必须与上游 replace_by_go 的输出逐字节一致（由基线构建脚本交叉校验）。
//
// 用法：
//   count_hits <替换前.json> <替换后.json> <目标文件> <替换次数> [统计输出.json]
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "错误: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) < 5 || len(os.Args) > 6 {
		fmt.Fprintln(os.Stderr, "用法: count_hits <替换前.json> <替换后.json> <目标文件> <替换次数> [统计输出.json]")
		return fmt.Errorf("参数数量错误")
	}
	count, err := strconv.Atoi(os.Args[4])
	if err != nil || count <= 0 {
		return fmt.Errorf("替换次数必须是正整数: %q", os.Args[4])
	}

	before, err := loadJSONArray(os.Args[1])
	if err != nil {
		return err
	}
	after, err := loadJSONArray(os.Args[2])
	if err != nil {
		return err
	}
	if len(before) != len(after) {
		return fmt.Errorf("规则数量不匹配: 替换前=%d 替换后=%d", len(before), len(after))
	}

	raw, err := os.ReadFile(os.Args[3])
	if err != nil {
		return err
	}
	inBytes := len(raw)

	// 规则索引：重复 before 取先出现者（与 Go trie 一致）
	rules := make(map[string]string, len(before))
	ruleOrder := 0
	for i := range before {
		if _, ok := rules[before[i]]; ok {
			continue
		}
		rules[before[i]] = after[i]
		ruleOrder++
	}

	// 按字节长度分桶 + 首字节可命中标记
	byLen := make(map[int]map[string]string)
	lead := make(map[byte]bool)
	for k, v := range rules {
		l := len(k)
		if byLen[l] == nil {
			byLen[l] = make(map[string]string)
		}
		byLen[l][k] = v
		lead[k[0]] = true
	}
	lens := make([]int, 0, len(byLen))
	for l := range byLen {
		lens = append(lens, l)
	}
	sort.Sort(sort.Reverse(sort.IntSlice(lens)))

	hits := make(map[string]int)
	passHits := make([]int, count)
	text := string(raw)
	for p := 0; p < count; p++ {
		var sb strings.Builder
		sb.Grow(len(text))
		applied := applyPass(text, byLen, lens, lead, rules, hits, &sb)
		passHits[p] = applied
		text = sb.String()
	}

	distinct, total := 0, 0
	for _, c := range hits {
		distinct++
		total += c
	}
	type kv struct {
		Before string `json:"before"`
		After  string `json:"after"`
		Hits   int    `json:"hits"`
	}
	top := make([]kv, 0, 24)
	for b, c := range hits {
		top = append(top, kv{Before: b, After: rules[b], Hits: c})
	}
	sort.Slice(top, func(i, j int) bool {
		if top[i].Hits != top[j].Hits {
			return top[i].Hits > top[j].Hits
		}
		return top[i].Before < top[j].Before
	})
	if len(top) > 24 {
		top = top[:24]
	}

	stat := map[string]any{
		"file":           os.Args[3],
		"in_bytes":       inBytes,
		"out_bytes":      len(text),
		"passes":         count,
		"hits_per_pass":  passHits,
		"replacements":   total,
		"distinct_rules": distinct,
		"rules_total":    ruleOrder,
		"top_rules":      top,
	}
	out, err := json.MarshalIndent(stat, "", "  ")
	if err != nil {
		return err
	}
	if len(os.Args) == 6 {
		if err := os.WriteFile(os.Args[5], out, 0644); err != nil {
			return err
		}
	}
	fmt.Println(string(out))
	if err := os.WriteFile(os.Args[3], []byte(text), 0644); err != nil {
		return err
	}
	return nil
}

// applyPass 走一遍「最左、最长匹配」替换：统计命中并生成替换后文本。
func applyPass(text string, byLen map[int]map[string]string, lens []int, lead map[byte]bool,
	rules map[string]string, hits map[string]int, sb *strings.Builder) int {
	applied := 0
	i, n := 0, len(text)
	for i < n {
		if !lead[text[i]] {
			_, size := utf8.DecodeRuneInString(text[i:])
			sb.WriteString(text[i : i+size])
			i += size
			continue
		}
		matched := false
		for _, l := range lens {
			if i+l > n {
				continue
			}
			seg := text[i : i+l]
			if v, ok := byLen[l][seg]; ok {
				sb.WriteString(v)
				hits[seg]++
				applied++
				i += l
				matched = true
				break
			}
		}
		if matched {
			continue
		}
		_, size := utf8.DecodeRuneInString(text[i:])
		sb.WriteString(text[i : i+size])
		i += size
	}
	return applied
}

func loadJSONArray(filename string) ([]string, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}
	var arr []string
	if err := json.Unmarshal(data, &arr); err != nil {
		return nil, fmt.Errorf("JSON 解析失败: %w", err)
	}
	return arr, nil
}

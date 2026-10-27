package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// 使用说明
const usage = `用法: %s <目标文件> <替换前.json> <替换后.json> <替换次数>

参数说明:
  目标文件      需要进行文本替换的文件
  替换前.json   包含原始文本的 JSON 数组文件
  替换后.json   包含目标文本的 JSON 数组文件
  替换次数      执行替换的次数（正整数）

示例:
  %s input.txt before.json after.json 3
`

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "错误: %v\n", err)
		os.Exit(1)
	}
}

// run 主逻辑入口
func run() error {
	// 解析命令行参数
	config, err := parseArgs()
	if err != nil {
		return err
	}

	// 加载替换规则
	rules, err := loadRules(config.beforeFile, config.afterFile)
	if err != nil {
		return fmt.Errorf("加载规则失败: %w", err)
	}

	// 读取目标文件
	content, err := os.ReadFile(config.targetFile)
	if err != nil {
		return fmt.Errorf("读取文件失败: %w", err)
	}

	// 执行替换
	result := applyReplacements(string(content), rules, config.count)

	// 写回文件
	if err := os.WriteFile(config.targetFile, []byte(result), 0644); err != nil {
		return fmt.Errorf("写入文件失败: %w", err)
	}

	fmt.Printf("✓ 替换完成，共执行 %d 次替换\n", config.count)
	return nil
}

// Config 存储命令行配置
type Config struct {
	targetFile string // 目标文件路径
	beforeFile string // 替换前规则文件
	afterFile  string // 替换后规则文件
	count      int    // 替换次数
}

// Rule 表示单条替换规则
type Rule struct {
	Before string // 原始文本
	After  string // 目标文本
}

// parseArgs 解析并验证命令行参数
func parseArgs() (*Config, error) {
	if len(os.Args) != 5 {
		fmt.Fprintf(os.Stderr, usage, os.Args[0], os.Args[0])
		return nil, fmt.Errorf("参数数量错误，需要 4 个参数")
	}

	count, err := strconv.Atoi(os.Args[4])
	if err != nil {
		return nil, fmt.Errorf("替换次数必须是整数: %q", os.Args[4])
	}
	if count <= 0 {
		return nil, fmt.Errorf("替换次数必须为正整数，当前: %d", count)
	}

	return &Config{
		targetFile: os.Args[1],
		beforeFile: os.Args[2],
		afterFile:  os.Args[3],
		count:      count,
	}, nil
}

// loadRules 从 JSON 文件加载替换规则
func loadRules(beforeFile, afterFile string) ([]Rule, error) {
	// 读取替换前规则
	beforeArr, err := loadJSONArray(beforeFile)
	if err != nil {
		return nil, fmt.Errorf("读取替换前规则: %w", err)
	}

	// 读取替换后规则
	afterArr, err := loadJSONArray(afterFile)
	if err != nil {
		return nil, fmt.Errorf("读取替换后规则: %w", err)
	}

	// 验证规则数量匹配
	if len(beforeArr) != len(afterArr) {
		return nil, fmt.Errorf("规则数量不匹配: 替换前=%d, 替换后=%d", len(beforeArr), len(afterArr))
	}

	if len(beforeArr) == 0 {
		return nil, fmt.Errorf("替换规则为空")
	}

	// 组装规则列表
	rules := make([]Rule, len(beforeArr))
	for i := range beforeArr {
		rules[i] = Rule{Before: beforeArr[i], After: afterArr[i]}
	}

	return rules, nil
}

// loadJSONArray 从文件读取 JSON 字符串数组
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

// applyReplacements 执行文本替换
func applyReplacements(content string, rules []Rule, count int) string {
	// 构建替换对 (old1, new1, old2, new2, ...)
	pairs := make([]string, 0, len(rules)*2)
	for _, r := range rules {
		pairs = append(pairs, r.Before, r.After)
	}

	// 创建替换器
	replacer := strings.NewReplacer(pairs...)

	// 按次数执行替换
	result := content
	for i := 0; i < count; i++ {
		result = replacer.Replace(result)
	}

	return result
}

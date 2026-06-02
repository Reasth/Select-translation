"""拉 Vercel 函数日志，把 METRIC 行聚合成「人能扫一眼看完」的小报。

用法:
    python analyze_metrics.py [--since 1d]

约定:
    Vercel Edge 函数每次请求会吐一条以 "METRIC " 开头的 JSON 日志。本脚本调
    `vercel logs translate --json --since <window>` 拉日志、过出 METRIC 行、
    聚合后打印每日翻译量 / eager 命中率 / P50P95 延迟 / 错误率 / 模型分布 /
    客户端版本分布。

依赖:
    - Vercel CLI 已登录 (`vercel login`)
    - 仓库已 link 到 translate 项目（.vercel/project.json 存在）
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections import Counter


METRIC_PREFIX = "METRIC "


def fetch_logs(since: str) -> str:
    cmd = ["vercel", "logs", "translate", "--json", "--since", since]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError:
        print("ERROR: 找不到 vercel CLI。先 `npm i -g vercel` 或 `winget install Vercel.Vercel`。", file=sys.stderr)
        sys.exit(2)
    except subprocess.TimeoutExpired:
        print("ERROR: `vercel logs` 超时。换更短的 --since 或检查网络。", file=sys.stderr)
        sys.exit(2)
    if result.returncode != 0:
        print(f"ERROR: vercel logs 返回 {result.returncode}\n{result.stderr[:400]}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout


def parse_metrics(raw_output: str) -> list[dict]:
    """从 vercel logs --json 输出里挑出 METRIC 事件。

    vercel 的 --json 每行是一个 log entry,字段里有 `message` 装实际打印内容。
    我们要的 METRIC 行,message 形如 "METRIC {json...}"。
    """
    metrics: list[dict] = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # 有时 stdout 也会直接出未包装的 METRIC 行
            if line.startswith(METRIC_PREFIX):
                try:
                    metrics.append(json.loads(line[len(METRIC_PREFIX):]))
                except json.JSONDecodeError:
                    pass
            continue
        msg = entry.get("message") or entry.get("text") or ""
        if not isinstance(msg, str):
            continue
        if msg.startswith(METRIC_PREFIX):
            try:
                metrics.append(json.loads(msg[len(METRIC_PREFIX):]))
            except json.JSONDecodeError:
                pass
    return metrics


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[idx]


def summarize(metrics: list[dict]) -> str:
    if not metrics:
        return "（窗口内没有 METRIC 事件。可能时间窗太短，或代理还未被调用过。）"

    total = len(metrics)
    ok = [m for m in metrics if int(m.get("status", 0)) < 400]
    errs = [m for m in metrics if int(m.get("status", 0)) >= 400]
    eager = [m for m in metrics if m.get("source") == "eager"]
    click = [m for m in metrics if m.get("source") == "click"]
    unknown_source = [m for m in metrics if m.get("source") not in {"eager", "click"}]
    durations = [int(m["duration_ms"]) for m in ok if "duration_ms" in m]
    out_bytes = [int(m["output_bytes"]) for m in ok if "output_bytes" in m]
    in_chars = [int(m["input_chars"]) for m in ok if "input_chars" in m]

    models = Counter(m.get("model", "unknown") for m in metrics)
    clients = Counter(m.get("client", "unknown") for m in metrics)
    thinking = Counter(m.get("thinking", "unknown") for m in metrics)
    error_types = Counter(m.get("error", "") for m in errs if m.get("error"))

    lines = []
    lines.append("=" * 64)
    lines.append("Translate-popup METRIC 小报")
    lines.append("=" * 64)
    lines.append(f"总请求      : {total}    (成功 {len(ok)}  /  失败 {len(errs)})")
    if total:
        lines.append(f"错误率      : {len(errs) / total:.1%}")
    lines.append("")
    lines.append("— 触发来源 —")
    lines.append(f"  eager     : {len(eager)}")
    lines.append(f"  click     : {len(click)}")
    if unknown_source:
        lines.append(f"  其它/旧版 : {len(unknown_source)}")
    if eager and (eager or click):
        ratio = len(eager) / (len(eager) + len(click)) if (eager or click) else 0
        lines.append(f"  eager 占比: {ratio:.1%}    （越高说明用户越习惯划完就点）")
    lines.append("")
    if durations:
        lines.append("— 延迟（仅成功请求，单位 ms） —")
        lines.append(f"  P50: {percentile(durations, 50):>6}    "
                     f"P95: {percentile(durations, 95):>6}    "
                     f"max: {max(durations):>6}")
    if out_bytes:
        lines.append("— 上游输出（字节，毛估等价于 token×3） —")
        lines.append(f"  P50: {percentile(out_bytes, 50):>6}    "
                     f"P95: {percentile(out_bytes, 95):>6}    "
                     f"总计: {sum(out_bytes):>8}")
    if in_chars:
        lines.append("— 输入文本（messages 序列化字符） —")
        lines.append(f"  P50: {percentile(in_chars, 50):>6}    "
                     f"P95: {percentile(in_chars, 95):>6}")
    lines.append("")
    lines.append("— 模型分布 —")
    for name, cnt in models.most_common():
        lines.append(f"  {name:<28} {cnt}")
    lines.append("")
    lines.append("— Thinking 模式 —")
    for name, cnt in thinking.most_common():
        lines.append(f"  {name:<28} {cnt}")
    lines.append("")
    lines.append("— 客户端版本 —")
    for name, cnt in clients.most_common():
        lines.append(f"  {name:<28} {cnt}")
    if error_types:
        lines.append("")
        lines.append("— 错误类型 —")
        for name, cnt in error_types.most_common():
            lines.append(f"  {name:<28} {cnt}")
    lines.append("=" * 64)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="把代理的 METRIC 日志聚合成小报。")
    ap.add_argument("--since", default="1d",
                    help="时间窗。支持 vercel logs 的语法，例 1h / 6h / 1d / 7d。默认 1d。")
    ap.add_argument("--raw", action="store_true",
                    help="只打印解析出的 METRIC JSON 行，不做聚合。")
    args = ap.parse_args()

    raw = fetch_logs(args.since)
    metrics = parse_metrics(raw)

    if args.raw:
        for m in metrics:
            print(json.dumps(m, ensure_ascii=False))
        return

    print(summarize(metrics))


if __name__ == "__main__":
    main()

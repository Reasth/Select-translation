"""把 Supabase events 表里的埋点折成「人能扫一眼看完」的小报。

用法:
    python analyze_metrics.py [--since 1d]

依赖配置(任选其一):
    1. 环境变量:SUPABASE_URL + SUPABASE_ANON_KEY
    2. 项目根目录的 `.env.local`(gitignore;`vercel env pull .env.local` 一键拉到本地)

口径:
    - metric 行:代理端每次翻译请求一条(event="metric")
    - 客户端事件:app_start / icon_shown / icon_clicked / eager_* / popup_* / settings_* / tray_*
    - DAU = 24h 内不同 install_id 数
    - eager 命中率 = eager_adopted / eager_started
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PAGE_SIZE = 1000     # Supabase 默认上限,翻页拉
MAX_PAGES = 20       # 安全上限,避免无限拉(=2 万行)


def load_dotenv(path: str = ".env.local") -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def parse_since(spec: str) -> str:
    """`1d` / `6h` / `30m` → 当前时刻减去这个间隔的 ISO 时间戳(UTC)。"""
    m = re.fullmatch(r"(\d+)\s*([smhd])", spec.strip().lower())
    if not m:
        raise SystemExit(f"--since 格式不对: {spec!r}(应该是 30m / 6h / 1d 这类)")
    n, unit = int(m.group(1)), m.group(2)
    delta = {"s": timedelta(seconds=n), "m": timedelta(minutes=n),
             "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    return (datetime.now(timezone.utc) - delta).isoformat()


def fetch_events(url: str, key: str, since_iso: str) -> list[dict]:
    """翻页拉 events,按 ts 倒序,过滤 ts >= since。"""
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        q = urllib.parse.urlencode({
            "select": "*",
            "ts": f"gte.{since_iso}",
            "order": "ts.desc",
            "limit": str(PAGE_SIZE),
            "offset": str(offset),
        }, safe="")
        req = urllib.request.Request(
            f"{url}/rest/v1/events?{q}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                batch = json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"ERROR: Supabase {e.code}: {e.read()[:200].decode('utf-8', 'ignore')}")
        except urllib.error.URLError as e:
            sys.exit(f"ERROR: 网络错误: {e.reason}")
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return rows


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))]


def summarize(rows: list[dict], since_iso: str) -> str:
    if not rows:
        return f"窗口内({since_iso} 起)没有任何事件。代理/客户端还没上 1.2 版,或者没人用。"

    proxy = [r for r in rows if r.get("origin") == "proxy"]
    client = [r for r in rows if r.get("origin") == "client"]
    metric = [r for r in rows if r.get("event") == "metric"]
    events_by_name = Counter(r.get("event", "?") for r in client)

    # 翻译延迟 / 字节(从 props 里挖)
    durations: list[int] = []
    out_bytes: list[int] = []
    in_chars: list[int] = []
    statuses: Counter = Counter()
    sources: Counter = Counter()
    models: Counter = Counter()
    thinking: Counter = Counter()
    for m in metric:
        p = m.get("props") or {}
        if isinstance(p.get("duration_ms"), int):
            durations.append(p["duration_ms"])
        if isinstance(p.get("output_bytes"), int):
            out_bytes.append(p["output_bytes"])
        if isinstance(p.get("input_chars"), int):
            in_chars.append(p["input_chars"])
        statuses[p.get("status", "?")] += 1
        sources[p.get("source", "unknown")] += 1
        models[m.get("props", {}).get("model", "?")] += 1
        thinking[p.get("thinking", "?")] += 1

    # 用户层
    install_ids = {r.get("install_id") for r in rows if r.get("install_id")}
    session_ids = {r.get("session_id") for r in rows if r.get("session_id")}
    clients = Counter(r.get("client", "unknown") for r in rows)

    # Eager 漏斗
    eager_started = events_by_name.get("eager_started", 0)
    eager_adopted = events_by_name.get("eager_adopted", 0)
    eager_completed = events_by_name.get("eager_completed", 0)
    eager_cancelled = events_by_name.get("eager_cancelled", 0)

    lines: list[str] = []
    bar = "=" * 64
    lines.append(bar)
    lines.append(f"Translate-popup 埋点小报      窗口:{since_iso} 起")
    lines.append(bar)
    lines.append(f"总事件         : {len(rows)}    (proxy {len(proxy)}  /  client {len(client)})")
    lines.append(f"独立 install   : {len(install_ids)}    独立 session: {len(session_ids)}")
    lines.append("")
    lines.append("─ 代理(metric) ─")
    if metric:
        ok = sum(1 for s in statuses if isinstance(s, int) and s < 400 for _ in range(statuses[s]))
        ok_count = sum(c for s, c in statuses.items() if isinstance(s, int) and s < 400)
        err_count = sum(c for s, c in statuses.items() if isinstance(s, int) and s >= 400)
        unknown_count = sum(c for s, c in statuses.items() if not isinstance(s, int))
        lines.append(f"  请求         : {len(metric)}    成功 {ok_count}   失败 {err_count}   未知 {unknown_count}")
        if durations:
            lines.append(f"  延迟 ms      : P50 {percentile(durations,50)}    P95 {percentile(durations,95)}    max {max(durations)}")
        if out_bytes:
            lines.append(f"  输出 bytes   : P50 {percentile(out_bytes,50)}    P95 {percentile(out_bytes,95)}    总和 {sum(out_bytes)}")
        if in_chars:
            lines.append(f"  输入 chars   : P50 {percentile(in_chars,50)}    P95 {percentile(in_chars,95)}")
        lines.append("  source 分布  : " + ", ".join(f"{k}={v}" for k, v in sources.most_common()))
        lines.append("  model 分布   : " + ", ".join(f"{k}={v}" for k, v in models.most_common()))
        lines.append("  thinking     : " + ", ".join(f"{k}={v}" for k, v in thinking.most_common()))
    else:
        lines.append("  (无)")
    lines.append("")
    lines.append("─ Eager 漏斗 ─")
    lines.append(f"  started      : {eager_started}")
    lines.append(f"  adopted      : {eager_adopted}    命中率: {eager_adopted/eager_started:.1%}" if eager_started else "  adopted      : 0")
    lines.append(f"  completed    : {eager_completed}")
    lines.append(f"  cancelled    : {eager_cancelled}    浪费率: {eager_cancelled/eager_started:.1%}" if eager_started else "  cancelled    : 0")
    lines.append("")
    lines.append("─ 客户端事件分布 ─")
    for ev, cnt in events_by_name.most_common(20):
        lines.append(f"  {ev:<24} {cnt}")
    lines.append("")
    lines.append("─ 客户端版本 ─")
    for c, cnt in clients.most_common():
        lines.append(f"  {c:<24} {cnt}")
    lines.append(bar)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="把 Supabase events 表折成小报。")
    ap.add_argument("--since", default="1d", help="时间窗。30m / 6h / 1d / 7d。默认 1d。")
    ap.add_argument("--raw", action="store_true", help="打印原始 JSON 行,不聚合。")
    args = ap.parse_args()

    env = {**load_dotenv(), **os.environ}  # 环境变量优先级高于 .env.local
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_ANON_KEY")
    if not url or not key:
        print("ERROR: 缺 SUPABASE_URL / SUPABASE_ANON_KEY。\n"
              "       本地一次:`vercel env pull .env.local` 把 Vercel 上的环境变量拉下来。",
              file=sys.stderr)
        sys.exit(2)

    since_iso = parse_since(args.since)
    rows = fetch_events(url.rstrip("/"), key, since_iso)
    if args.raw:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return
    print(summarize(rows, since_iso))


if __name__ == "__main__":
    main()

/**
 * OpenAI 兼容的 MiniMax 代理 —— 部署在 Vercel Edge。
 *
 * 客户端把请求打到本端点（base_url = .../api/v1，路径 /chat/completions），
 * 函数自动注入服务端的 MINIMAX_API_KEY，并转发到国内端点 api.minimaxi.com。
 * Key 全程不离开服务端。
 *
 * 最小防护：
 *  - 只放行 chat 模型白名单（防止被借道跑文生图/视频等贵接口）
 *  - 限制 max_tokens 上限（防一次烧爆）
 *  - 限制输入总字符（防长 prompt 攻击）
 *  - 透传 stream，让 SSE 流式正常工作
 *
 * 埋点：每次请求收尾都吐一条 "METRIC <json>" 到 stdout，含
 * model / input_chars / output_bytes / duration_ms / thinking / source /
 * client / status。本地 `vercel logs translate --json` 可拉取，配合
 * analyze_metrics.py 出每日量、eager 命中率、P50/P95 延迟、错误率。
 */

import { writeEvent } from '../../_supabase.mjs';

// 上游是 api.minimaxi.com（中国大陆），固定到 Tokyo edge 以缩短回程跳数。
// Vercel 默认全球边缘自动调度，从美西 edge 回上游要绕大半圈，可省 100-200ms。
export const config = { runtime: 'edge', regions: ['hnd1'] };

const UPSTREAM = 'https://api.minimaxi.com/v1/chat/completions';

const ALLOWED_MODELS = new Set([
  'MiniMax-M3',
  'MiniMax-M2.7',
  'MiniMax-M2.7-highspeed',
  'MiniMax-M2.5',
  'MiniMax-M2.5-highspeed',
  'MiniMax-M2.1',
  'MiniMax-M2.1-highspeed',
  'MiniMax-M2',
]);

const MAX_INPUT_CHARS = 12000; // messages 序列化后的字符上限
const MAX_TOKENS_CAP = 4096;   // 单次最多生成 token
// Vercel Hobby Edge 函数硬限制 ~25s，留点 buffer 主动 abort 比被 runtime 切断错误信息更好。
const UPSTREAM_TIMEOUT_MS = 22_000;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Client, X-Source, X-Install-Id, X-Session-Id',
};

function jsonError(status, message) {
  return new Response(JSON.stringify({ error: { message } }), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

function emitMetric(tags, extra) {
  // 双写:console.log（短期排错）+ Supabase events 表（持久化,满足安哥「不是 stdout」要求）。
  // 返回 Promise,让调用方可以 await——fire-and-forget 在 Edge runtime 会被 worker 回收吞掉。
  const props = { source: tags.source, ...extra };
  try {
    console.log('METRIC ' + JSON.stringify({
      ts: new Date().toISOString(),
      client: tags.client,
      ...props,
    }));
  } catch {}
  return writeEvent({
    origin: 'proxy',
    install_id: tags.install_id || null,
    session_id: tags.session_id || null,
    client: tags.client,
    event: 'metric',
    props,
  });
}

function readClientTags(req) {
  return {
    client: req.headers.get('x-client') || 'unknown',
    source: req.headers.get('x-source') || 'unknown',
    install_id: req.headers.get('x-install-id') || null,
    session_id: req.headers.get('x-session-id') || null,
  };
}

export default async function handler(req) {
  const t0 = Date.now();
  const tags = readClientTags(req);

  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (req.method !== 'POST') {
    await emitMetric(tags, { status: 405, error: 'method' });
    return jsonError(405, 'method not allowed');
  }

  const key = process.env.MINIMAX_API_KEY;
  if (!key) {
    await emitMetric(tags, { status: 500, error: 'no_key' });
    return jsonError(500, 'server is missing MINIMAX_API_KEY env var');
  }

  let body;
  try {
    body = await req.json();
  } catch {
    await emitMetric(tags, { status: 400, error: 'bad_json' });
    return jsonError(400, 'invalid JSON body');
  }

  if (typeof body !== 'object' || body === null) {
    await emitMetric(tags, { status: 400, error: 'bad_body' });
    return jsonError(400, 'body must be a JSON object');
  }
  if (typeof body.model !== 'string' || !ALLOWED_MODELS.has(body.model)) {
    await emitMetric(tags, { model: body.model, status: 400, error: 'model_blocked' });
    return jsonError(400, 'model not allowed; pick one of the MiniMax chat models');
  }
  if (typeof body.max_tokens === 'number' && body.max_tokens > MAX_TOKENS_CAP) {
    body.max_tokens = MAX_TOKENS_CAP;
  }
  const inputChars = JSON.stringify(body.messages ?? []).length;
  if (inputChars > MAX_INPUT_CHARS) {
    await emitMetric(tags, { model: body.model, input_chars: inputChars, status: 413, error: 'input_too_long' });
    return jsonError(413, `input too long (${inputChars} > ${MAX_INPUT_CHARS} chars)`);
  }

  const thinkingMode = body.thinking?.type || 'default';
  const baseExtra = {
    model: body.model,
    input_chars: inputChars,
    thinking: thinkingMode,
    stream: !!body.stream,
  };

  let upstream;
  try {
    upstream = await fetch(UPSTREAM, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${key}`,
        'Content-Type': 'application/json',
        Accept: body.stream ? 'text/event-stream' : 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (e) {
    await emitMetric(tags, {
      ...baseExtra,
      status: 502,
      duration_ms: Date.now() - t0,
      error: 'upstream_' + (e?.name || 'fetch_failed'),
    });
    return jsonError(502, `upstream fetch failed: ${e?.message ?? e}`);
  }

  // 透传 status + 流式 body，同时用 TransformStream 统计输出字节并在流结束时吐 METRIC。
  const headers = new Headers(CORS);
  const ct = upstream.headers.get('Content-Type');
  if (ct) headers.set('Content-Type', ct);
  headers.set('Cache-Control', 'no-store');

  let outputBytes = 0;
  const counter = new TransformStream({
    transform(chunk, controller) {
      outputBytes += chunk.byteLength;
      controller.enqueue(chunk);
    },
    async flush() {
      // async flush 会让 transform readable 端在 await 完成前不关闭,
      // Vercel Edge runtime 因此会保持函数活到 writeEvent 完成,metric 才不会丢。
      await emitMetric(tags, {
        ...baseExtra,
        status: upstream.status,
        duration_ms: Date.now() - t0,
        output_bytes: outputBytes,
      });
    },
  });

  // 非 200 时上游可能给的是非流式 JSON 错误体；同样让它经过 counter，flush 里会记录 status。
  return new Response(upstream.body.pipeThrough(counter), {
    status: upstream.status,
    headers,
  });
}

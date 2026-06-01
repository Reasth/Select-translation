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
 */

export const config = { runtime: 'edge' };

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
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Client',
};

function jsonError(status, message) {
  return new Response(JSON.stringify({ error: { message } }), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

export default async function handler(req) {
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (req.method !== 'POST') {
    return jsonError(405, 'method not allowed');
  }

  const key = process.env.MINIMAX_API_KEY;
  if (!key) {
    return jsonError(500, 'server is missing MINIMAX_API_KEY env var');
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return jsonError(400, 'invalid JSON body');
  }

  if (typeof body !== 'object' || body === null) {
    return jsonError(400, 'body must be a JSON object');
  }
  if (typeof body.model !== 'string' || !ALLOWED_MODELS.has(body.model)) {
    return jsonError(400, 'model not allowed; pick one of the MiniMax chat models');
  }
  if (typeof body.max_tokens === 'number' && body.max_tokens > MAX_TOKENS_CAP) {
    body.max_tokens = MAX_TOKENS_CAP;
  }
  const inputSize = JSON.stringify(body.messages ?? []).length;
  if (inputSize > MAX_INPUT_CHARS) {
    return jsonError(413, `input too long (${inputSize} > ${MAX_INPUT_CHARS} chars)`);
  }

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
    return jsonError(502, `upstream fetch failed: ${e?.message ?? e}`);
  }

  // 透传 status + 流式 body。Edge runtime 下 upstream.body 是 ReadableStream，
  // 直接交给 new Response 即可保持 SSE 流式。
  const headers = new Headers(CORS);
  const ct = upstream.headers.get('Content-Type');
  if (ct) headers.set('Content-Type', ct);
  headers.set('Cache-Control', 'no-store');

  return new Response(upstream.body, { status: upstream.status, headers });
}

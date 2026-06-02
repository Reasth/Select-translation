/**
 * 客户端埋点事件端点。
 *
 * 客户端 POST 一条事件,服务端注入 Supabase ANON key 落库,
 * 满足安哥「每个交互一条 log + 持久化数据库」的约束。
 *
 * 请求 body 形如:
 *   { "event": "popup_shown" | "settings_opened" | ... ,
 *     "props": { ...任意键值,JSON 可序列化... } }
 *
 * Headers:
 *   X-Client       e.g. "translate-popup/1.1.0"
 *   X-Install-Id   匿名持久 UUID(客户端首次启动生成,落 config.json)
 *   X-Session-Id   每次启动随机 UUID(在内存里)
 *
 * 严格意义上「客户端能 POST 任意事件」=「攻击者也能 POST 任意垃圾」,
 * 所以加最小防护:body 大小、event 名格式、props 是 object。不发 anon key 给客户端,
 * 客户端永远不直连 Supabase,这样 anon key 可以随时在 Vercel 后台轮换。
 */

import { writeEvent } from './_supabase.mjs';

export const config = { runtime: 'edge', regions: ['hnd1'] };

const MAX_BODY_BYTES = 8 * 1024;
const EVENT_NAME_RE = /^[a-z][a-z0-9_]{0,63}$/;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Client, X-Install-Id, X-Session-Id',
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

  // 读 body 时控大小,防被刷垃圾。
  const raw = await req.text();
  if (raw.length > MAX_BODY_BYTES) {
    return jsonError(413, 'event body too large');
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return jsonError(400, 'invalid JSON body');
  }
  if (typeof body !== 'object' || body === null) {
    return jsonError(400, 'body must be a JSON object');
  }

  const event = body.event;
  if (typeof event !== 'string' || !EVENT_NAME_RE.test(event)) {
    return jsonError(400, 'event must be snake_case ([a-z][a-z0-9_]{0,63})');
  }
  const props = body.props && typeof body.props === 'object' && !Array.isArray(body.props)
    ? body.props : {};

  await writeEvent({
    origin: 'client',
    install_id: req.headers.get('x-install-id') || null,
    session_id: req.headers.get('x-session-id') || null,
    client: req.headers.get('x-client') || 'unknown',
    event,
    props,
  });

  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

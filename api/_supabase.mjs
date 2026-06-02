/**
 * Supabase events 表写入封装。
 *
 * 两个 Edge 函数(api/v1/chat/completions.mjs 和 api/event.mjs)共用。
 * 失败永远静默——埋点不能拖垮主请求或事件转发。
 */

const TABLE = 'events';
const WRITE_TIMEOUT_MS = 5_000;

/**
 * 把一行 event 推到 Supabase。
 * @param {object} row - { origin, install_id, session_id, client, event, props }
 *                       ts 由 DB 默认 now() 填，不需要传。
 * @returns {Promise<void>} 失败吞掉
 */
export async function writeEvent(row) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_ANON_KEY;
  if (!url || !key) return;
  try {
    const r = await fetch(`${url}/rest/v1/${TABLE}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: key,
        Authorization: `Bearer ${key}`,
        // return=minimal 让 Supabase 不回传 row,省字节
        Prefer: 'return=minimal',
      },
      body: JSON.stringify(row),
      signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
    });
    if (!r.ok) {
      // 业务路径不抛,但留一条 stderr 行便于 vercel logs 排错
      console.error('SUPABASE_WRITE_FAIL ' + r.status + ' ' + (await r.text()).slice(0, 200));
    }
  } catch (e) {
    console.error('SUPABASE_WRITE_ERR ' + (e?.message || e));
  }
}

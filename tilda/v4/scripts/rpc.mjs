// Minimal JSON-RPC client for the Tilda MCP (key read from ~/.claude.json, never printed).
// Usage as module: import { call } from './rpc.mjs'; await call('tool', {args})
// CLI: node rpc.mjs <tool> '<json args>'  |  node rpc.mjs <tool> @file.json
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const cfg = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.claude.json'), 'utf8')).mcpServers.tilda;
const URL_ = cfg.url, AUTH = cfg.headers.Authorization;
let session = null, nextId = 1;

async function post(body, extra = {}) {
  const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', Authorization: AUTH, ...extra };
  if (session) headers['Mcp-Session-Id'] = session;
  const r = await fetch(URL_, { method: 'POST', headers, body: JSON.stringify(body) });
  const sid = r.headers.get('mcp-session-id');
  if (sid) session = sid;
  const text = await r.text();
  if (!text) return null;
  if ((r.headers.get('content-type') || '').includes('event-stream')) {
    const datas = text.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim());
    return JSON.parse(datas[datas.length - 1]);
  }
  return JSON.parse(text);
}

async function init() {
  if (session) return;
  await post({ jsonrpc: '2.0', id: nextId++, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'gv-rpc', version: '1' } } });
  await post({ jsonrpc: '2.0', method: 'notifications/initialized' }, { 'MCP-Protocol-Version': '2025-06-18' });
}

export async function call(name, args, tries = 3) {
  await init();
  for (let i = 0; ; i++) {
    try {
      const res = await post({ jsonrpc: '2.0', id: nextId++, method: 'tools/call', params: { name, arguments: args } }, { 'MCP-Protocol-Version': '2025-06-18' });
      if (res.error) throw new Error(JSON.stringify(res.error));
      const txt = (res.result.content || []).map((c) => c.text || '').join('');
      if (res.result.isError) throw new Error(txt);
      return txt;
    } catch (e) {
      const m = /"retry_at":(\d+)/.exec(e.message);
      if (m && i < 8) {
        const wait = Math.max(5000, Number(m[1]) * 1000 - Date.now() + 2000);
        console.error('rate limited, waiting ' + Math.round(wait / 1000) + ' s');
        await new Promise((r) => setTimeout(r, wait));
        continue;
      }
      if (i + 1 >= tries) throw e;
      await new Promise((r) => setTimeout(r, 3000 * (i + 1)));
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1'))) {
  const [tool, a] = process.argv.slice(2);
  const args = a ? JSON.parse(a.startsWith('@') ? fs.readFileSync(a.slice(1), 'utf8') : a) : {};
  call(tool, args).then((t) => console.log(t.length > 4000 ? t.slice(0, 4000) + '…[' + t.length + ']' : t)).catch((e) => { console.error('ERR', e.message); process.exit(1); });
}

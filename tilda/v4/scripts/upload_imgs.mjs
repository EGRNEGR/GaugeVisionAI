// Upload site/v4 JPGs to the Tilda CDN by jsDelivr URL, one at a time, then md5-check them against the originals.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { call } from './rpc.mjs';

const SITE = 'C:/Hakatons/GaugeVisionAIDesign DashBoard/.claude/worktrees/website-v4/site/v4/assets/img';
const OUT = '' + new URL('../images.json', import.meta.url).pathname.replace(/^/(w:)/, '$1') + '';
const B = 'https://cdn.jsdelivr.net/gh/EGRNEGR/GaugeVisionAI@b5d88b7/site/v4/assets/img/';
const map = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf8')) : {};
const md5 = (b) => crypto.createHash('md5').update(b).digest('hex');

for (const f of fs.readdirSync(SITE).filter((x) => x.endsWith('.jpg'))) {
  if (map[f] && map[f].ok) continue;
  const txt = await call('upload_image', { projectid: 7124340, images: [{ image_url: B + f }] });
  const url = (txt.match(/https:\/\/[^"\s]+/) || [])[0];
  if (!url) { console.log('NO URL', f, txt.slice(0, 300)); continue; }
  const got = Buffer.from(await (await fetch(url)).arrayBuffer());
  const ok = md5(got) === md5(fs.readFileSync(path.join(SITE, f)));
  map[f] = { url, ok, bytes: got.length };
  fs.writeFileSync(OUT, JSON.stringify(map, null, 1));
  console.log(f, ok ? 'md5 OK' : 'md5 DIFF', got.length, url);
}

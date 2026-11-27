// Upload tilda/v5/dist to Tilda page 424686809: head code, N Vibe blocks (padding 0, animationoff, code),
// deletes any extra leftover blocks beyond manifest length. Idempotent by tilda/v5/records.json.
// Usage: node upload_page.mjs <pageid> [--only=changed]
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { call } from '../../v4/scripts/rpc.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const W = path.resolve(HERE, '..');
const DIST = path.join(W, 'dist');
const P = 7124340;
const PAGE = Number(process.argv[2]);
const ONLY_CHANGED = process.argv.includes('--only=changed');
const recFile = path.join(W, 'records.json');
const rec = fs.existsSync(recFile)
  ? JSON.parse(fs.readFileSync(recFile, 'utf8'))
  : { projectid: P, pageid: PAGE, head_md5: '', records: [] };
if (rec.pageid !== PAGE) throw new Error('records.json is for page ' + rec.pageid);
const man = JSON.parse(fs.readFileSync(path.join(DIST, 'manifest.json'), 'utf8'));
const save = () => fs.writeFileSync(recFile, JSON.stringify(rec, null, 2) + '\n');
const expectOK = (t, what) => { if (t.trim() !== 'OK') throw new Error(what + ': ' + t.slice(0, 300)); };

// 1. head code
const head = fs.readFileSync(path.join(DIST, 'head.html'), 'utf8');
if (!ONLY_CHANGED || rec.head_md5 !== man.head.md5) {
  const t = await call('update_page_head_code', { projectid: P, pageid: PAGE, headcode: head });
  console.log('head', t.slice(0, 80));
  rec.head_md5 = man.head.md5;
  save();
}

// 2. align records count with manifest
let existing = JSON.parse(await call('get_page_records', { projectid: P, pageid: PAGE })).map((r) => Number(r.recordid));
for (let i = 0; i < man.blocks.length; i++) {
  if (!rec.records[i]) {
    let id;
    if (i < existing.length && !rec.records.some((x) => x.recordid === existing[i])) {
      id = existing[i];
    } else {
      const args = { projectid: P, pageid: PAGE, tplid: 1370 };
      if (i > 0) args.afterid = rec.records[i - 1].recordid;
      id = Number(JSON.parse(await call('add_record', args)).recordid);
    }
    rec.records[i] = { recordid: id, md5: '', settings: false };
    save();
  }
}

// 3. upload each block
for (let i = 0; i < man.blocks.length; i++) {
  const b = man.blocks[i], r = rec.records[i];
  if (!r.settings) {
    expectOK(await call('update_record', {
      projectid: P, pageid: PAGE, recordid: r.recordid, tab: 'settings',
      fields: { margintop: '0px', margintop_res_480: '0px', marginbottom: '0px', marginbottom_res_480: '0px', animationoff: 'y' }
    }), 'settings ' + i);
    r.settings = true;
    save();
  }
  if (ONLY_CHANGED && r.md5 === b.md5) { console.log(b.file, 'unchanged'); continue; }
  const code = fs.readFileSync(path.join(DIST, b.file), 'utf8');
  if (crypto.createHash('md5').update(code).digest('hex') !== b.md5) throw new Error('md5 mismatch ' + b.file);
  expectOK(await call('update_record', {
    projectid: P, pageid: PAGE, recordid: r.recordid, tab: 'content', only_field: 'code', fields: { code }
  }), 'code ' + b.file);
  r.md5 = b.md5;
  save();
  console.log(b.file, r.recordid, 'OK', b.bytes);
}

// 4. delete leftover blocks on the page beyond manifest.blocks.length
const keep = new Set(rec.records.slice(0, man.blocks.length).map((r) => r.recordid));
const latest = JSON.parse(await call('get_page_records', { projectid: P, pageid: PAGE })).map((r) => Number(r.recordid));
for (const id of latest) {
  if (!keep.has(id)) {
    const res = await call('delete_record', { projectid: P, pageid: PAGE, recordid: id });
    console.log('deleted extra record', id, res.slice(0, 80));
  }
}
rec.records = rec.records.slice(0, man.blocks.length);
save();

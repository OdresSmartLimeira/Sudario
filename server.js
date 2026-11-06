const express = require('express');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { Pool } = require('pg');
const ffmpegPath = require('ffmpeg-static');

const {
  DATABASE_URL, WA_TOKEN, WA_PHONE_ID, APP_SECRET,
  WA_VERIFY_TOKEN = 'troque-este-token',
  ADMIN_USER = 'admin', ADMIN_PASS = 'admin123',
  SESSION_SECRET = 'troque-esta-chave', PORT = 3000,
} = process.env;

const GRAPH = 'https://graph.facebook.com/v21.0';
const STAGES = ['Triagem', 'Follow-Up', 'Convertido', 'Perdido'];
const pool = new Pool({
  connectionString: DATABASE_URL,
  ssl: DATABASE_URL && !/localhost|127\.0\.0\.1/.test(DATABASE_URL) ? { rejectUnauthorized: false } : false,
});

const app = express();
app.use(express.json({ verify: (req, _res, buf) => { req.raw = buf; } }));
app.use(express.static(path.join(__dirname, 'public')));
app.get('/health', (_req, res) => res.send('ok'));

/* ---------- login simples (token assinado) ---------- */
const sign = (exp) => `${exp}.${crypto.createHmac('sha256', SESSION_SECRET).update(String(exp)).digest('hex')}`;
const valid = (t) => !!t && Date.now() < Number(t.split('.')[0]) && sign(t.split('.')[0]) === t;
const auth = (req, res, next) => {
  const t = (req.headers.authorization || '').replace('Bearer ', '') || req.query.t;
  return valid(t) ? next() : res.status(401).json({ error: 'Sessão expirada' });
};
app.post('/api/login', (req, res) => {
  const { user, pass } = req.body || {};
  if (user === ADMIN_USER && pass === ADMIN_PASS) return res.json({ token: sign(Date.now() + 7 * 864e5) });
  res.status(401).json({ error: 'Usuário ou senha incorretos' });
});

/* ---------- banco ---------- */
async function initDb() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS contacts (
      id SERIAL PRIMARY KEY, phone TEXT UNIQUE NOT NULL, name TEXT,
      stage TEXT DEFAULT 'Triagem', last_text TEXT,
      last_msg_at TIMESTAMPTZ, last_inbound_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ DEFAULT now());
    CREATE TABLE IF NOT EXISTS messages (
      id SERIAL PRIMARY KEY, contact_id INT REFERENCES contacts(id) ON DELETE CASCADE,
      direction TEXT NOT NULL, type TEXT NOT NULL, body TEXT, media_id TEXT,
      wa_id TEXT UNIQUE, status TEXT, created_at TIMESTAMPTZ DEFAULT now());
    CREATE INDEX IF NOT EXISTS idx_msg_contact ON messages(contact_id, id);
    CREATE TABLE IF NOT EXISTS bookings (
      id SERIAL PRIMARY KEY, contact_id INT REFERENCES contacts(id) ON DELETE CASCADE,
      when_at TIMESTAMPTZ NOT NULL, note TEXT, status TEXT DEFAULT 'Pendente',
      created_at TIMESTAMPTZ DEFAULT now());`);
}
const q = (text, params) => pool.query(text, params).then((r) => r.rows);

async function upsertContact(phone, name) {
  const [c] = await q(
    `INSERT INTO contacts (phone, name) VALUES ($1, $2)
     ON CONFLICT (phone) DO UPDATE SET name = COALESCE(contacts.name, EXCLUDED.name) RETURNING *`,
    [phone, name || null]);
  return c;
}
async function saveMessage(contactId, dir, type, body, mediaId, waId, status) {
  await q(`INSERT INTO messages (contact_id, direction, type, body, media_id, wa_id, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (wa_id) DO NOTHING`,
    [contactId, dir, type, body, mediaId, waId, status]);
  const preview = body || { audio: '🎤 Áudio', image: '📷 Imagem', document: '📄 Documento' }[type] || `[${type}]`;
  await q(`UPDATE contacts SET last_text=$2, last_msg_at=now(),
           last_inbound_at = CASE WHEN $3='in' THEN now() ELSE last_inbound_at END WHERE id=$1`,
    [contactId, preview.slice(0, 120), dir]);
}

/* ---------- API do WhatsApp (Meta Cloud API) ---------- */
async function graph(p, opts = {}) {
  const r = await fetch(`${GRAPH}/${p}`, {
    ...opts, headers: { Authorization: `Bearer ${WA_TOKEN}`, ...(opts.headers || {}) },
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error?.message || 'Erro na API do WhatsApp');
  return j;
}
const sendWA = (payload) => graph(`${WA_PHONE_ID}/messages`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ messaging_product: 'whatsapp', ...payload }),
});

// WhatsApp só aceita áudio ogg/opus (o navegador grava webm/mp4) -> converte com ffmpeg
function toOgg(buf) {
  return new Promise((ok, fail) => {
    const id = crypto.randomUUID();
    const inp = path.join(os.tmpdir(), id + '.in'), out = path.join(os.tmpdir(), id + '.ogg');
    fs.writeFileSync(inp, buf);
    const p = spawn(ffmpegPath, ['-y', '-i', inp, '-vn', '-c:a', 'libopus', '-b:a', '32k', '-ac', '1', '-ar', '48000', out]);
    p.on('error', fail);
    p.on('close', (code) => {
      try { code === 0 ? ok(fs.readFileSync(out)) : fail(new Error('Falha ao converter o áudio')); }
      finally { fs.rmSync(inp, { force: true }); fs.rmSync(out, { force: true }); }
    });
  });
}

/* ---------- webhook (mensagens recebidas) ---------- */
app.get('/webhook', (req, res) => {
  const { 'hub.mode': mode, 'hub.verify_token': tk, 'hub.challenge': ch } = req.query;
  return mode === 'subscribe' && tk === WA_VERIFY_TOKEN ? res.send(ch) : res.sendStatus(403);
});
app.post('/webhook', async (req, res) => {
  res.sendStatus(200);
  if (APP_SECRET) {
    const sig = (req.headers['x-hub-signature-256'] || '').replace('sha256=', '');
    const mine = crypto.createHmac('sha256', APP_SECRET).update(req.raw || '').digest('hex');
    if (sig !== mine) return console.warn('Assinatura inválida no webhook');
  }
  try {
    for (const e of req.body.entry || []) for (const c of e.changes || []) {
      const v = c.value || {};
      for (const m of v.messages || []) {
        const name = (v.contacts || []).find((x) => x.wa_id === m.from)?.profile?.name;
        const contact = await upsertContact(m.from, name);
        const t = m.type;
        const body = t === 'text' ? m.text.body : m[t]?.caption || (m[t]?.id ? null : `[${t}]`);
        await saveMessage(contact.id, 'in', t, body, m[t]?.id || null, m.id, 'received');
      }
      for (const s of v.statuses || []) await q('UPDATE messages SET status=$2 WHERE wa_id=$1', [s.id, s.status]);
    }
  } catch (err) { console.error('webhook:', err); }
});

/* ---------- API do painel ---------- */
const wrap = (fn) => (req, res) => fn(req, res).catch((e) => res.status(400).json({ error: e.message }));
const getContact = async (id) => (await q('SELECT * FROM contacts WHERE id=$1', [id]))[0];

app.get('/api/conversations', auth, wrap(async (req, res) => {
  const s = `%${req.query.q || ''}%`;
  res.json(await q(`SELECT * FROM contacts WHERE last_msg_at IS NOT NULL AND (name ILIKE $1 OR phone ILIKE $1)
                    ORDER BY last_msg_at DESC LIMIT 200`, [s]));
}));
app.get('/api/conversations/:id/messages', auth, wrap(async (req, res) => {
  res.json(await q('SELECT * FROM messages WHERE contact_id=$1 ORDER BY id LIMIT 500', [req.params.id]));
}));
app.post('/api/conversations/:id/text', auth, wrap(async (req, res) => {
  const c = await getContact(req.params.id); const body = (req.body.body || '').trim();
  if (!c || !body) throw new Error('Mensagem vazia');
  const r = await sendWA({ to: c.phone, type: 'text', text: { body } });
  await saveMessage(c.id, 'out', 'text', body, null, r.messages[0].id, 'sent');
  res.json({ ok: true });
}));
app.post('/api/conversations/:id/audio', auth, express.raw({ type: '*/*', limit: '16mb' }), wrap(async (req, res) => {
  const c = await getContact(req.params.id);
  if (!c || !req.body?.length) throw new Error('Áudio vazio');
  const ogg = await toOgg(req.body);
  const form = new FormData();
  form.append('messaging_product', 'whatsapp');
  form.append('type', 'audio/ogg');
  form.append('file', new Blob([ogg], { type: 'audio/ogg' }), 'voice.ogg');
  const up = await graph(`${WA_PHONE_ID}/media`, { method: 'POST', body: form });
  const r = await sendWA({ to: c.phone, type: 'audio', audio: { id: up.id } });
  await saveMessage(c.id, 'out', 'audio', null, up.id, r.messages[0].id, 'sent');
  res.json({ ok: true });
}));
app.get('/api/media/:id', auth, wrap(async (req, res) => {
  const meta = await graph(req.params.id);
  const r = await fetch(meta.url, { headers: { Authorization: `Bearer ${WA_TOKEN}` } });
  res.set({ 'Content-Type': meta.mime_type, 'Cache-Control': 'private, max-age=86400' });
  res.send(Buffer.from(await r.arrayBuffer()));
}));

app.get('/api/leads', auth, wrap(async (req, res) => {
  const s = `%${req.query.q || ''}%`, st = req.query.stage || '';
  res.json({ stages: STAGES, leads: await q(
    `SELECT * FROM contacts WHERE (name ILIKE $1 OR phone ILIKE $1) AND ($2='' OR stage=$2)
     ORDER BY COALESCE(name, phone) LIMIT 300`, [s, st]) });
}));
app.patch('/api/contacts/:id', auth, wrap(async (req, res) => {
  await q('UPDATE contacts SET stage=COALESCE($2,stage), name=COALESCE($3,name) WHERE id=$1',
    [req.params.id, req.body.stage || null, req.body.name || null]);
  res.json({ ok: true });
}));
app.post('/api/contacts', auth, wrap(async (req, res) => {
  const phone = String(req.body.phone || '').replace(/\D/g, '');
  if (phone.length < 10) throw new Error('Telefone inválido (use DDI+DDD+número, ex.: 5519999999999)');
  res.json(await upsertContact(phone, req.body.name));
}));

app.get('/api/bookings', auth, wrap(async (_req, res) => {
  res.json(await q(`SELECT b.*, c.name, c.phone FROM bookings b JOIN contacts c ON c.id=b.contact_id
                    ORDER BY b.when_at DESC LIMIT 200`));
}));
app.post('/api/bookings', auth, wrap(async (req, res) => {
  const { contact_id, when_at, note } = req.body;
  if (!contact_id || !when_at) throw new Error('Escolha o contato e o horário');
  await q('INSERT INTO bookings (contact_id, when_at, note) VALUES ($1,$2,$3)', [contact_id, when_at, note || null]);
  res.json({ ok: true });
}));
app.patch('/api/bookings/:id', auth, wrap(async (req, res) => {
  await q('UPDATE bookings SET status=$2 WHERE id=$1', [req.params.id, req.body.status]);
  res.json({ ok: true });
}));

initDb().then(() => app.listen(PORT, () => console.log('Rodando na porta', PORT)))
  .catch((e) => { console.error('Erro ao iniciar o banco:', e); process.exit(1); });

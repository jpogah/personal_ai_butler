/**
 * WhatsApp Web Bridge
 * Wraps whatsapp-web.js in an Express HTTP + SSE server.
 *
 * Endpoints:
 *   GET  /health        → { ok: true, ready: bool, qr_pending: bool }
 *   GET  /events        → SSE stream of { type, ...data } events
 *   POST /send          → { to, body, media_path? } → { ok: true }
 *   POST /send-typing   → { to } → { ok: true }
 *
 * Run: node bridge.js [--port 8765] [--session-dir ./data/sessions]
 */

const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const fs = require('fs');
const path = require('path');

// ─── CLI args ─────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let port = 8765;
let sessionDir = './data/sessions';

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--port' && args[i + 1]) port = parseInt(args[i + 1], 10);
  if (args[i] === '--session-dir' && args[i + 1]) sessionDir = args[i + 1];
}

// ─── State ────────────────────────────────────────────────────────────────
let isReady = false;
let qrPending = false;
const sseClients = new Set();

// ─── SSE helpers ─────────────────────────────────────────────────────────
function broadcast(event) {
  const data = `data: ${JSON.stringify(event)}\n\n`;
  for (const res of sseClients) {
    try { res.write(data); } catch (_) { sseClients.delete(res); }
  }
}

// ─── WhatsApp client ──────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: sessionDir }),
  puppeteer: {
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-accelerated-2d-canvas',
      '--no-first-run',
      '--no-zygote',
      '--single-process',
      '--disable-gpu',
    ],
  },
});

client.on('qr', (qr) => {
  qrPending = true;
  qrcode.generate(qr, { small: true });
  console.log('[bridge] QR code generated – scan with WhatsApp');
  broadcast({ type: 'qr', qr });
});

client.on('ready', () => {
  isReady = true;
  qrPending = false;
  console.log('[bridge] WhatsApp client ready');
  broadcast({ type: 'ready' });
});

client.on('authenticated', () => {
  qrPending = false;
  console.log('[bridge] Authenticated');
  broadcast({ type: 'authenticated' });
});

client.on('auth_failure', (msg) => {
  console.error('[bridge] Auth failure:', msg);
  broadcast({ type: 'auth_failure', message: msg });
});

client.on('disconnected', (reason) => {
  isReady = false;
  console.warn('[bridge] Disconnected:', reason);
  broadcast({ type: 'disconnected', reason });
});

client.on('message', async (msg) => {
  if (msg.fromMe) return;
  try {
    let media_path = null;
    if (msg.hasMedia) {
      const media = await msg.downloadMedia();
      if (media) {
        const ext = media.mimetype.split('/')[1]?.split(';')[0] || 'bin';
        const fname = `wa_media_${Date.now()}.${ext}`;
        const fpath = path.join(sessionDir, fname);
        fs.writeFileSync(fpath, Buffer.from(media.data, 'base64'));
        media_path = fpath;
      }
    }
    const event = {
      type: 'message',
      id: msg.id._serialized,
      from: msg.from.replace(/@c\.us$/, '').replace(/^(\d+)$/, '+$1'),
      from_name: msg.notifyName || msg.from,
      body: msg.body,
      media_path,
      timestamp: msg.timestamp,
    };
    console.log(`[bridge] Message from ${event.from}: ${event.body?.slice(0, 80)}`);
    broadcast(event);
  } catch (err) {
    console.error('[bridge] Error handling message:', err);
  }
});

// ─── Express server ───────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ ok: true, ready: isReady, qr_pending: qrPending });
});

app.get('/events', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  // Send current state immediately
  res.write(`data: ${JSON.stringify({ type: 'connected', ready: isReady, qr_pending: qrPending })}\n\n`);

  sseClients.add(res);
  req.on('close', () => sseClients.delete(res));

  // Heartbeat every 30s
  const hb = setInterval(() => {
    try { res.write(': heartbeat\n\n'); } catch (_) { clearInterval(hb); }
  }, 30000);
  req.on('close', () => clearInterval(hb));
});

app.post('/send', async (req, res) => {
  const { to, body, media_path } = req.body;
  if (!to || (!body && !media_path)) {
    return res.status(400).json({ ok: false, error: 'Missing to or body/media_path' });
  }
  if (!isReady) {
    return res.status(503).json({ ok: false, error: 'WhatsApp not ready' });
  }

  try {
    // Normalize number to WhatsApp ID
    const chatId = to.replace(/^\+/, '') + '@c.us';
    if (media_path) {
      const media = MessageMedia.fromFilePath(media_path);
      await client.sendMessage(chatId, media, { caption: body || undefined });
    } else {
      await client.sendMessage(chatId, body);
    }
    res.json({ ok: true });
  } catch (err) {
    console.error('[bridge] Send error:', err);
    res.status(500).json({ ok: false, error: String(err) });
  }
});

app.post('/send-typing', async (req, res) => {
  const { to } = req.body;
  if (!to || !isReady) {
    return res.status(400).json({ ok: false, error: 'Missing to or not ready' });
  }
  try {
    const chat = await client.getChatById(to.replace(/^\+/, '') + '@c.us');
    await chat.sendStateTyping();
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ ok: false, error: String(err) });
  }
});

// ─── Start ────────────────────────────────────────────────────────────────
app.listen(port, '127.0.0.1', () => {
  console.log(`[bridge] HTTP server listening on http://127.0.0.1:${port}`);
});

console.log('[bridge] Initializing WhatsApp client…');
client.initialize().catch((err) => {
  console.error('[bridge] Failed to initialize client:', err);
  process.exit(1);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('[bridge] SIGTERM received, shutting down…');
  await client.destroy();
  process.exit(0);
});
process.on('SIGINT', async () => {
  await client.destroy();
  process.exit(0);
});

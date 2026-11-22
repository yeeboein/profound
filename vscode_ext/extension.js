// Profound for VS Code / VSCodium.
// Talks to the Profound desktop app on this PC (http://127.0.0.1:39291). Nothing leaves your computer.
const vscode = require('vscode');
const http = require('http');

const PORT = 39291;
const HEADERS = { 'Content-Type': 'application/json', 'X-Profound': '1' };

function ask(payload, onChunk) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(payload));
    const req = http.request({ host: '127.0.0.1', port: PORT, path: '/api/ask', method: 'POST',
      headers: Object.assign({ 'Content-Length': data.length }, HEADERS) }, res => {
      res.setEncoding('utf8');
      let all = '';
      if (res.statusCode !== 200) {
        res.on('data', c => { all += c; });
        res.on('end', () => reject(new Error(all || ('Profound returned ' + res.statusCode))));
        return;
      }
      res.on('data', c => { all += c; if (onChunk) onChunk(c); });
      res.on('end', () => resolve(all));
    });
    req.on('error', () => reject(new Error('Profound is not running. Open the Profound app, then try again.')));
    req.write(data);
    req.end();
  });
}

function status() {
  return new Promise(resolve => {
    const req = http.request({ host: '127.0.0.1', port: PORT, path: '/api/status', method: 'GET', headers: HEADERS, timeout: 1500 }, res => {
      let all = '';
      res.setEncoding('utf8');
      res.on('data', c => { all += c; });
      res.on('end', () => { try { resolve(JSON.parse(all)); } catch (e) { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.end();
  });
}

function firstCode(text) {
  const m = text.match(/```[^\n]*\n([\s\S]*?)```/);
  return m ? m[1].replace(/\n$/, '') : null;
}

function editorContext(ed) {
  const sel = ed.document.getText(ed.selection);
  return {
    code: sel || ed.document.getText().slice(0, 14000),
    file: vscode.workspace.asRelativePath(ed.document.uri),
    language: ed.document.languageId,
    selection: !!sel
  };
}

class ChatView {
  constructor() { this.view = null; this.queue = []; }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = page();
    view.webview.onDidReceiveMessage(m => this.onMessage(m));
    this.queue.forEach(m => view.webview.postMessage(m));
    this.queue = [];
    this.check();
  }

  post(m) { if (this.view) this.view.webview.postMessage(m); else this.queue.push(m); }

  async check() {
    const s = await status();
    this.post({ type: 'status', ok: !!s, ready: !!(s && s.ready), model: s ? s.model : '' });
  }

  async onMessage(m) {
    if (m.type === 'ask') {
      const ed = vscode.window.activeTextEditor;
      this.run(m.text, ed && m.useFile ? editorContext(ed) : null, 'ask');
    } else if (m.type === 'insert') {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return vscode.window.showWarningMessage('Open a file first.');
      ed.edit(e => e.replace(ed.selection, m.code));
    } else if (m.type === 'copy') {
      vscode.env.clipboard.writeText(m.code);
      vscode.window.setStatusBarMessage('Copied', 1500);
    } else if (m.type === 'status') {
      this.check();
    }
  }

  async run(text, ctx, mode) {
    this.post({ type: 'user', text });
    this.post({ type: 'start' });
    try {
      const all = await ask(Object.assign({ prompt: text, mode }, ctx || {}), c => this.post({ type: 'chunk', text: c }));
      this.post({ type: 'end' });
      return all;
    } catch (e) {
      this.post({ type: 'error', text: e.message });
      return null;
    }
  }
}

async function rewrite(chat, instruction) {
  const ed = vscode.window.activeTextEditor;
  if (!ed) return vscode.window.showWarningMessage('Open a file first.');
  const ctx = editorContext(ed);
  const doc = ed.document;
  const range = ed.selection.isEmpty ? new vscode.Range(0, 0, doc.lineCount, 0) : new vscode.Range(ed.selection.start, ed.selection.end);
  await vscode.commands.executeCommand('profound.chat.focus');
  const out = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'Profound is working on your code...' },
    () => chat.run(instruction, ctx, 'rewrite'));
  const code = out && firstCode(out);
  if (!code) return vscode.window.showWarningMessage('Profound did not return any code.');
  await ed.edit(e => e.replace(range, code));
  vscode.window.showInformationMessage('Profound updated your code. Press Ctrl+Z to undo.');
}

function activate(context) {
  const chat = new ChatView();
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('profound.chat', chat, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.commands.registerCommand('profound.ask', () => vscode.commands.executeCommand('profound.chat.focus')),
    vscode.commands.registerCommand('profound.explain', async () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return vscode.window.showWarningMessage('Open a file first.');
      await vscode.commands.executeCommand('profound.chat.focus');
      chat.run('Explain this code simply.', editorContext(ed), 'explain');
    }),
    vscode.commands.registerCommand('profound.fix', () =>
      rewrite(chat, 'Find and fix any bugs and improve this code. Return the complete corrected code in one code block.')),
    vscode.commands.registerCommand('profound.edit', async () => {
      const ins = await vscode.window.showInputBox({ prompt: 'What should Profound change?', placeHolder: 'e.g. add error handling' });
      if (ins) rewrite(chat, ins + '. Return the complete updated code in one code block.');
    })
  );
}

function deactivate() {}

function page() {
  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); margin: 0; display: flex; flex-direction: column; height: 100vh; }
  #status { padding: 8px 12px; font-size: 11px; opacity: .8; display: flex; align-items: center; gap: 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #e5a84b; display: inline-block; }
  .dot.ok { background: #4cc38a; } .dot.bad { background: #ff7b7b; }
  #log { flex: 1; overflow-y: auto; padding: 4px 12px; }
  .msg { margin: 10px 0; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
  .user { background: var(--vscode-input-background); padding: 8px 10px; border-radius: 10px; }
  .who { font-size: 11px; font-weight: 600; opacity: .7; margin-bottom: 4px; }
  pre { background: var(--vscode-textCodeBlock-background); padding: 10px; border-radius: 8px; overflow-x: auto; white-space: pre; margin: 6px 0; }
  code { font-family: var(--vscode-editor-font-family); font-size: var(--vscode-editor-font-size); }
  .bar { display: flex; gap: 6px; margin: -2px 0 8px; }
  button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); border: 0; border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 11px; }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  #form { padding: 10px 12px; border-top: 1px solid var(--vscode-panel-border); }
  textarea { width: 100%; box-sizing: border-box; resize: none; height: 64px; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); border-radius: 8px; padding: 8px; font-family: inherit; }
  .row { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 11px; opacity: .85; }
  .err { color: #ff7b7b; }
</style></head><body>
<div id="status"><span class="dot" id="dot"></span><span id="stext">Connecting to Profound...</span></div>
<div id="log"><div class="msg"><div class="who">Profound</div>Hi! Ask me anything, or select code and right-click for Explain, Fix or Edit.</div></div>
<div id="form"><textarea id="inp" placeholder="Ask Profound... (Enter to send)"></textarea>
<div class="row"><label><input type="checkbox" id="usefile" checked> Include current file / selection</label><button class="primary" id="send">Send</button></div></div>
<script>
  const vscode = acquireVsCodeApi();
  const log = document.getElementById('log'), inp = document.getElementById('inp');
  let cur = null, curText = '';
  function esc(s) { return s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }
  function render(el, text, done) {
    const parts = text.split('\`\`\`'); el.innerHTML = '';
    parts.forEach((p, i) => {
      if (i % 2 === 0) { const d = document.createElement('div'); d.innerHTML = esc(p.replace(/^\\n+|\\n+$/g, '')); el.appendChild(d); return; }
      const nl = p.indexOf('\\n'); const code = nl > -1 ? p.slice(nl + 1).replace(/\\n$/, '') : '';
      const pre = document.createElement('pre'); const c = document.createElement('code'); c.textContent = code; pre.appendChild(c); el.appendChild(pre);
      if (done || i < parts.length - 1) {
        const bar = document.createElement('div'); bar.className = 'bar';
        const ins = document.createElement('button'); ins.textContent = 'Insert at cursor'; ins.className = 'primary'; ins.onclick = () => vscode.postMessage({ type: 'insert', code });
        const cp = document.createElement('button'); cp.textContent = 'Copy'; cp.onclick = () => vscode.postMessage({ type: 'copy', code });
        bar.appendChild(ins); bar.appendChild(cp); el.appendChild(bar);
      }
    });
  }
  function add(cls, who, text) {
    const m = document.createElement('div'); m.className = 'msg ' + cls;
    if (who) { const w = document.createElement('div'); w.className = 'who'; w.textContent = who; m.appendChild(w); }
    const b = document.createElement('div'); b.textContent = text; m.appendChild(b); log.appendChild(m); log.scrollTop = log.scrollHeight; return b;
  }
  function send() { const t = inp.value.trim(); if (!t) return; inp.value = ''; vscode.postMessage({ type: 'ask', text: t, useFile: document.getElementById('usefile').checked }); }
  document.getElementById('send').onclick = send;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  window.addEventListener('message', ev => {
    const m = ev.data;
    if (m.type === 'status') {
      document.getElementById('dot').className = 'dot ' + (m.ok ? (m.ready ? 'ok' : '') : 'bad');
      document.getElementById('stext').textContent = !m.ok ? 'Profound app is not running' : (m.ready ? 'Connected \\u00B7 ' + m.model : 'Profound is loading its AI...');
      if (!m.ok || !m.ready) setTimeout(() => vscode.postMessage({ type: 'status' }), 4000);
    }
    if (m.type === 'user') add('user', '', m.text);
    if (m.type === 'start') { cur = add('', 'Profound', '...'); curText = ''; }
    if (m.type === 'chunk' && cur) { curText += m.text; render(cur, curText, false); log.scrollTop = log.scrollHeight; }
    if (m.type === 'end' && cur) { render(cur, curText, true); cur = null; }
    if (m.type === 'error') { if (cur) { cur.textContent = m.text; cur.className = 'err'; cur = null; } else add('err', '', m.text); }
  });
</script></body></html>`;
}

module.exports = { activate, deactivate };

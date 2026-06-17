'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const S = {
  token: localStorage.getItem('it_help_token'),
  user: null,
  profiles: [],
  devices: [],
  permissions: [],
  users: [],
  rollbacks: [],
};

// ── API Client ────────────────────────────────────────────────────────────
const API = {
  async req(method, path, body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (S.token) headers['Authorization'] = `Bearer ${S.token}`;
    let resp;
    try {
      resp = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      throw new Error('Cannot reach server. Is it running?');
    }
    if (resp.status === 401) { Auth.logout(); throw new Error('Session expired — please log in again.'); }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${resp.status}`);
    }
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('text/csv')) return resp;
    return resp.json();
  },
  get:  (p)    => API.req('GET', p),
  post: (p, b) => API.req('POST', p, b),
  del:  (p)    => API.req('DELETE', p),

  // EventSource passes token as query param (SSE can't use Authorization header)
  sse(path) {
    const sep = path.includes('?') ? '&' : '?';
    return new EventSource(`${path}${sep}token=${encodeURIComponent(S.token)}`);
  },

  async download(path, filename) {
    const resp = await API.req('GET', path);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

// ── Toast Notifications ───────────────────────────────────────────────────
function toast(type, msg) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ── Log Viewer ────────────────────────────────────────────────────────────
const Log = {
  append(id, msg) {
    const el = document.getElementById(id);
    if (!el) return;
    const span = document.createElement('span');
    const m = (msg || '').toLowerCase();
    if (m.includes('[err]') || m.includes('error'))           span.className = 'log-line-err';
    else if (m.includes('simul') || m.includes('would'))      span.className = 'log-line-sim';
    else if (m.includes('[ok]') || m.includes('success')
          || m.includes('complete') || m.includes('done'))    span.className = 'log-line-ok';
    else if (m.includes('warn'))                              span.className = 'log-line-warn';
    else if (msg.startsWith('===') || msg.startsWith('['))    span.className = 'log-line-hdr';
    else                                                       span.className = 'log-line-default';
    span.textContent = msg + '\n';
    el.appendChild(span);
    el.scrollTop = el.scrollHeight;
  },
  clear(id) { const el = document.getElementById(id); if (el) el.innerHTML = ''; },
  setLines(id, lines) { this.clear(id); lines.forEach(l => this.append(id, l)); },
};

// ── Helpers ───────────────────────────────────────────────────────────────
function statusDot(status) {
  return `<span class="status-dot status-${status}" title="${status}">&#11044;</span>`;
}
function pctClass(val, w = 75, c = 90) {
  if (val >= c) return 'pct-crit';
  if (val >= w) return 'pct-warn';
  return 'pct-ok';
}
// Safe HTML escape for user data in templates
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                           .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
// Access-level badge with color
const ACCESS_COLORS = {
  FullControl: 'danger', Modify: 'warning', ReadAndExecute: 'accent',
  Read: 'success', Write: 'purple', NoAccess: 'dim',
};
function accessBadge(level) {
  const c = ACCESS_COLORS[level] || 'dim';
  return `<span class="access-badge access-${c}">${esc(level)}</span>`;
}

// ── Clock ─────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('hdr-clock');
  const tick = () => { el.textContent = new Date().toLocaleString(); };
  tick(); setInterval(tick, 1000);
}

// ── Auth ──────────────────────────────────────────────────────────────────
const Auth = {
  async init() {
    if (!S.token) return false;
    try { S.user = await API.get('/api/me'); return true; }
    catch { S.token = null; localStorage.removeItem('it_help_token'); return false; }
  },

  async login() {
    const username = document.getElementById('login-user').value.trim();
    const password = document.getElementById('login-pass').value;
    const errEl = document.getElementById('login-err');
    errEl.classList.add('hidden');
    if (!username || !password) {
      errEl.textContent = 'Username and password required.';
      errEl.classList.remove('hidden'); return;
    }
    const btn = document.getElementById('login-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Signing in…';
    try {
      const data = await API.post('/api/auth/login', { username, password });
      S.token = data.token;
      S.user  = data.user;
      localStorage.setItem('it_help_token', data.token);
      App.showMain();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false; btn.textContent = 'Sign In';
    }
  },

  logout() {
    S.token = null; S.user = null;
    localStorage.removeItem('it_help_token');
    document.getElementById('app').classList.add('hidden');
    document.getElementById('login-screen').classList.remove('hidden');
    document.getElementById('login-pass').value = '';
    document.getElementById('login-err').classList.add('hidden');
  },
};

// ── App Router ────────────────────────────────────────────────────────────
const App = {
  async init() {
    document.getElementById('login-btn').addEventListener('click', Auth.login);
    document.getElementById('login-pass').addEventListener('keydown', e => {
      if (e.key === 'Enter') Auth.login();
    });
    document.getElementById('tab-nav').addEventListener('click', e => {
      const btn = e.target.closest('.tab-btn');
      if (!btn || btn.disabled) return;
      App.switchTab(btn.dataset.tab);
    });
    // Profile card clicks via event delegation (avoids inline onclick string issues)
    document.getElementById('profiles-list').addEventListener('click', e => {
      const card    = e.target.closest('.profile-card');
      const preview = e.target.closest('[data-action="preview"]');
      const apply   = e.target.closest('[data-action="apply"]');
      if (!card) return;
      const name = card.dataset.name;
      if (preview) { e.stopPropagation(); Settings.preview(name); }
      else if (apply) { e.stopPropagation(); Settings.apply(name); }
      else Settings.select(name);
    });

    if (await Auth.init()) App.showMain();
  },

  showMain() {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');

    const role = S.user?.role || '';
    document.getElementById('hdr-user').textContent = S.user?.username || '';
    const roleEl = document.getElementById('hdr-role');
    roleEl.textContent = role;
    roleEl.setAttribute('data-role', role);

    const canSettings  = ['Admin','IT_Staff'].includes(role);
    const canInventory = ['Admin','IT_Staff','Standard_User'].includes(role);
    document.querySelectorAll('.tab-btn').forEach(btn => {
      if (btn.dataset.tab === 'settings'  && !canSettings)  btn.disabled = true;
      if (btn.dataset.tab === 'inventory' && !canInventory) btn.disabled = true;
    });
    if (role !== 'Admin') {
      document.getElementById('assign-card').style.display = 'none';
      document.getElementById('users-card').style.display  = 'none';
    }

    startClock();
    Settings.load();
    Inventory.load();
    Perms.load();

    const first = canSettings ? 'settings' : canInventory ? 'inventory' : 'permissions';
    App.switchTab(first);
  },

  switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tab-pane').forEach(p =>
      p.classList.toggle('active', p.id === `tab-${name}`));
    App.setStatus('Ready');
  },

  setStatus(msg) { document.getElementById('status-text').textContent = msg; },
};

// ── Settings ──────────────────────────────────────────────────────────────
const Settings = {
  async load() {
    try {
      S.profiles  = await API.get('/api/profiles');
      const rb    = await API.get('/api/rollbacks');
      S.rollbacks = rb.rollbacks || [];
      this._render();
      this._renderRollbacks();
    } catch (e) { toast('error', 'Failed to load profiles: ' + e.message); }
  },

  _render() {
    const list = document.getElementById('profiles-list');
    if (!S.profiles.length) {
      list.innerHTML = '<div class="empty-state">No profiles found. Add JSON files to config/profiles/ and reload.</div>';
      return;
    }
    list.innerHTML = S.profiles.map(p => `
      <div class="profile-card" data-name="${esc(p.name)}">
        <div class="profile-name">${esc(p.name)}</div>
        <div class="profile-desc">${esc(p.description || '')}</div>
        <div class="profile-actions">
          <button class="btn btn-ghost btn-sm" data-action="preview">Preview</button>
          <button class="btn btn-success btn-sm" data-action="apply">&#9654; Apply</button>
        </div>
      </div>
    `).join('');
  },

  _renderRollbacks() {
    const sel = document.getElementById('rollback-sel');
    if (!S.rollbacks.length) {
      sel.innerHTML = '<option value="">— No snapshots available —</option>';
    } else {
      sel.innerHTML = S.rollbacks.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
    }
  },

  select(name) {
    document.querySelectorAll('.profile-card').forEach(c =>
      c.classList.toggle('selected', c.dataset.name === name));
  },

  async preview(name) {
    Log.clear('settings-log');
    App.setStatus('Generating preview…');
    try {
      const data = await API.get(`/api/profiles/${encodeURIComponent(name)}/preview`);
      Log.setLines('settings-log', data.lines);
      App.setStatus(`Preview: ${name}`);
    } catch (e) { toast('error', e.message); App.setStatus('Preview failed.'); }
  },

  apply(name) {
    if (!confirm(`Apply "${name}" to this workstation?\n\nA rollback snapshot will be created first.`)) return;
    Log.clear('settings-log');
    Log.append('settings-log', `Starting: ${name}…`);
    App.setStatus(`Applying ${name}…`);

    const es = API.sse(`/api/profiles/${encodeURIComponent(name)}/apply`);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.done) {
        es.close();
        toast(d.ok ? 'success' : 'error', d.msg || (d.ok ? 'Profile applied.' : 'Apply failed.'));
        App.setStatus(d.ok ? `${name} applied.` : 'Apply failed — see log.');
        Settings.load();
        return;
      }
      Log.append('settings-log', d.line);
    };
    es.onerror = () => {
      es.close();
      Log.append('settings-log', '[ERR] Connection lost.');
      App.setStatus('Connection error.');
      toast('error', 'Lost connection to server.');
    };
  },

  doRollback() {
    const filename = document.getElementById('rollback-sel').value;
    if (!filename) { toast('info', 'No snapshot selected.'); return; }
    if (!confirm(`Restore settings from snapshot:\n\n${filename}\n\nThis will overwrite current settings.`)) return;

    Log.clear('settings-log');
    Log.append('settings-log', `Restoring from: ${filename}…`);
    App.setStatus('Restoring snapshot…');

    const es = API.sse(`/api/rollbacks/restore?filename=${encodeURIComponent(filename)}`);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.done) {
        es.close();
        toast(d.ok ? 'success' : 'error', d.msg || (d.ok ? 'Rollback complete.' : 'Rollback failed.'));
        App.setStatus(d.ok ? 'Rollback complete.' : 'Rollback failed — see log.');
        return;
      }
      Log.append('settings-log', d.line);
    };
    es.onerror = () => { es.close(); Log.append('settings-log', '[ERR] Connection lost.'); };
  },
};

// ── Inventory ─────────────────────────────────────────────────────────────
const Inventory = {
  _all: [],

  async load() {
    try {
      S.devices = this._all = await API.get('/api/devices');
      this._render(this._all);
    } catch { /* silently skip — server may not be ready yet */ }
  },

  _render(devices) {
    const tbody = document.getElementById('devices-tbody');
    if (!devices.length) {
      tbody.innerHTML = '<tr><td colspan="13" class="empty-cell">No devices yet — click <strong>Scan Network</strong> to discover devices.</td></tr>';
    } else {
      tbody.innerHTML = devices.map(d => {
        const dp = parseFloat(d.disk_pct_used) || 0;
        const cp = parseFloat(d.cpu_pct)       || 0;
        const mp = parseFloat(d.mem_pct)       || 0;
        return `<tr>
          <td>${statusDot(d.status || 'unknown')} ${esc(d.status || 'unknown')}</td>
          <td><strong>${esc(d.hostname || '—')}</strong></td>
          <td class="mono">${esc(d.ip_address || '—')}</td>
          <td>${esc(d.os_version || '—')}</td>
          <td title="${esc(d.cpu_model || '')}" style="max-width:150px;overflow:hidden;text-overflow:ellipsis">${esc(d.cpu_model || '—')}</td>
          <td>${d.cores || '—'}</td>
          <td>${d.ram_gb != null ? d.ram_gb : '—'}</td>
          <td>${d.disk_gb_free != null ? d.disk_gb_free : '—'}</td>
          <td class="${pctClass(dp)}">${dp}%</td>
          <td class="${pctClass(cp, 85, 95)}">${cp}%</td>
          <td class="${pctClass(mp)}">${mp}%</td>
          <td>${d.uptime_hours != null ? d.uptime_hours : '—'}</td>
          <td class="mono">${esc((d.last_seen || '').slice(0,16))}</td>
        </tr>`;
      }).join('');
    }
    document.querySelector('#sc-total   .sc-num').textContent = devices.length;
    document.querySelector('#sc-healthy .sc-num').textContent = devices.filter(d => d.status === 'healthy').length;
    document.querySelector('#sc-warning .sc-num').textContent = devices.filter(d => d.status === 'warning').length;
    document.querySelector('#sc-critical .sc-num').textContent = devices.filter(d => d.status === 'critical').length;
    App.setStatus(devices.length ? `${devices.length} device(s)` : 'No devices — run a scan.');
  },

  applyFilter() {
    const status = document.getElementById('inv-filter').value;
    const search = document.getElementById('inv-search').value.toLowerCase();
    let rows = this._all;
    if (status !== 'all') rows = rows.filter(d => (d.status || '') === status);
    if (search) rows = rows.filter(d =>
      (d.hostname   || '').toLowerCase().includes(search) ||
      (d.ip_address || '').toLowerCase().includes(search) ||
      (d.cpu_model  || '').toLowerCase().includes(search));
    this._render(rows);
  },

  startScan() {
    const btn = document.getElementById('scan-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Scanning…';
    Log.clear('inventory-log');
    Log.append('inventory-log', 'Starting network scan…');
    App.setStatus('Scanning network…');

    const es = API.sse('/api/scan');
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.done) {
        es.close();
        btn.disabled = false; btn.innerHTML = '&#128269; Scan Network';
        const count = d.count ?? 0;
        toast('success', `Scan complete — ${count} device(s) found.`);
        App.setStatus(`Scan complete — ${count} device(s).`);
        Inventory.load();
        return;
      }
      Log.append('inventory-log', d.line);
    };
    es.onerror = () => {
      es.close();
      btn.disabled = false; btn.innerHTML = '&#128269; Scan Network';
      Log.append('inventory-log', '[ERR] Connection lost.');
      App.setStatus('Scan failed.');
      toast('error', 'Scan failed — connection lost.');
    };
  },

  async exportCSV() {
    if (!this._all.length) { toast('info', 'No devices to export — run a scan first.'); return; }
    try {
      await API.download('/api/devices/export.csv', 'inventory.csv');
      toast('info', 'CSV downloaded.');
    } catch (e) { toast('error', e.message); }
  },
};

// ── Permissions ───────────────────────────────────────────────────────────
const Perms = {
  async load() {
    try {
      [S.permissions, S.users] = await Promise.all([
        API.get('/api/permissions'),
        API.get('/api/users'),
      ]);
      this._renderPerms();
      this._renderUsers();
    } catch { /* not all roles have access */ }
  },

  _renderPerms() {
    const tbody = document.getElementById('perms-tbody');
    if (!S.permissions.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">No permission records.</td></tr>';
      return;
    }
    const isAdmin = S.user?.role === 'Admin';
    tbody.innerHTML = S.permissions.map(p => `
      <tr>
        <td><strong>${esc(p.target_name)}</strong></td>
        <td class="mono" title="${esc(p.resource_path)}" style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${esc(p.resource_path)}</td>
        <td>${accessBadge(p.access_level)}</td>
        <td>${esc(p.applied_by_name || '—')}</td>
        <td class="mono">${esc((p.created_at || '').slice(0,16))}</td>
        <td>${isAdmin ? `<button class="btn btn-danger btn-sm" onclick="Perms.revoke(${p.id})">Revoke</button>` : ''}</td>
      </tr>
    `).join('');
  },

  _renderUsers() {
    const tbody = document.getElementById('users-tbody');
    tbody.innerHTML = S.users.map(u => `
      <tr>
        <td>${u.id}</td>
        <td><strong>${esc(u.username)}</strong></td>
        <td>${esc(u.email || '—')}</td>
        <td><span class="hdr-role" data-role="${esc(u.role)}">${esc(u.role)}</span></td>
        <td class="mono">${esc((u.created_at || '').slice(0,10))}</td>
        <td>${u.username !== S.user?.username
          ? `<button class="btn btn-danger btn-sm" onclick="Perms.deleteUser(${u.id},'${esc(u.username)}')">Delete</button>`
          : '<span style="color:var(--dim);font-size:12px">(you)</span>'}</td>
      </tr>
    `).join('');
  },

  async apply() {
    const target = document.getElementById('p-target').value.trim();
    const path   = document.getElementById('p-path').value.trim();
    const level  = document.getElementById('p-level').value;
    if (!target || !path) { toast('error', 'Target and resource path are required.'); return; }
    if (!confirm(`Set ${level} for:\n  "${target}"\n  on: ${path}`)) return;

    Log.clear('perms-log');
    Log.append('perms-log', `Applying ${level} → ${target}…`);
    App.setStatus('Applying permission…');

    const params = new URLSearchParams({ target_name: target, resource_path: path, access_level: level });
    const es = API.sse(`/api/permissions/apply?${params}`);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.done) {
        es.close();
        toast(d.ok ? 'success' : 'error', d.msg || (d.ok ? 'Permission applied.' : 'Failed.'));
        App.setStatus(d.ok ? 'Permission applied.' : 'Permission failed.');
        Perms.load();
        return;
      }
      Log.append('perms-log', d.line);
    };
    es.onerror = () => {
      es.close(); Log.append('perms-log', '[ERR] Connection lost.');
      App.setStatus('Connection error.');
    };
  },

  async revoke(id) {
    if (!confirm('Remove this permission record from the database?')) return;
    try {
      await API.del(`/api/permissions/${id}`);
      toast('info', 'Permission revoked.');
      App.setStatus('Permission revoked.');
      Perms.load();
    } catch (e) { toast('error', e.message); }
  },

  async queryAcl() {
    const path = document.getElementById('acl-path').value.trim();
    if (!path) { toast('info', 'Enter a path to query.'); return; }
    document.getElementById('acl-output').textContent = 'Querying…';
    try {
      const data = await API.post('/api/acl/query', { resource_path: path });
      document.getElementById('acl-output').textContent = data.lines.join('\n') || '(no output)';
    } catch (e) {
      document.getElementById('acl-output').textContent = e.message;
    }
  },

  async createUser() {
    const username = document.getElementById('nu-user').value.trim();
    const email    = document.getElementById('nu-email').value.trim();
    const password = document.getElementById('nu-pass').value;
    const role     = document.getElementById('nu-role').value;
    if (!username || !password) { toast('error', 'Username and password are required.'); return; }
    try {
      await API.post('/api/users', { username, email, role, password });
      toast('success', `User "${username}" created.`);
      document.getElementById('nu-user').value  = '';
      document.getElementById('nu-email').value = '';
      document.getElementById('nu-pass').value  = '';
      Perms.load();
    } catch (e) { toast('error', e.message); }
  },

  async deleteUser(id, username) {
    if (!confirm(`Permanently delete user "${username}"?`)) return;
    try {
      await API.del(`/api/users/${id}`);
      toast('info', `User "${username}" deleted.`);
      Perms.load();
    } catch (e) { toast('error', e.message); }
  },

  exportCSV() {
    if (!S.permissions.length) { toast('info', 'No permission records to export.'); return; }
    const cols = ['target_name','resource_path','access_level','applied_by_name','created_at'];
    const hdrs = ['Target','Resource Path','Access Level','Applied By','Date'];
    const rows = [hdrs.join(','), ...S.permissions.map(p =>
      cols.map(c => `"${(p[c] || '').replace(/"/g,'""')}"`).join(','))];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = 'permissions.csv'; a.click();
    URL.revokeObjectURL(url);
    toast('info', 'CSV exported.');
  },
};

// ── Audit Log Modal ───────────────────────────────────────────────────────
const AuditLog = {
  async open() {
    document.getElementById('audit-modal').classList.remove('hidden');
    const tbody = document.getElementById('audit-tbody');
    tbody.innerHTML = '<tr><td colspan="6" class="empty-cell"><span class="spinner"></span> Loading…</td></tr>';
    try {
      const rows = await API.get('/api/logs?limit=500');
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">No log entries yet.</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(r => {
        const cls = r.status === 'error' ? 'pct-crit'
                  : r.status === 'simulated' ? 'log-line-sim'
                  : 'pct-ok';
        return `<tr>
          <td class="mono">${esc((r.timestamp || '').slice(0,19))}</td>
          <td><strong>${esc(r.username || '—')}</strong></td>
          <td>${esc(r.action_type || '')}</td>
          <td>${esc(r.device_hostname || '—')}</td>
          <td class="${cls}">${esc(r.status || '')}</td>
          <td class="mono" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;font-size:11px;color:var(--dim)"
              title="${esc(r.details_json || '')}">${esc(r.details_json || '')}</td>
        </tr>`;
      }).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  },
  close() { document.getElementById('audit-modal').classList.add('hidden'); },
};

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => App.init());

// PWA install prompt
let _deferredInstall = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  _deferredInstall = e;
  setTimeout(() => {
    if (_deferredInstall) {
      toast('info', 'Tip: Install IT Help as an app using the ⊕ icon in your browser address bar.');
    }
  }, 12000);
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}

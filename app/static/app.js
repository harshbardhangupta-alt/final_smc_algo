// Shared frontend helpers. Credentials stay server-side; this only calls the JSON API.

function fmt(n) {
  if (n === null || n === undefined || n === 0) return '—';
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  return d.toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' });
}

async function api(path, opts) {
  try {
    const res = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
    if (res.status === 401) return { _unauth: true };
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
      toast('Error: ' + msg);
      return null;
    }
    if (res.status === 204) return {};
    return await res.json();
  } catch (e) {
    toast('Network error');
    return null;
  }
}

function toast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2600);
}

function updateStatbar(d) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('s-market', d.market_status);
  set('s-scan', fmtTime(d.last_scan));
  set('s-buy', d.qualified_buy);
  set('s-sell', d.qualified_sell);
  set('s-auto', d.auto_trading);
  const broker = d.broker_health || {};
  const el = document.getElementById('s-broker');
  if (el) {
    if (broker.offline) { el.textContent = 'OFFLINE'; el.className = 'v pill off'; }
    else if (broker.ok) { el.textContent = 'OK'; el.className = 'v pill ok'; }
    else { el.textContent = 'ERROR'; el.className = 'v pill bad'; }
  }
  const auto = document.getElementById('s-auto');
  if (auto) auto.className = 'v ' + (String(d.auto_trading).startsWith('ON') ? 'dir-buy' : 'muted');
}

// Load the top-bar stats on every page.
async function refreshStatbar() {
  const d = await api('/api/dashboard');
  if (d && !d._unauth) updateStatbar(d);
}
if (!document.getElementById('buy-table')) {
  // dashboard page refreshes stats itself; other pages do it here.
  refreshStatbar();
}

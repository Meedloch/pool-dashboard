(() => {
'use strict';
const root = document.getElementById('app');
const POOL = root.dataset.pool, ADMIN = root.dataset.admin === '1', CSRF = root.dataset.csrf;
const $ = id => document.getElementById(id);
const dataFields = ['check_date','ph','free_chlorine','total_chlorine','combined_chlorine','tac','th','temp','pressure','water_state','products','notes'];
const checkFields = ['baskets','waterline','floor_walls','filter_washed','flow_checked'];
const COLS = [['ph','n'],['free_chlorine','n'],['total_chlorine','n'],['combined_chlorine','n'],['tac','n'],['th','n'],['temp','n'],
  ['baskets','b'],['waterline','b'],['floor_walls','b'],['filter_washed','b'],['pressure','n'],['flow_checked','b'],['water_state','t'],['products','t'],['notes','t']];
const TABS = ADMIN ? ['entry','history','charts'] : ['history','charts'];
let rows = [];

const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const frDate = s => s ? s.split('-').reverse().join('/') : '—';
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v => { if (v === null || v === undefined || v === '') return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const sortRows = () => rows.sort((a, b) => b.check_date.localeCompare(a.check_date) || b.id - a.id);

function notify(msg, err = false) {
  const n = $('notice'); n.textContent = msg; n.classList.toggle('err', err); n.classList.add('show');
  clearTimeout(notify.t); notify.t = setTimeout(() => n.classList.remove('show'), 4500);
}

async function api(method, url, body) {
  const r = await fetch(url, { method, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
    body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) { location.href = '/login'; throw new Error('Session expirée.'); }
  let data = null; try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((data && data.errors && data.errors.join(' ')) || ('Erreur ' + r.status));
  return data;
}

function showTab(t) {
  TABS.forEach(x => {
    $('panel-' + x).classList.toggle('hidden', x !== t);
    const b = root.querySelector(`[data-tab="${x}"]`);
    b.classList.toggle('active', x === t); b.classList.toggle('secondary', x !== t);
  });
  if (t === 'history') renderHistory();
  if (t === 'charts') renderCharts();
}

function resetForm() {
  if (!ADMIN) return;
  $('recordForm').reset(); $('recordId').value = ''; $('check_date').value = today();
  $('formTitle').textContent = 'Contrôle du jour'; $('saveBtn').textContent = 'Enregistrer le contrôle';
}

function editRow(id) {
  const r = rows.find(x => x.id === id); if (!r) return;
  dataFields.forEach(k => $(k).value = r[k] ?? '');
  checkFields.forEach(k => $(k).checked = !!r[k]);
  $('recordId').value = id; $('formTitle').textContent = 'Modifier un contrôle';
  $('saveBtn').textContent = 'Enregistrer les modifications';
  showTab('entry'); scrollTo({ top: 0, behavior: 'smooth' });
}

async function deleteRow(id) {
  if (!confirm('Supprimer définitivement ce contrôle ?')) return;
  try { await api('DELETE', '/api/checks/' + id); } catch (e) { notify(e.message, true); return; }
  rows = rows.filter(r => r.id !== id); renderHistory(); renderCharts(); notify('Contrôle supprimé.');
}

function renderHistory() {
  const q = $('search').value.toLowerCase();
  const list = rows.filter(r => !q || (frDate(r.check_date) + ' ' + Object.values(r).join(' ')).toLowerCase().includes(q));
  $('totalCount').textContent = rows.length;
  $('lastDate').textContent = rows.length ? frDate(rows[0].check_date) : '—';
  const body = $('historyBody');
  if (!list.length) { body.innerHTML = `<tr><td colspan="18" class="empty">Aucun contrôle enregistré pour le moment.</td></tr>`; return; }
  body.innerHTML = list.map(r => `<tr><td>${frDate(r.check_date)}</td>` +
    COLS.map(([k, t]) => `<td>${t === 'b' ? (r[k] ? 'Oui' : 'Non') : (r[k] === null || r[k] === '' ? '—' : esc(r[k]))}</td>`).join('') +
    (ADMIN ? `<td><button class="small" data-edit="${r.id}">Modifier</button><button class="small danger" data-del="${r.id}">Supprimer</button></td>` : '') +
    '</tr>').join('');
}

function renderCharts() {
  const range = $('chartRange').value;
  const cutoff = range === 'all' ? null : new Date(); if (cutoff) cutoff.setDate(cutoff.getDate() - Number(range));
  const list = rows.filter(r => !cutoff || new Date(r.check_date + 'T12:00:00') >= cutoff).slice().sort((a, b) => a.check_date.localeCompare(b.check_date));
  const defs = [['ph','pH'],['free_chlorine','Chlore libre'],['total_chlorine','Chlore total'],['combined_chlorine','Chlore combiné'],['tac','TAC'],['th','TH'],['temp','Température (°C)'],['pressure','Pression filtre']];
  const el = $('charts');
  if (!list.length) { el.innerHTML = '<div class="empty">Aucun contrôle sur cette période.</div>'; return; }
  el.innerHTML = defs.map(d => {
    const pts = list.map(r => ({ date: r.check_date, v: num(r[d[0]]) })).filter(p => p.v !== null);
    if (!pts.length) return `<div class="chartbox"><h3>${d[1]}</h3><div class="empty">Aucune valeur saisie.</div></div>`;
    const W = 480, H = 210, L = 42, R = 14, T = 16, B = 34, pw = W - L - R, ph = H - T - B;
    let min = Math.min(...pts.map(p => p.v)), max = Math.max(...pts.map(p => p.v)); const lo = min, hi = max;
    if (min === max) { const pad = Math.abs(min) * .1 || 1; min -= pad; max += pad; }
    const x = i => L + (pts.length === 1 ? pw / 2 : i * pw / (pts.length - 1)), y = v => T + (max - v) / (max - min) * ph;
    const grid = [0,1,2,3].map(i => { const val = min + (max - min) * i / 3, yy = y(val);
      return `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#dce6eb" stroke-dasharray="3 4"/><text x="${L-7}" y="${yy+4}" text-anchor="end" font-size="10" fill="#607583">${Number(val.toFixed(2))}</text>`; }).join('');
    const line = pts.map((p, i) => (i ? 'L' : 'M') + x(i) + ',' + y(p.v)).join(' ');
    const circles = pts.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.v)}" r="3.5" fill="#168779"><title>${frDate(p.date)} : ${p.v}</title></circle>`).join('');
    const idx = [...new Set([0, Math.floor((pts.length - 1) / 2), pts.length - 1])];
    const labels = idx.map(i => `<text x="${x(i)}" y="${H-10}" text-anchor="middle" font-size="10" fill="#607583">${frDate(pts[i].date).slice(0,5)}</text>`).join('');
    return `<div class="chartbox"><h3>${d[1]}</h3><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Graphique ${d[1]}">${grid}<path d="${line}" fill="none" stroke="#168779" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>${circles}${labels}</svg><div class="muted">${pts.length} mesure(s) · min ${lo} · max ${hi}</div></div>`;
  }).join('');
}

// ---- événements (aucun gestionnaire inline : compatible avec la CSP)
root.addEventListener('click', e => {
  const t = e.target.closest('[data-tab],[data-edit],[data-del]'); if (!t) return;
  if (t.dataset.tab) showTab(t.dataset.tab);
  else if (t.dataset.edit) editRow(Number(t.dataset.edit));
  else if (t.dataset.del) deleteRow(Number(t.dataset.del));
});
$('search').addEventListener('input', renderHistory);
$('chartRange').addEventListener('change', renderCharts);
$('backupBtn').addEventListener('click', () => {
  const u = URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = u; a.download = 'sauvegarde_piscine.json'; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000);
});
if (ADMIN) {
  $('resetBtn').addEventListener('click', resetForm);
  $('recordForm').addEventListener('submit', async e => {
    e.preventDefault();
    const id = $('recordId').value, body = {};
    dataFields.forEach(k => body[k] = $(k).value.trim()); checkFields.forEach(k => body[k] = $(k).checked);
    try {
      const res = id ? await api('PUT', '/api/checks/' + id, body) : await api('POST', `/api/pools/${POOL}/checks`, body);
      const i = rows.findIndex(x => x.id === res.check.id); if (i >= 0) rows[i] = res.check; else rows.push(res.check);
      sortRows(); resetForm(); renderHistory(); renderCharts(); notify(id ? 'Contrôle modifié.' : 'Contrôle enregistré.');
    } catch (err) { notify(err.message, true); }
  });
  resetForm();
}

(async () => {
  showTab(ADMIN ? 'entry' : 'history');
  try { rows = (await api('GET', `/api/pools/${POOL}/checks`)).checks; sortRows(); renderHistory(); renderCharts(); }
  catch (e) { notify(e.message, true); }
})();
})();

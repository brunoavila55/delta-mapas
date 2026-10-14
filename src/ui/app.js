'use strict';
const $ = id => document.getElementById(id);
let csrf = '', user = null, config = {}, properties = [], fields = [], analyses = [], registering = false, editingField = null, selectedField = null, requestKey = null, busy = false;
let noticeTimer, authEpoch = 0;
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 6500); }
async function api(path, options = {}) {
  const requestEpoch = authEpoch;
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (csrf) headers['X-CSRF-Token'] = csrf;
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && requestEpoch === authEpoch && !['/api/login', '/api/register'].includes(path)) showAuth();
    throw new Error(data.error || `Não foi possível concluir (${response.status}).`);
  }
  return data;
}
function showAuth() { authEpoch++; properties = []; fields = []; analyses = []; user = null; csrf = ''; $('auth').hidden = false; $('workspace').hidden = true; document.querySelectorAll('dialog[open]').forEach(d => d.close()); $('result-image').removeAttribute('src'); $('result-downloads').replaceChildren(); $('field-list').replaceChildren(); $('analysis-list').replaceChildren(); $('property-list').replaceChildren(); }
function button(label, action, secondary = false) { const b = document.createElement('button'); b.textContent = label; b.type = 'button'; if (secondary) b.className = 'secondary'; b.addEventListener('click', action); return b; }
function text(tag, value, cls = '') { const el = document.createElement(tag); el.textContent = value; el.className = cls; return el; }
function empty(container, title, description, label, action) { const el = document.createElement('div'); el.className = 'empty'; el.append(text('h3', title), text('p', description)); if (label) el.append(button(label, action)); container.append(el); }
const titles = { fields: ['Meus talhões', 'Organize suas áreas e escolha o que analisar.'], analyses: ['Análises', 'Resultados e histórico de cada solicitação.'], properties: ['Propriedades', 'Organize os talhões de cada propriedade.'] };
function view(name) { Object.keys(titles).forEach(v => $('view-' + v).hidden = v !== name); document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === name)); $('page-title').textContent = titles[name][0]; $('page-description').textContent = titles[name][1]; }
function preview(geometry) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.classList.add('field-preview'); svg.setAttribute('viewBox', '0 0 300 160');
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  const coords = polygons.flat(2); const xs = coords.map(c => c[0]), ys = coords.map(c => c[1]);
  const left = Math.min(...xs), right = Math.max(...xs), bottom = Math.min(...ys), top = Math.max(...ys);
  const scale = Math.min(250 / (right - left), 120 / (top - bottom));
  const x = n => 150 + (n - (left + right) / 2) * scale; const y = n => 80 - (n - (top + bottom) / 2) * scale;
  for (const polygon of polygons) { const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('fill-rule', 'evenodd'); path.setAttribute('d', polygon.map(ring => ring.map((c, i) => `${i ? 'L' : 'M'}${x(c[0])},${y(c[1])}`).join(' ') + ' Z').join(' ')); svg.append(path); }
  return svg;
}
function renderFields() {
  const list = $('field-list'); list.replaceChildren();
  for (const field of fields) {
    const card = document.createElement('article'); card.className = 'field-card'; card.append(preview(field.geometry));
    const content = document.createElement('div'); content.className = 'field-content'; content.append(text('span', field.property_name, 'eyebrow'), text('h3', field.name), text('p', `${field.area_ha.toLocaleString('pt-BR', { maximumFractionDigits: 2 })} hectares`));
    const actions = document.createElement('div'); actions.className = 'field-actions'; actions.append(button('Analisar talhão', () => openAnalysis(field)), button('Editar área', () => openField(field), true)); content.append(actions); card.append(content); list.append(card);
  }
  if (!fields.length) empty(list, 'Seu primeiro talhão começa aqui', 'Cadastre uma propriedade e importe a área que deseja analisar.', 'Cadastrar talhão', () => openField());
}
function openField(field = null) {
  if (!properties.length) { view('properties'); notice('Cadastre uma propriedade antes de adicionar o talhão.'); return; }
  editingField = field; $('field-form').reset(); $('import-detail').hidden = true; $('geometry-details').open = false; $('field-title').textContent = field ? 'Editar talhão' : 'Cadastrar talhão'; $('property-select').replaceChildren();
  for (const property of properties) { const option = new Option(property.name, property.id); $('property-select').add(option); }
  if (field) { $('property-select').value = field.property_id; $('field-form').elements.name.value = field.name; $('geometry-input').value = JSON.stringify(field.geometry, null, 2); }
  $('field-dialog').showModal();
}
function openAnalysis(field) {
  selectedField = field; requestKey = crypto.randomUUID(); $('analysis-form').reset(); $('selected-field').textContent = `${field.name} · ${field.property_name}`;
  const today = new Date(); const before = new Date(today); before.setDate(today.getDate() - 30); const date = d => d.toISOString().slice(0, 10);
  $('analysis-form').elements.date_from.value = date(before); $('analysis-form').elements.date_to.value = date(today);
  $('analysis-form').elements.date_from.max = date(today); $('analysis-form').elements.date_to.max = date(today);
  $('analysis-mode').value = config.demo_enabled ? 'synthetic' : 'satellite'; $('analysis-dialog').showModal();
}
function renderAnalyses() {
  const list = $('analysis-list'); list.replaceChildren(); const labels = { queued: 'Na fila', running: 'Processando', completed: 'Concluída', failed: 'Não concluída' };
  for (const item of analyses) {
    const row = document.createElement('article'); row.className = 'analysis-row'; const content = document.createElement('div'); const heading = text('h3', item.field_name); heading.append(text('span', labels[item.status], 'badge ' + item.status));
    content.append(heading, text('p', `${item.date_from} a ${item.date_to} · NDVI${item.mode === 'synthetic' ? ' · DADOS SINTÉTICOS' : ''}`)); if (item.error) content.append(text('p', item.error, 'error')); row.append(content);
    if (item.status === 'completed') row.append(button('Ver resultado', () => openResult(item))); list.append(row);
  }
  if (!analyses.length) empty(list, 'Sua história ainda vai começar', 'Escolha um talhão para solicitar a primeira análise.', 'Ver meus talhões', () => view('fields'));
}
function openResult(item) {
  $('result-title').textContent = item.field_name + ' · NDVI'; $('result-origin').textContent = item.mode === 'synthetic' ? 'DEMONSTRAÇÃO: este resultado usa dados sintéticos.' : 'Imagem de satélite. A data da cena e a origem estão no relatório.';
  const base = `/api/analyses/${item.id}/files/`; $('result-image').src = base + 'ndvi.png'; const stats = item.statistics; $('result-stats').replaceChildren();
  for (const [label, value] of [['NDVI médio', stats.mean.toFixed(3)], ['Mínimo', stats.minimum.toFixed(3)], ['Máximo', stats.maximum.toFixed(3)], ['Pixels válidos', stats.valid_percent.toFixed(1) + '%']]) $('result-stats').append(text('span', `${label}: ${value}`));
  $('result-downloads').replaceChildren(); for (const [name, label] of [['report.pdf', 'Relatório PDF'], ['ndvi.png', 'Mapa PNG'], ['ndvi.tif', 'GeoTIFF'], ['analysis.json', 'Metadados']]) { const link = document.createElement('a'); link.href = base + name; link.download = name; link.textContent = label; $('result-downloads').append(link); } $('result-dialog').showModal();
  $('result-dialog').dataset.analysisId = item.id; const epoch = authEpoch;
  if (item.mode === 'satellite') api(base + 'analysis.json').then(metadata => {
    if (epoch !== authEpoch || !$('result-dialog').open || $('result-dialog').dataset.analysisId !== item.id) return;
    const scene = metadata.source?.metadata?.tiles?.[0]; if (!scene?.date) return;
    const day = scene.date.slice(0, 10).split('-').reverse().join('/');
    const clouds = Number.isFinite(scene.cloudCoverage) ? ` · Nuvens na cena: ${scene.cloudCoverage.toLocaleString('pt-BR')}%` : '';
    $('result-origin').textContent = `Sentinel-2 L2A · Cena de ${day}${clouds}.`;
  }).catch(() => {});
}
async function refresh() {
  if (busy) { await new Promise(resolve => setTimeout(resolve, 50)); return refresh(); } busy = true; const epoch = authEpoch;
  try {
    const data = await Promise.all([api('/api/me'), api('/api/properties'), api('/api/fields'), api('/api/analyses')]);
    if (epoch !== authEpoch) return; [user, properties, fields, analyses] = data; csrf = user.csrf_token; $('account-email').textContent = user.email; $('auth').hidden = true; $('workspace').hidden = false;
    $('property-count').textContent = properties.length; $('field-count').textContent = fields.length; $('available-count').textContent = user.usage.available; $('usage-detail').textContent = `${user.usage.used} utilizadas · ${user.usage.reserved} em processamento`;
    renderFields(); renderAnalyses(); $('property-list').replaceChildren(); for (const p of properties) $('property-list').append(text('div', p.name, 'property-item')); $('demo-banner').hidden = !config.demo_enabled;
  } finally { busy = false; }
}
async function submit(form, task) { const submit = form.querySelector('button:not([type="button"])'); submit.disabled = true; try { await task(); } catch (e) { notice(e.message, true); } finally { submit.disabled = false; } }
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => view(b.dataset.view)));
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => $(b.dataset.close).close()));
$('auth-toggle').addEventListener('click', () => { registering = !registering; $('auth-title').textContent = registering ? 'Crie sua conta' : 'Entre na sua conta'; $('auth-submit').textContent = registering ? 'Criar conta' : 'Entrar'; $('auth-toggle').textContent = registering ? 'Já tenho uma conta' : 'Criar uma conta'; $('password-help').hidden = !registering; $('auth-form').elements.password.autocomplete = registering ? 'new-password' : 'current-password'; $('auth-form').elements.password.minLength = registering ? 12 : 1; });
$('auth-form').addEventListener('submit', e => { e.preventDefault(); submit(e.target, async () => { const payload = Object.fromEntries(new FormData(e.target)); const result = await api(registering ? '/api/register' : '/api/login', { method: 'POST', body: JSON.stringify(payload) }); authEpoch++; csrf = result.csrf_token; e.target.reset(); await refresh(); }); });
$('logout').addEventListener('click', async () => { try { await api('/api/logout', { method: 'POST' }); showAuth(); } catch (e) { notice(e.message, true); } });
$('refresh').addEventListener('click', () => refresh().catch(e => notice(e.message, true)));
$('new-field').addEventListener('click', () => openField());
$('property-form').addEventListener('submit', e => { e.preventDefault(); submit(e.target, async () => { await api('/api/properties', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(e.target))) }); e.target.reset(); await refresh(); notice('Propriedade cadastrada.'); }); });
$('geojson-file').addEventListener('change', async e => {
  const file = e.target.files[0]; if (!file) return;
  const zipped = file.name.toLowerCase().endsWith('.zip');
  $('geometry-input').value = ''; $('import-detail').hidden = true; $('save-field').disabled = true;
  try {
    if (file.size > (zipped ? 10000000 : 2000000)) throw new Error(zipped ? 'O ZIP deve ter até 10 MB.' : 'O GeoJSON deve ter até 2 MB.');
    if (zipped) {
      const report = await api('/api/imports/car', { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
      $('geometry-input').value = JSON.stringify(report.geometry);
      $('import-detail').textContent = `Área do imóvel: ${report.area_ha.toLocaleString('pt-BR', { maximumFractionDigits: 2 })} ha. ${report.warnings.join(' ')}`;
      $('import-detail').hidden = false;
      if (!$('field-form').elements.name.value.trim()) $('field-form').elements.name.value = 'Área do imóvel (CAR)';
      notice('Limite do imóvel importado. Confira o nome e salve a área.');
    } else {
      const content = await file.text(); JSON.parse(content); $('geometry-input').value = content;
      notice('GeoJSON carregado. Salve para validar a área.');
    }
  } catch (error) { notice(error.message, true); }
  finally { $('save-field').disabled = false; }
});
$('field-form').addEventListener('submit', e => { e.preventDefault(); submit(e.target, async () => { const form = Object.fromEntries(new FormData(e.target)); if (!form.geometry.trim()) throw new Error('Importe o ZIP do CAR ou o GeoJSON da área.'); try { form.geometry = JSON.parse(form.geometry); } catch { throw new Error('O GeoJSON informado não é válido.'); } await api(editingField ? '/api/fields/' + editingField.id : '/api/fields', { method: editingField ? 'PUT' : 'POST', body: JSON.stringify(form) }); $('field-dialog').close(); await refresh(); notice('Talhão salvo.'); }); });
$('analysis-form').addEventListener('input', () => requestKey = crypto.randomUUID());
$('analysis-form').addEventListener('submit', e => { e.preventDefault(); submit(e.target, async () => { const form = Object.fromEntries(new FormData(e.target)); form.field_id = selectedField.id; form.max_cloud = Number(form.max_cloud); await api('/api/analyses', { method: 'POST', headers: { 'Idempotency-Key': requestKey }, body: JSON.stringify(form) }); $('analysis-dialog').close(); view('analyses'); await refresh(); notice('Solicitação recebida. Você pode acompanhar aqui.'); }); });
setInterval(() => { if (user && analyses.some(a => ['queued', 'running'].includes(a.status))) refresh().catch(e => notice(e.message, true)); }, 5000);
(async () => { try { config = await api('/api/config'); $('auth-toggle').hidden = !config.registration_enabled; if (config.demo_enabled) $('analysis-mode').add(new Option('NDVI · demonstração com dados sintéticos', 'synthetic')); await refresh(); } catch (e) { showAuth(); if (!e.message.includes('sessão')) notice(e.message, true); } })();

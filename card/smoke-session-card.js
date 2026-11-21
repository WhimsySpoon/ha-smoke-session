// smoke-session-card v0.1.0 — guided smoker cook for the Smoke Session integration.
// v0.1.0: first version. Idle: pick the cook, weight, planned start and meat probe, then start. Cooking: the current
// step with a two-tap Done, pit temperature on a band gauge with trend and what to do about it, meat temperature with
// rate, ETA and its alert thresholds, quick logging (spritz, lid, probe check with a note, bottom vents), the next
// reminder, the phase timeline (planned and projected) and the cook log. Finished: the summary and result notes.
// Config: `entity` = the integration's Status sensor (sensor.<name>_smoke_session_status). Every other entity is
// found from that sensor's `entities` attribute, so renames don't break the card.
// Follows claude/custom-card-rules.md: redraws only when an entity it read changes (plus a 15 s clock tick for
// times); formatters built once; listeners attached once; timer cleaned up; regions only rewritten when their HTML
// changes, so the note boxes keep focus; anything missing is said on the card and in the console. ES2021 syntax.

const SSC_TAG = 'smoke-session-card';
const SSC_VERSION = '0.1.0';

const SSC_COL = { good: '#6BD69B', warn: '#F4C06A', bad: '#FF8A66', blue: '#8FC2FF', dim: '#B4BFCA', text: '#E6EBF0', grey: '#5B6675' };
const SSC_PIT = {
  offline: ['Offline', SSC_COL.grey], below: ['Too cold', SSC_COL.bad], low: ['Low', SSC_COL.warn],
  in_band: ['In range', SSC_COL.good], high: ['High', SSC_COL.warn], above: ['Too hot', SSC_COL.bad],
};
const SSC_VENTS = ['Closed', '25% open', '50% open', '75% open', 'Fully open'];
const SSC_VENT_SHORT = ['Shut', '25%', '50%', '75%', 'Open'];
const SSC_EVENT_ICON = {
  session_start: 'mdi:flag-outline', chimney_lit: 'mdi:fire', pit_stable: 'mdi:thermometer-check', ribs_on: 'mdi:grill',
  spritz: 'mdi:spray', lid_open: 'mdi:arrow-up-box', probe_check: 'mdi:needle', vent_adjust: 'mdi:valve', wrap: 'mdi:package-variant',
  probe_tender: 'mdi:check-decagram', unwrap: 'mdi:package-variant-closed-remove', off_smoker: 'mdi:silverware-fork-knife',
  note: 'mdi:note-text-outline', session_end: 'mdi:flag-checkered',
};

const SSC_CSS = `
:host{display:block}
.card{background:#0A0E13;color:${SSC_COL.text};font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-variant-numeric:tabular-nums;border-radius:24px;padding:16px;display:flex;flex-direction:column;gap:14px;box-sizing:border-box}
.panel{background:#121820;border-radius:20px;padding:18px 20px;display:flex;flex-direction:column;gap:12px;min-width:0}
.label{color:${SSC_COL.dim};font-size:13px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}
.label span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.label span:first-child{flex:none}
.row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;font-size:14px;background:rgba(255,255,255,.06);color:${SSC_COL.dim};white-space:nowrap}
.chip b{font-weight:600;color:${SSC_COL.text}}
.chip ha-icon{--mdc-icon-size:16px}
h1{margin:0;font-size:26px;font-weight:600;letter-spacing:-.3px}
h2{margin:0;font-size:24px;font-weight:600;line-height:1.2}
.sub{font-size:15px;color:${SSC_COL.dim};line-height:1.45}
.big{font-size:56px;font-weight:600;letter-spacing:-1.5px;line-height:1}
.big small{font-size:24px;color:${SSC_COL.dim};font-weight:500;letter-spacing:0}
button{font:inherit;color:inherit;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent}
.btn{background:rgba(255,255,255,.08);border-radius:14px;padding:12px 16px;font-size:15px;font-weight:600;display:inline-flex;align-items:center;gap:8px;justify-content:center}
.btn:active{background:rgba(255,255,255,.16)}
.btn ha-icon{--mdc-icon-size:20px}
.btn.primary{background:#1E4D36;color:#C9F0DC}
.btn.primary.arm{background:${SSC_COL.good};color:#0A0E13}
.btn.danger{background:#4A2418;color:#FFB199}
.btn.danger.arm{background:${SSC_COL.bad};color:#0A0E13}
.btn.on{background:#1E3A5C;color:#CFE3FF}
.btn[disabled]{opacity:.4;cursor:default}
.btns{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.seg{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}
.seg .btn{padding:10px 4px;font-size:14px}
.step-detail{font-size:17px;line-height:1.5;color:${SSC_COL.text}}
.step-meta{font-size:14px;color:${SSC_COL.dim}}
.auto{font-size:14px;color:${SSC_COL.blue}}
.gauge{position:relative;height:14px;border-radius:7px;overflow:hidden;display:flex}
.gauge i{display:block;height:100%}
.gwrap{position:relative;padding:12px 0 18px}
.marker{position:absolute;top:4px;width:4px;height:30px;margin-left:-2px;border-radius:2px;background:#fff;box-shadow:0 0 0 2px #0A0E13}
.ticks{position:absolute;left:0;right:0;bottom:0;height:16px;font-size:12px;color:${SSC_COL.dim}}
.ticks span{position:absolute;transform:translateX(-50%)}
.rec{border-radius:16px;padding:14px 16px;font-size:16px;line-height:1.45;display:flex;gap:12px;align-items:flex-start}
.rec ha-icon{--mdc-icon-size:22px;flex:none;margin-top:1px}
.thr{display:flex;gap:8px;flex-wrap:wrap}
.thr .chip.done{background:rgba(107,214,155,.14);color:${SSC_COL.good}}
textarea,input,select{font:inherit;font-size:15px;color:${SSC_COL.text};background:#0B1016;border:1px solid #232C38;border-radius:12px;padding:10px 12px;box-sizing:border-box;width:100%}
textarea{min-height:64px;resize:vertical}
.field{display:flex;flex-direction:column;gap:6px;min-width:0;flex:1 1 160px}
.field span{font-size:13px;color:${SSC_COL.dim}}
.tl{display:flex;flex-direction:column;gap:6px}
.ph{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:10px;align-items:center;padding:8px 10px;border-radius:12px}
.ph.current{background:rgba(95,168,255,.10)}
.ph .dot{width:12px;height:12px;border-radius:6px;background:#2A3440;justify-self:center}
.ph.done .dot{background:${SSC_COL.good}}
.ph.current .dot{background:#5FA8FF;box-shadow:0 0 0 4px rgba(95,168,255,.25)}
.ph .nm{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ph .tm{font-size:14px;color:${SSC_COL.dim};text-align:right;white-space:nowrap}
.ph .tm b{color:${SSC_COL.text};font-weight:600}
.steps{display:flex;flex-direction:column;gap:2px;margin:-2px 0 6px 32px}
.steps div{font-size:14px;color:${SSC_COL.dim};display:flex;gap:8px;align-items:center}
.steps div.done{color:#6E7B89;text-decoration:line-through}
.steps div.current{color:${SSC_COL.text};font-weight:600}
.log{display:flex;flex-direction:column;gap:4px;max-height:340px;overflow:auto}
.ev{display:grid;grid-template-columns:48px 22px minmax(0,1fr) auto;gap:8px;align-items:start;font-size:14px;padding:6px 4px;border-bottom:1px solid #18202A}
.ev .t{color:${SSC_COL.dim}}
.ev ha-icon{--mdc-icon-size:18px;color:${SSC_COL.dim}}
.ev .w{min-width:0}
.ev .w i{display:block;font-style:normal;color:${SSC_COL.dim};font-size:13px;margin-top:2px;overflow-wrap:anywhere}
.ev .tp{color:${SSC_COL.dim};white-space:nowrap;font-size:13px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}
.stat{background:rgba(255,255,255,.05);border-radius:14px;padding:12px 14px}
.stat .k{font-size:13px;color:${SSC_COL.dim}}
.stat .v{font-size:22px;font-weight:600;margin-top:4px}
.err{background:rgba(120,40,24,.45);color:#FFB199;border-radius:16px;padding:16px;font-size:15px}
.toast{font-size:14px;color:#FFB199}
[hidden]{display:none!important}
`;

const SSC_HTML = `
<div class="card">
  <div class="err" id="err" hidden></div>
  <div class="panel" id="head"></div>
  <div id="idle" hidden>
    <div class="panel" id="setup"></div>
  </div>
  <div id="active" hidden style="display:flex;flex-direction:column;gap:14px">
    <div class="panel" id="now"></div>
    <div class="grid">
      <div class="panel" id="pit"></div>
      <div class="panel" id="meat"></div>
    </div>
    <div class="panel">
      <div class="label">Log</div>
      <div class="btns" id="logbtns"></div>
      <textarea id="note" placeholder="Note (optional): how a probe check felt, what you changed…"></textarea>
      <div class="label" style="margin-top:4px">Bottom vents <span id="vent-now"></span></div>
      <div class="seg" id="vents"></div>
    </div>
    <div class="grid">
      <div class="panel" id="timeline"></div>
      <div class="panel" id="events"></div>
    </div>
    <div class="panel">
      <div class="label">End the cook</div>
      <textarea id="endnote" placeholder="Result notes: tenderness, bark, smoke flavour, moisture"></textarea>
      <div class="row"><button class="btn danger" data-act="end"><ha-icon icon="mdi:flag-checkered"></ha-icon><span>End session</span></button><span class="toast" id="end-hint"></span></div>
    </div>
  </div>
  <div id="done" hidden style="display:flex;flex-direction:column;gap:14px">
    <div class="panel" id="summary"></div>
    <div class="grid">
      <div class="panel" id="timeline2"></div>
      <div class="panel" id="events2"></div>
    </div>
  </div>
  <div class="toast" id="toast" hidden></div>
</div>`;

function sscEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

class SmokeSessionCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) throw new Error('smoke-session-card: set `entity` to the Smoke Session Status sensor');
    this._config = { ...config };
    this._seen = null;
    this._built = false;
    if (this.shadowRoot) this._build();
  }

  set hass(h) {
    const old = this._hass;
    this._hass = h;
    if (!this._built) this._build();
    if (this._stale(old, h)) this._render();
  }

  _stale(old, h) {
    if (!old || !this._seen || old.config !== h.config || old.locale !== h.locale) return true;
    for (const id of this._seen) if (old.states[id] !== h.states[id]) return true;
    return false;
  }

  connectedCallback() {
    if (!this._built && this._config) this._build();
    clearInterval(this._tick);
    this._tick = setInterval(() => { this._seen = null; this._render(); }, 15000);
    if (this._hass) this._render();
  }

  disconnectedCallback() {
    clearInterval(this._tick);
    this._tick = null;
    clearTimeout(this._armTimer);
    this._armTimer = null;
    clearTimeout(this._toastTimer);
  }

  getCardSize() { return 12; }

  _build() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    if (!this._listening) {
      this._listening = true;
      this.shadowRoot.addEventListener('click', (ev) => this._onClick(ev));
      this.shadowRoot.addEventListener('change', (ev) => this._onChange(ev));
    }
    this.shadowRoot.innerHTML = `<style>${SSC_CSS}</style>${SSC_HTML}`;
    this._$ = (s) => this.shadowRoot.querySelector(s);
    if (!document.getElementById('edc-inter-font')) {
      const l = document.createElement('link');
      l.id = 'edc-inter-font';
      l.rel = 'stylesheet';
      l.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
      document.head.appendChild(l);
    }
    this._armed = null;
    this._seen = null;
    this._built = true;
  }

  // ---------- helpers ----------
  _st(id) { if (this._seen && id) this._seen.add(id); return id && this._hass ? this._hass.states[id] : undefined; }
  _tz() { return (this._hass && this._hass.config && this._hass.config.time_zone) || undefined; }
  _df(opts) {
    const key = `${this._tz()}|${JSON.stringify(opts)}`;
    this._dfs = this._dfs || new Map();
    let f = this._dfs.get(key);
    if (!f) { f = new Intl.DateTimeFormat('en-GB', { timeZone: this._tz(), ...opts }); this._dfs.set(key, f); }
    return f;
  }
  _hm(iso) {
    if (!iso) return '–';
    const d = iso instanceof Date ? iso : new Date(iso);
    return isNaN(d) ? '–' : this._df({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d);
  }
  _dur(min) {
    if (min == null || !isFinite(min)) return '–';
    const m = Math.max(0, Math.round(min));
    return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m` : `${m}m`;
  }
  _t(v, dp) { return v == null || !isFinite(v) ? '–' : (dp ? Number(v).toFixed(dp) : String(Math.round(v))); }
  _html(el, html) { if (el && el.__k !== html) { el.innerHTML = html; el.__k = html; } }
  _complain(msg) {
    this._complaints = this._complaints || new Set();
    if (this._complaints.has(msg)) return;
    this._complaints.add(msg);
    console.error(`${SSC_TAG}: ${msg}`);
  }
  _toast(msg) {
    const el = this._$('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.hidden = true; }, 8000);
  }
  _call(domain, service, data) {
    return this._hass.callService(domain, service, data).catch((err) => {
      const msg = (err && (err.message || err.code)) || String(err);
      console.error(`${SSC_TAG}: ${domain}.${service} failed: ${msg}`);
      this._toast(`Couldn't do that: ${msg}`);
    });
  }
  _ent(key) { return (this._a.entities || {})[key]; }
  _btn(act, icon, text, cls, extra) {
    return `<button class="btn ${cls || ''}" data-act="${act}" ${extra || ''}><ha-icon icon="${icon}"></ha-icon><span>${sscEsc(text)}</span></button>`;
  }

  // Two-tap confirm for anything that's hard to undo: first tap arms the button for 4 s
  _confirm(act) {
    if (this._armed === act) { this._armed = null; clearTimeout(this._armTimer); return true; }
    this._armed = act;
    clearTimeout(this._armTimer);
    this._armTimer = setTimeout(() => { this._armed = null; this._seen = null; this._render(); }, 4000);
    this._seen = null;
    this._render();
    return false;
  }

  // ---------- events ----------
  _onClick(ev) {
    const b = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!b || b.disabled || !this._a) return;
    const act = b.dataset.act;
    const press = (key) => { const id = this._ent(key); if (!id) { this._toast(`Missing entity for ${key}`); return; } this._call('button', 'press', { entity_id: id }); };
    if (act === 'next') { if (this._confirm('next')) press('next_step'); return; }
    if (act === 'start') { if (this._confirm('start')) press('start_session'); return; }
    if (act === 'end') {
      if (!this._confirm('end')) return;
      const notes = this._$('#endnote').value.trim();
      this._call('smoke_session', 'end_session', notes ? { notes } : {}).then(() => { this._$('#endnote').value = ''; });
      return;
    }
    if (act === 'reset') { if (this._confirm('reset')) this._call('smoke_session', 'reset', {}); return; }
    if (act === 'log') {
      const type = b.dataset.type;
      const note = this._$('#note').value.trim();
      if (type === 'note' && !note) { this._toast('Type the note first.'); return; }
      this._call('smoke_session', 'log_event', note ? { event_type: type, note } : { event_type: type }).then(() => { this._$('#note').value = ''; });
      return;
    }
    if (act === 'vent') { this._call('select', 'select_option', { entity_id: this._ent('bottom_vents'), option: b.dataset.v }); return; }
    if (act === 'cook') { this._call('select', 'select_option', { entity_id: this._ent('cook'), option: b.dataset.v }); return; }
    if (act === 'wt') {
      const cur = Number(this._a.weight_kg) || 0;
      const v = Math.max(0.1, Math.round((cur + Number(b.dataset.d)) * 10) / 10);
      this._call('number', 'set_value', { entity_id: this._ent('meat_weight'), value: v });
    }
  }

  _onChange(ev) {
    const t = ev.target;
    if (!t || !this._a) return;
    if (t.id === 'start-time' && t.value) this._call('time', 'set_value', { entity_id: this._ent('planned_start'), time: `${t.value}:00` });
    if (t.id === 'probe') this._call('select', 'select_option', { entity_id: this._ent('meat_probe'), option: t.value });
  }

  // ---------- render ----------
  _render() {
    if (!this._hass || !this._built) return;
    this._seen = new Set();
    const s = this._st(this._config.entity);
    const err = this._$('#err');
    if (!s) {
      this._complain(`${this._config.entity} not found — is the Smoke Session integration loaded?`);
      err.hidden = false;
      err.textContent = `${this._config.entity} not found. Is the Smoke Session integration set up and loaded?`;
      ['#head', '#idle', '#active', '#done'].forEach((x) => { this._$(x).hidden = true; });
      return;
    }
    err.hidden = true;
    this._a = s.attributes || {};
    this._$('#head').hidden = false;
    // Read the source probes too, so their changes redraw the card
    this._st(this._a.pit_entity);
    this._st(this._a.meat_entity);
    Object.values(this._a.entities || {}).forEach((id) => this._st(id));
    const state = s.state;
    this._renderHead(state);
    this._$('#idle').hidden = state !== 'idle';
    this._$('#active').hidden = state !== 'active';
    this._$('#done').hidden = state !== 'finished';
    if (state === 'idle') this._renderSetup();
    if (state === 'active') {
      this._renderNow();
      this._renderPit();
      this._renderMeat();
      this._renderLog();
      this._renderTimeline(this._$('#timeline'));
      this._renderEvents(this._$('#events'));
      const end = this._$('[data-act="end"]');
      end.classList.toggle('arm', this._armed === 'end');
      end.querySelector('span').textContent = this._armed === 'end' ? 'Tap again to end' : 'End session';
    }
    if (state === 'finished') {
      this._renderSummary();
      this._renderTimeline(this._$('#timeline2'));
      this._renderEvents(this._$('#events2'));
    }
  }

  _renderHead(state) {
    const a = this._a;
    const words = { idle: ['Ready', SSC_COL.dim], active: ['Cooking', SSC_COL.good], finished: ['Finished', SSC_COL.blue] };
    const [w, col] = words[state] || [state, SSC_COL.dim];
    const phases = a.phases || [];
    const last = phases[phases.length - 1];
    const finish = state === 'finished' ? a.finished_at : last && last.projected_end;
    const chips = [];
    if (state === 'active' && a.cook_started) chips.push(`<span class="chip">Cooking <b>${this._dur(a.elapsed_min)}</b></span>`);
    if (state === 'active' && !a.cook_started) chips.push(`<span class="chip">Starts <b>${this._hm(a.planned_start)}</b></span>`);
    if (state !== 'idle' && finish) chips.push(`<span class="chip">${state === 'finished' ? 'Finished' : 'Eat about'} <b>${this._hm(finish)}</b></span>`);
    if (state !== 'idle') chips.push(`<span class="chip">${sscEsc(a.weight_kg)} kg</span>`);
    this._html(this._$('#head'),
      `<div class="label"><span>Smoke session</span><span style="color:${col}">${w}</span></div>` +
      `<div class="row" style="justify-content:space-between"><h1>${sscEsc(a.profile || '–')}</h1><div class="row">${chips.join('')}</div></div>`);
  }

  _renderSetup() {
    const a = this._a;
    const probeSel = this._ent('meat_probe') ? this._st(this._ent('meat_probe')) : null;
    const startSel = this._st(this._ent('planned_start'));
    const cooks = Object.values(a.profiles || {});
    const startVal = startSel && startSel.state ? startSel.state.slice(0, 5) : '';
    const probeOpts = probeSel ? (probeSel.attributes.options || []) : [];
    const probeName = (id) => { const st = this._st(id); return (st && st.attributes.friendly_name) || id; };
    const phases = a.phases || [];
    const plan = phases.map((p) => `<div class="ph"><span class="dot"></span><span class="nm">${sscEsc(p.name)}</span><span class="tm">${this._hm(p.planned_start)} – ${this._hm(p.planned_end)}</span></div>`).join('');
    const armed = this._armed === 'start';
    const el = this._$('#setup');
    // Keep the time input and probe select if they're already there (don't steal focus mid-edit)
    const key = JSON.stringify([cooks, a.profile, a.weight_kg, startVal, probeOpts, a.meat_entity, plan, armed]);
    if (el.__k === key) return;
    const focused = this.shadowRoot.activeElement && this.shadowRoot.activeElement.id;
    if (focused === 'start-time' || focused === 'probe') return;
    el.__k = key;
    el.innerHTML =
      `<div class="label">Set up the cook</div>` +
      `<div class="row">${cooks.map((n) => this._btn('cook', n === a.profile ? 'mdi:check' : 'mdi:food-drumstick-outline', n, n === a.profile ? 'on' : '', `data-v="${sscEsc(n)}"`)).join('')}</div>` +
      `<div class="row" style="align-items:flex-end">` +
      `<div class="field"><span>Meat weight</span><div class="row" style="flex-wrap:nowrap">${this._btn('wt', 'mdi:minus', '', '', 'data-d="-0.1"')}<div class="big" style="font-size:32px;min-width:110px;text-align:center">${sscEsc(a.weight_kg)}<small> kg</small></div>${this._btn('wt', 'mdi:plus', '', '', 'data-d="0.1"')}</div></div>` +
      `<label class="field"><span>Light the chimney at</span><input type="time" id="start-time" value="${sscEsc(startVal)}"></label>` +
      (probeOpts.length ? `<label class="field"><span>Probe in the meat</span><select id="probe">${probeOpts.map((o) => `<option value="${sscEsc(o)}" ${o === a.meat_entity ? 'selected' : ''}>${sscEsc(probeName(o))}</option>`).join('')}</select></label>` : '') +
      `</div>` +
      `<div class="label" style="margin-top:6px">Plan</div><div class="tl">${plan}</div>` +
      `<div class="row">${this._btn('start', 'mdi:play', armed ? 'Tap again to start' : 'Start session', `primary ${armed ? 'arm' : ''}`)}` +
      `<span class="sub">Reminders start 15 minutes before the planned start. Pit alerts switch on once the pit is stable.</span></div>`;
  }

  _renderNow() {
    const a = this._a;
    const c = a.current_step || {};
    const cur = (a.phases || []).find((p) => p.status === 'current');
    const armed = this._armed === 'next';
    const nxt = a.next_reminder;
    let auto = '';
    if (c.auto === 'pit_stable') auto = `<div class="auto"><ha-icon icon="mdi:timer-sand" style="--mdc-icon-size:16px"></ha-icon> Finishes by itself once the pit holds ${this._t(a.pit_band && a.pit_band.target_low)}–${this._t(a.pit_band && a.pit_band.target_high)}°C.</div>`;
    this._html(this._$('#now'),
      `<div class="label"><span>${sscEsc(cur ? cur.name : '')} · step ${sscEsc(c.step_number || '–')} of ${sscEsc(c.steps_in_phase || '–')}</span><span>since ${this._hm(c.step_started)}</span></div>` +
      `<h2>${sscEsc(c.title || '–')}</h2>` +
      `<div class="step-detail">${sscEsc(c.detail || '')}</div>${auto}` +
      `<div class="row">${this._btn('next', armed ? 'mdi:check-bold' : 'mdi:check', armed ? 'Tap again to confirm' : 'Done', `primary ${armed ? 'arm' : ''}`)}` +
      (c.next_step ? `<span class="step-meta">Next: ${sscEsc(c.next_step)}</span>` : '') + `</div>` +
      (nxt ? `<div class="chip" style="align-self:flex-start"><ha-icon icon="mdi:bell-outline"></ha-icon>${sscEsc(nxt.title)} <b>${this._hm(nxt.due)}</b></div>` : ''));
  }

  _renderPit() {
    const a = this._a;
    const b = a.pit_band || {};
    const [word, col] = SSC_PIT[a.pit_status] || ['–', SSC_COL.dim];
    const lo = b.alert_low - 15;
    const hi = b.alert_high + 15;
    const pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
    const seg = (from, to, c) => `<i style="width:${pct(to) - pct(from)}%;background:${c}"></i>`;
    const gauge = seg(lo, b.alert_low, '#4A2418') + seg(b.alert_low, b.target_low, '#4A3A16') + seg(b.target_low, b.target_high, '#1E4D36') +
      seg(b.target_high, b.alert_high, '#4A3A16') + seg(b.alert_high, hi, '#4A2418');
    const marker = a.pit == null ? '' : `<span class="marker" style="left:${pct(a.pit)}%"></span>`;
    const ticks = [b.alert_low, b.target_low, b.target_high, b.alert_high].map((v) => `<span style="left:${pct(v)}%">${this._t(v)}</span>`).join('');
    const trend = a.pit_trend;
    const arrow = trend == null ? '' : trend > 0.5 ? 'mdi:arrow-top-right' : trend < -0.5 ? 'mdi:arrow-bottom-right' : 'mdi:arrow-right';
    let mode = '';
    if (!a.pit_alerts_armed && a.cook_started && !(a.summary)) mode = '<span class="chip"><ha-icon icon="mdi:fire"></ha-icon>Warming up · alerts off</span>';
    if (a.lid_recovering) mode = '<span class="chip" style="color:#F4C06A"><ha-icon icon="mdi:arrow-up-box"></ha-icon>Lid recovery · alerts paused</span>';
    const recCol = /^Holding steady|^In the band/.test(a.recommendation || '') ? ['rgba(107,214,155,.12)', SSC_COL.good, 'mdi:check-circle-outline']
      : ['rgba(244,192,106,.12)', SSC_COL.warn, 'mdi:lightbulb-on-outline'];
    this._html(this._$('#pit'),
      `<div class="label"><span>Pit · grate</span><span style="color:${col}">${word}</span></div>` +
      `<div class="row" style="justify-content:space-between;align-items:flex-end"><div class="big" style="color:${col}">${this._t(a.pit, 0)}<small>°C</small></div>` +
      `<div class="row">${trend == null ? '<span class="chip">Trend building…</span>' : `<span class="chip"><ha-icon icon="${arrow}"></ha-icon><b>${trend > 0 ? '+' : ''}${this._t(trend, 1)}</b>°C / 10 min</span>`}` +
      `<span class="chip">Vents <b>${sscEsc(SSC_VENT_SHORT[SSC_VENTS.indexOf(a.vent)] || a.vent)}</b></span></div></div>` +
      `<div class="gwrap"><div class="gauge">${gauge}</div>${marker}<div class="ticks">${ticks}</div></div>` +
      (mode ? `<div class="row">${mode}</div>` : '') +
      `<div class="rec" style="background:${recCol[0]};color:${recCol[1]}"><ha-icon icon="${recCol[2]}"></ha-icon><span>${sscEsc(a.recommendation || '')}</span></div>`);
  }

  _renderMeat() {
    const a = this._a;
    const alerts = a.meat_alerts || [];
    const thr = alerts.map((x) => `<span class="chip ${x.fired ? 'done' : ''}">${x.fired ? '<ha-icon icon="mdi:check"></ha-icon>' : ''}<b>${this._t(x.temp)}°</b> ${sscEsc(x.title)}</span>`).join('');
    const armed = alerts.length && a.meat != null;
    const eta = a.meat_eta ? `<span class="chip">${this._t(a.meat_eta_target)}°C about <b>${this._hm(a.meat_eta)}</b></span>` : '';
    const rate = a.meat_rate == null ? '' : `<span class="chip"><b>${a.meat_rate > 0 ? '+' : ''}${this._t(a.meat_rate, 1)}</b>°C / h</span>`;
    const stall = a.stall ? `<span class="chip" style="color:#F4C06A"><ha-icon icon="mdi:pause-circle-outline"></ha-icon>Stall</span>` : '';
    const probe = this._st(a.meat_entity);
    const pname = (probe && probe.attributes.friendly_name) || a.meat_entity || 'No meat probe';
    this._html(this._$('#meat'),
      `<div class="label"><span>Meat</span><span>${sscEsc(pname)}</span></div>` +
      `<div class="row" style="justify-content:space-between;align-items:flex-end"><div class="big">${this._t(a.meat, 0)}<small>°C</small></div><div class="row">${rate}${eta}${stall}</div></div>` +
      `<div class="thr">${thr}</div>` +
      `<div class="sub">${armed ? 'Doneness is by feel: the probe slides between the bones like soft butter, and the rack bends and cracks when lifted.' : 'Meat alerts start once the meat is on.'}</div>`);
  }

  _renderLog() {
    const a = this._a;
    this._html(this._$('#logbtns'),
      this._btn('log', 'mdi:spray', 'Spritz', '', 'data-type="spritz"') +
      this._btn('log', 'mdi:arrow-up-box', 'Lid opened', '', 'data-type="lid_open"') +
      this._btn('log', 'mdi:needle', 'Probe check', '', 'data-type="probe_check"') +
      this._btn('log', 'mdi:note-text-outline', 'Note', '', 'data-type="note"'));
    this._$('#vent-now').textContent = a.vent || '';
    this._html(this._$('#vents'), SSC_VENTS.map((v, i) => `<button class="btn ${v === a.vent ? 'on' : ''}" data-act="vent" data-v="${v}">${SSC_VENT_SHORT[i]}</button>`).join(''));
  }

  _renderTimeline(el) {
    const a = this._a;
    const rows = (a.phases || []).map((p) => {
      const start = p.actual_start || p.projected_start;
      const end = p.actual_end || p.projected_end;
      const late = !p.actual_end && p.projected_end && p.planned_end && (new Date(p.projected_end) - new Date(p.planned_end)) / 60000;
      const lateTxt = late && late >= 5 ? ` <span style="color:${SSC_COL.warn}">+${Math.round(late)}m</span>` : '';
      const steps = p.status === 'current'
        ? `<div class="steps">${(p.steps || []).map((s) => `<div class="${s.status}">${s.status === 'done' ? '✓' : s.status === 'current' ? '›' : '·'} ${sscEsc(s.title)}</div>`).join('')}</div>`
        : '';
      return `<div class="ph ${p.status}"><span class="dot"></span><span class="nm">${sscEsc(p.name)}</span>` +
        `<span class="tm"><b>${this._hm(start)}–${this._hm(end)}</b>${lateTxt}<br>plan ${this._hm(p.planned_start)}–${this._hm(p.planned_end)}</span></div>${steps}`;
    }).join('');
    this._html(el, `<div class="label">Timeline</div><div class="tl">${rows}</div>`);
  }

  _renderEvents(el) {
    const ev = (this._a.events || []).slice().reverse();
    const rows = ev.map((e) => {
      const temps = [e.pit != null ? `pit ${Math.round(e.pit)}°` : '', e.meat != null ? `meat ${Math.round(e.meat)}°` : ''].filter(Boolean).join(' · ');
      const src = e.source === 'detected' ? ' (detected)' : e.source === 'auto' ? ' (auto)' : '';
      return `<div class="ev"><span class="t">${this._hm(e.ts)}</span><ha-icon icon="${SSC_EVENT_ICON[e.type] || 'mdi:circle-small'}"></ha-icon>` +
        `<span class="w">${sscEsc(e.label)}${src}${e.note ? `<i>${sscEsc(e.note)}</i>` : ''}</span><span class="tp">${temps}</span></div>`;
    }).join('');
    this._html(el, `<div class="label"><span>Cook log</span><span>${ev.length} events</span></div><div class="log">${rows || '<div class="sub">Nothing logged yet.</div>'}</div>`);
  }

  _renderSummary() {
    const a = this._a;
    const sm = a.summary || {};
    const k = sm.key_events || {};
    const stat = (label, v) => `<div class="stat"><div class="k">${sscEsc(label)}</div><div class="v">${v}</div></div>`;
    const at = (key, what) => (k[key] ? `${this._hm(k[key].ts)}${what === 'meat' && k[key].meat != null ? ` · ${Math.round(k[key].meat)}°` : ''}` : '–');
    const armed = this._armed === 'reset';
    const notes = (a.events || []).filter((e) => e.type === 'session_end' && e.note).map((e) => e.note)[0];
    this._html(this._$('#summary'),
      `<div class="label">Summary</div>` +
      `<div class="stats">` +
      stat('Cook time', this._dur(a.elapsed_min)) +
      stat('Time to stable', sm.minutes_to_stable == null ? '–' : `${sm.minutes_to_stable}m`) +
      stat(`Pit in ${this._t(a.pit_band && a.pit_band.target_low)}–${this._t(a.pit_band && a.pit_band.target_high)}`, sm.pit_in_target_pct == null ? '–' : `${sm.pit_in_target_pct}%`) +
      stat('Pit in alert band', sm.pit_in_alert_band_pct == null ? '–' : `${sm.pit_in_alert_band_pct}%`) +
      stat('Pit range', sm.pit_min == null ? '–' : `${Math.round(sm.pit_min)}–${Math.round(sm.pit_max)}°`) +
      stat('Lid openings', this._t(sm.lid_openings)) +
      stat('Vent changes', this._t(sm.vent_adjustments)) +
      stat('Wrapped', at('wrap', 'meat')) +
      stat('Probe-tender', at('probe_tender', 'meat')) +
      `</div>` +
      (notes ? `<div class="sub"><b style="color:${SSC_COL.text}">Result:</b> ${sscEsc(notes)}</div>` : '') +
      `<div class="sub">The full log is available from the smoke_session.get_session action.</div>` +
      `<div class="row">${this._btn('reset', 'mdi:restart', armed ? 'Tap again to clear' : 'Clear for the next cook', armed ? 'danger arm' : 'danger')}</div>`);
  }
}

if (!customElements.get(SSC_TAG)) {
  customElements.define(SSC_TAG, SmokeSessionCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: SSC_TAG, name: 'Smoke Session Card', description: 'Guided smoker cook: steps, pit and meat, alerts, log' });
  console.info(`%c ${SSC_TAG} %c v${SSC_VERSION} `, 'background:#F4C06A;color:#0A0E13;font-weight:700', 'background:#121820;color:#E6EBF0');
}

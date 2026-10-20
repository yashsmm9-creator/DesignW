/* EduAdapt client-side behaviour — no external dependencies. */
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /* ---------- Navigation drawer (mobile) ---------- */
  $$('[data-nav-toggle]').forEach(b => b.addEventListener('click', () => document.body.classList.toggle('nav-open')));

  /* ---------- Flash toasts ---------- */
  $$('[data-flash]').forEach(el => {
    const close = () => { el.style.transition = 'opacity .3s, transform .3s'; el.style.opacity = '0'; el.style.transform = 'translateY(-6px)'; setTimeout(() => el.remove(), 300); };
    $('[data-flash-close]', el)?.addEventListener('click', close);
    if (el.parentElement.classList.contains('flash-stack')) setTimeout(close, 5500);
  });

  /* ---------- Password show / hide ---------- */
  $$('[data-toggle-pw]').forEach(btn => btn.addEventListener('click', () => {
    const input = btn.parentElement.querySelector('input');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.querySelector('use').setAttribute('href', show ? '#i-eyeoff' : '#i-eye');
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  }));

  /* ---------- Demo account autofill ---------- */
  $$('[data-demo]').forEach(btn => btn.addEventListener('click', () => {
    $('input[name=email]').value = 'demo@eduadapt.com';
    $('input[name=password]').value = 'Demo@12345';
    const phone = $('input[name=phone]'); if (phone) phone.value = '+919999999999';
    $('input[name=password]').focus();
  }));

  /* ---------- Range slider live value ---------- */
  $$('input[type=range][data-output]').forEach(r => {
    const out = document.getElementById(r.dataset.output);
    const sync = () => { if (out) out.textContent = r.value + '%'; };
    r.addEventListener('input', sync); sync();
  });

  /* ---------- Live search / filter (syllabus + tests) ---------- */
  window.initFilter = function () {
    const q = $('#filterQ'), subj = $('#filterSubject'), items = $$('[data-item]'), groups = $$('[data-group]');
    const count = $('#filterCount'), none = $('#noResults');
    if (!q) return;
    const run = () => {
      const term = q.value.trim().toLowerCase(), s = subj ? subj.value : '';
      let shown = 0;
      items.forEach(it => {
        const ok = (!term || it.dataset.item.includes(term) || it.dataset.subject.toLowerCase().includes(term)) && (!s || it.dataset.subject === s);
        it.hidden = !ok; if (ok) shown++;
      });
      groups.forEach(g => {
        const any = $$('[data-item]', g).some(i => !i.hidden);
        g.hidden = !any;
        if (g.tagName === 'DETAILS' && (term || s)) g.open = any;
      });
      if (count) count.textContent = shown + ' topic' + (shown === 1 ? '' : 's');
      if (none) none.classList.toggle('show', shown === 0);
    };
    q.addEventListener('input', run); subj && subj.addEventListener('change', run); run();
  };

  /* ---------- Test taking: timer, answered progress, leave warning ---------- */
  window.startTestTimer = function () {
    const form = $('#testForm'); if (!form) return;
    const timer = $('#timerText'), bar = $('#answerBar'), label = $('#answerLabel');
    const total = $$('.question-card', form).length;
    const t0 = Date.now();
    setInterval(() => {
      const s = Math.floor((Date.now() - t0) / 1000);
      timer.textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    }, 1000);
    let submitting = false;
    const update = () => {
      const done = $$('.question-card', form).filter(c => c.querySelector('input:checked'));
      $$('.question-card', form).forEach(c => c.classList.toggle('answered', !!c.querySelector('input:checked')));
      bar.style.width = (done.length * 100 / total) + '%';
      label.textContent = done.length + ' / ' + total + ' answered';
      return done.length;
    };
    form.addEventListener('change', e => {
      const n = update();
      const card = e.target.closest('.question-card');
      const next = card && card.nextElementSibling;
      if (next && next.classList.contains('question-card') && !next.classList.contains('answered') && n < total) {
        setTimeout(() => next.scrollIntoView({ behavior: 'smooth', block: 'center' }), 250);
      }
    });
    form.addEventListener('submit', () => { submitting = true; });
    window.addEventListener('beforeunload', e => { if (!submitting && update() > 0) { e.preventDefault(); e.returnValue = ''; } });
    update();
  };

  /* ---------- Result gauge animation ---------- */
  window.animateGauge = function (pct) {
    const fg = $('.gauge .fg'); if (!fg) return;
    const len = 2 * Math.PI * 64; fg.style.strokeDasharray = len; fg.style.strokeDashoffset = len;
    requestAnimationFrame(() => requestAnimationFrame(() => { fg.style.strokeDashoffset = len * (1 - pct / 100); }));
  };

  /* ---------- Progress line chart (dependency-free SVG) ---------- */
  window.renderChart = function (el, data) {
    if (!el || !data.length) return;
    const W = 900, H = 300, m = { t: 16, r: 18, b: 34, l: 40 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const x = i => m.l + (data.length === 1 ? iw / 2 : i * iw / (data.length - 1));
    const y = v => m.t + ih - (v / 100) * ih;
    let g = '';
    [0, 25, 50, 75, 100].forEach(t => {
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="#e2e8f0" stroke-dasharray="${t ? '3 5' : ''}"/><text x="${m.l - 10}" y="${y(t) + 4}" text-anchor="end" font-size="11" fill="#94a3b8">${t}%</text>`;
    });
    const pts = data.map((d, i) => [x(i), y(d.value)]);
    const smooth = pts.map((p, i) => {
      if (!i) return `M${p[0]},${p[1]}`;
      const q = pts[i - 1], cx = (q[0] + p[0]) / 2;
      return `C${cx},${q[1]} ${cx},${p[1]} ${p[0]},${p[1]}`;
    }).join(' ');
    const area = `${smooth} L${pts[pts.length - 1][0]},${y(0)} L${pts[0][0]},${y(0)} Z`;
    const step = Math.ceil(data.length / 8);
    const uniqueDays = new Set(data.map(d => d.label)).size === data.length;
    const xl = data.map((d, i) => i % step === 0 ? `<text x="${x(i)}" y="${H - 10}" text-anchor="middle" font-size="11" fill="#94a3b8">${uniqueDays ? d.label.slice(5) : '#' + (i + 1)}</text>` : '').join('');
    const dots = pts.map((p, i) => `<circle class="pt" data-i="${i}" cx="${p[0]}" cy="${p[1]}" r="5" fill="#fff" stroke="#4f46e5" stroke-width="2.5"/><circle data-i="${i}" cx="${p[0]}" cy="${p[1]}" r="16" fill="transparent"/>`).join('');
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Test scores over time">
      <defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#6366f1" stop-opacity=".28"/><stop offset="1" stop-color="#6366f1" stop-opacity="0"/></linearGradient></defs>
      ${g}${data.length > 1 ? `<path d="${area}" fill="url(#ga)"/>` : ''}<path d="${smooth}" fill="none" stroke="#4f46e5" stroke-width="3" stroke-linecap="round"/>${dots}${xl}</svg><div class="chart-tip"></div>`;
    const tip = $('.chart-tip', el);
    $$('circle[data-i]', el).forEach(c => {
      c.addEventListener('mouseenter', () => {
        const d = data[+c.dataset.i], r = c.getBoundingClientRect(), p = el.getBoundingClientRect();
        tip.innerHTML = `<b>${d.value}%</b>${d.topic}<br>${d.label}`;
        tip.style.left = (r.left + r.width / 2 - p.left) + 'px'; tip.style.top = (r.top - p.top) + 'px'; tip.style.opacity = 1;
      });
      c.addEventListener('mouseleave', () => { tip.style.opacity = 0; });
    });
  };

  /* ---------- Reminders: voice + notification + visual alarm ---------- */
  function updatePerm() {
    const el = $('#permStatus'); if (!el) return;
    const ok = 'Notification' in window && Notification.permission === 'granted';
    el.classList.toggle('on', ok);
    el.querySelector('span').textContent = ok ? 'Voice & notifications enabled' : 'Not enabled yet — click “Enable voice alarm”';
  }
  window.enableNotifications = async function () {
    if ('Notification' in window && Notification.permission === 'default') { try { await Notification.requestPermission(); } catch (e) {} }
    if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance('Voice reminders are enabled.'); speechSynthesis.speak(u); } catch (e) {} }
    updatePerm();
  };
  function beep() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
      const c = new AC(), o = c.createOscillator(), g = c.createGain();
      o.type = 'sine'; o.frequency.value = 880; g.gain.value = .12; o.connect(g); g.connect(c.destination); o.start();
      setTimeout(() => o.frequency.value = 660, 300); setTimeout(() => { o.stop(); c.close(); }, 900);
    } catch (e) {}
  }
  function speak(text) {
    if (!('speechSynthesis' in window)) return;
    try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.rate = .92; speechSynthesis.speak(u); } catch (e) {}
  }
  window.showAlarm = function (title) {
    const ov = $('#alarmOverlay'), tx = $('#alarmText');
    if (ov) { if (tx) tx.textContent = title + ' — your scheduled study session is starting.'; ov.classList.add('show'); beep(); }
    else { beep(); alert('Study time!\n\n' + title); }
    if ('Notification' in window && Notification.permission === 'granted') {
      try { new Notification('EduAdapt — Study time', { body: title + ' is starting now.' }); } catch (e) {}
    }
  };
  window.dismissAlarm = function () { const ov = $('#alarmOverlay'); if (ov) ov.classList.remove('show'); try { speechSynthesis.cancel(); } catch (e) {} };
  window.testAlarm = function () { speak('Study reminder. This is a test. It is time to study.'); showAlarm('Test reminder'); };

  async function checkReminders() {
    try {
      const res = await fetch('/api/reminders', { cache: 'no-store', credentials: 'same-origin' });
      if (!res.ok) return;
      for (const r of await res.json()) {
        if (!r.due) continue;
        const key = 'eduadapt-fired-' + r.id + '-' + r.due_at;
        try { if (localStorage.getItem(key)) continue; localStorage.setItem(key, '1'); } catch (e) {}
        speak('Study reminder. ' + r.title + '. It is time to study.');
        showAlarm(r.title);
        await fetch('/api/reminders/' + r.id + '/fired', { method: 'POST', credentials: 'same-origin' });
      }
    } catch (e) {}
  }

  async function checkDailyTargets() {
    try {
      const res = await fetch('/api/daily-targets', { cache: 'no-store', credentials: 'same-origin' });
      if (!res.ok) return;
      const now = new Date();
      const today = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
      const currentTime = String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0');
      for (const target of await res.json()) {
        if (target.completed_today || !target.daily_reminder_time || currentTime < target.daily_reminder_time) continue;
        const key = 'eduadapt-target-alarm-' + target.id + '-' + today;
        try { if (localStorage.getItem(key)) continue; localStorage.setItem(key, '1'); } catch (e) {}
        speak('Daily study target reminder. ' + target.title + '. You planned ' + target.daily_minutes + ' minutes of study today.');
        showAlarm('Daily target: ' + target.title);
      }
    } catch (e) {}
  }

  document.addEventListener('DOMContentLoaded', () => {
    updatePerm();
    if ($('#alarmOverlay')) { checkReminders(); setInterval(checkReminders, 10000); }
    initFilter();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { dismissAlarm(); document.body.classList.remove('nav-open'); } });
})();

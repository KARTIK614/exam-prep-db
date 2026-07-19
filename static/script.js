/* ═══════════════════════════════════════════════════════════
   Exam Platform — Frontend JS
   ═══════════════════════════════════════════════════════════ */

// Global 401 handler: any fetch that comes back Unauthorized redirects to /login.
(function () {
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await origFetch(...args);
    if (resp.status === 401) {
      window.location.href = '/login';
    }
    return resp;
  };
})();

// ─── Theme (dark/light) ──────────────────────────────────
// The initial theme-set runs inline in each template <head> to avoid
// flash-of-wrong-theme. These helpers handle the toggle button.
window.setTheme = function (t) {
  try { localStorage.setItem('theme', t); } catch (_e) { /* ignore */ }
  document.documentElement.dataset.theme = t;
  _refreshThemeButtons();
};
window.toggleTheme = function () {
  const cur = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  window.setTheme(cur === 'dark' ? 'light' : 'dark');
};
function _refreshThemeButtons() {
  const isDark = document.documentElement.dataset.theme === 'dark';
  document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
    const icon = btn.querySelector('.theme-icon');
    const label = btn.querySelector('.theme-label');
    if (icon) icon.textContent = isDark ? '☀' : '☽';  // sun in dark, moon in light
    if (label) label.textContent = isDark ? 'Light mode' : 'Dark mode';
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  });
}
document.addEventListener('DOMContentLoaded', _refreshThemeButtons);

// ─── Resolve Error ────────────────────────────────────────
let pendingResolveId = null;

function resolveError(errorId) {
  pendingResolveId = errorId;
  document.getElementById('resolve-id').textContent = errorId;
  document.getElementById('resolve-modal').style.display = 'flex';
}

async function confirmResolve() {
  const rootCause = document.getElementById('root-cause').value;
  const notes = document.getElementById('resolve-notes').value;
  const cause = [rootCause, notes].filter(Boolean).join('. ');

  const resp = await fetch('/api/resolve_error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ error_id: pendingResolveId, root_cause: cause })
  });

  if (resp.ok) {
    document.getElementById('resolve-modal').style.display = 'none';
    location.reload();
  }
}

// ─── Redo Error ───────────────────────────────────────────
let pendingRedoId = null;
let pendingRedoAttempt = null;

function redoError(errorId, attempt) {
  pendingRedoId = errorId;
  pendingRedoAttempt = attempt;
  document.getElementById('redo-modal').style.display = 'flex';
}

async function confirmRedo(score) {
  const resp = await fetch('/api/redo_error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      error_id: pendingRedoId,
      attempt: pendingRedoAttempt,
      score: score
    })
  });

  if (resp.ok) {
    document.getElementById('redo-modal').style.display = 'none';
    location.reload();
  }
}

// ─── Study Session Logger ─────────────────────────────────
async function logStudySession(topicId, duration, mcqs, score, notes) {
  const resp = await fetch('/api/study_session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic_id: topicId,
      duration: duration,
      mcqs: mcqs,
      score: score || 0,
      notes: notes || ''
    })
  });
  return resp.ok;
}

// ─── Settings ─────────────────────────────────────────────
async function updateSettings(settings) {
  const resp = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  });
  return resp.ok;
}

// ─── Close modals on Escape ───────────────────────────────
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
  }
});

// Close modals on overlay click
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
  }
});

// ─── Formatting Utilities ─────────────────────────────────
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}

function formatDate(isoString) {
  const d = new Date(isoString);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

// ─── Confetti / Achievement Animation ─────────────────────
function showAchievement(text) {
  const el = document.createElement('div');
  el.style.cssText = `
    position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
    background: #059669; color: #fff; padding: 16px 32px;
    border-radius: 12px; font-size: 18px; font-weight: 700;
    z-index: 9999; box-shadow: 0 8px 32px rgba(5,150,105,0.3);
    animation: slideDown 0.4s ease-out;
  `;
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// Add keyframe for achievement toast
const style = document.createElement('style');
style.textContent = `
  @keyframes slideDown {
    from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }
`;
document.head.appendChild(style);

// ─── Global search (Cmd/Ctrl-K) ──────────────────────────
// Opens the search modal from any page. Debounces keystrokes.
(function () {
  let searchTimer = null;
  let activeIdx = -1;
  let lastResults = [];

  function ensureModal() {
    let overlay = document.getElementById('global-search-modal');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'global-search-modal';
    overlay.className = 'search-modal-overlay';
    overlay.innerHTML = `
      <div class="search-modal" role="dialog" aria-label="Search question bank">
        <div class="search-modal-header">
          <span class="search-modal-icon" aria-hidden="true">&#128269;</span>
          <input type="text" class="search-modal-input" id="global-search-input"
                 placeholder="Search 3,712 questions… (topic keywords, phrases)"
                 autocomplete="off" spellcheck="false">
          <span class="search-modal-hint">Esc</span>
        </div>
        <div class="search-modal-body" id="global-search-results">
          <div class="search-modal-status">Type to search across the question bank.</div>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    // Click outside → close.
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeSearch();
    });

    const input = overlay.querySelector('#global-search-input');
    input.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => runSearch(input.value.trim()), 250);
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { closeSearch(); return; }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        moveActive(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        moveActive(-1);
      } else if (e.key === 'Enter') {
        if (activeIdx >= 0 && lastResults[activeIdx]) {
          e.preventDefault();
          openResult(lastResults[activeIdx]);
        }
      }
    });
    return overlay;
  }

  function moveActive(delta) {
    if (!lastResults.length) return;
    activeIdx = (activeIdx + delta + lastResults.length) % lastResults.length;
    document.querySelectorAll('.search-result').forEach((el, i) => {
      el.classList.toggle('active', i === activeIdx);
      if (i === activeIdx) el.scrollIntoView({ block: 'nearest' });
    });
  }

  function openResult(r) {
    // No dedicated per-question route yet — open /search?q=<query>&highlight=id
    // OR go to /bookmarks list. For now, fall back to running /search page.
    window.location.href = '/search?q=' + encodeURIComponent(r._query || '');
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderResults(query, data) {
    const body = document.getElementById('global-search-results');
    if (!body) return;
    if (!data || data.error) {
      body.innerHTML = `<div class="search-modal-status">Error: ${escapeHtml(data && data.error || 'unknown')}</div>`;
      lastResults = [];
      return;
    }
    if (!data.results || !data.results.length) {
      body.innerHTML = `<div class="search-modal-status">No matches for "${escapeHtml(query)}".</div>`;
      lastResults = [];
      return;
    }
    const parts = [];
    parts.push(`<div class="search-modal-status">${data.total} match${data.total === 1 ? '' : 'es'} · showing top ${data.results.length}</div>`);
    data.results.forEach((r, i) => {
      r._query = query;
      const opts = ['A', 'B', 'C', 'D'].map(L => {
        const key = 'option_' + L.toLowerCase();
        const txt = r[key] || '';
        const isCorrect = r.correct_option === L;
        const cls = isCorrect ? 'correct-opt' : '';
        return `<span class="${cls}"><strong>${L}.</strong> ${escapeHtml(txt).slice(0, 80)}</span>`;
      }).join('');
      parts.push(`
        <div class="search-result" data-idx="${i}" data-qid="${r.id}">
          <div class="search-result-meta">
            <span class="badge badge-muted">#${r.id}</span>
            <span>${escapeHtml(r.topic_name || '')}</span>
            <span>· ${escapeHtml(r.difficulty || '')}</span>
            ${r.pyq_exam ? `<span>· PYQ ${escapeHtml(r.pyq_exam)} ${escapeHtml(String(r.pyq_year || ''))}</span>` : ''}
          </div>
          <div class="search-result-text">${r.snippet || escapeHtml((r.question_text || '').slice(0, 220))}</div>
          <div class="search-result-options">${opts}</div>
        </div>
      `);
    });
    body.innerHTML = parts.join('');
    lastResults = data.results;
    activeIdx = -1;

    // Click a row → go to search page (until per-question route exists).
    document.querySelectorAll('.search-result').forEach((el, i) => {
      el.addEventListener('click', () => openResult(lastResults[i]));
    });
  }

  async function runSearch(query) {
    const body = document.getElementById('global-search-results');
    if (!query) {
      body.innerHTML = '<div class="search-modal-status">Type to search across the question bank.</div>';
      lastResults = [];
      return;
    }
    if (query.length < 2) {
      body.innerHTML = '<div class="search-modal-status">Keep typing…</div>';
      return;
    }
    body.innerHTML = '<div class="search-modal-status">Searching…</div>';
    try {
      const resp = await fetch('/api/search?q=' + encodeURIComponent(query) + '&limit=20');
      const data = await resp.json();
      renderResults(query, data);
    } catch (e) {
      renderResults(query, { error: String(e) });
    }
  }

  window.openSearch = function () {
    const overlay = ensureModal();
    overlay.classList.add('open');
    setTimeout(() => {
      const input = document.getElementById('global-search-input');
      if (input) input.focus();
    }, 10);
  };

  function closeSearch() {
    const overlay = document.getElementById('global-search-modal');
    if (overlay) overlay.classList.remove('open');
  }
  window.closeSearch = closeSearch;

  // Global Cmd-K / Ctrl-K + global Escape to close.
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      window.openSearch();
      return;
    }
    if (e.key === 'Escape') {
      const overlay = document.getElementById('global-search-modal');
      if (overlay && overlay.classList.contains('open')) {
        closeSearch();
      }
    }
  });
})();

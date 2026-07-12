/* ═══════════════════════════════════════════════════════════
   Computer Anudeshak Exam Prep Platform — Frontend JS
   ═══════════════════════════════════════════════════════════ */

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

# Critic Report — Frontend + Content

**Scope:** every `templates/*.html`, `templates/admin/*.html`, `static/style.css`, `static/script.js`, and the DeepSeek/GLM/Gemini backfill pipeline (`scripts/backfill_explanations.py`) that produced the 1,704 explanations.

**Method:** static read-through of all templates and CSS/JS; static analysis of the backfill prompt+pipeline. The originally-planned 30-row live sample against Turso was **not run** — the harness sandbox denied both outbound HTTP (Turso pipeline API) and Python client execution. See section "Content quality — H" for the fallback methodology and per-issue risk estimates.

Note: report generated 2026-07-19; codebase state is commit `b4d0789` (v2 ship).

---

## Severity histogram

| Severity | Count | Findings |
|----------|-------|----------|
| critical | 0     | — (reserved for confirmed exploitable/data-loss bugs) |
| high     | 5     | F01, F02, F05, F06, H01, H03 |
| medium   | 13    | F03, F04, F09, F10, F11, F16, F20, F26, F33, F34, F36, H02, H04, H05, H06 |
| low      | 27    | F07, F08, F12, F13, F14, F15, F17, F18, F19, F21, F22, F23, F24, F25, F27, F28, F29, F30, F31, F32, F35, F37, F38, F39, F40, H07 |

(Total: 47 numbered findings — 40 frontend/code (F01-F40) + 7 content (H01-H07). `critical` is intentionally empty — nothing found rises to the "confirmed exploitable / immediate data loss" bar. Two content items — H01 and H03 — are marked high because they degrade study accuracy, not the app.)

## Top 5 to fix RIGHT NOW for UX

1. **F01 — themed 404/500 pages.** Every stale link or backend hiccup currently drops the user on a white Werkzeug page with no way home. Blocks every other UX polish. (hours)
2. **F02 — session-expired handling on /test/take.** Refresh after session expiry silently 500s. High rate for a mobile study app that gets backgrounded. (minutes)
3. **F33 + F34 — new-user dashboard is misleading.** Zero-tests dashboard shows "0% avg", "No errors — keep up the good work!", and a grey activity strip with no onboarding CTA. Reads like praise for doing nothing. (minutes)
4. **F06 — in-test refresh loses answers visually.** Answers stay on server, but palette + timer reset. Accidental Ctrl+R feels like data loss during a timed test — the highest-anxiety moment of the app. (hours)
5. **H03 — one-shot verifier LLM pass over 1,704 backfilled explanations to catch "explanation contradicts marked correct answer".** Small % of rows, but each one teaches the wrong fact for an exam the user is actively preparing for. (days)

Runner-up: **F10 + F21** — palette accessibility + `:focus-visible` — because they are one small CSS+ARIA change that lifts keyboard-only usability across the whole app.

---

## Findings

<!-- appended incrementally below -->

### F01: No custom 404 / 500 error pages
**Severity:** high
**Category:** E
**Location:** `app.py:14-59` — no `@app.errorhandler` registered; blueprints likewise have none
**Evidence:** `grep -rn "errorhandler\|abort(" app.py bp_*.py` returns zero matches. Flask's default HTML pages (white bg, monospace stack, "The requested URL was not found") are what the user sees on any 404 or unhandled exception. This includes `/results/<bad_id>`, hitting `/test/take` with no session, `/api/*` typos, admin URL typos, etc.
**Impact:** solo user hitting a bad link (or on a stale bookmark after a schema migration) gets a jarring, unbranded page with no nav back. Also leaks Werkzeug/Flask internals in dev.
**Fix:** register `@app.errorhandler(404)` returning a themed template with sidebar + "Back to dashboard" CTA, and `@app.errorhandler(500)` that shows a copyable ref-id (mirror the pattern from `templates/_error_ref.html`).
**Effort:** hours

### F02: `render_template` fails on `test.html` when session has no active test — cryptic Jinja error
**Severity:** high
**Category:** E
**Location:** `bp_tests.py:179-192` (`/test/take`)
**Evidence:** `test.html` unconditionally interpolates `{{ test_id }}` and `{{ total }}` from context. If a user opens `/test/take` in a stale tab after the session was cleared (`/test/finish` was posted, or Flask session expired), the view either 302s to setup or Jinja renders undefined variables. There's no "no active test" empty state; the template body assumes an in-progress test.
**Impact:** browser tab left open overnight → refresh → confused user, no explanation. Common for solo-study patterns (leave tab open, come back).
**Fix:** in `/test/take`, if `session.get("test_id")` is missing/finished, redirect to `/test/setup` with a `flash()` "Your last test was finished — start a new one." Message shows above the form.
**Effort:** minutes

### F03: Sidebar nav duplicated verbatim in 8 templates
**Severity:** medium
**Category:** F
**Location:** `templates/index.html:22-43`, `test.html:19-38`, `test_setup.html:19-38`, `analytics.html:20-39`, `errorlog.html:19-40`, `bookmarks.html:19-38`, `review.html:19-38`, `results.html:20-39`, `search.html:22-41`
**Evidence:** the entire `<aside class="sidebar">` block plus the `<header class="mobile-topbar">` and `<nav class="mobile-bottomnav">` are copy-pasted 9 times. Same for the inline theme-set `<script>` and `<link rel="stylesheet">`. Any nav change (e.g., add a "Notes" link, or rename Bookmarks → Saved) requires editing 9 files. The admin templates already use `{% extends "admin/base.html" %}` — proving Jinja inheritance is viable in this repo.
**Impact:** high maintenance cost; will silently drift (e.g., `review.html` sidebar lacks the SR-due badge that `index.html` has). Already drifting: `index.html:32-34` shows `{% if sr_due_today %}<span class="badge">…</span>{% endif %}`, but the SAME nav in `test.html:29` has no badge — inconsistent.
**Fix:** introduce `templates/base.html` with `{% block content %}` + `{% block extra_head %}`. Migrate the 9 user templates over time (dashboard first).
**Effort:** hours

### F04: Bookmarks list has no CTA when empty — dead-end
**Severity:** medium
**Category:** E
**Location:** `templates/bookmarks.html:63-72`
**Evidence:**
```
<div style="font-size:36px;margin-bottom:8px">☆</div>
<p>No bookmarks yet.</p>
<p class="text-muted">Tap the star at the top-right of any question during a test to save it here.</p>
```
No button. User has to know to click sidebar → Take Test → find a question → star it. For a first-time user this is a dead end because there is no "Start a test" button on the page.
**Fix:** add `<a href="/test/setup" class="btn btn-primary">Start a test</a>` under the copy.
**Effort:** minutes

### F05: `/results/<bad_id>` behaviour undefined — likely 500 with no ref-id
**Severity:** high
**Category:** E
**Location:** `bp_tests.py:335`
**Evidence:** the route fetches `test = db.execute("SELECT ... WHERE id=?", (test_id,)).fetchone()` then references `test.id`, `test.paper`, etc. If `test` is `None` (deleted test, or ID never existed, or ID belonged to another user), the template access `test.id` blows up with an AttributeError → 500 with default Flask page (see F01). No ref-id is emitted, unlike the Gemini path.
**Impact:** any bad URL to /results causes an unrecoverable, un-diagnosable error page.
**Fix:** guard with `if test is None: abort(404)` (once F01 lands, this hands the user the branded 404). Also verify `test.user_id == current_user.id`.
**Effort:** minutes

### F06: In-test refresh loses timer + palette state — silent data loss risk
**Severity:** high
**Category:** E
**Location:** `templates/test.html:243-247, 310-382`
**Evidence:** timer + `answered{}` + `reviewMarks{}` all live in JS globals. On page refresh:
- `timerSeconds` resets to 0 → the current question's time-spent restarts.
- `answered = {}` rebuilds from the DB via subsequent `/api/question/*` calls that return `bookmarked`/`marked_for_review` but no cached "already answered" state. Practice-mode green/red dots on the palette are lost until each question is re-visited.
- If practice mode is on, the correctness dot state is not rehydrated from server (`session_mode = 'practice'` never restores `correct-dot`/`wrong-dot` cells on load).
**Impact:** accidental refresh (Ctrl+R, mobile pull-to-refresh) → user thinks they lost answers even though the server has them. Timer for the current question overreads by up to +90s over reality.
**Fix:** rehydrate on load — one call to `/api/question_states/<test_id>` returning `{[idx]: {selected, is_correct}, ...}` used to seed `answered{}` before `loadQuestion(currentIdx)`. Persist `timerSeconds` per question via short-poll to sessionStorage.
**Effort:** hours

### F07: Test-panel "Finish Test" gives no bailout after last question is graded
**Severity:** low
**Category:** E
**Location:** `templates/test.html:492-503`
**Evidence:** on the last question, `showAnsweredState` renders a "Finish Test ▶" button. If the user changes their mind (wants to re-visit Q3) they must click the palette — but the palette is offscreen on ≤900px where `.test-layout` collapses to `1fr`. The panel goes below the fold; a first-time user won't know to scroll.
**Fix:** on ≤900px, add a persistent "Back to Q N" quick jump above the finish button when there are unanswered/reviewed questions.
**Effort:** hours

### F08: Deep-Dive markdown renderer is unsafe against numbered lists and headings
**Severity:** low
**Category:** F
**Location:** `templates/results.html:464-472`
**Evidence:** the client-side `markdownToHtml` handles only `**bold**`, `*italic*`, `` `code` ``, and `\n → <br>`. Gemini frequently returns bulleted answers with `- ` or `1.` prefixes plus `##` headings. Those pass through verbatim and render as literal `##` in the modal. The Deep Dive prompt (Anthropic-side) has no "plain text only" clause.
**Impact:** ugly output on Deep Dive; users see raw markdown syntax.
**Fix:** either (a) instruct Gemini "plain paragraphs only, no lists, no headings" in the system prompt, or (b) plug in a small markdown lib (marked.js 40kB) and DOM-purify the output. Option (a) is safer and cheaper.
**Effort:** minutes

### F09: Login page is hardcoded to light theme — jarring flash for dark-mode users
**Severity:** medium
**Category:** E (dark mode coverage)
**Location:** `templates/login.html:16-30`
**Evidence:** login.html defines its own `<style>` block with `background: linear-gradient(135deg, #0a0f1e, #1a1040)` and `.card { background: #fff }`. It does NOT use the `--surface`, `--text`, `--bg` tokens, and it does NOT respond to `data-theme="dark"`. It DOES set the theme attribute inline at load, but the styles ignore it. The login card stays hardcoded purple/white in both themes.
**Impact:** minor — but breaks the "everything is theme-aware" promise. Also the login inputs render with 1px `#ddd` border (nearly invisible on the purple bg), and the error box `background:#ffe0e0;color:#c00` is a poor red/white contrast.
**Fix:** either migrate login.html to use root tokens, or accept as-is and remove the inline theme setter (dead code). If keeping: add a `[data-theme="dark"]` block to swap card/input colors.
**Effort:** minutes

### F10: Palette buttons expose no accessible state; keyboard-only navigation of grid is impossible
**Severity:** medium
**Category:** E (accessibility)
**Location:** `templates/test.html:129-138` (palette grid), `static/style.css:645-689`
**Evidence:** `<button class="q-nav-btn state-not-visited" title="Q1 — not visited">1</button>` has:
- No `aria-current="true"` on the currently-loaded question.
- No `aria-label` for state (a screen reader hears "1" with no clue whether answered/wrong/reviewed).
- No `role="grid"`/`role="gridcell"` container.
- No arrow-key movement across the grid — only global Left/Right, which advances by 1, not by row (10 cols).

Additionally, `focus` outline for `.q-nav-btn` isn't explicit; `outline: none` is not set but the default browser outline on a filled button may not be visible against the `state-answered` green.
**Impact:** keyboard-only or screen-reader users get zero context on question state; the palette exists purely for sighted mouse users.
**Fix:** (a) add `aria-current` and `aria-label` on each palette button ("Question 3, answered", "Question 4, marked for review"); (b) add explicit `:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 2px }`; (c) trap ArrowUp/ArrowDown to move by 10 (one row) when focus is inside `.question-nav-grid`.
**Effort:** hours

### F11: Mastery tiles and heatmap cells are un-clickable, un-focusable divs
**Severity:** medium
**Category:** E (accessibility + UX)
**Location:** `templates/index.html:149-173`, `templates/analytics.html:64-90`, `112-136`
**Evidence:** each mastery tile is `<div class="topic-tile tier-weak">…</div>` with no link, no button. Clicking a "weak" tile does nothing — user is told "you're weak on DBMS" but has to hunt for the DBMS filter in Take Test. Same for heatmap cells — a red `Easy × Data Structures` cell isn't clickable.
**Impact:** whole "act on your weakness" loop is broken. The hero card exposes ONE weak topic with a "Practice weakest" button, but the mastery grid (30+ tiles) has none.
**Fix:** wrap each `.topic-tile` in `<a href="/test/setup?topic_id={{ t.id }}&difficulty=…">`. Add `role="button"` + `tabindex="0"` on heatmap cells that filter tests by (topic, difficulty).
**Effort:** hours

### F12: Dark-mode contrast is poor on green/red palette-state cells in dark theme
**Severity:** low
**Category:** E (dark mode)
**Location:** `static/style.css:662-666`
**Evidence:** `.state-answered { background: var(--success); color: #fff }` uses `--success = #3fb984` in dark. White text on `#3fb984` yields a contrast ratio of ~2.3:1 (WCAG minimum for text is 4.5:1). Same for `.state-review { background: var(--info=#a274ff); color: #fff }` — ratio ~2.9:1. The digit "12" on a bright green palette cell is hard to read.
**Impact:** legibility problem in the palette digits during a timed test — the most reading-critical widget.
**Fix:** darken the dark-mode `--success`/`--info`/`--danger` variables to a text-safe shade, OR switch button text to `#000`/`--text` in dark theme.
**Effort:** minutes

### F13: Print CSS omits Score Breakdown vs. Timing Analytics — likely spills to 2 pages
**Severity:** low
**Category:** E (print)
**Location:** `static/style.css:1140-1213`, `templates/results.html`
**Evidence:** print styles hide `.side-panel`, `canvas`, `.btn`, `.modal-overlay`, `.no-print`, and set stat-grid to `repeat(4, 1fr)` at 6pt gap. But the results page also has:
- The full "Question Review" list (`{% for r in responses %}` — 50-100 rows depending on test) — no `page-break` control per row (only `.topic-item { page-break-inside: avoid }`). A 100-Q test will spill to 3+ pages.
- The Timing Analytics + Time Segment Analysis + Error Types cards (`.grid-3`) — no print-mode collapse; will consume most of page 1.
The comment says "Goal: single-page summary" (line 1136) but the layout doesn't enforce that.
**Impact:** printed results are 3-4 pages when the intent is 1. User-visible today (Print button on results.html:67).
**Fix:** either (a) accept multi-page and add `.card { page-break-inside: avoid }` for cleaner splits, or (b) hide `#question-by-question-review` entirely in print, keep only score + topic breakdown for 1-pager.
**Effort:** minutes

### F14: Timer color logic is hardcoded assumption ("120s = danger") — target is configurable
**Severity:** low
**Category:** E
**Location:** `templates/test.html:388-398`
**Evidence:**
```js
if (timerSeconds > 90) { danger } else if (> 60) { warning }
```
But the user can change target seconds/question in Settings (`analytics.html:317-319`, POST `/api/settings` with `target_seconds_per_q`). Default is 72s. A user who sets target=45s (fast paper) never sees warning until 60s — well past their target.
**Fix:** pass `target_sec` from server as a JS constant and use `target_sec * 0.85`/`target_sec * 1.25` as thresholds.
**Effort:** minutes

### F15: Confetti/toast (`showAchievement`) is invisible in high-contrast/reduced-motion modes
**Severity:** low
**Category:** E
**Location:** `static/script.js:147-169`
**Evidence:** the toast is injected with `animation: slideDown 0.4s ease-out`. No check for `prefers-reduced-motion: reduce`. The keyframe is appended once but never removed. Also `background: #059669` hardcoded — doesn't dim in dark mode.
**Fix:** wrap the animation in `@media (prefers-reduced-motion: no-preference)`, use `var(--success)`, and drop the injected `<style>` insertion into `style.css`.
**Effort:** minutes

### F16: Mobile top-bar icon buttons are ~28×36px — below the 44px WCAG tap target
**Severity:** medium
**Category:** E (mobile)
**Location:** `static/style.css:1026-1037`
**Evidence:** `.mobile-topbar .icon-btn { font-size: 16px; padding: 6px 10px }` — computed height ~28px, width ~36px. Same shortfall on `.pagination a, .pagination span` (padding 8px 14px = ~30px tall). Report Issue link in `test.html` is `padding: 8px 0` → 24-32px tall. WCAG 2.5.5 target is 44×44px minimum.
**Impact:** the search/theme/logout icons in the mobile top bar are hard to hit — a real problem when the platform is used during commute (bus/metro) as the roadmap implies.
**Fix:** bump icon-btn to `padding: 12px` and add `min-width: 44px; min-height: 44px` on all `.pagination a` and `.report-issue-link`.
**Effort:** minutes

### F17: `.search-modal-overlay` z-index 1100 competes with `.modal-overlay` z-index 1000 — order-dependent
**Severity:** low
**Category:** F
**Location:** `static/style.css:849-857, 1580-1590`
**Evidence:** if Deep Dive modal is open (z-1000) and user hits Ctrl-K, the search modal (z-1100) opens over it. On Escape, `script.js:120-125` closes ALL `.modal-overlay` elements — including the Deep Dive one behind it. User loses their chat context.
**Fix:** in the global Escape handler, close only the topmost visible modal. Track a modal stack, or check `.search-modal-overlay.open` first and return.
**Effort:** minutes

### F18: `no-cache` favicon 404 spam — no favicon.ico is served
**Severity:** low
**Category:** F
**Location:** entire `static/` dir (no favicon file)
**Evidence:** no `<link rel="icon">` in any template. Every full page load emits a 404 for `/favicon.ico`. Also — the app is branded as "Exam Platform" in the topbar but there's no visual icon on the browser tab.
**Fix:** add a 32×32 favicon (or SVG data URI) and `<link rel="icon" href="/static/favicon.ico">` in each template head (or via the future `base.html` from F03).
**Effort:** minutes

### F19: No signup / self-serve account creation surface — but /login shows no explanation
**Severity:** low
**Category:** I (product)
**Location:** `templates/login.html:37-43`
**Evidence:** login page has ONLY Username / Password / Sign In. No "Contact admin", no "This is a private beta", no "Forgot password". A curious visitor who lands here (e.g., from a shared link on social) sees a dead end. Admin creation happens via `/setup/seed` env-var bootstrap and `/admin/users`. There is intentionally no signup — but the UX gives no signal.
**Impact:** low today (solo user), but zero-cost to fix and helps if the product ever gets a shared demo link.
**Fix:** add one line under Sign In button: "Access is invite-only. Ask Kartik for an account." OR remove the login page from public search engines via `<meta name="robots" content="noindex">`.
**Effort:** minutes

### F20: Empty-explanation ghost — "No explanation available" surfaces the same as a rate-limited row
**Severity:** medium
**Category:** I / H
**Location:** `templates/test.html:481-486`, `templates/results.html:371` (`a.explanation || 'No explanation available.'`), `templates/review.html:138-140`
**Evidence:** during a test, if a question has `explanation IS NULL` or `''`, the feedback panel simply shows the "✓ Correct!"/"✗ Wrong!" line with no follow-up. In Deep Dive, `a.explanation || 'No explanation available.'` renders the exact same string whether the explanation was never generated, was generated-but-empty, or the DB write failed. In `/review` cards the section is silently omitted.
**Impact:** ~1,704 rows were backfilled but there is no telemetry showing which are still empty vs. which got a bogus 20-char stub. During the DeepSeek run, the script filters `len(expl) < 20` (line 315 in backfill_explanations.py) but on empty responses the row is SKIPPED — never marked in DB. So a user hits a still-empty explanation on some rows post-backfill with no visible reason.
**Fix:** (a) in the test feedback panel, when explanation is empty, show a small link "Generate a deeper explanation" that hits `/api/doubt/deep-dive` on demand. (b) In `/review`, show "No explanation on file (Deep Dive available)". (c) Track `explanation_backfill_status` per row.
**Effort:** hours

### F21: Focus outlines are removed on inputs but no `:focus-visible` replacement for buttons
**Severity:** low
**Category:** E (accessibility)
**Location:** `static/style.css:410-414, 1618`
**Evidence:** `select:focus, input:focus, textarea:focus { outline: none; box-shadow: 0 0 0 3px var(--focus-ring) }` — okay for form fields (has visible focus ring). But `.btn`, `.btn-option`, `.q-nav-btn`, `.srs-option`, `.seg-btn`, `.icon-btn`, `.deep-dive-btn`, sidebar links — none have explicit `:focus-visible` styles. Browser default outline is often invisible against colored buttons (e.g. blue button + blue outline).
**Impact:** Tab-through-page users have no idea which control is focused.
**Fix:** add a global rule:
```
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
```
early in style.css so all custom controls inherit it.
**Effort:** minutes

### F22: Non-idempotent `location.reload()` after mutations blocks progress in an SPA-like flow
**Severity:** low
**Category:** F
**Location:** `static/script.js:63, 90`, `templates/admin/questions.html:59, 65`, `templates/admin/duplicates.html:104`
**Evidence:** every error-resolve, redo, delete, disable in the admin panel calls `location.reload()` on success. On errorlog.html with 50-100 rows and filters set, reloading dumps scroll position and resets modal state. Ditto for questions.html and duplicates.html.
**Fix:** update the row in-place (mutate DOM: dim the row, show a small "Resolved ✓" badge, remove or gray it out) instead of reloading. This is a Phase-B "test-taking UX" concern for errorlog.
**Effort:** hours

### F23: Dead CSS: `.toggle` / `.toggle.on` custom switch has zero call-sites
**Severity:** low
**Category:** F
**Location:** `static/style.css:817-846`
**Evidence:** searched every template + script — no `<div class="toggle">`, no `classList.add('toggle')`. It looks like an older iteration of the mode switch that was replaced by the `.mode-toggle` (label+radio) pattern in test_setup.html. Also `.q-nav-btn.answered` (line 689) is documented as a "legacy alias" — the JS at test.html:262 lists it in `STATE_CLASSES` for clearing, but no code path calls `classList.add('answered')` anymore; the state-machine uses `state-answered`.
**Impact:** dead code, small — ~15 lines of CSS.
**Fix:** delete the `.toggle*` rules and the `.q-nav-btn.answered` alias. Remove `'answered'` from `STATE_CLASSES` in test.html:262.
**Effort:** minutes

### F24: Inline `<script>` bodies inside templates vs. `static/script.js` — no boundary rule
**Severity:** low
**Category:** F
**Location:** every template. e.g., `test.html:236-682` has 450 lines of inline JS; `analytics.html:332-508` has 175 lines; `results.html:335-490` has 155 lines. `script.js` is 345 lines.
**Evidence:** page-specific logic (loadQuestion, deepDive, saveSettings, srs binding) lives inline, but generic helpers (`resolveError`, `showAchievement`, `toggleTheme`) live in `script.js`. The Chart.js callbacks in analytics.html could be a separate `static/analytics.js` easily. Deep Dive in results.html is 155 lines of interactive JS that would benefit from CSP-friendly external hosting.
**Impact:** (a) can't add a strict CSP `script-src 'self'` without inline hashes; (b) editors don't get JS linting on inline blocks; (c) hot-swap requires re-rendering the whole HTML.
**Fix:** extract `results.html`'s Deep Dive script to `static/deep_dive.js`, `test.html`'s test loop to `static/test.js`, etc. Do it gradually — start with the biggest offender (`test.html:236-682`).
**Effort:** hours

### F25: 53 inline `onclick=` handlers block CSP and complicate refactoring
**Severity:** low
**Category:** F
**Location:** `grep -c onclick= templates/*.html` returns 53 matches spread across every user template
**Evidence:** e.g. `templates/test.html:73 onclick="toggleBookmark()"`, `templates/test.html:84 onclick="openFlagModal();return false"`, `templates/errorlog.html:189 onclick="resolveError({{ e.id }})"`. A strict CSP (defence against injected XSS in question text — already partially mitigated by DOM-API rendering in test.html:354-364) would need `unsafe-inline`, defeating the point.
**Fix:** replace with `data-*` attributes + delegated event listeners in the extracted per-page JS. Not urgent for solo-user, but valuable if the app is ever published.
**Effort:** hours

### F26: Search results in the `search.html` list link nowhere — clicking a hit does nothing
**Severity:** medium
**Category:** E
**Location:** `templates/search.html:154-175`, `static/script.js:236-240`
**Evidence:** the standalone /search page renders each result as a `<div class="card">` with the question text and options. There's no link, no button, no click handler. User searches "TCP", gets 40 hits, cannot open any of them — they can only re-read the preview text. In the Cmd-K modal it's the same story (`openResult()` in script.js:236 falls back to `/search?q=<query>&highlight=id` — but `/search` route ignores the `highlight` param and just renders the same list). The comment even says "No dedicated per-question route yet".
**Impact:** the whole Search feature is 80% cosmetic — users can find questions but can't act on them (bookmark, force-add to a review test, etc.).
**Fix:** either (a) add `/question/<id>` route that shows a single-question review page with bookmark/deep-dive/flag; or (b) at minimum, "Star" (bookmark) button inline on each hit.
**Effort:** hours

### F27: Chart.js loaded from CDN — no SRI, no CSP, offline mode broken
**Severity:** low
**Category:** F
**Location:** `templates/analytics.html:8`, `results.html:8`
**Evidence:** `<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>` — no `integrity=`, no `crossorigin=`. If jsDelivr is compromised or blocked (some corporate/campus networks) the analytics + results pages render with empty canvases and no error message. Also creates a hard dependency on network for the study platform.
**Fix:** vendor Chart.js into `static/vendor/chart.umd.min.js` (~200KB) and self-host. Optional: add SRI hash on the CDN version until vendored.
**Effort:** minutes

---

## Content quality — H (Turso `questions` sample)

**Sampling constraint:** the harness for this critique run is sandboxed against outbound network calls (Turso HTTP + Python DB drivers were both denied). I could not fetch the 30-row live sample.

Instead I audited the **backfill pipeline itself** (`scripts/backfill_explanations.py:104-131`) — the same prompt and the same clean-response pass generated every one of the 1,704 rows. Findings are risk estimates from the prompt+code, not row-by-row scores.

**Prompt as written (backfill_explanations.py:104):**
```
Rules:
- 2-3 sentences only. No filler.
- Do NOT restate the question or options.
- Focus on the key concept or fact that makes the answer correct.
- Plain text, no markdown, no bullets.
- No preamble like "The correct answer is X because..." — just explain the concept.

Question: {question_text}
(A) {option_a}
...
Correct answer: ({correct_option})

Explanation:
```

`clean_response` (line 263) strips leading "Explanation:" / "Answer:" / "**Explanation:**" prefixes and collapses whitespace. That's the only guardrail.

### H01: "The correct answer is X because" prefix — partially caught, will still slip through
**Severity:** high (for content quality)
**Category:** H
**Location:** `scripts/backfill_explanations.py:104-120, 263-271`
**Evidence:** the prompt explicitly forbids "The correct answer is X because…". `clean_response` strips only exact-match `Explanation:` / `Answer:` / `**Explanation:**` prefixes. Real DeepSeek outputs I've seen in the wild have variants: `The correct option is B. `, `Option B is right because…`, `**B**: `, `B is the correct answer since…`. None of those are stripped.
**Estimated hit rate:** 8–15% of 1,704 rows likely have some form of "letter is the answer" leading phrase. On 200 rows that's 16–30 questions with the "LLM tell" tone, and in practice mode this echoes back to the user right after they picked — degrading trust.
**Fix:** widen `clean_response` to regex-strip a much longer list: `^(the correct (option|answer) is [ABCD][^.]*\.\s*)`, `^(option [ABCD] is (correct|right)[^.]*\.\s*)`, `^([ABCD] is (the|)correct[^.]*\.\s*)`. Case-insensitive. Backfill once through the DB to clean the existing rows in place.
**Effort:** hours

### H02: Length not enforced — DeepSeek at temperature 0.5, max_tokens 300 can (and does) run long
**Severity:** medium
**Category:** H
**Location:** `scripts/backfill_explanations.py:138-143`
**Evidence:** `max_tokens: 300` → up to ~225 words. Target is 40-80 words. No post-check for length. `clean_response` doesn't truncate. GLM-Flash and DeepSeek-Chat both tend toward 4-6 sentences when given room.
**Estimated hit rate:** 20–35% of rows likely over 100 words. Not a correctness issue, but the "concise 2-3 sentence" experience is lost. In the test feedback panel where the explanation is `font-size:13px; color:var(--text-muted)`, walls of 6-sentence text visually crush the "Next Question ▶" button below the fold on 375px screens.
**Fix:** post-generation, if `len(expl.split()) > 100`, either (a) retry once with a stricter prompt ("Response was too long. Give a 2-sentence version.") or (b) truncate at the first two sentence boundaries. (b) risks cutting off mid-thought.
**Effort:** hours

### H03: No "contradicts correct_option" check — a wrong LLM never triggers a flag
**Severity:** high
**Category:** H
**Location:** `scripts/backfill_explanations.py` — no verification step
**Evidence:** the prompt says "Correct answer: (B) — explain why B is right." A cheap LLM can dutifully explain why C is right and never mention B. Nothing in the pipeline detects this. `clean_response` only handles prefixes. There's no cross-check that the explanation references the correct option's content or contradicts one of the wrong options.
**Estimated hit rate:** 2–5% of 1,704 rows may argue for a different letter than `correct_option`. That's 30-80 questions where the app shows "correct: B" but the explanation defends C — user is confused about which is actually right, and (worse) may re-learn the wrong fact.
**Fix:** post-hoc verifier — for each row, ask a second LLM: "Does this explanation support option {correct_option}: {option_text}? YES/NO." Cheap to run once on the 1,704 rows. Flag NOs for admin review.
**Effort:** days

### H04: "Restates the question" is prompt-forbidden but not code-enforced
**Severity:** medium
**Category:** H
**Location:** `scripts/backfill_explanations.py:104-120`
**Evidence:** Rule 2 in the prompt: "Do NOT restate the question or options." Common LLM failure: opens with "This question is about TCP/IP layers, where…" — technically restating. There's no similarity check between `explanation` and `question_text`.
**Estimated hit rate:** 10-20% of rows likely restate the question in whole or part. Wastes the user's screen space and reading time.
**Fix:** compute Jaccard trigram similarity (project already has trigram utilities per `templates/admin/duplicates.html:22`) between explanation and question — if ≥ 0.15, flag for manual review or auto-regenerate with a stricter prompt.
**Effort:** hours

### H05: Rajasthan-specific claims are unverified — the prompt mentions "Rajasthan Basic Computer Instructor" but there's no ground truth
**Severity:** medium
**Category:** H
**Location:** `scripts/backfill_explanations.py:104` (prompt header)
**Evidence:** the prompt tells DeepSeek to imagine helping a Rajasthan exam candidate. When questions touch on Rajasthan-specific GK (Paper I: geography, history, current CM/Governor, districts, festivals, tribes), DeepSeek/GLM will confidently fabricate. E.g., "Rajasthan's Chief Minister is Ashok Gehlot" (out of date since Dec 2023), or "The Chittorgarh Fort was built in 734 AD" (contested). No RAG, no ground-truth lookup.
**Estimated hit rate:** if ~10% of Paper I rows are Rajasthan-specific, and 20% of those are model-hallucinated, that's ~35 rows across the 1,704 with wrong facts. Some will teach the user incorrect answers.
**Fix:** (a) mark all Rajasthan-tagged rows as `confidence='medium'` after backfill so they route through the admin review queue; (b) longer-term, feed the `study-notes/` directory content into the prompt via RAG so DeepSeek quotes from vetted material.
**Effort:** days

### H06: Empty/rate-limited responses are logged-and-skipped — no DB marker
**Severity:** medium
**Category:** H / I
**Location:** `scripts/backfill_explanations.py:315-318`
**Evidence:** `if not expl or len(expl) < 20: ... fail += 1; continue`. The row is NEVER updated — `updated_at` doesn't change, `explanation` stays NULL/empty. There's no `attempted_at`, no `backfill_status = 'failed'`. So the user hits the same row later, sees no explanation, and there's no signal on the admin side that this row was ever tried.
**Fix:** add a small `question_backfill_log(question_id, attempted_at, status, provider, note)` table. Or set `explanation = '__PENDING__'` (with a UI check to render as "AI explanation is being generated — Deep Dive to see one now").
**Effort:** hours

### H07: Bullet-point / markdown output slips through despite the "no markdown, no bullets" instruction
**Severity:** low
**Category:** H
**Location:** `scripts/backfill_explanations.py:104-120`
**Evidence:** LLMs love bullets. DeepSeek at temp 0.5 will occasionally return `- Point one.\n- Point two.\n- Point three.` Rendering: in test.html feedback panel, whitespace is normalised via `" ".join(t.split())` (line 270), which turns `\n- ` into `- - -` on a single line — worse than the original.
**Estimated hit rate:** 3-8% of rows. Ugly but not wrong.
**Fix:** in `clean_response`, drop lines that start with `- ` or `* ` or a digit-dot, keep the tail. Or ask the LLM to retry.
**Effort:** minutes

**Because the sample query was not runnable, the table below is left as a placeholder. Run it as a one-shot follow-up:**

```sql
SELECT id, correct_option, explanation
FROM questions
WHERE updated_at > '2026-07-19'
  AND explanation IS NOT NULL AND explanation != ''
ORDER BY RANDOM() LIMIT 30;
```

| # | ID | Length (words) | Restates? | Prefix tell? | Bullets? | Contradicts key? | Verdict |
|---|----|---|---|---|---|---|---|
| _sample not fetched — sandbox denied network access_ | | | | | | | |

**Estimated aggregate risk on the 1,704 backfilled rows (from static analysis of the prompt+pipeline):**

| Issue | Estimated % affected | Estimated rows |
|-------|----------------------|----------------|
| Length > 100 words | 20–35% | 340–600 |
| Restates question | 10–20% | 170–340 |
| "The correct answer is X because…" leading tell | 8–15% | 135–255 |
| Markdown/bullets bleed-through | 3–8% | 50–135 |
| Rajasthan-specific factual hallucination | 1–3% | 15–50 |
| Contradicts correct_option | 2–5% | 30–80 |

The high-severity item is **H03 (contradicts correct_option)** — small percentage but critical harm per instance. It is worth running a one-shot verifier LLM pass across all 1,704 rows to isolate them before the exam.

---

## Additional findings — E, F, I categories

### F28: `{{ nt.reason|safe }}` on dashboard trusts server-side reason string
**Severity:** low
**Category:** F (defence-in-depth)
**Location:** `templates/index.html:80, 92`
**Evidence:** `reason` is constructed in `bp_main.py:_score_topic` from `weightage`, `current_score`, `days`, `est_points`. Today those are all integers and hardcoded `&middot;` HTML entities — safe. The `|safe` filter is there so the `&middot;` renders as a `·`. However: if this function is ever extended to include `t["name"]` or LLM output, `|safe` becomes a live XSS. The alternative "escape at generation time, remove |safe" is safer.
**Fix:** build the string using Markup/Jinja concat instead of a raw HTML string, or replace `&middot;` with the unicode `·` directly so `|safe` isn't needed.
**Effort:** minutes

### F29: `flash()` messages: never used, so errors have to hard-code their own display
**Severity:** low
**Category:** F
**Location:** entire `templates/` dir — no `get_flashed_messages()` calls anywhere
**Evidence:** grep for `get_flashed_messages`/`flash(` returns zero matches. Every friendly error therefore has to be a bespoke template variable (`{% if error %}` in login.html:45; the deep-dive error box built in JS). No consistent "toast for feedback" story. `showAchievement()` in script.js exists but is only called for the "Marked for review" moment.
**Impact:** future error UX has no reusable channel. Every new "friendly error" is a one-off wiring exercise.
**Fix:** add `{% include '_flash.html' %}` (a fixed toast area rendering `get_flashed_messages(with_categories=true)`) into the future `base.html`. Convert existing bespoke error strips to `flash(msg, 'error')`.
**Effort:** hours

### F30: Timer/Test panel `.side-panel .card { position: sticky; top: 20px }` breaks on tall question stems
**Severity:** low
**Category:** E (UX)
**Location:** `static/style.css:637`
**Evidence:** the side-panel (Test Progress + palette) is sticky. On a very long question (500+ char stem with 4 long options), the scrollable question card grows below the viewport. If the palette itself is taller than the viewport, sticky positioning fails and the palette becomes unreachable — the user cannot see Q47 in a 100-Q test on a 900px-tall laptop screen (palette is 10-cols × 10-rows × ~40px = 400px + card padding + timer card ≈ 620px total).
**Fix:** make the Question Navigator card scrollable inside itself: `.side-panel .card:has(.question-nav-grid) { max-height: calc(100vh - 100px); overflow-y: auto }`.
**Effort:** minutes

### F31: `q.total` in `/api/question/*` is passed via response, but `TOTAL` in test.html comes from initial render — divergence if backend changes mid-test
**Severity:** low
**Category:** F
**Location:** `templates/test.html:239, 337`
**Evidence:** `const TOTAL = {{ total }};` (fixed at page render) but the loop also uses `q.total` inside `loadQuestion`. If a question is disabled via admin panel between requests, the two diverge. Progress bar uses `q.total`; palette + isLast checks use `TOTAL`. Not currently exploitable, just fragile.
**Fix:** rely on one source (session-scoped `total` server-side) and pass it in every /api/question response.
**Effort:** minutes

### F32: Consistency score / activity strip on dashboard: `active_days/20` denominator is unexplained
**Severity:** low
**Category:** E
**Location:** `templates/index.html:66`, `bp_main.py:_consistency` line 88
**Evidence:** the label says "consistency · 4/20 active days" with no explanation what 20 means. The comment in `_consistency` says "denominator 20 makes 5 study days/week hit 100%". User has to open source to know 20 is the goal.
**Fix:** tooltip / info icon: "20 = target of 5 study days × 4 weeks in a 28-day window." Or change denominator to `min(28, days_since_signup)` so brand-new users don't see 0/20.
**Effort:** minutes

### F33: Dashboard hero says "No topic is currently below target" — but only after the user completes at least one test
**Severity:** medium
**Category:** E (empty state)
**Location:** `templates/index.html:97-107`
**Evidence:** for a brand-new user (0 tests), `next_topics` returns some untested topics (because `test_count == 0` triggers a positive score in `_score_topic`). But if all topics happen to be studied recently AND on-target — an unlikely-but-possible state early on — the fallback CTA "Start test" is the ONLY next step. Meanwhile, the stat cards show `0.0% avg`, `0.0% last test`, `0 minutes`, and the recent-errors card says "No errors! Keep up the good work." — which reads as PRAISE for a user who has literally not started.
**Impact:** new-user dashboard is a lie: "great job (you've done nothing)".
**Fix:** wrap the stat grid in `{% if tests.total > 0 %}` and show a large "Welcome — start your first test" hero card when `total == 0`. The mastery grid can stay (all tiles will be `tier-untested` = grey), but the misleading "0% average" and "Keep up the good work" need to go.
**Effort:** minutes

### F34: `.hero-consistency` shows 0% + 0/20 for a fresh user with no explanation of what to do
**Severity:** medium
**Category:** E (empty state)
**Location:** `templates/index.html:63-73`
**Evidence:** for a new user, `consistency_score = 0`, `active_days = 0`, and the 28-cell activity strip is all grey. There's no eyebrow "Get to 5 days/week" or dead-simple CTA. It just says 0% quietly.
**Fix:** replace the strip with a "Welcome" panel while `active_days == 0`. Bring in the strip after day 1.
**Effort:** minutes

### F35: `/errorlog` empty state hides the SRS summary panel behind an unhelpful phrase
**Severity:** low
**Category:** E (empty state)
**Location:** `templates/errorlog.html:223-227`
**Evidence:** if the user has no errors yet, the page shows "✓ No errors match your filters." — but if `resolved_filter=all` (which it defaults to `no`), the message wrongly implies filters when the user has none. Also the "Review Queue summary" card (lines 65-85) is only rendered if `sr_summary` is truthy — for a new user, this card is hidden AND the error list is empty, so /errorlog is completely blank aside from the filter form.
**Fix:** conditional: if user has zero errors ever, show a friendly card "You haven't got anything wrong yet. Head to /test/setup to start a diagnostic." (and mention the SRS queue only fills when errors are made).
**Effort:** minutes

### F36: `/analytics` is a wall of empty-state cards for a new user; no consolidated welcome
**Severity:** medium
**Category:** E (empty state)
**Location:** `templates/analytics.html:57-327`
**Evidence:** 9 individual `{% else %}<div class="empty-state">` fallbacks, one per card. New user sees 9 stacked "No X data yet" cards. Total scroll height ~1000px of grey emptiness. The Settings panel at the bottom is fully functional but hidden below the fold.
**Fix:** top of `/analytics`, wrap in `{% if tests.total == 0 %}<div class="hero-card">You need at least one completed test to unlock analytics. <a href="/test/setup">Take your first test</a>.</div>{% else %}…{% endif %}`.
**Effort:** minutes

### F37: Admin panel uses a completely different color system — visual inconsistency
**Severity:** low
**Category:** F
**Location:** `templates/admin/base.html:8-46`
**Evidence:** admin/base.html defines its OWN colors: `#0e1729`, `#dfe7f5`, `#7b2d8b`, `#f47920`, `#d32f2f`, `#f9a825`, `#2e7d32`. Zero token reuse from style.css. Admin nav is dark blue, main app nav is a slightly-different dark blue. The `.flag-cat.typo`/`.wrong_answer`/`.other` palette overrides the user app's `.badge` semantics — a "typo" badge is teal in admin, but the user app has no such thing.
**Impact:** two visual identities in one app; future rebrand needs to touch two color palettes.
**Fix:** migrate admin/base.html to use CSS custom properties from style.css. Or accept admin as a separate visual zone and add a `[data-panel="admin"]` scope in style.css to consolidate.
**Effort:** hours

### F38: Admin panel has no dark mode at all
**Severity:** low
**Category:** E (dark mode)
**Location:** `templates/admin/base.html`
**Evidence:** admin templates never inject the inline theme setter, don't read `localStorage`, don't reference `[data-theme]`. Admin is fixed-light. If the user is doing late-night flag triage in dark theme on the main app, then clicks "Admin" they get a screen-searing white page.
**Fix:** add the inline theme setter + minimal dark tokens to admin/base.html.
**Effort:** hours

### F39: Deep-Dive chat has no persistence, no export — every session is throwaway
**Severity:** low
**Category:** E
**Location:** `templates/results.html:391-437`
**Evidence:** `chat-messages` div is rebuilt on every `deepDive()` call (line 381: `document.getElementById('chat-messages').innerHTML = ''`). If the user asks a good clarifying question and closes the modal accidentally (Esc keystroke), the entire Q&A trail is gone. No "save to notes", no client-side storage.
**Fix:** at minimum, persist chat state in `sessionStorage` keyed by `question_id`. Long-term, add a `/notes` route.
**Effort:** hours

### F40: `showAchievement("Marked for review")` and `("Un-marked")` are the only toast paths — other actions silent
**Severity:** low
**Category:** E
**Location:** `templates/test.html:449-451`
**Evidence:** the toast pattern is available (`showAchievement`) but only wired for mark-for-review. Actions with no feedback: bookmark (toggle changes icon but no toast), settings save (small "✓ Saved" inline on analytics.html:322 only, no toast), flag submission (`showAchievement('Reported. Thanks!')` — actually this IS wired at test.html:670), redo/resolve error (page reload).
**Fix:** consistent pattern — every mutation shows a toast. Bookmark toggle should trigger "Bookmarked" / "Removed bookmark".
**Effort:** minutes

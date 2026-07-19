# E — Polish + General UX Plan

**Status:** Proposal — not implemented
**Scope:** Four cross-cutting polish items that don't fit neatly into A/B/C/D but move the platform from "functional prototype" to "actually pleasant to use." Solo-user tool, so priorities are Kartik's daily experience over broad accessibility.
**Guiding principle:** Prefer additive CSS + small template diffs over rewrites. The design system in `static/style.css` (CSS custom properties + a clean component vocabulary) is already good — extend it, don't replace it.

The four items:

1. **Mobile responsiveness** — usable on a phone (iPhone SE / 375px minimum), because Kartik will want to sneak in 10-question drills on the bus.
2. **Dark mode** — CSS custom-property re-mapping under `[data-theme="dark"]`, no framework, localStorage-persisted.
3. **Global question search** — search the 3,712-row bank by keyword + filters (topic, difficulty, paper, and forthcoming Plan-D fields).
4. **Structured question flagging** — the flag modal is already partly structured; tighten the categories, add a required-choice UX, and update the admin flag review page to match.

---

## 0. TL;DR — Recommended Build Order

| # | Item                       | Effort | Files touched                                             | Rationale                                                                                                                                                              |
|---|----------------------------|--------|-----------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | **Structured flagging v2** | 2h     | `bp_api.py`, `templates/test.html`, `templates/admin/flags.html` | Smallest surface area, no schema change (`category` already exists). Ships value immediately for the growing flag backlog. Good warm-up.                                |
| 2 | **Dark mode**              | 4h     | `static/style.css`, `static/script.js`, every template `<head>` | Pure CSS variables — the current palette is already fully tokenized. Zero risk to layout. Ships a visible win for evenings/night study.                                 |
| 3 | **Mobile responsiveness**  | 8h     | `static/style.css` (biggest LOC), all templates for hamburger + drawer | Biggest CSS diff. Do it AFTER dark mode so the mobile media queries only have to worry about one set of tokens — dark tokens will be inherited automatically.           |
| 4 | **Global question search** | 6h     | New route on `bp_main`, new template `search.html`, sidebar link, optional FTS5 migration | Depends on Plan D's new columns (`confidence`, `pyq_exam`, `pyq_year`, `section`, `sub_topic`) for its filter UI. Ship AFTER Plan D or at minimum after column shape is frozen. |

**Total: ~20h focused work.**

**On ordering flagging first vs mobile first:** The temptation is to do mobile first because it's the biggest visible win. Resist. Flagging is 2h and unblocks better data hygiene; dark mode is a pre-req for clean mobile media queries; mobile builds on dark; search waits on Plan D. This sequence is monotone in dependency direction.

**Mobile first vs last — the argument:**
- **For first:** Highest LOC touch means highest risk of merge conflicts with parallel work on B/C/D; get it out of the way. Also, if it takes longer than 8h, better to know early.
- **For last (chosen):** Dark-mode's CSS-variable pass rewrites the same declarations mobile would rewrite. Doing mobile first means you touch every color rule twice. Also, mobile testing needs a stable design language — B (test-taking UX) is redesigning the test screen and will invalidate any mobile work done on the current `test.html`.

Verdict: **last**, gated on Plan B's palette redesign landing.

---

## 1. Current State Audit

### 1.1 `static/style.css` — 737 lines

- **CSS custom properties (`:root`)**: 22 tokens (lines 5–27). All colors are tokenized. Radii and shadows tokenized. Already 90% of the way to dark-mode-ready.
- **Media queries**: exactly **one** — `@media (max-width: 900px)` at line 710, ends line 717. It only:
  - Collapses `.sidebar` from 240px → 60px (icons only, no labels).
  - Removes `.main` left margin correspondingly.
  - Flattens `.test-layout`, `.grid-2`, `.chart-row` to a single column.
  - Keeps `.grid-3` at 2 columns.
- **Zero breakpoints below 900px.** iPhone SE (375px), iPhone 12/13/14 (390px), iPhone Plus / Android common (414–428px), foldables (280px unfolded) all get the 60px sidebar + 1-column layout, which technically works but has issues (see §2).
- **Fixed-width elements that break on phones:**
  - `.stat-grid` uses `minmax(200px, 1fr)` — fine down to 200px.
  - `.checkbox-grid` uses `minmax(220px, 1fr)` — will single-column on 375px, which is what we want.
  - `.side-panel` in test.html is 320px sibling — see §2.2.
  - `.question-nav-grid` uses `repeat(10, 1fr)` — 10 cells × ~28px min = 280px minimum. On a 375px viewport with 60px sidebar + 32px content padding (each side), the content width is `375 - 60 - 64 = 251px`, which forces cells below the 28px comfortable tap target. **This is the worst offender for mobile.**
  - `.pagination` has no wrapping — on 375px with 5+ pages, buttons overflow horizontally.
  - `.heatmap-grid` uses `repeat(7, 1fr)` — 7 cells is fine at 375px but the labels get tiny (currently 8px font). Marginal.

### 1.2 Templates — sidebar layout

All four user-facing templates (`index.html`, `test.html`, `analytics.html`, `errorlog.html`, `test_setup.html`, `results.html`) use the same `<aside class="sidebar">` + `<div class="main">` pattern with 5 links.

Sidebar links currently: Dashboard, Take Test, Analytics, Error Log, Logout — five items, perfect fit for bottom nav.

None of the templates have:
- A hamburger button.
- A "close menu" backdrop.
- Any JS for menu state.

The 60px collapsed sidebar has no `title` attributes on the icon-only links, so on mobile the user sees five glyphs and has to memorize what each means.

### 1.3 `templates/test.html` on 375px

Walking through the layout at 375px width:
- Sidebar takes 60px → content column has 315px usable.
- `.page-header` fits (h2 + question count + timer stacks awkwardly because of `flex-between` with two rich children — timer wraps below the count on narrow screens, which is ugly but readable).
- `.test-layout` collapses to single column (media query kicks in at 900px), so the sidebar (question navigator card) drops below the question. Correct behavior.
- **Question navigator**: 10 columns × 3712 / 20 = 186 tests would be huge, but for a typical 20-question test that's 2 rows of 10. At 315px content − 40px card padding = 275px card body → 27.5px per cell. Tap targets should be 44px per Apple HIG. **Fail.**
- **Options list**: `.btn-option` is `padding: 14px 20px` and `font-size: 15px` — comfortable at 375px. Fine.
- **Report issue link**: 12px muted text, right-aligned, tap target ~10px tall. Fail against WCAG 2.5.5 (target size).
- **Modal**: `max-width: 500px; width: 90%` → on 375px viewport = 337.5px modal, comfortable.
- **Flag select + textarea**: 100% width — fine.
- **Modal actions row**: two buttons with `padding: 10px 20px` each, `gap: 10px`. Total ~200px — fits.

**Verdict:** test.html on 375px is 70% usable. The question navigator is the actual blocker. Everything else is minor polish.

### 1.4 `bp_api.py` — flag route

Located at `/api/flag_question` (POST). Already validates against a fixed set:
```python
FLAG_CATEGORIES = {"data_inconsistency", "bad_latex", "typo", "wrong_answer", "other"}
```
Falls back to `"other"` if unknown. Inserts into `question_flags` with `status='open'`.

**So the freeform-vs-structured distinction the user described is not quite accurate — categories are already whitelist-enforced server-side, and the modal already has a `<select>`.** The real improvement is:
- Rename + regroup categories along the "actionable to fix" axis instead of the "kind of defect" axis.
- Make the note field conditionally required (for "Other" and "Multiple correct").
- Show category badges on the admin `/admin/flags` list (currently free-text `f.category` in a table cell).
- Add per-category counts to admin dashboard stats.

### 1.5 `question_flags` table (db.py line 88)

```sql
CREATE TABLE IF NOT EXISTS question_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER REFERENCES questions(id),
    test_id INTEGER REFERENCES mock_tests(id),
    reporter TEXT,
    category TEXT,       -- already exists, currently one of 5 whitelisted values
    note TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);
```

`category` is populated and used by `/admin/flags`. No schema change needed for flagging v2.

### 1.6 `bp_admin.py` question search

Admin questions page has three filter dropdowns (topic / paper / difficulty) + one checkbox (show disabled) + pagination. **There is no text search input.** The user's premise that admin already has search is off — admin has faceted filtering only. That means the global search feature does not have an admin analog to lift from; it's greenfield.

Also relevant: `/admin/questions` requires admin role. The user-facing global search is a separate feature — accessible from the main sidebar, no role restriction beyond login.

---

## 2. Item-by-Item Design

---

### Item 1 — Structured question flagging (2h)

#### 2.1 Competitor scan

| Platform | Model | Categories | Notes |
|----------|-------|------------|-------|
| **Stack Overflow "Flag post"** | Radio list, 4 top-level → sub-reasons | needs improvement / off-topic / duplicate / other → each has 2–5 sub-reasons | Two-level. The "in a few words, why?" text field appears only for "needs improvement" and "other." **This is the model to steal.** |
| **Wikipedia templates** (`{{cn}}`, `{{disputed}}`, `{{clarify}}`) | Named templates, inline | citation-needed, disputed, clarify, weasel-word, POV, dead-link, etc | Semantic — each template implies a specific fix. Overkill for us but the naming discipline is instructive. |
| **YouTube "Report"** | Flat radio list, 6 top-level | sexual / violent / hateful / harmful / spam / other → sub-reasons | Flat is faster than two-level but harder to maintain — YouTube's list is famously long |
| **Duolingo "Report"** | Flat radio list, 4 options | audio wrong / picture wrong / my answer should be accepted / another problem | Domain-specific. Their model: name the exact defect, no vague "wrong answer" |
| **Anki add-on "Ranked cards"** | Free text | N/A | Flag categories per-user, no discipline |

**Chosen model: Stack Overflow flat variant.** One-level radio list, 6 categories + Other, note field required only for Other and "Multiple correct." Faster than two-level and forces a concrete choice.

#### 2.2 Proposed categories (7)

Replaces the current 5. The current categories mix defect-type (`typo`, `bad_latex`) with review-outcome (`wrong_answer`, `data_inconsistency`). The new set is **grouped by the fix an admin has to make**:

| ID (stored) | Label (shown to user) | Fix path in admin | Priority |
|-------------|-----------------------|-------------------|----------|
| `wrong_key` | Wrong answer key | Change `correct_option` | HIGH |
| `multi_correct` | Multiple options are correct | Rewrite options or mark question ambiguous → disable | HIGH |
| `no_correct` | No option is correct | Rewrite options → disable if unfixable | HIGH |
| `question_typo` | Typo / unclear wording in question | Edit `question_text` | MED |
| `option_typo` | Typo in options | Edit option text | MED |
| `bad_explanation` | Explanation is wrong or missing | Edit `explanation` | MED |
| `duplicate` | Duplicate of another question | Disable one | LOW |
| `other` | Something else | Read note, decide | VAR |

Removed from current: `data_inconsistency` (too vague — split into wrong_key + multi_correct + no_correct), `bad_latex` (folded into question_typo — LaTeX breakage IS a typo in the source). Kept: none by literal name, but conceptually `typo` → `question_typo`+`option_typo`, `wrong_answer` → `wrong_key`, `other` → `other`.

**Migration:** old rows have `category` values `data_inconsistency`, `bad_latex`, `typo`, `wrong_answer`, `other`. Do not migrate — leave historical values as-is. Admin flags list should display any string; the whitelist is enforced only on new inserts. Add a small "legacy" chip in admin UI for values not in the new set.

#### 2.3 UX mockup — flag modal

Radio buttons, not select. Radios show all options at once → faster scan than dropdown click-open-scan.

```
┌────────────────────────────────────────────────────────┐
│  Report an issue with this question              [×]   │
├────────────────────────────────────────────────────────┤
│  Your report won't affect your score.                  │
│                                                        │
│  ○ Wrong answer key                            (HIGH)  │
│  ○ Multiple options are correct                (HIGH)  │
│  ○ No option is correct                        (HIGH)  │
│  ○ Typo / unclear wording in question                  │
│  ○ Typo in options                                     │
│  ○ Explanation is wrong or missing                     │
│  ○ Duplicate of another question                       │
│  ○ Other  (please describe below)                      │
│                                                        │
│  Notes (optional; required for Other):                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │                                                  │  │
│  │                                                  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│              [ Cancel ]     [ Submit report ]          │
└────────────────────────────────────────────────────────┘
```

Priority tag (HIGH) is subtle — grey text, right-aligned, only on the three "answer is wrong" categories. Signals to the user that these get faster attention without shaming Low-priority reporters.

#### 2.4 Implementation checklist

1. **`bp_api.py` line 10** — replace `FLAG_CATEGORIES` set literal with new 8-value set (7 + `other`). Note: `other` requires note (add `if category == "other" and not note: return 400`).
2. **`templates/test.html` lines 100–120** — swap `<select>` for a `<div class="flag-radio-list">` with 8 radios. Add small JS to enable/disable the Submit button until a radio is picked, and to require the note textarea for `other`.
3. **`templates/admin/flags.html`** — add category badge with color-coded pills. Add a category filter dropdown alongside status filter.
4. **`bp_admin.py` dashboard route** — add `flags_by_category` aggregation to the stats dict, render as small bar in admin dashboard.
5. **CSS** — add `.flag-radio-list`, `.flag-radio-item`, `.priority-tag` styles. ~30 lines.

**No schema change. No migration.**

---

### Item 2 — Dark mode (4h)

#### 2.5 Competitor scan

| Platform | Mechanism | Toggle | Palette strategy |
|----------|-----------|--------|------------------|
| **GitHub** | `<html data-color-mode="dark">` + `data-dark-theme="dark"`. CSS custom properties per token. | Three-state: light / dark / follow system. Stored server-side + `prefers-color-scheme` fallback. | Full color-role tokenization (`--color-canvas-default`, `--color-fg-default`, etc). ~60 tokens. |
| **Notion** | `.dark` class on `<html>` toggled via JS. CSS variables per role. | Three-state, follows system. | Named color roles (`--fg`, `--bg`, `--text-default-color`). Fewer tokens (~30). |
| **Linear** | `[data-theme="dark"]` on `<html>`, CSS variables. Also has "midnight" third theme. | Two-state per theme + follows system. Preferences UI. | Semantic role naming; no raw color values in components. |
| **Tailwind `dark:` variant** | `<html class="dark">` + `dark:bg-slate-900` inline utilities. | User implements toggle. | Utility-first; no central palette. |
| **VS Code** | JSON theme files. | Selector command palette. | Every UI element has a named color role. Overkill for us. |

**Chosen model: Linear's `[data-theme="dark"]` attribute selector.** Reasons:
- Attribute selectors are trivially JS-toggled: `document.documentElement.dataset.theme = 'dark'`.
- No class-list churn.
- Cleaner CSS: `:root { --bg: #fff; } [data-theme="dark"] { --bg: #111; }`.
- Three-state (light / dark / auto) is straightforward with a `<select>` in settings.

#### 2.6 Token inventory

Current tokens in `:root` (style.css lines 5–27):

```
--bg              light-1  #f0f2f5    dark  #0f1419
--surface         light-2  #ffffff    dark  #1a1f26
--surface-alt     light-3  #f8f9fa    dark  #232830
--border          light    #e0e4e8    dark  #2d333b
--text            light    #1a1d23    dark  #e6edf3
--text-muted      light    #6b7280    dark  #8b949e
--primary                  #2563eb    dark  #4c8dff   (lightened for contrast)
--primary-hover            #1d4ed8    dark  #6ba1ff
--primary-light            #eff6ff    dark  #1c2b4a   (dark surface tint)
--success                  #059669    dark  #3fb984
--success-light            #ecfdf5    dark  #16352a
--danger                   #dc2626    dark  #f85149
--danger-light             #fef2f2    dark  #3d1a1a
--warning                  #d97706    dark  #d29922
--warning-light            #fffbeb    dark  #3a2e17
--sidebar-bg               #111827    dark  #0d1117   (already dark — slight tweak)
--sidebar-text             #d1d5db    dark  #c9d1d9
--sidebar-active           #2563eb    dark  #4c8dff
```

**17 color tokens need dark values.** Radii and shadows carry over unchanged, though shadows should get more opacity in dark mode (`0 1px 3px rgba(0,0,0,0.4)` vs light's `0.08`) to remain visible.

**Un-tokenized colors in the codebase to hunt down** (grep for `#` and `rgba` outside `:root`):
- `style.css` line 89: `rgba(255,255,255,0.06)` — sidebar hover, works in both modes
- `style.css` line 240: `#f3f4f6` and `#6b7280` in `.badge-muted` — needs tokens
- `style.css` line 261: `#047857` success hover — tokenize as `--success-hover`
- `style.css` line 264: `#b91c1c` danger hover — tokenize as `--danger-hover`
- `style.css` lines 427–428: `#a7f3d0`, `#fecaca` — feedback panel borders, tokenize
- `style.css` line 587: `rgba(0,0,0,0.5)` modal overlay — carries over fine
- `templates/index.html` line 20: `color:#c04040` (logout link) — inline, needs to reference token
- `templates/results.html`, `templates/errorlog.html`, `templates/test.html` — audit for inline colors

**Estimated tokenization work:** ~10 additional tokens + ~30 inline color references to replace with `var(--*)`. Grep + manual review = 1h.

#### 2.7 UX mockup — palette side-by-side

```
        LIGHT MODE                                DARK MODE
    ┌────────────────────────┐              ┌────────────────────────┐
    │ ▓▓▓ #111827 sidebar    │              │ ▓▓▓ #0d1117 sidebar    │
    │                        │              │                        │
    │  Dashboard             │              │  Dashboard             │
    │  ○ Take Test  █████████│  bg #f0f2f5  │  ○ Take Test  █████████│  bg #0f1419
    │  ⭐ Analytics ██ card ██│  surf #fff   │  ⭐ Analytics ██ card ██│  surf #1a1f26
    │  ⚠ Errors    ██████████│  text #1a1d23│  ⚠ Errors    ██████████│  text #e6edf3
    │  ← Logout              │              │  ← Logout              │
    │                        │              │                        │
    │  Primary btn: #2563eb  │              │  Primary btn: #4c8dff  │
    │  Success:    #059669   │              │  Success:    #3fb984   │
    │  Danger:     #dc2626   │              │  Danger:     #f85149   │
    └────────────────────────┘              └────────────────────────┘
```

Contrast checks (targeting WCAG AA = 4.5:1 for body text):
- Light `#1a1d23` on `#ffffff` = 15.9:1 ✓
- Light `#6b7280` (muted) on `#ffffff` = 4.83:1 ✓ (barely)
- Dark `#e6edf3` on `#1a1f26` = 13.6:1 ✓
- Dark `#8b949e` (muted) on `#1a1f26` = 6.4:1 ✓
- Dark `#4c8dff` on `#1a1f26` = 6.7:1 ✓ (primary must stay accessible for links)

#### 2.8 Implementation

1. **`static/style.css`** — after `:root { … }`, add:
   ```css
   [data-theme="dark"] {
     --bg: #0f1419;
     --surface: #1a1f26;
     /* … 15 more tokens … */
   }
   @media (prefers-color-scheme: dark) {
     :root:not([data-theme="light"]) { /* auto-mode inherits dark */ }
   }
   ```
2. **`static/script.js`** — add on top:
   ```js
   (function() {
     const saved = localStorage.getItem('theme');
     const theme = saved || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
     document.documentElement.dataset.theme = theme;
   })();
   window.setTheme = function(t) {
     localStorage.setItem('theme', t);
     document.documentElement.dataset.theme = t;
   };
   ```
   Inline into `<head>` (not via `<script src>`) to avoid flash-of-wrong-theme.
3. **Toggle UI** — add a small sun/moon button next to Logout in the sidebar, in every template. Or add a "Theme" select in the analytics page settings card. Recommend: **both**. Sidebar toggle for quick swap, settings for the auto/light/dark tri-state.
4. **Grep + replace inline colors** — see §2.6.
5. **Chart.js color adjustment** — the analytics page has `borderColor: '#2563eb'` hardcoded in JS. Read them from CSS variables at chart-init time via `getComputedStyle(document.documentElement).getPropertyValue('--primary')`.

**Flash-of-unstyled-content risk:** The inline `<script>` in `<head>` fixes this. Do not defer the theme-setter script.

---

### Item 3 — Mobile responsiveness (8h)

#### 2.9 Competitor scan

| Platform | Nav pattern on ≤768px | Key insights |
|----------|-----------------------|--------------|
| **Anki mobile / AnkiDroid** | Bottom nav 4 items (Decks / Add / Browse / Stats) + hamburger for settings | Study screen is full-bleed, no chrome. Nav hides during a review session. |
| **Duolingo mobile** | Bottom nav 5 items (Learn / Practice / Leagues / Quests / Profile) | Icons + labels always visible. Active tab has highlight bar under icon. |
| **Notion mobile** | Sidebar becomes a slide-out drawer (hamburger top-left) + bottom tabs for main sections | Two-level nav — top-level via tabs, deep via drawer. Overkill for us. |
| **Slack mobile** | Bottom tab bar 4 items + swipe-to-open drawer for workspaces | Fast switching between contexts. |
| **GitHub mobile** | Bottom nav 5 items; profile menu in header | Same layout as Duolingo essentially. |

**Chosen pattern: bottom nav with 4 items + hamburger.** Rationale:
- Kartik uses 4 primary sections (Dashboard, Test, Analytics, Errors). Logout is not "primary" — it goes in a menu.
- Bottom nav is thumb-reachable on 6.5"+ phones; top-left hamburger requires two-hand grip.
- The single-user context makes the case for tabs stronger — no workspace/team switching complexity.
- 4 items + more menu = 5 visible affordances; matches iOS HIG (max 5 tabs).

**What the bottom nav is:**

| Icon | Label     | Route          |
|------|-----------|----------------|
| ▤    | Dashboard | `/`            |
| ▶    | Test      | `/test/setup`  |
| ★    | Analytics | `/analytics`   |
| ⚠    | Errors    | `/errorlog`    |
| ⋯    | More      | opens drawer (Logout, Theme, Search, Admin if role=admin) |

#### 2.10 Breakpoint plan

Extend the existing `@media (max-width: 900px)` with two more:

```
default (≥900px)        Sidebar 240px full-labels. Current design.
@media ≤900px           Sidebar 60px icons-only. Current @media block.
@media ≤640px  NEW      Hide sidebar entirely. Show top app-bar (48px) + bottom nav (60px).
                        Content padding drops to 16px. Test palette collapses to 5 cols.
@media ≤380px  NEW      Question navigator 5 cols. Font size adjustments. Modals full-width.
```

**Test on:** iPhone SE (375), iPhone 12/13 (390), iPhone 14 Plus (428), Pixel 7 (412), foldable unfolded (280). Chrome DevTools device toolbar covers all of these.

#### 2.11 UX mockup — mobile bottom nav layout

```
┌─────────────────────────────┐  ← 48px top bar
│  ≡  Exam Platform      🌙   │      (hamburger + brand + theme toggle)
├─────────────────────────────┤
│                             │
│                             │
│                             │
│                             │
│      Dashboard              │  ← scrollable content area
│                             │      (padding: 16px)
│      ┌───────────────────┐  │
│      │   12 Tests done   │  │
│      │   64.2% avg       │  │
│      └───────────────────┘  │
│                             │
│      Weak Topics            │
│      • Networking     45%   │
│      • Data Structures 51%  │
│                             │
│                             │
├─────────────────────────────┤  ← 60px bottom nav
│  ▤    ▶    ★    ⚠    ⋯     │
│ Dash Test Anly Errs More    │
└─────────────────────────────┘
```

Active tab: primary-colored icon + label + 3px underline. Inactive: `--text-muted`.

#### 2.12 Question navigator on mobile

Current: `grid-template-columns: repeat(10, 1fr)` — 10 cells wide.
Mobile ≤640px: `repeat(5, 1fr)`.
Mobile ≤380px: `repeat(5, 1fr)` (keep 5 not 4 — 5 works for 20/25/50/100 question tests without awkward rows).

Cell size at 375px viewport, 16px content padding, 20px card padding: usable card body = 375 − 32 − 40 = 303px → 5 cells = ~60px per cell → comfortable 44px+ tap targets. ✓

Font size on cells: bump from 11px to 13px on mobile (11px is unreadable at that size).

#### 2.13 Implementation checklist

1. **`static/style.css`** — add ~150 lines of media queries under existing `@media (max-width: 900px)` block:
   - New `@media (max-width: 640px)`: hide sidebar, show `.mobile-topbar` + `.mobile-bottomnav`, adjust content padding.
   - New `@media (max-width: 380px)`: question navigator 5 cols, font tweaks, `.pagination` wrapping.
2. **All user templates** (`index.html`, `test.html`, `analytics.html`, `errorlog.html`, `results.html`, `test_setup.html`, `login.html`) — add two blocks at the top of `<body>`:
   ```html
   <header class="mobile-topbar" role="banner">…</header>
   <nav class="mobile-bottomnav" role="navigation">…</nav>
   ```
   Consider factoring these into a Jinja include (`templates/_mobile_nav.html`) — currently there's no shared base template for user pages, but this is a good excuse to add one. **Sub-task: introduce `templates/_base_user.html`** to DRY the sidebar + mobile nav. ~2h of the 8h estimate.
3. **`static/script.js`** — hamburger open/close handlers for the "More" drawer.
4. **Testing** — Chrome DevTools device emulation on the 5 target viewports. Manual smoke test of every route.

**Sub-task cost breakdown:**
- Extract shared base template: 2h
- Bottom nav + top bar CSS + templates: 2h
- Question navigator + palette fixes: 1h
- Modal + form mobile tweaks: 1h
- Analytics charts responsive audit (Chart.js is already responsive but legend placement breaks): 1h
- Manual testing + polish: 1h

---

### Item 4 — Global question search (6h)

#### 2.14 Competitor scan

| Platform | Mechanism | Latency | Ranking |
|----------|-----------|---------|---------|
| **Notion Cmd-K** | Server-side, indexed on Elasticsearch (theirs) or SQLite FTS (self-hosted forks) | ~200ms | Recency + relevance |
| **VS Code Cmd-Shift-P** | Client-side fuzzy match over pre-loaded command list (~500 items) | <10ms | Fuzzy score |
| **VS Code Cmd-P (file search)** | Client-side over file index (loaded on workspace open) | <50ms for 10k files | Fuzzy score + recency |
| **Algolia InstantSearch** | Server-side, custom index. Powers Stripe / Coinbase docs. | <50ms typical | TF-IDF + custom typo tolerance |
| **GitHub code search** | Server-side full-text index | 200–500ms | Path relevance + recency |
| **SQLite FTS5** (via Turso) | Server-side, BM25 ranking, supports prefix + phrase + boolean | <20ms for 3712 rows | BM25 |

#### 2.15 Server-side vs client-side decision

**Client-side (JS filter over JSON):**
- 3712 questions × ~500 bytes per row (question_text + options + explanation) = ~1.8 MB payload.
- Gzipped: ~400 KB.
- Load-time cost: one-shot fetch on first search-page visit, then cached in-memory.
- Runtime cost: filter over 3712 items is <50ms even with substring matching in vanilla JS.
- **Downside:** Every page reload re-downloads the payload (unless we cache in localStorage — but then staleness is a problem when admin edits questions).

**Server-side FTS5 (via Turso):**
- Turso is libSQL, which is a SQLite fork — **FTS5 is supported**. Verified: Turso docs list FTS5 as one of the SQLite extensions bundled by default in libSQL.
- New virtual table `questions_fts` mirrors `questions` via triggers.
- One query returns paginated results, ~10ms.
- Ranking: BM25 out of the box.
- **Migration:** one-time backfill of 3712 rows into FTS index. Add `INSERT/UPDATE/DELETE` triggers on `questions`.

**Recommendation: server-side FTS5.**

Reasons:
1. 400 KB per page load is not free on Kartik's mobile data.
2. FTS5 supports proper phrase search (`"data structure"`), prefix (`net*`), and boolean (`stack OR queue`) — hand-rolling this in JS is bug-bait.
3. When Plan D adds `confidence`, `pyq_year`, etc., they'll be indexed automatically via triggers.
4. Turso latency from India → Render (US) is ~300ms round-trip, but the query itself is <20ms; total <400ms which is fine for a search page.

**Fallback if FTS5 doesn't work on Turso:** `LIKE '%foo%'` scan of 3712 rows over Turso is ~100ms — still acceptable, just no ranking. Use this as the v1.

#### 2.16 Coordination with Plan D

Plan D will add these columns to `questions`:
- `confidence` (`high` | `medium` | `low`) — extraction confidence
- `pyq_exam` (TEXT) — source exam name if this is a previous-year question
- `pyq_year` (INTEGER)
- `section` (TEXT) — sub-topic grouping
- `sub_topic` (TEXT) — finer than topic

Search UI must include these as filters (see mockup §2.17). Effort estimate assumes columns exist; if not, filter dropdowns simply don't appear.

#### 2.17 UX mockup — search interface

Sidebar link: "🔍 Search" as 5th item (or 4th on mobile — replaces Errors in the bottom nav, Errors goes into More).

```
┌────────────────────────────────────────────────────────────────────┐
│  Search question bank                                              │
│  Search across 3,712 questions                                     │
├────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────┐          │
│  │ 🔍  binary tree traversal                         [×]│          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                    │
│  Filters:                                                          │
│  Topic     [ Data Structures ▼ ]  Paper [ II ▼ ]                   │
│  Difficulty[ Any ▼ ]              Confidence [ Any ▼ ]  ← Plan D   │
│  PYQ Year  [ Any ▼ ]              Section    [ Any ▼ ]  ← Plan D   │
│                                                                    │
│  47 results (BM25 ranked)                                          │
│  ────────────────────────────────────────────────────────          │
│                                                                    │
│  #2341  Data Structures · medium · pyq 2019                        │
│  Which traversal of a binary tree visits the root                  │
│  between the left and right subtrees? …                            │
│    A. Preorder   B. Inorder ✓  C. Postorder  D. Level              │
│  Practice this →                                                   │
│                                                                    │
│  #1874  Data Structures · easy                                     │
│  In a binary tree with n nodes, the number of null                 │
│  pointers is …                                                     │
│  Practice this →                                                   │
│                                                                    │
│  [ Load 25 more ]                                                  │
└────────────────────────────────────────────────────────────────────┘
```

**"Practice this" link:** starts a 1-question mini-test with just that question. Requires a route `/test/single?question_id=NNN` — small addition to `bp_tests.py`, reuses existing test infrastructure.

**Search input UX:**
- Debounced 300ms.
- Live results (fetch on each debounced keystroke) — same pattern as Algolia InstantSearch.
- Keyboard: `↑` / `↓` navigate results, `Enter` opens top result.
- `Esc` clears query.

#### 2.18 Implementation checklist

1. **`db.py`** — add `CREATE VIRTUAL TABLE questions_fts USING fts5(question_text, option_a, option_b, option_c, option_d, explanation, content='questions', content_rowid='id')` + three triggers (AFTER INSERT/UPDATE/DELETE on `questions`) to keep FTS in sync. Add to `SCHEMA` const so `init_db()` runs it on boot. **Backfill:** `INSERT INTO questions_fts(questions_fts) VALUES('rebuild')` — one-shot after table creation, gated on `SELECT count(*) FROM questions_fts` being 0.
2. **`bp_main.py`** — new route `GET /search` renders `templates/search.html`. New route `GET /api/search?q=&topic_id=&difficulty=&…` returns JSON `{results: […], total: N}`. Query:
   ```sql
   SELECT q.id, q.question_text, q.difficulty, t.name AS topic_name,
          q.correct_option, q.option_a, q.option_b, q.option_c, q.option_d,
          bm25(questions_fts) AS rank
   FROM questions_fts
   JOIN questions q ON questions_fts.rowid = q.id
   JOIN topics t ON q.topic_id = t.id
   WHERE questions_fts MATCH ?
     AND (? IS NULL OR q.topic_id = ?)
     AND (? IS NULL OR q.difficulty = ?)
     AND (q.disabled IS NULL OR q.disabled = 0)
   ORDER BY rank
   LIMIT ? OFFSET ?
   ```
3. **`templates/search.html`** — new template ~120 lines. Reuse existing `.card`, `.btn-option`, filter dropdown patterns from `admin/questions.html`.
4. **`static/script.js`** — add search-page functions: `debounce()`, `runSearch()`, keyboard nav.
5. **Sidebar link** — add "Search" to nav in all user templates. If shared base template lands (§2.13), one place.
6. **`bp_tests.py`** — add `/test/single` route that creates a 1-question mock test session.

**Turso caveat:** If `push_extracted_to_turso.py` or `turso_patch.py` bypasses the trigger path (direct INSERT that dodges triggers), the FTS index will drift. Verify: triggers on the main DB table fire regardless of client. But if turso_patch does its own remote INSERT via HTTP without going through SQLite, the trigger won't fire. **Check turso_patch.py before committing.**

---

## 3. Effort Summary

| Item                       | Hours | Files new | Files changed        | Schema change       |
|----------------------------|-------|-----------|----------------------|---------------------|
| Structured flagging v2     | 2     | 0         | 4                    | none                |
| Dark mode                  | 4     | 0         | 8 (all user templates + style.css + script.js) | none |
| Mobile responsiveness      | 8     | 1 (`_base_user.html`) | 8+                    | none                |
| Global question search     | 6     | 1 (`search.html`)     | 3 (`bp_main.py`, `db.py`, `bp_tests.py`) | +1 virtual table (`questions_fts`) + 3 triggers |
| **Total**                  | **20**| 2         | ~15 files            | additive only       |

## 4. Risks + Open Questions

1. **Turso FTS5 support** — need to verify with a live query before committing to §2.15. If FTS5 unavailable on the specific libSQL build Turso is running, fall back to `LIKE` scan. 15-min spike.
2. **Base user template extraction** — currently every template repeats the sidebar HTML. Introducing `_base_user.html` mid-plan means every template gets a diff. Do it as part of Item 3 (mobile), not Item 2 (dark mode), so the dark-mode inline scripts land first without a rebase headache.
3. **Chart.js dark mode** — Chart.js reads colors at chart-init time. Theme toggle after a chart is drawn does NOT re-color it. Fix: on theme toggle, iterate registered Chart instances and call `.update()`. Or use CSS custom properties (Chart.js 4 supports this natively via `getComputedStyle`). Small piece of work included in Item 2's 4h.
4. **Flag category migration** — old rows keep their old category values. Admin flag list must render them without breaking. Consider a display-time map: `{"data_inconsistency": "Wrong answer key (legacy)", …}`.
5. **Search + admin overlap** — admin's `/admin/questions` filter page and the new user-facing `/search` will look similar. Long-term, admin should reuse the same search widget with an admin-only mode toggle showing disabled + edit buttons. Out of scope for this plan; noted.
6. **Autocomplete on search** — not included. Add later if needed. FTS5 supports prefix (`net*`) queries which cover most autocomplete needs already.
7. **Mobile testing without a real device** — Kartik should test on his actual phone before considering mobile "done." Chrome DevTools emulation catches ~80% of issues; the rest are real-device only (touch gestures, iOS safe-area insets).

## 5. What's Deliberately Out of Scope

- Internationalization / RTL support. Content is bilingual Hindi/English but layout is LTR-only. Not urgent.
- Progressive Web App / offline mode. Would need service worker + IndexedDB caching. Big lift, low daily value.
- Full accessibility audit (ARIA labels, screen reader flow). Single-user tool; can be done later once the design settles.
- Print stylesheet. Duplicative with Plan B's PDF export feature.
- Font size / density preferences beyond dark mode. YAGNI for a solo user.
- Multi-column layout switcher on desktop. Current design is already fine on 27" monitors.

---

## 6. Acceptance Criteria

- **Flagging:** Submitting a report without picking a radio button shows an inline error. Submitting "Other" without a note shows an inline error. Admin flag list shows category as a colored pill matching priority tier. Admin dashboard shows a count-by-category summary.
- **Dark mode:** Toggle in sidebar swaps theme instantly, no flash. Preference persists across reloads. Auto mode follows `prefers-color-scheme`. Every page renders correctly in both themes (visual smoke test). Charts respect the theme.
- **Mobile:** All primary flows (login → dashboard → take test → view results → view analytics → view errors) work on iPhone SE (375px) with no horizontal scroll. Tap targets meet 44×44px. Question navigator is usable one-handed.
- **Search:** Query "binary tree" returns questions containing those words, ranked by BM25 relevance. Filters composable with the text query. `Practice this` starts a 1-question mock. Debounced input, live results, keyboard nav.

---

## Appendix — File-by-File Change Summary

| File                                       | Item(s)         | Change                                           |
|--------------------------------------------|-----------------|--------------------------------------------------|
| `bp_api.py`                                | 1 (flagging)    | Update `FLAG_CATEGORIES` set; add `note` required-for-Other check. |
| `templates/test.html`                      | 1, 2, 3         | Radio-list flag modal; theme-aware; mobile-friendly. |
| `templates/admin/flags.html`               | 1               | Category badges, category filter dropdown.        |
| `templates/admin/dashboard.html`           | 1               | Add flags-by-category widget.                     |
| `static/style.css`                         | 2, 3            | Dark tokens (`[data-theme="dark"]` block); new media queries `≤640px`, `≤380px`; mobile nav classes; flag-radio-list styles. |
| `static/script.js`                         | 2, 3, 4         | Theme setter (inline in `<head>`); mobile nav handlers; search debounce + kb nav. |
| `templates/index.html`                     | 2, 3            | Theme meta, mobile nav.                           |
| `templates/analytics.html`                 | 2, 3            | Chart.js theme-var reading; mobile nav.           |
| `templates/errorlog.html`                  | 2, 3            | Mobile nav; theme-aware.                          |
| `templates/results.html`                   | 2, 3            | Mobile nav; theme-aware.                          |
| `templates/test_setup.html`                | 2, 3            | Mobile nav; theme-aware.                          |
| `templates/login.html`                     | 2               | Theme-aware (mobile nav N/A — no logged-in yet).  |
| `templates/_base_user.html` **(new)**      | 3               | Shared sidebar + mobile nav + head.               |
| `templates/search.html` **(new)**          | 4               | Search UI.                                        |
| `bp_main.py`                               | 4               | `/search` route + `/api/search` route.            |
| `bp_tests.py`                              | 4               | `/test/single?question_id=` route.                |
| `db.py`                                    | 4               | `questions_fts` virtual table + triggers.         |
| `turso_patch.py`                           | 4 (verify)      | Confirm INSERT path fires FTS triggers.           |

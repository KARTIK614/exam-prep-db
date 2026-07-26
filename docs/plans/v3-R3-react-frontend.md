# v3-R3 — React + TypeScript Frontend Stack

**Status:** Research / planning only — no code, no scaffolding. Companion to R1 (Rust API) and R2 (Turso schema) planning docs in the v3 replatform series.
**Scope:** Pick the frontend stack that replaces the current Flask + Jinja templates with a React/TypeScript SPA talking to the Rust API. Feature parity with the v2 plans in this directory (A–E) is the acceptance bar; a small set of new pages (signup, forgot-password, profile) is additive.
**Audience:** Kartik, solo dev, evenings only. All decisions optimize for "minimum tools I have to reason about at 10 PM" over "maximum theoretical power."
**Author:** research fork, 2026-07-19.

---

## 0. TL;DR — the stack in one table

| Concern | Pick | Runner-up | Why |
|---|---|---|---|
| **Build tool** | Vite 5 | Next.js 14 | Client-only SPA; no SSR benefit for authed exam prep; 10× faster dev server than a Next.js app of comparable size |
| **Router** | React Router v6 (data APIs) | TanStack Router | Mature, ubiquitous; TanStack's type-safe routes are attractive but its churn cost (majors every ~6 mo) exceeds the benefit for a 20-page app |
| **Server state** | TanStack Query v5 | RTK Query | Best-in-class cache/invalidation, no store boilerplate, plays nicely with a hand-written or generated client |
| **Client/UI state** | Zustand | Jotai / Redux Toolkit | Test-taking screen has ~8 shared UI atoms (current index, palette state, timer tick, marked-for-review set, theme, modal stack); Zustand is 4 KB and fits on one screen |
| **Styling** | Tailwind CSS + CSS variables (dark via `data-theme`) | vanilla-extract | Existing CSS is already token-driven; Tailwind config lifts the tokens 1:1; zero runtime cost |
| **Forms** | react-hook-form + Zod | Formik | Uncontrolled by default = fast + tiny; Zod resolver shares schemas with API DTOs |
| **Components** | shadcn/ui (Radix + Tailwind) | Headless UI | Copy-paste, no package to upgrade, a11y from Radix, styles you own |
| **API client** | openapi-typescript (types) + thin `fetch` wrapper | orval / codegen w/ hooks | R4 owns the OpenAPI spec; we consume types, hand-write ~15 endpoint functions |
| **Auth on client** | httpOnly cookie (access) + refresh via silent-renew endpoint | localStorage JWT | XSS-safe; requires R4 CORS/credentials plumbing; worth it |
| **Testing (unit)** | Vitest + React Testing Library + jest-axe | Jest + RTL | Vitest reuses Vite config, ~2× faster; RTL is the only sane choice; axe for a11y regressions |
| **Testing (E2E)** | Playwright | Cypress | Multi-browser, better CI story, tracing viewer, faster on cold-start |
| **Deploy** | Vercel (SPA, preview per PR) | Render Static Site | Better DX, PR previews out of the box; Render still fine if we want one vendor |

**Bundle-size envelope target:** 180 KB gzipped for the initial route (login/dashboard). Route-split analytics, admin, and search below that.

---

## 1. Build tool

### 1.1 Options

- **Vite 5** — dev server on native ESM, Rollup for production build, first-class React plugin. What everyone new to React reaches for in 2026.
- **Next.js 14 (App Router)** — full-stack framework with SSR, RSC, file-system routing, image optimization.
- **Remix 2** — nested routes + progressive enhancement; strongest at forms and server data.
- **Create React App** — deprecated by the React team in 2023; skip.
- **Parcel / Rspack / Turbopack** — real but marginal; Vite is the Schelling point for a React SPA.

### 1.2 What we actually need

- Client-side app; the Rust API in R4 owns all data.
- Authed content only. No SEO on `/dashboard`, `/test/:id`, `/analytics`, `/admin/*`.
- Public pages: `/login`, `/signup`, `/forgot-password`, `/reset-password/:token`. Even those don't need SSR — they're single-form pages, no crawlable content.
- HMR that survives editing `test.html`-equivalent code without losing test-in-progress state.
- Small bundle: solo user on possibly-flaky Indian mobile networks.

### 1.3 Why Vite over Next.js

**Against Next.js (App Router):**
- React Server Components add a mental model overhead ("is this file server or client?" branching in every new component) that pays off only when you have SSR / streaming needs. We don't.
- Deployment on Vercel is Next.js-tuned but works fine with static Vite too.
- App Router had breaking changes in 13.0, 13.4, 14.0 — churn tax on a 4-week-attention-span project.
- Middleware for auth in Next is edge-runtime restricted; we already do auth server-side in R4.

**Against Remix:**
- Its strengths are progressive enhancement + form actions, which we don't need — our forms POST JSON to a Rust API.
- Smaller community than Next; more likely to hit an unanswered edge case.

**For Vite:**
- Cold start ~300 ms vs Next's ~2–4 s for a comparable project.
- Prod build is Rollup — mature, predictable code-splitting.
- Static output → hosts anywhere (Vercel, Render, Netlify, Cloudflare Pages, S3+CDN, even Render as a Static Site fronting the Rust API).
- Vitest reuses the Vite config → one build pipeline for dev, prod, unit tests.

**Verdict:** Vite. Reconsider only if we ever need SEO on public marketing pages, at which point a separate marketing-site Next.js repo is cheaper than SSR-ing an authed SPA.

### 1.4 Vite config essentials

```ts
// vite.config.ts (sketch)
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3000', changeOrigin: true },
    },
  },
  build: {
    target: 'es2020',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['recharts'],
          markdown: ['react-markdown', 'remark-math', 'rehype-katex'],
        },
      },
    },
  },
});
```

Two chunks worth breaking out early: **recharts** (heavy, only on `/analytics`) and **KaTeX/markdown** (heavy, only on question rendering). Everything else can auto-split by route.

---

## 2. Router

### 2.1 Options

- **React Router v6** with data APIs (`loader`, `action`, `useLoaderData`)
- **TanStack Router** — fully type-safe routes, first-class integration with TanStack Query
- **wouter** — 1.5 KB minimalist; skip, we have real needs (nested layouts, guards)
- **Next/Remix built-in** — moot given §1

### 2.2 Recommendation: React Router v6

**For TanStack Router:**
- End-to-end route param typing is legit useful — no more `useParams()` returning `Record<string, string | undefined>`.
- Same author as TanStack Query → they compose well.

**Against TanStack Router:**
- v1 shipped only in 2024; churn risk high through 2026.
- The type-safe URLs are cool but they don't save enough LOC on 20 routes to justify a stack pick that reduces the pool of Stack Overflow answers by 20×.
- Kartik will Google `react router protected route redirect` more than `tanstack router` and needs the top-result to work.

**For React Router v6:**
- Everyone knows it. AI code assistants know it best.
- Data APIs (`loader`, `action`) let us pre-fetch on navigation and avoid render-then-fetch waterfalls without changing the mental model to RSC.
- Nested routes cleanly express the admin layout.

**Verdict:** React Router v6. Revisit TanStack Router in 2027 once its API stabilizes.

### 2.3 Route sketch

```tsx
// router.tsx (sketch)
createBrowserRouter([
  { path: '/login', element: <Login /> },
  { path: '/signup', element: <Signup /> },
  { path: '/forgot-password', element: <ForgotPassword /> },
  { path: '/reset-password/:token', element: <ResetPassword /> },

  {
    element: <RequireAuth><AppShell /></RequireAuth>,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },
      { path: 'test/new', element: <TestSetup /> },
      { path: 'test/:id', element: <TakeTest /> },
      { path: 'test/:id/results', element: <TestResults /> },
      { path: 'analytics', element: <Analytics /> },
      { path: 'errors', element: <ErrorLog /> },
      { path: 'review', element: <Review /> },
      { path: 'bookmarks', element: <Bookmarks /> },
      { path: 'search', element: <Search /> },
      { path: 'profile', element: <Profile /> },
    ],
  },

  {
    path: 'admin',
    element: <RequireAdmin><AdminShell /></RequireAdmin>,
    children: [
      { index: true, element: <AdminDashboard /> },
      { path: 'questions', element: <AdminQuestions /> },
      { path: 'questions/:id', element: <AdminQuestionEdit /> },
      { path: 'flags', element: <AdminFlags /> },
      { path: 'review', element: <AdminReview /> },
      { path: 'duplicates', element: <AdminDuplicates /> },
      { path: 'topics', element: <AdminTopics /> },
      { path: 'uploads', element: <AdminUploads /> },
      { path: 'synthesize', element: <AdminSynthesize /> },
      { path: 'prompts', element: <AdminPrompts /> },
      { path: 'users', element: <AdminUsers /> },
    ],
  },

  { path: '*', element: <NotFound /> },
]);
```

`RequireAuth` reads from `useAuth()` (§7); on 401 from the API, an axios-esque interceptor calls `logout()` which resets the store and navigates to `/login?next=<current>`.

---

## 3. State management

### 3.1 The two-store rule (recommended posture)

Split state by origin, not by feature:

- **Server state** — anything the Rust API owns: questions, tests, analytics, error log, bookmarks, review queue, admin data. → **TanStack Query.**
- **Client state** — UI-only atoms: theme, current test in-progress state (index, palette states, timer, marked-for-review set), open modals, toast stack, sidebar collapse. → **Zustand.**

This is the same split every React app converges on around the second refactor. Do it from day one.

### 3.2 Why TanStack Query for server state

- Automatic cache keys per URL + params. Free stale/refetch semantics on window focus.
- Mutations with `onSuccess` invalidation are the natural fit for "submit answer → dashboard stats refresh".
- DevTools panel shows every in-flight and cached query — invaluable when debugging why the mastery grid didn't update.
- Works with any fetching primitive; not opinionated about the client.

Alternatives considered:
- **RTK Query** — bundled with Redux Toolkit; adds Redux ceremony we otherwise avoid.
- **SWR** — smaller, but Query's mutation ergonomics and mature typing win at this app size.
- **Apollo Client** — GraphQL; we're REST.

### 3.3 Why Zustand for client state

The test-taking screen is the only page with meaningful client state:

```
useTestSession {
  testId, questionCount, currentIndex,
  answers: Record<qIdx, 'A'|'B'|'C'|'D'>,
  markedForReview: Set<qIdx>,
  visited: Set<qIdx>,
  startedAt, elapsedSec, totalDurationSec, mode: 'exam'|'practice',
  select(qIdx, opt), toggleMark(qIdx), next(), prev(),
  jumpTo(qIdx), tick(), autoSubmitIfExpired()
}
```

Also small, independent stores:

- `useTheme` — `'light' | 'dark' | 'system'`, persisted to localStorage
- `useToasts` — a global toast stack
- `useModal` — a lightweight modal stack (or use Radix `Dialog` and skip this)
- `useCommandPalette` — Cmd-K open/close state, current query

**Zustand's traits that matter here:**
- No provider. Just import the hook.
- Selector-based subscriptions — the timer ticking every second doesn't re-render the palette.
- `persist` middleware for `useTheme`.
- 4 KB gzipped.

**Against Redux Toolkit:** For 3–4 slices of client state, Redux is overkill. If in 12 months the state graph balloons (e.g., multi-user, real-time), migrating Zustand → RTK is straightforward — the store shape moves 1:1.

**Against Jotai:** Atom-per-value is elegant for widget state but awkward when the widget state has real internal invariants ("if `mode === 'exam'` then don't show `correct_option`"). Zustand slices those invariants naturally.

### 3.4 What NOT to put in the server-state cache

- The in-progress test session. It's a client-side scratchpad that gets flushed to the server on `submit_answer` / `toggle_review` mutations. Storing it in Query cache invites accidental refetches that wipe user input.
- Theme, sidebar collapse, modal open state — obviously.

### 3.5 What NOT to put in Zustand

- Any list of items fetched from the API. Even if it "feels like client state" (e.g., bookmarks list), Query owns it — otherwise cache invalidation gets manual.

---

## 4. Styling

### 4.1 Current state (v2 CSS)

- `static/style.css` (737 L) is already token-driven: 22 CSS custom properties on `:root`, dark mode via `[data-theme="dark"]` overrides (`static/style.css:5-70`).
- Component classes (`.btn-primary`, `.stat-card`, `.score-bar`, `.badge-success`) follow a consistent naming. Not a framework, but disciplined.
- Chart.js is loaded on analytics; we'll swap to recharts (better React integration).

### 4.2 Options

| Option | Pros | Cons |
|---|---|---|
| **Tailwind CSS 3** | Utility-first, huge community, JIT compiler → tiny prod CSS; native dark-mode via `dark:` variant or `data-theme`; shadcn/ui native fit | Learning curve if unfamiliar; long class strings in JSX |
| **CSS-in-JS (Emotion / styled-components)** | Colocated styles, dynamic props | Runtime cost (~5 KB) + SSR gotchas; both libraries in slow-maintenance mode |
| **vanilla-extract** | Zero-runtime, typed styles, atomic option | Steepest learning curve; smallest community; overkill for a solo app |
| **Plain CSS + CSS variables** | Zero new tools; migrate v2 CSS as-is | No design-system enforcement, class-name collisions, still need PostCSS for autoprefixer |
| **CSS Modules** | Scoped classes, plain CSS | Fine but doesn't buy much over Tailwind and loses shadcn/ui compatibility |

### 4.3 Recommendation: Tailwind + `data-theme` dark mode

**Why Tailwind here specifically:**
- The existing v2 tokens map to `tailwind.config.ts`'s `theme.extend.colors` 1:1. Zero translation work.
- shadcn/ui components (see §6) assume Tailwind. Picking anything else forfeits that library.
- Dark mode via CSS variables + `data-theme` attribute matches the v2 pattern exactly — we don't need Tailwind's `dark:` variant, we drive it from variables.
- Prod CSS is ~15–25 KB after purge for this feature surface.

**Config sketch:**

```ts
// tailwind.config.ts
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        primary: 'rgb(var(--primary) / <alpha-value>)',
        'primary-hover': 'rgb(var(--primary-hover) / <alpha-value>)',
        'primary-light': 'rgb(var(--primary-light) / <alpha-value>)',
        success: 'rgb(var(--success) / <alpha-value>)',
        danger:  'rgb(var(--danger)  / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        // ...map the remaining v2 tokens
      },
      borderRadius: {
        DEFAULT: 'var(--radius)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        DEFAULT: 'var(--shadow)',
        md: 'var(--shadow-md)',
      },
    },
  },
  plugins: [require('@tailwindcss/forms'), require('tailwindcss-animate')],
};
```

Colors as CSS-variable references (using Tailwind's `rgb(var(--x) / <alpha-value>)` pattern) means dark-mode swapping happens in one place — `[data-theme="dark"]` on `<html>` — without duplicating every rule.

### 4.4 Dark-mode strategy

1. `useTheme` Zustand store, persisted to localStorage, three modes: `light | dark | system`.
2. On app boot, an inline script in `index.html` reads localStorage and sets `data-theme` on `<html>` **before** React mounts (avoids the flash of wrong theme). This script is <10 LOC.
3. When mode is `system`, listen to `matchMedia('(prefers-color-scheme: dark)')` and update `data-theme` on change.
4. All Tailwind utilities that reference tokens automatically flip; component code has zero conditional theme logic.
5. Charts (recharts) accept a color prop → read from `useTheme()` and pass through.

### 4.5 Migration path from v2 CSS

The 737-line `static/style.css` isn't wasted. Strategy:

1. Copy the `:root` and `[data-theme="dark"]` token blocks verbatim to `src/styles/tokens.css`.
2. Import once in `main.tsx` before Tailwind's base.
3. Rewrite component styles as Tailwind classes in the JSX. The `.score-bar`, `.stat-card`, etc. patterns collapse into 5–10 Tailwind utilities each.
4. Print CSS (`@media print`, for Plan B's PDF export) stays a small dedicated stylesheet.

Estimated CSS rewrite effort: ~6 hours across all pages, front-loaded on the shared shell (sidebar/topbar) and test-taking screen (highest visual complexity).

---

## 5. Forms

### 5.1 Options

- **react-hook-form** + **Zod** — uncontrolled inputs, resolver-based validation, tiny (~9 KB + Zod)
- **Formik** — controlled, mature, in maintenance mode
- **TanStack Form** — new, type-safe, still stabilizing
- **Native `<form>` + `useState`** — fine for 2-field forms

### 5.2 Where forms live

| Page | Fields | Complexity |
|---|---|---|
| Login | email, password | Trivial |
| Signup | email, password, confirm, name | Trivial + cross-field validation (password match, strength) |
| Forgot password | email | Trivial |
| Reset password | password, confirm | Trivial + cross-field |
| Profile | name, email, current password, new password | Medium |
| Test setup | paper, topics[], difficulty, question_count, focus_weak, pyq_only, mode, negative_ratio, duration_min | High — 9 fields, conditional visibility (neg-marking only in exam mode) |
| Admin question edit | statement, options × 4, correct_option, topic_id, difficulty, source, explanation, confidence, disabled | High — 12 fields, LaTeX preview beside statement |
| Admin synthesize form | prompt, topic, count, difficulty | Medium |
| Flag question modal | category (radio), note (conditional required) | Medium — see Plan E §2.2 |

### 5.3 Recommendation: react-hook-form + Zod

- Uncontrolled inputs = no re-render on every keystroke = the test-setup form with 9 fields feels instant.
- Zod schemas double as OpenAPI-derived DTOs on the client — a login schema is 6 lines and gives us runtime validation + TS types for free.
- The `useController` hook handles the rare controlled-input case (Radix `Select`, shadcn `RadioGroup`) cleanly.
- Solves the two hardest form problems in this app: cross-field validation (password match) and conditional field visibility (neg-marking).

### 5.4 Schema-sharing plan

Zod schemas live in `src/lib/schemas/`, one file per resource. They serve two consumers:

1. Client-side form validation via `zodResolver`.
2. Runtime validation of API responses (defence-in-depth against R4 drift): after `fetch`, `parse` with the schema; on failure, throw and let the error boundary render a "server returned malformed data" message with a stack.

If R4 publishes an OpenAPI spec (R4 §X), we can regenerate a subset of these via `openapi-zod-client` — but hand-writing 15 schemas is a two-hour job and we get exactly the shapes we want.

---

## 6. Component library

### 6.1 Options survey

| Library | Model | Fit | Notes |
|---|---|---|---|
| **shadcn/ui** | Copy-paste Radix + Tailwind components | Excellent | Not a package. You run `npx shadcn add button` and it drops `src/components/ui/button.tsx` into your repo. You own it. |
| **Radix UI Primitives** | Unstyled, accessible primitives | Excellent | shadcn/ui builds on this. Use directly for widgets shadcn doesn't ship (e.g., toolbar). |
| **Headless UI** (Tailwind Labs) | Unstyled + Tailwind | Good | Smaller surface than Radix; Radix is now the default answer |
| **MUI** | Opinionated Material | Poor | Design language mismatch; huge bundle; Emotion runtime |
| **Chakra UI** | Opinionated + themeable | Poor | Same category as MUI; slower ecosystem |
| **Ant Design** | Opinionated + dense | Poor | Enterprise CRUD look; wrong vibe |
| **Mantine** | Opinionated + comprehensive | Fair | Great, but you buy their design system, not yours |

### 6.2 Recommendation: shadcn/ui, backed by Radix directly for gaps

**Why:**
- We already own the design system (v2 tokens). shadcn/ui components pull colors from our Tailwind config → they look like ours from day one.
- No dependency to upgrade. If Radix ships a fix, we pull the diff into the local copy. If we don't want their change, we don't take it.
- Accessibility is Radix-grade (focus trap, keyboard, ARIA) without us thinking about it.
- shadcn ships exactly the primitives we need: `Button`, `Dialog`, `DropdownMenu`, `Tabs`, `Select`, `RadioGroup`, `Toast`, `Tooltip`, `Command` (Cmd-K), `Popover`.

**What shadcn doesn't give us (build hand-rolled):**
- `PaletteButton` — the 5-state exam palette cell (Plan B §2). Own component using Radix `Tooltip`.
- `MasteryTile` — the topic mastery card (Plan C §1). Pure CSS grid + Tailwind.
- `Heatmap` — the topic × difficulty × recency matrix (Plan A F2). No good library; hand-roll ~150 LOC.
- `Timer` — countdown with 5-min red-flash warning (Plan B §4.3). Hand-roll ~40 LOC.
- `QuestionRenderer` — markdown + LaTeX (KaTeX). Compose `react-markdown` + `remark-math` + `rehype-katex`.

### 6.3 Charts

**recharts** for the 6 charts on `/analytics` (mastery bars, progress-over-time line, difficulty pie, pacing chart, error-type breakdown, paper comparison). Alternatives (Chart.js via `react-chartjs-2`, Visx, Nivo) were considered:

- Chart.js is what v2 uses; recharts is more idiomatic React and renders to SVG (a11y-friendlier).
- Visx is powerful but low-level — too much LOC for our chart set.
- Nivo has beautiful defaults but heavier bundles.

Route-split recharts into its own chunk (~90 KB gzipped) so it doesn't hit the dashboard bundle.

### 6.4 KaTeX for math

Questions contain LaTeX (see v2 `templates/test.html` and `bad_latex` flag category in Plan E). `react-katex` or the `rehype-katex` pipeline into `react-markdown`. Prefer the pipeline: markdown-first content survives a future switch to a rich editor.

---

## 7. Auth handling on the client

### 7.1 Token model (assumed from R2 auth planning)

- **Access token** — short-lived (15 min), sent as `Authorization: Bearer <jwt>` OR as httpOnly cookie.
- **Refresh token** — long-lived (7 d rolling), httpOnly cookie only, tied to a device/session row in Turso.
- **CSRF** — if we use cookies for the access token, need CSRF token on state-changing requests OR SameSite=Lax + double-submit cookie.

### 7.2 Storage options

| Storage | XSS-safe? | CSRF-safe? | Complexity | Verdict |
|---|---|---|---|---|
| **localStorage** | No — any XSS reads the token | Yes | Low | Fine for pure prototype; not for this |
| **httpOnly cookie (SameSite=Lax)** | Yes | Needs care on mutations | Medium | **Chosen** |
| **In-memory only** | Yes | Yes | High — every reload needs a refresh call | Overkill |

**Recommendation:** httpOnly cookie for both access and refresh. Client never sees the JWT. Every request goes with `credentials: 'include'`.

Consequences:
- `fetch` calls must all set `credentials: 'include'`. Wrap in `src/lib/api/client.ts`.
- CORS on R4 must allow the frontend origin **with credentials**. Not `*`.
- Login POST → server sets both cookies, responds with `{ user: { id, email, roles } }`. Client stores that user object in `useAuth` Zustand store.
- Logout → POST `/api/auth/logout`; server clears cookies; client zeroes `useAuth`.
- On any 401 from a protected endpoint: client attempts silent refresh via `/api/auth/refresh` (idempotent, 1× per 401). On refresh success, replay the original request. On refresh 401, clear `useAuth` and route to `/login?next=<current>`.

### 7.3 Silent renewal

Access token expires every 15 minutes. Two approaches:

- **Reactive**: only refresh on 401. Simple, occasional 1-request stall for the user.
- **Proactive**: set a `setTimeout` to refresh 60 s before expiry. Adds background chatter.

**Recommendation:** Reactive. The 401→refresh→replay path is 2 extra network round-trips only when the tab has been idle past expiry. In the test-taking flow (steady traffic), the refresh happens between two answer submissions; imperceptible.

### 7.4 Route guards

```tsx
// src/components/RequireAuth.tsx (sketch)
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, hydrated } = useAuth();
  const location = useLocation();
  if (!hydrated) return <FullPageSpinner />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user, hydrated } = useAuth();
  if (!hydrated) return <FullPageSpinner />;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.roles.includes('admin')) return <Forbidden />;
  return <>{children}</>;
}
```

On boot, `useAuth` calls `/api/auth/me` (cheap; reads cookie, returns user). If 401, sets `user=null, hydrated=true` and unauthenticated routes render. If 200, sets user and authed routes render. Splash screen during hydration prevents a "flash of login page" for already-signed-in users.

### 7.5 Login `next` redirect

Preserve intent when the app kicks the user to `/login` mid-navigation:

- `RequireAuth` sends the user to `/login?next=/analytics`.
- Login form on success reads `next` from query params, defaults to `/dashboard`.
- Validate `next` is a relative path (starts with `/`, no `//` or `http://`) to avoid open-redirect vulns.

---

## 8. API client

### 8.1 Options

| Approach | Effort | Type-safety | Maintenance |
|---|---|---|---|
| **Hand-written thin `fetch` wrapper** | Low | Only if we hand-type responses | Low |
| **openapi-typescript** (types-only from OpenAPI) + hand-written functions | Low | High — types from spec | Low |
| **orval** (client + hooks from OpenAPI) | Medium | High | Medium — regenerate on API changes |
| **openapi-fetch** (typed fetch wrapper) | Low | High | Low |
| **Axios + manual typing** | Low | Manual | Low |
| **tRPC** | High | Highest | High — requires TS server, not Rust |

### 8.2 Recommendation: openapi-typescript for types + hand-written thin wrapper

**Assumes R4 publishes an OpenAPI spec.** If it doesn't, fall back to hand-typed DTOs and Zod schemas as the source of truth.

**Why not full codegen (orval):**
- Generated code is verbose and rarely reads well. We have ~25 endpoints — writing them by hand is a half-day and the result is prettier + more debuggable.
- Codegen tools have their own bugs; a stale generator is a support burden.
- The Query hook wrappers we want are opinionated (retry policy, invalidation keys, error toasts) — hand-writing them means they do exactly what we want.

**Why not tRPC:**
- Requires a TypeScript backend. R4 is Rust. Non-starter.

### 8.3 Sketch

```ts
// src/lib/api/client.ts
import type { paths } from './openapi';   // generated by openapi-typescript
import createClient from 'openapi-fetch';

export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE ?? '',
  credentials: 'include',
});

// One wrapper per resource, thin:
export async function login(body: { email: string; password: string }) {
  const { data, error } = await api.POST('/api/auth/login', { body });
  if (error) throw new ApiError(error);
  return data;
}

// Query hook layer:
export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/dashboard');
      if (error) throw new ApiError(error);
      return data;
    },
  });
}
```

**Interceptor for 401 → silent refresh:** wrap `createClient` with middleware that catches 401s, calls `/api/auth/refresh` once, retries the original request. If refresh 401s, dispatch a logout event that the `useAuth` store subscribes to.

### 8.4 Error model

Every API error surfaces as an `ApiError` with `{ status, code, message, details? }`. Query layer:
- 4xx (except 401) → surface as toast + render inline in the offending component.
- 401 → handled by interceptor, invisible unless refresh fails.
- 5xx → global error boundary or persistent toast with a retry button.

---

## 9. Directory structure

```
frontend/
  index.html                     # single entry; inline theme-flash-prevention script
  package.json
  vite.config.ts
  tailwind.config.ts
  postcss.config.js
  tsconfig.json
  .eslintrc.cjs
  .prettierrc
  vercel.json                    # or render.yaml — SPA fallback + headers
  openapi.yaml                   # copy of R4's spec; regen types from here
  scripts/
    gen-api-types.ts             # runs openapi-typescript
  public/
    favicon.svg
    og-image.png
  src/
    main.tsx                     # ReactDOM.createRoot; QueryClientProvider; RouterProvider
    App.tsx                      # error boundary; toast portal
    router.tsx                   # route tree (§2.3)
    pages/
      Login.tsx
      Signup.tsx
      ForgotPassword.tsx
      ResetPassword.tsx
      Dashboard.tsx
      TestSetup.tsx
      TakeTest.tsx
      TestResults.tsx
      Analytics.tsx
      ErrorLog.tsx
      Review.tsx                 # SRS due queue
      Bookmarks.tsx
      Search.tsx
      Profile.tsx
      NotFound.tsx
      admin/
        AdminShell.tsx
        AdminDashboard.tsx
        AdminQuestions.tsx
        AdminQuestionEdit.tsx
        AdminFlags.tsx
        AdminReview.tsx
        AdminDuplicates.tsx
        AdminTopics.tsx
        AdminUploads.tsx
        AdminSynthesize.tsx
        AdminPrompts.tsx
        AdminUsers.tsx
    components/
      layout/
        AppShell.tsx             # sidebar + main
        Sidebar.tsx
        Topbar.tsx               # user menu, theme toggle, Cmd-K trigger
        MobileNav.tsx            # bottom nav for phones
      ui/                        # shadcn/ui components live here (copy-paste, owned)
        button.tsx
        dialog.tsx
        input.tsx
        select.tsx
        radio-group.tsx
        tabs.tsx
        tooltip.tsx
        toast.tsx
        command.tsx              # Cmd-K palette
        popover.tsx
        dropdown-menu.tsx
      test/
        PaletteButton.tsx        # 5-state cell (Plan B)
        Palette.tsx              # grid of PaletteButtons
        QuestionCard.tsx
        OptionRow.tsx
        Timer.tsx
        Shortcuts.tsx            # keyboard handler + hint bar
        ShortcutsCheatsheet.tsx  # `?` modal
        FlagQuestionDialog.tsx
        BookmarkStar.tsx
        NegativeMarkingBadge.tsx
      dashboard/
        ConsistencyBadge.tsx
        MasteryGrid.tsx
        MasteryTile.tsx
        NextWeakTopicCard.tsx
        SrsDuePill.tsx           # "N cards due today"
      analytics/
        MasteryBarChart.tsx
        ProgressLineChart.tsx
        Heatmap.tsx              # Plan A F2
        HeatmapCell.tsx
        PacingChart.tsx
        DifficultyPie.tsx
      forms/
        FormField.tsx            # label + input + error, shared shell
        PasswordInput.tsx        # with strength meter
      question/
        QuestionRenderer.tsx     # markdown + KaTeX
        ExplanationPanel.tsx
      common/
        Spinner.tsx
        EmptyState.tsx
        ErrorBoundary.tsx
        ThemeToggle.tsx
        CommandPalette.tsx       # Cmd-K (search + nav)
    hooks/
      useAuth.ts
      useTheme.ts
      useTestSession.ts          # Zustand store hook
      useShortcuts.ts            # register keyboard handlers with cleanup
      useMediaQuery.ts
      useDebounce.ts
      useLocalStorage.ts
    stores/
      auth.ts
      theme.ts
      testSession.ts
      toasts.ts
    lib/
      api/
        client.ts                # openapi-fetch + interceptors
        openapi.d.ts             # generated types (gitignored or committed — TBD)
        auth.ts                  # login/logout/refresh/me
        tests.ts                 # test setup + submit
        questions.ts             # fetch by id, flag, bookmark
        analytics.ts
        errors.ts                # error log + SRS review
        bookmarks.ts
        search.ts
        admin.ts
      schemas/                   # Zod schemas paired with each API resource
        auth.ts
        test.ts
        question.ts
        analytics.ts
      utils/
        cn.ts                    # tailwind class merge (shadcn convention)
        formatDate.ts
        formatTime.ts
        keyboard.ts              # key event normalization
        redirect.ts              # safe `next` validation
        scoring.ts               # neg-marking math mirrored client-side for previews
      constants/
        routes.ts
        keys.ts                  # keyboard bindings map
        paletteColors.ts         # TCS-iON convention (Plan B §2)
    types/
      api.ts                     # re-exports from openapi.d.ts + custom
      domain.ts                  # branded types: TestId, QuestionId, TopicId
    styles/
      tokens.css                 # copied from v2 `static/style.css` :root + [data-theme=dark]
      globals.css                # tailwind base/components/utilities + a few resets
      print.css                  # @media print for Plan B PDF export
      katex.css                  # KaTeX styles
    test/                        # Vitest + RTL setup, mock helpers
      setup.ts
      renderWithProviders.tsx
      mocks/
        handlers.ts              # MSW handlers
        server.ts
```

### 9.1 Notes on the layout

- **Pages are dumb.** They compose components, call query hooks, dispatch to Zustand stores. Business logic lives in `components/` and `lib/`.
- **`components/ui/` is a boundary.** Anything shadcn-generated stays there and is treated as vendored. Diffs against upstream are annotated in git commit messages.
- **`stores/` is separate from `hooks/`.** Zustand stores get their own dir so the hooks dir stays for small utilities.
- **No `containers/`, no `contexts/`.** Providers for Query, Router, ErrorBoundary go in `App.tsx`. No feature-scoped provider hierarchies.
- **Admin is a subtree, not a sibling app.** Same shell, same components, gated at the router. If admin diverges enough later we can hoist it to a route-lazy chunk.

---

## 10. Page-by-page feature parity checklist

| v2 Flask template | v3 React page | Key components used | Notes |
|---|---|---|---|
| `templates/login.html` | `pages/Login.tsx` (`/login`) | `Input`, `Button`, `Form`, `PasswordInput` | Adds `next` param handling |
| — | `pages/Signup.tsx` (`/signup`) | Same + password strength meter | New in v3 |
| — | `pages/ForgotPassword.tsx` (`/forgot-password`) | Single-field form | New in v3 |
| — | `pages/ResetPassword.tsx` (`/reset-password/:token`) | Password confirm | New in v3 |
| `templates/index.html` | `pages/Dashboard.tsx` (`/dashboard`) | `ConsistencyBadge`, `MasteryGrid`, `NextWeakTopicCard`, `SrsDuePill`, recent tests list | Merges Plan C §1 (mastery grid), §3 (next weak topic), §2 (consistency) |
| `templates/test_setup.html` | `pages/TestSetup.tsx` (`/test/new`) | `RadioGroup` for paper + mode; `MultiSelect` for topics; `Slider` for count; `PyqToggle`; `NegativeMarkingConfig` | Plan A F3 + Plan B mode + neg-marking |
| `templates/test.html` | `pages/TakeTest.tsx` (`/test/:id`) | `QuestionCard`, `OptionRow`, `Palette`, `Timer`, `Shortcuts`, `ShortcutsCheatsheet`, `FlagQuestionDialog`, `BookmarkStar` | The most complex page. Zustand `useTestSession` owns state. |
| `templates/results.html` | `pages/TestResults.tsx` (`/test/:id/results`) | `ScoreCard`, per-question deep-dive list, `QuestionRenderer`, pacing sparkline | Plan B §5 (neg-marking breakdown) + Plan A F4 (bookmark toggle in review) |
| `templates/analytics.html` | `pages/Analytics.tsx` (`/analytics`) | `MasteryBarChart`, `ProgressLineChart`, `Heatmap`, `PacingChart`, `DifficultyPie`, tables | Plan A F2 (heatmap), Plan C §1/§4 (mastery + pacing) |
| `templates/errorlog.html` | `pages/ErrorLog.tsx` (`/errors`) | Table with filters, per-row R1/R2 redo, links into `/review` | Plan A F1 integration |
| `templates/review.html` | `pages/Review.tsx` (`/review`) | Single-card queue view with 4-grade buttons | Plan A F1 (Leitner review queue) |
| `templates/bookmarks.html` | `pages/Bookmarks.tsx` (`/bookmarks`) | Grid/list of starred questions with `QuestionRenderer` preview | Plan A F4 |
| `templates/search.html` | `pages/Search.tsx` (`/search`) | Search input + filter sidebar + result list; Cmd-K opens same page pre-focused | Plan E §3 (FTS5 on server; client debounces + renders) |
| `templates/admin/dashboard.html` | `pages/admin/AdminDashboard.tsx` | Counters + recent flags | Plan D §2 preview |
| `templates/admin/questions.html` | `pages/admin/AdminQuestions.tsx` | Filterable table | |
| `templates/admin/question_edit.html` | `pages/admin/AdminQuestionEdit.tsx` | Form + LaTeX preview | |
| `templates/admin/flags.html` | `pages/admin/AdminFlags.tsx` | Flag list with category badges | Plan E §2 |
| `templates/admin/review.html` | `pages/admin/AdminReview.tsx` | Mid-confidence review UI | Plan D §2 |
| `templates/admin/duplicates.html` | `pages/admin/AdminDuplicates.tsx` | Dedupe pairs | Plan D §3 |
| `templates/admin/topics.html` | `pages/admin/AdminTopics.tsx` | Topic CRUD | |
| `templates/admin/uploads.html` + `upload_preview.html` | `pages/admin/AdminUploads.tsx` | File upload + preview + import | |
| `templates/admin/synthesize.html` + `synthesize_preview.html` | `pages/admin/AdminSynthesize.tsx` | LLM-generate flow | |
| `templates/admin/prompts.html` | `pages/admin/AdminPrompts.tsx` | Prompt library CRUD | |
| `templates/admin/users.html` | `pages/admin/AdminUsers.tsx` | User list (multi-user prep) | |
| — | `pages/Profile.tsx` (`/profile`) | Update name/email/password | New in v3 |
| `templates/_error_ref.html` (partial) | Absorbed into `components/question/QuestionRenderer.tsx` | | |

**Total pages:** 25 (12 user + 12 admin + 1 profile). Matches v2's template inventory (25) plus 3 new auth pages.

---

## 11. Accessibility strategy

### 11.1 Non-negotiables

Two widgets need explicit a11y engineering because they aren't standard HTML:

- **Question palette (Plan B §2)** — 5-state grid, keyboard-driven.
- **Heatmap (Plan A F2)** — 2D grid of colored cells with tooltips.

Everything else falls out of using Radix primitives correctly (Dialog, Popover, DropdownMenu, Tabs, RadioGroup — all a11y-audited upstream).

### 11.2 Palette a11y contract

- Container: `role="grid"`, `aria-label="Question navigator, 20 questions"`, `aria-rowcount`, `aria-colcount`.
- Cells: `role="gridcell"`, `aria-label="Question 4, answered, marked for review"`, `aria-current="true"` on the active cell.
- Focus management: one tabstop into the palette; arrow keys move focus within (roving `tabindex`). `Enter` navigates to that question. `M` on a focused cell toggles marked-for-review. `Esc` returns focus to the question area.
- Screen-reader announcements on state change via `aria-live="polite"` region ("Question 4 marked for review").
- Color is never the only signal — every state also has a distinct shape/border/icon (Plan B §2 already specifies purple with a green corner for answered+marked).

### 11.3 Heatmap a11y contract

- `role="table"` with row/column headers.
- Each cell: `role="cell"`, `aria-label="Polity, Hard, 45% correct, 12 questions"`.
- Tooltip content mirrors the aria-label (do not rely on hover-only).
- Legend rendered as a descriptive list before the grid, not just a color bar.

### 11.4 Focus management

- Every modal (Radix `Dialog`) auto-traps focus and restores on close.
- Route changes: focus moves to the page's `<h1>` (custom `useRouteFocus` hook fires on `location` change).
- Skip link at the top of every page (`Skip to main content`).

### 11.5 Contrast

- Both light and dark palettes must pass WCAG AA on text (4.5:1). The v2 dark tokens already do; verify after Tailwind swap using axe.

### 11.6 Tooling

- **`@axe-core/react` in dev only** — logs violations to console. Zero prod cost.
- **`jest-axe` in Vitest** — every page gets a smoke `expect(await axe(container)).toHaveNoViolations()`.
- **Playwright + `@axe-core/playwright`** — E2E accessibility scan on 3 key flows: login → dashboard → take a test.
- **Manual keyboard-only pass** before each release. Documented as a checklist item in the release notes.

---

## 12. Testing strategy

### 12.1 Layers

| Layer | Tool | Scope | Goal |
|---|---|---|---|
| Static | TypeScript `strict`, ESLint, Prettier | Every file | No shape drift; no lint noise |
| Unit — pure | Vitest | `lib/utils/*`, `lib/schemas/*`, scoring math | 90% coverage on pure functions |
| Unit — component | Vitest + RTL | Every widget with logic | Behaviour, not markup — assert what a user would see/do |
| Integration | Vitest + RTL + MSW | Page-level: mount page, mock API, verify flows | Login → dashboard, submit test → results |
| Accessibility | jest-axe (unit) + axe-playwright (E2E) | Every page | Zero violations at commit time |
| E2E | Playwright | Real browsers against dev server | Critical path: signup → take test → view analytics |
| Visual regression | Playwright screenshots (optional) | Palette, heatmap | Detect CSS drift on high-visual-density widgets |

### 12.2 What NOT to test

- shadcn/ui components as vendored (already tested upstream by Radix).
- Third-party libraries (Query, Router).
- Trivial getters/setters on Zustand stores.

### 12.3 MSW for API mocking

Mock Service Worker runs the same handlers in Vitest (Node) and in the browser during dev if we want offline mode. Handlers live in `src/test/mocks/handlers.ts`. In production, MSW is not shipped.

### 12.4 Playwright choice justification

vs Cypress:
- Cypress runs one tab per test; Playwright runs many workers in parallel — for a suite of 20+ E2E tests, Playwright is 3–5× faster.
- Playwright supports Chromium + Firefox + WebKit; Cypress dropped multi-browser as a first-class citizen.
- Playwright's trace viewer beats Cypress's snapshot for post-hoc debugging.
- Both are fine; Playwright is where new investment is going.

### 12.5 CI gate

Minimum green-bar for merging:
- `typecheck` (`tsc --noEmit`)
- `lint` (`eslint`)
- `test` (`vitest run`) — unit + integration
- `e2e:smoke` — 3 critical-path Playwright tests
- Full E2E on `main` (nightly).

---

## 13. Deployment

### 13.1 Options

| Host | Pros | Cons |
|---|---|---|
| **Vercel** | Preview deploys per PR; edge CDN; zero config for SPA fallback; free tier fits solo use | Vendor lock (mild); requires GitHub integration |
| **Render Static Site** | Same vendor as R4 API (co-locate billing, one dashboard) | Slower cold builds; preview deploys behind paid plan |
| **Netlify** | Similar to Vercel; slightly less React-optimized | Same lock story |
| **Cloudflare Pages** | Great CDN; generous free tier | Preview deploys good; less DX polish |
| **S3 + CloudFront** | Cheapest at scale; total control | Setup overhead, no PR previews out of the box |

### 13.2 Recommendation: Vercel

Why:
- Preview deploys per PR (each PR gets a unique URL that runs against a chosen backend env) — huge for a solo dev reviewing their own work on mobile before merging.
- SPA fallback (`rewrites` in `vercel.json`) is one line.
- Free tier bandwidth + build minutes are comfortable at this scale.
- Zero-config domain + auto-HTTPS.
- If we ever move to Next.js / Remix later, no config to redo.

`vercel.json` sketch:
```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/" }],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    }
  ]
}
```

### 13.3 Environment layering

- `VITE_API_BASE` — e.g. `https://api.exam.example.com` for prod, `http://127.0.0.1:3000` for local (Vite proxy handles same-origin in dev).
- `VITE_ENVIRONMENT` — `local | preview | production`; drives a small "PREVIEW" ribbon in the UI so we don't confuse dashboards.
- No secrets in `VITE_*` — anything prefixed with `VITE_` is inlined into the client bundle.

### 13.4 CORS + cookie plumbing

Because auth is httpOnly cookie + `credentials: include`:
- R4 must serve `Access-Control-Allow-Origin: https://<frontend-domain>` (exact, not `*`) and `Access-Control-Allow-Credentials: true`.
- Cookies from R4 need `SameSite=None; Secure` if frontend and API are on different domains, or `SameSite=Lax` if we serve them from the same registrable domain (`api.example.com` + `example.com`). Prefer the same-domain arrangement — better CSRF story and no `SameSite=None` pitfalls.

---

## 14. Package.json dependency sketch

Not final versions — pin closer to install time. Recommended majors below.

```json
{
  "name": "exam-prep-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit",
    "lint": "eslint . --ext .ts,.tsx",
    "format": "prettier --write .",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test",
    "e2e:smoke": "playwright test --grep @smoke",
    "gen:api": "openapi-typescript openapi.yaml -o src/lib/api/openapi.d.ts"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.26.0",
    "@tanstack/react-query": "^5.51.0",
    "@tanstack/react-query-devtools": "^5.51.0",
    "zustand": "^4.5.0",
    "react-hook-form": "^7.53.0",
    "@hookform/resolvers": "^3.9.0",
    "zod": "^3.23.0",
    "openapi-fetch": "^0.11.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.5.0",
    "class-variance-authority": "^0.7.0",
    "lucide-react": "^0.454.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-dropdown-menu": "^2.1.0",
    "@radix-ui/react-popover": "^1.1.0",
    "@radix-ui/react-radio-group": "^1.2.0",
    "@radix-ui/react-select": "^2.1.0",
    "@radix-ui/react-tabs": "^1.1.0",
    "@radix-ui/react-toast": "^1.2.0",
    "@radix-ui/react-tooltip": "^1.1.0",
    "cmdk": "^1.0.0",
    "recharts": "^2.13.0",
    "react-markdown": "^9.0.0",
    "remark-math": "^6.0.0",
    "rehype-katex": "^7.0.0",
    "katex": "^0.16.0",
    "date-fns": "^4.1.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@tailwindcss/forms": "^0.5.9",
    "tailwindcss-animate": "^1.0.7",
    "eslint": "^9.11.0",
    "@typescript-eslint/eslint-plugin": "^8.8.0",
    "@typescript-eslint/parser": "^8.8.0",
    "eslint-plugin-react": "^7.37.0",
    "eslint-plugin-react-hooks": "^4.6.2",
    "eslint-plugin-jsx-a11y": "^6.10.0",
    "prettier": "^3.3.0",
    "vitest": "^2.1.0",
    "@vitest/ui": "^2.1.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "@testing-library/jest-dom": "^6.5.0",
    "jest-axe": "^9.0.0",
    "@axe-core/react": "^4.10.0",
    "jsdom": "^25.0.0",
    "msw": "^2.4.0",
    "@playwright/test": "^1.48.0",
    "@axe-core/playwright": "^4.10.0",
    "openapi-typescript": "^7.4.0"
  }
}
```

Bundle-size back-of-envelope (gzipped, prod):

| Chunk | Size (est.) |
|---|---|
| React + React DOM + Router | ~45 KB |
| TanStack Query | ~13 KB |
| Zustand | ~1 KB |
| Radix primitives (used ones) | ~15 KB |
| shadcn components (all owned code) | ~8 KB |
| react-hook-form + zod | ~14 KB |
| Tailwind (purged) | ~15–25 KB |
| App code (v3 features) | ~35 KB |
| **Initial route (dashboard) total** | **~150–180 KB** |
| Recharts chunk (loaded on `/analytics`) | ~90 KB |
| KaTeX + markdown chunk (loaded on question render) | ~65 KB |

Comfortable under the 200 KB soft-cap for the initial page.

---

## 15. Open questions

Things this plan intentionally leaves unresolved — mark in DECISIONS.md when we start.

1. **OpenAPI spec ownership.** Does R4 publish `openapi.yaml`, or do we handwrite Zod schemas and treat them as the contract? Prefer the former.
2. **Commit `openapi.d.ts` to the frontend repo, or regen in CI?** Committing = reproducible + reviewable diffs; regen = never stale. Lean toward commit + a check that verifies it's up-to-date.
3. **Monorepo or two repos?** If we want to share TypeScript types with future Node tooling (unlikely for a Rust backend), a monorepo helps. Otherwise, keep `frontend/` a standalone repo. Recommend standalone.
4. **Feature flags?** Solo user for now — skip. Add `unleash` or a homegrown `flags.ts` when multi-user lands.
5. **i18n?** Hindi/English is out of scope per README, but if it lands, `react-intl` or `i18next` — both work with Vite. Design components with translatable strings from day one (never inline copy in the JSX; always `t('login.submit')`).
6. **Analytics telemetry (PostHog, Plausible)?** Not required for solo use. If multi-user, Plausible for lightness.
7. **PWA / installable?** Nice-to-have for the "10-question drill on the bus" use case. `vite-plugin-pwa` adds it in ~30 minutes. Defer to a post-parity milestone.
8. **Error tracking (Sentry)?** Post-launch. `@sentry/react` is a 20-minute integration.

---

## 16. Migration / rollout sequencing

Full front-to-back sequencing lives in a separate v3-R0 doc; this section is only the frontend-specific pieces.

**Milestone F0 — Scaffold (4h)**
- Vite + TS + Tailwind + shadcn init.
- Router with public routes only.
- `useAuth` store + login page against R4's `/api/auth/login`.
- Deploy to Vercel preview.

**Milestone F1 — Read-only parity (8h)**
- Dashboard, Analytics, ErrorLog, Bookmarks, Search — all reading from R4.
- No mutations yet. Focus on layout + Query wiring.

**Milestone F2 — Test-taking (12h)**
- TestSetup, TakeTest, TestResults.
- `useTestSession` Zustand store.
- Palette, Timer, Shortcuts, Flag dialog, Bookmark star.

**Milestone F3 — Admin (8h)**
- All 12 admin pages. Bulk of it is table + form CRUD; lean on shadcn's `Table`, `Form`, `Dialog`.

**Milestone F4 — Polish (6h)**
- Dark mode QA across every page.
- Mobile responsive pass (bottom nav swap at md breakpoint).
- Cmd-K command palette.
- Empty states + error states everywhere.

**Milestone F5 — Testing + accessibility (6h)**
- Playwright critical-path suite.
- axe smoke on every page.
- Manual keyboard-only pass.

**Total frontend build: ~44h** — 8 evenings if focused. Real duration will be double (context switching, R4 API drift, unknowns), so plan for ~85h wall-clock.

---

## 17. What this plan deliberately doesn't cover

- **R4 API contract** — that's R4's plan. This doc assumes REST + OpenAPI.
- **R2 schema** — Turso stays; this frontend consumes whatever R4 exposes.
- **Rust backend framework choice (axum/actix)** — R4.
- **Deployment of R4** — R4.
- **CI/CD full pipeline** — will live in a separate infra plan.
- **Content pipeline (question ingestion)** — R5.
- **The v2 Flask app's fate** — R0 sequencing plan will address deprecation + cutover.

---

_Written: 2026-07-19. Companion to R1 (Rust API), R2 (Turso schema), and the v2 A–E feature plans in this directory. Planning only — no scaffold committed until decisions in §15 are resolved._

# Answer-leak audit (task #62)

**Driver:** User feedback from Sujit (2026-07-19) — "answers and result most of test apps me final submit ke baad hi aata a". Real exam apps only reveal the correct answer after final submit. Ours was leaking on every answer submission in v2.

**Scope:** three surfaces — v3 Rust backend, v3 React frontend, v2 Flask (currently in prod).

---

## v3 Rust backend — CLEAN ✅

| Endpoint | DTO checked | Verdict |
|---|---|---|
| `POST /api/v1/tests/{id}/answers` | `schemas/tests.rs::SubmitAnswerResponse` | Returns only `{status: "ok"}`. No leak. |
| `POST /api/v1/tests/{id}/mark-for-review` | `schemas/tests.rs::MarkForReviewResponse` | Returns only `{status: "ok"}`. No leak. |
| `GET /api/v1/tests/{id}` (resume) | `schemas/tests.rs::TestStateResponse` → `TestQuestion` + `TestResponseSnapshot` | `TestQuestion` has `{id, question_text, option_a-d, order_index}` — **no `correct_option`**. `TestResponseSnapshot` has `{question_id, selected_option, marked_for_review, visit_count, time_spent_sec}` — **no `is_correct`**. No leak. |
| `GET /api/v1/tests/{id}/results` | `ResultsResponse` → `ResultsQuestionRow` | Returns `correct_option` + `is_correct` — **but this is expected**; `/results` is only reachable after `/finish`. No pre-submit leak. |

**Server-side persistence** (not exposed): `test_responses.is_correct` is computed and stored on every answer via `api/tests.rs:511-527`. This is internal — the client never sees it until `/results`.

---

## v3 React frontend — CLEAN ✅

- `frontend/src/pages/TakeTest.tsx`: no grep matches for `is_correct` or `correct_option` (verified). The palette + question card render only from `selected` state. Correctness first appears on `TestResults.tsx` (post-finish only).

---

## v2 Flask — LEAKED, PATCHED 🔧

### What leaked

`POST /submit_answer` in `bp_api.py:113-144` was returning the full answer key on every submission:

```json
{
  "is_correct": true,
  "correct_option": "C",
  "explanation": "3NF eliminates transitive dependencies…",
  "answered": 5,
  "total": 25
}
```

The frontend template `templates/test.html` used those fields to:
1. Render a green "Correct!" / red "Wrong!" panel (line 471)
2. Highlight the correct option button (line 463)
3. Show the explanation immediately (line 481)
4. Increment a "correct so far" counter in the sidebar (line 104)
5. Add `correct-dot` / `wrong-dot` classes on the palette cell (line 291) — but this was already gated by `session_mode === 'practice'` (line 288). Correctness dots were never a leak in exam mode.

The first four DID leak in every mode.

### Patch

Gate correctness fields by `session["test_mode"]`:

- **`bp_api.py:138-155`** — `/submit_answer` now returns only `{answered, total}` in exam mode. Practice mode retains full feedback (that's the point of practice).
- **`templates/test.html:418-451`** — `submitAnswer()` JS reads `result.is_correct !== undefined` to decide whether to render the feedback panel + increment the correct counter. In exam mode it calls `showAnsweredStateExamMode()` which lets the answer be recorded without any correctness UI.
- **`templates/test.html:103-113`** — the "correct so far" sidebar block is hidden via inline `<script>` when `session.test_mode == 'exam'`.

### What survives across modes

- The palette still marks cells as answered / marked-for-review / current (no correctness reveal).
- Timer, mark-for-review flag, Finish Test button all work identically.
- Results page still shows the full per-question breakdown after `/finish` — that's the expected reveal point.

### Files changed in v2

- `bp_api.py` — 1 route (`submit_answer`), 15-line change
- `templates/test.html` — 2 blocks (submit handler + correct-so-far sidebar), ~30-line change

No new migrations, no schema changes, no session-shape changes. Fully backward-compatible for tests already in progress (default `session["test_mode"]` is `"practice"` per `bp_tests.py:23-25`).

---

## Rollout

- v2 patch ships on next Flask deploy — Sujit (who's on v2) sees the fixed behavior immediately.
- v3 doesn't need a patch — was correct from Phase 5.
- No commit hash yet — worker fork left changes uncommitted per the phase convention.

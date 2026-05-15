# TODOS (from eng review)

## E1 — OpenAI structured outputs

**What:** Use `response_format` with JSON Schema (or `client.chat.completions.parse` + Pydantic) for batch LLM responses so invalid JSON is rare and repairable.  
**Why:** Prompt-only JSON is brittle at scale; matches “explicit > clever.”  
**Depends on:** EPIC 5 prompt builder.  
**Blocked by:** None.

## E2 — Download path hardening

**What:** Resolve `outputs/<basename>` only; reject `..`, separators, and absolute paths.  
**Why:** Prevents local file read via crafted `GET /download/`.  
**Depends on:** EPIC 8.  
**Blocked by:** None.

## E3 — API key handling

**What:** Prefer `OPENAI_API_KEY` in environment; document never commit `settings.yaml` with secrets; keep `openai_api_key: ""` in template.  
**Why:** Blast radius if repo is shared.  
**Depends on:** EPIC 1.4.  
**Blocked by:** None.

## E4 — Job registry + concurrency

**What:** In-memory job map with lock; define behavior when double-click Generate or second tab.  
**Why:** Avoid corrupt shared state under polling model.  
**Depends on:** EPIC 8.  
**Blocked by:** None.

## E5 — Fixture xlsx for tests

**What:** Commit minimal `tests/fixtures/schedule_min.xlsx` and `stats_min.xlsx` matching Epic columns.  
**Why:** Parser + integration tests without client files.  
**Depends on:** EPIC 2.  
**Blocked by:** None.

## E6 — Client open questions (product)

**What:** Resolve Topic Import ID CSV column, timezone assumption, near-duplicate policy.  
**Why:** Prevents rework in CSV writer and QA.  
**Depends on:** Client feedback.  
**Blocked by:** None.

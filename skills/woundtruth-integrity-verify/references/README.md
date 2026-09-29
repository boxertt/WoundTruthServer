# references — woundtruth-integrity-verify

Read these before changing this skill:

- `publishable/README.md` — the Internal Tool ↔ Publishable Skill mapping, the scope
  injection chain, and the Viewer/physician permission matrix.
- `LAOXIA_DECISION_AGENT_SKILLS_20260920_165253.md` (in the team share) — the review
  decision this layer implements, including the red lines below.
- `app/agent_runtime.py` — the internal tools are the ONLY implementation of these slices; the
  adapter calls `dispatch(tool, {}, frozen_snapshot)` directly. The copy that used to live under
  `code/backend/skills/` is gone (老夏 2026-09-20 18:19 §3): never copy slice logic into a skill.

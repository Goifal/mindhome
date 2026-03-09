# Audit Prompts Review

Review of the 16-prompt sequential audit system in `docs/audit-prompts/`.

---

## Overall Assessment

This is a **professionally designed, thorough audit framework** for a 276-module AI assistant system. The sequential dependency chain, context-block handoff mechanism, and Claude Code tool-usage guidance are well thought out. The prompts demonstrate deep understanding of the codebase architecture and the practical limits of LLM-based code analysis.

**Strengths:**
- Clear sequential dependency chain with explicit context requirements per prompt
- Practical Claude Code tool guidance (Grep for bulk, Read for detail, Edit for fixes, Bash for verification)
- Parallelization strategy for file reads is well-documented
- The "Grundlichkeits-Pflicht" (thoroughness obligation) with code-reference requirements prevents hallucinated analysis
- The PROMPT_RESET mechanism for multi-pass auditing is a smart addition
- Context-block size limits (30-50 lines) show awareness of accumulation problems
- Each prompt is self-contained enough to work in a fresh session (with context blocks)

**Key issues to address:**
1. Several prompts are scope-overloaded
2. A few technical bugs in tool-usage examples
3. Subjective scoring lacks calibration
4. Static analysis limitations not consistently acknowledged

---

## Per-Prompt Findings

### PROMPT_00_OVERVIEW.md

**Status: Good**

- Clear system description with module counts
- Dependency table is well-organized
- Two usage options (single session vs. separate sessions) are practical
- Coverage matrix showing which aspects each prompt covers is excellent

**Suggestion:** Add a time/effort estimate column to the dependency table. Some prompts (04c, 06b, 06d, 07b) are significantly heavier than others, and the user should plan accordingly.

---

### PROMPT_01_ARCHITEKTUR.md

**Status: Good**

- Six conflict categories (A-F) provide excellent structure for the analysis
- The emphasis on inter-service interaction (Konflikt F) is critical and well-placed
- The Claude Code strategy for building the import map via Grep is efficient
- Requiring a complete wiring graph is ambitious but valuable

**Minor issues:**
- The wiring table for "JEDES Modul" across 276 files is unrealistic in a single pass. Consider specifying that the table should cover the top 30-40 most critical modules, with Grep-based coverage confirmation for the rest.
- The Grep example `^from \.|^import \.` will miss absolute imports like `from personality import ...` or `from brain import ...`. Consider broadening the pattern.

---

### PROMPT_02_MEMORY.md

**Status: Good**

- The 12-module scope is comprehensive and correctly identifies that memory is distributed across more modules than the obvious 4
- The Redis/ChromaDB/SQLite schema extraction via Grep is well-designed
- The 22-item check table is methodical
- Performance checks (Schritt 4b) bridging to P4c is a smart cross-reference

**Suggestion:** The alternative approaches table (Schritt 6) asks the executor to evaluate 7 options. This is valuable but time-consuming. Consider marking 2-3 as the primary candidates to evaluate in depth, with the rest as quick-reject/accept assessments.

---

### PROMPT_03a_FLOWS_CORE.md

**Status: Good**

- The split into Core (3a) and Extended (3b) flows is well-scoped
- Starting with Init-Sequence and System-Prompt before flows is the right order
- Seven core flows cover the primary user-facing functionality

**No significant issues found.**

---

### PROMPT_03b_FLOWS_EXTENDED.md

**Status: Minor issues**

- Flow 10 (Workshop System, 80+ endpoints) could dominate the analysis and exhaust context. Consider adding a scope limit: "Focus on the Workshop's integration points with brain.py and main.py, not individual endpoint logic."
- Flow collision scenarios are valuable but some (e.g., "Speech in Room A + Speech in Room B simultaneously") may be impossible to determine from static analysis alone. Acknowledge this limitation.
- The merged handoff block (combining P3a+P3b) doesn't specify conflict resolution if findings contradict.

---

### PROMPT_04a_BUGS_CORE.md

**Status: Good**

- 13 error classes provide excellent systematic coverage
- Prioritization (Core first, then Extended, then Addon) is logical
- The scope (~26 core modules) is manageable for a single session

**No significant issues found.**

---

### PROMPT_04b_BUGS_EXTENDED.md

**Status: Scope concern**

- 53 modules across 9 batches is very large for one session
- The pragmatic scoping ("Priority 5-7 thorough, 8-9 top-6 error classes only") is good but risks missing critical bugs in lower-priority modules
- References like "Protocol Engine: 5 Bugs documented" and "Insight Engine: 70% complete" lack source citations
- No explicit file paths are provided for the module names (unlike other prompts that specify `assistant/assistant/` or `addon/...`)

**Suggestion:** Add a note that the executor should prioritize modules flagged in P3b's flow analysis over modules with no flow involvement.

---

### PROMPT_04c_BUGS_ADDON_SECURITY.md

**Status: Scope overload -- needs splitting**

This is the most overloaded prompt in the series. It combines:
- Addon bug hunting (53+ modules across domains, engines, routes)
- Speech server review
- Shared module review
- 18-item Security audit
- 10-item Resilience check
- 12-item Performance/Latency analysis

**Issues:**
1. **Module numbering reuse:** Items 86-88 appear in both Teil 1 and Teil 2, making cross-referencing error-prone. Use a continuous numbering scheme or prefix with section (e.g., "S1", "S2").
2. **Performance estimates from static analysis:** The latency budget table asks for "?ms" estimates that will be speculative without runtime profiling. Acknowledge this explicitly: "Estimate order of magnitude, not precise values."
3. **Fragile bash commands:** The `pip-audit` commands use `cd` chaining that breaks if any path doesn't exist.

**Recommendation:** Consider splitting this into P04c (Addon bugs + Speech + Shared) and P04d (Security + Resilience + Performance). This would improve thoroughness and reduce the risk of superficial coverage.

---

### PROMPT_05_PERSONALITY.md

**Status: Good, minor misplacement**

- MCU-Jarvis authenticity evaluation is well-structured
- The cross-path personality consistency check is valuable

**Issues:**
- Teil E (Config audit) covering settings.yaml, .env, translations, and HA manifests is surprisingly broad for a "personality" prompt. Items 7-12 (addon configs, translations, manifests, .env) feel like they belong in a deployment or architecture prompt.
- MCU-Authenticity scores (1-10) lack calibration criteria. What distinguishes a 7 from an 8? Add anchor descriptions (e.g., "7 = mostly consistent, occasional breaks; 8 = consistently in character with minor gaps").
- Teil G (Explainability) is only 4 lines and feels disconnected from the rest.

---

### PROMPT_06a_STABILISIERUNG.md

**Status: Good**

- Tight focus on only two things (critical bugs + memory fix) is excellent discipline
- The prioritization within critical bugs (start-blocking > main-flow-crashing > data-loss) is well-ordered
- The Phase Gate concept (tests must pass before proceeding) is a sound practice

**No significant issues found.**

---

### PROMPT_06b_ARCHITEKTUR.md

**Status: Ambitious, has a bug**

- The step-by-step refactoring approach with test verification is sound
- The Rollback-Regel with three options is practical

**Issues:**
1. **Grep pattern bug (line ~108):** A Grep call uses two `path=` parameters, which is invalid. Grep accepts only one path. Split into two separate Grep calls.
2. **Brain.py refactoring scope:** Refactoring a 10,000+ line file in one session is extremely ambitious. Consider adding a scope limit: "If brain.py refactoring exceeds 3 significant structural changes, stop and document the remaining changes for a follow-up session."
3. The Rollback option (c) "discard" could create dependency issues if earlier refactoring steps depend on the discarded change. Add a note to verify no cascading dependencies before discarding.

---

### PROMPT_06c_CHARAKTER.md

**Status: Good**

- Personality harmonization focus is clear
- The "one voice" principle is well-articulated
- Dead code removal guidance correctly warns about dynamic loading

**Minor issues:**
- Dead code detection should also warn about `getattr()`, string-based imports, and plugin/registry patterns that could cause false positives.
- The warning "don't remove instructions added by bug fixes" is important but hard to verify without a P6a/6b changelog. Consider requiring P6a/6b to output a "files modified" list in their context blocks.

---

### PROMPT_06d_HAERTUNG.md

**Status: Has contradictions**

- Security + Resilience + Addon-coordination is a logical grouping
- The 15 security checks and 10 resilience scenarios are comprehensive

**Issues:**
1. **Security ordering contradiction:** The "Security-Reihenfolge" rule states "Input-Validierung VOR Prompt-Injection-Schutz" (Input validation before prompt injection). But the task table lists Prompt Injection as check #1 and Input Validation as check #2. **These need to be aligned.**
2. The Addon coordination "Losung" column is left entirely as "?" with no guidance on preferred resolution strategies. Add a decision framework (e.g., "Prefer single-owner for each entity type; the service closest to the data source owns it").
3. Security scope (15 checks across 200+ endpoints) is very large. Consider prioritizing: "Checks 1-5 are mandatory, 6-15 are best-effort."

---

### PROMPT_07a_TESTING.md

**Status: Good**

- Running existing tests first before writing new ones is the right order
- Security endpoint verification (factory-reset, system-restart, API-key-regeneration) is a valuable addition
- 14 critical test scenarios provide good coverage

**Suggestion:** Add a note about test environment setup. If the sandbox lacks Redis/ChromaDB/Ollama, many tests may fail due to missing infrastructure rather than code bugs. The executor should distinguish infrastructure failures from code failures.

---

### PROMPT_07b_DEPLOYMENT.md

**Status: Scope heavy, practical issues**

- Target hardware specification is valuable and should be referenced in P4c's performance analysis too
- Section numbering (starting at Teil C) correctly continues from P7a
- The top-5 recommendations output format is a good executive summary

**Issues:**
1. **Docker builds may not work** in the sandbox environment. The prompt mentions this briefly but should more prominently set expectations ("Docker build verification may be limited to Dockerfile analysis if docker daemon is unavailable").
2. **Latency estimates from static analysis** (same issue as P4c): Add the caveat that these are order-of-magnitude estimates.
3. **Performance test code example** uses mocks without specifying how to mock external services. A meaningless test that measures mock speed is worse than no test.
4. `pip-audit` commands repeat the fragile `cd`-chaining pattern from P4c.

---

### PROMPT_RESET.md

**Status: Excellent**

- The delta-checklist concept is valuable for iterative improvement
- The explicit "forget / keep" distinction is well-articulated
- Durchlauf-nummerierung (audit cycle numbering) enables tracking across sessions
- The separate-conversation instructions are practical

**No issues found.**

---

## Cross-Cutting Recommendations

### 1. Split P04c into two prompts

P04c is doing the work of two prompts. Split into:
- **P04c:** Addon + Speech + Shared module bugs
- **P04d:** Security audit + Resilience checks + Performance analysis

This adds one prompt to the series but significantly improves quality.

### 2. Fix the Grep bug in P06b

The dual-path Grep call will fail at runtime. Split into two separate calls.

### 3. Resolve the security ordering contradiction in P06d

Align the task table numbering with the stated priority rule, or update the rule to match the table order.

### 4. Add MCU-Score calibration anchors

In P05 and P06c, add descriptions for what each score level means:
- 1-3: Rarely in character, frequent inconsistencies
- 4-6: Sometimes in character, noticeable gaps
- 7-8: Mostly in character, minor inconsistencies
- 9-10: Consistently authentic MCU-Jarvis

### 5. Acknowledge static analysis limitations

In P04c and P07b, add explicit caveats that latency/performance estimates from code reading are order-of-magnitude approximations, not measured values.

### 6. Add "files modified" to P06a/6b/6c/6d context blocks

Each stabilization prompt should output a list of files it modified. This helps subsequent prompts (and PROMPT_RESET) identify what changed and avoid accidentally reverting fixes.

### 7. Consider context window budget guidance

Add a note in P00 estimating the context budget per prompt phase:
- Analysis prompts (P1-P5): ~60% for file reading, ~30% for analysis output, ~10% for context blocks
- Fix prompts (P6a-6d): ~40% for reading, ~40% for edits/tests, ~20% for context
- Verification prompts (P7a-7b): ~30% for reading, ~50% for test execution, ~20% for reports

This helps the executor pace their work.

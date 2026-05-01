# Intent Mapping Rationale

**File:** `intent_mapping.yml`  
**Version:** 1  
**Approved:** 2026-05-01 (verbal approval from Dave Galloway)

This document explains each mapping decision in `intent_mapping.yml` and addresses the three edge cases required by spec v2 Gap 1.

---

## Priority ordering

Rules fire top-to-bottom; first match wins. The priority order is:

1. **Domain-role overrides** — client and known competitor URLs are always navigational, regardless of content type. A searcher visiting a brand they know is not in discovery mode.
2. **Unclassifiable content drops** — `unknown` and `other` content types are dropped to `uncategorised`. It is better to reduce confidence than to force-fit a bad guess into the distribution.
3. **Service pages** — the most nuanced bucket; locality and entity type matter here.
4. **Content-type-specific rules** (directory, guide, news, pdf) — straightforward.
5. **Catch-all** — anything that matched nothing becomes `uncategorised`.

---

## Rule-by-rule rationale

### Domain role overrides (priority 1)

**Client URL → navigational.** If the client's own domain appears in the organic results, the searcher is looking for a specific site. Intent is navigational.

**Known competitor → navigational.** If a named competitor brand (from `known_brands` config or `domain_overrides.yml`) appears, the searcher knows the brand and is navigating to it.

### Unclassifiable content (priority 2)

**`unknown` → uncategorised.** The HTML enricher could not read the page. No classification signal exists.

**`other` → uncategorised.** The content matched no recognised pattern. Counting it as any specific intent would be speculation. Reddit threads, YouTube videos, and similarly unstructured pages fall here — correctly excluded per spec edge case 5.

### Service pages (priority 3)

**`service` + `directory` entity → `commercial_investigation`.** See Edge Case 1 below.

**`service` + `counselling` or `legal` entity + local pack present → `local`.** When a service provider's page appears and the SERP also has a local 3-pack, the dominant user need is proximity-based. The local pack is the dominant intent signal.

**`service` + `counselling` or `legal` entity + no local pack → `transactional`.** The user wants to hire someone or book a session, but without local context. This is classic transactional intent.

**`service` + `nonprofit` or `government` → `transactional`.** Free vs. paid is irrelevant to intent. A user clicking "Book a session at a nonprofit counselling centre" has the same intent as a user clicking "Book a session at a private clinic." Both are transactional. (Edge case 4 from v2 spec.)

**`service` + any other entity → `transactional`.** Default for service pages.

### Directory content (priority 4)

**`directory` → `commercial_investigation`.** Psychology Today, BetterHelp, lists of "best therapists in X" — these pages exist to support comparison. The user is researching, not transacting.

### Guide content (priority 5)

**`guide` → `informational`.** Guides answer questions. Entity type and locality do not change this. See Edge Case 2 below.

### News and PDFs (priority 6)

**`news` → `informational`.** News reporting answers "what happened" or "what is." Rarely transactional.

**`pdf` → `informational`.** PDFs in SERPs are almost always reference documents, whitepapers, or research reports.

### Catch-all (priority 7)

**Any remaining URL → `uncategorised`.** Belt-and-suspenders. A well-formed `intent_mapping.yml` always has this rule as the final entry.

---

## Edge cases (required by spec v2 Gap 1)

### Edge Case 1: Service page on a directory domain

**Decision: `commercial_investigation`.**

**Fixture example:** `https://www.psychologytoday.com/ca/therapists/bc/vancouver?category=couples` — `entity_type=directory`, keyword "How much is couples therapy in Vancouver?" (run `20260501_0828`). This is a Psychology Today therapist-listing page: service-shaped (browsable therapist profiles with bios, specialties, and contact forms) on a directory domain.

Rationale: A therapist profile on Psychology Today is service-shaped (it has a bio, specialties, contact form), but the domain is a directory. The user landed on this page because they were browsing a comparison surface, not because they typed the URL directly. The discovery context is investigative. Calling it `transactional` would falsely imply that Living Systems can win by improving its own service pages — it cannot, because the user's decision happens *inside the Psychology Today directory*. The `commercial_investigation` label correctly signals that the keyword is dominated by a directory intermediary.

Implementation: the `service` + `directory` rule fires before the generic `service` + `any` rule.

### Edge Case 2: Guide URL on a counselling provider's domain when the SERP has a local pack

**Decision: `informational` (locality does NOT override).**

**Fixture example:** `https://openspacecounselling.ca/` — `entity_type=counselling`, `content_type=guide` (URL pattern rule for bare root on counselling domain), keyword "What type of therapist is best for couples therapy?" (run `20260501_0828`). That SERP has `local_pack_present: True` with 23 businesses. Despite local pack presence, this URL maps to `informational`.

Rationale: A guide is a guide. The local pack is a separate intent signal — its presence shifts *service-page* URLs toward `local`, but it does not retroactively reclassify guide-format content. Reclassifying every provider-hosted guide as `local` because the SERP also has a 3-pack would conflate authoring intent with SERP mix. The result would be: a SERP with 7 informational guides + 1 local pack gets called `local`, which misrepresents the actual competitive landscape. The guide rule fires unconditionally regardless of local_pack value.

### Edge Case 3: AI Overview presence

**Decision: NO effect on intent classification.**

**Fixture example:** keyword "How much is couples therapy in Vancouver?" (run `20260501_0828`) has 11 AIO citations (`ai_overview_citations` table). `serp_intent.primary_intent` = `"informational"`. The AIO's presence did not affect the classification — the verdict is driven entirely by the organic URL classifications in the top-10 organic results.

AI Overviews now appear on informational, commercial, and local SERPs alike. Their presence does not reliably indicate any particular intent type. They are recorded in `evidence.local_pack_present` style metadata but do not shift any mapping rule.

---

## Limitations and known gaps

- **Bare domain roots** (e.g. `https://clinic.ca/`) are classified by the URL pattern rules in `url_pattern_rules.yml` as `service` when the entity type is a known service provider. If entity type is `N/A`, they fall through to `uncategorised`. This is conservative — we prefer `low` confidence over false precision.
- **Navigational intent in mixed SERPs**: When a named competitor dominates via navigational URLs, the intent verdict reflects that. This is intentional — it signals the keyword is partially brand-contested, which affects the mixed-intent strategy.

# GUI step reference — serp-me.py

| Step | Script | When to run |
|------|--------|-------------|
| 1. Full Pipeline | `run_pipeline.py` | Fresh SERP fetch for a keyword set |
| 2. Fetch SERPs Only | `serp_audit.py` | Fetch without pipeline validation |
| 3. Content Brief | `generate_content_brief.py` | After a pipeline run |
| 4. Refresh Outputs | `refresh_analysis_outputs.py` | Re-classify without re-fetching |
| 5. Export History | `export_history.py` | Export DB to CSV |
| 6. Domain Overrides | — | Review/approve entity type overrides |
| 7. Feasibility Analysis | `run_feasibility.py` | DA scoring from existing JSON (cached — free to re-run) |

## Configuration Manager tabs

Opened via **Edit Configuration**. Each tab edits one editorial file with
validation. The tabs and their files are listed in
`docs/config_reference.md` ("Configuration Manager GUI"). One tab is not a
raw-file editor:

**Client Profile & Queries** (`client_profiles.yml`, yoast_geo_upgrade Y.13)
edits the **selected client's** profile — brand, domain, location, cities, and
its personas with named funnel/intent tiers (each tier's verbatim
`seed_questions` and per-city `templates`). A **Preview generated questions**
button runs `profile_questions.generate` for the selected client and lists the
exact questions (with persona / tier / city tags) that a probe would ask — a
**no-cost** action, no API calls. Save is atomic and validated: it round-trips
through the Y.1 loader, rejects malformed input (empty persona label, bad
tier) with an inline message, and never touches other clients' blocks.

WHY it exists: this is a multi-client tool, and the queries are the app's job
to manage **per client, in the GUI** — top-of-funnel and progression tiers are
configured here, not in a keyword CSV, and a non-developer never has to edit
YAML by hand.

# Prompt Iteration Packages

This directory contains standalone markdown packages for iterating the current report prompts in a chatbot workflow.

Each package includes:
- the current prompt text
- a fixed representative data bundle
- known failure examples
- specific rewrite goals
- output requirements for the AI tool

Recommended order:
1. [`01_main_report_system_prompt_iteration.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/01_main_report_system_prompt_iteration.md)
2. [`02_main_report_user_template_iteration.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/02_main_report_user_template_iteration.md)
3. [`03_advisory_system_prompt_iteration.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/03_advisory_system_prompt_iteration.md)
4. [`04_advisory_user_template_iteration.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/04_advisory_user_template_iteration.md)
5. [`05_correction_prompt_iteration.md`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/05_correction_prompt_iteration.md)

Shared evidence lives in [`examples/`](/Users/davemini2/ProjectsLocal/serp/prompt_iteration_packages/examples).

Notes:
- The authoritative autocomplete evidence lives in the extracted payload's
  top-level `autocomplete_by_keyword` data and in the raw analysis JSON's
  `autocomplete_suggestions` section.
- Summary excerpts in `examples/` should preserve representative
  autocomplete terms. Do not infer autocomplete absence from a truncated
  keyword profile excerpt alone.

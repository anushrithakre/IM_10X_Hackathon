# Security Guardrails

- Use read-only SCM/project tokens for analysis.
- Never give the agent production DB write access.
- Do not push directly to protected branches.
- Require human approval before branch/MR creation.
- Store what context was read for each run.
- Show missing validation honestly instead of implying runtime proof.
- Keep secrets out of prompts and generated reports.

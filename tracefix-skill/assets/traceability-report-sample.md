# Traceability Report Sample

## Input

- Ticket: OP-4821
- Repository: billing-cron-go
- Branch: develop
- BRD source: ticket attachment
- LLM model: openrouter/anthropic/claude-sonnet-4.6

## Output

- Summary: 5 requirement bullets.
- Current flow: repository-supported behavior flow.
- Expected flow: BRD-derived updated behavior.
- Test cases: 18 generated.
- Requirement-linked cases: 14.
- Code-supported cases: 9.
- Runtime-validated cases: 0.

## Example Test Trace

Test Case: Verify duplicate invoice is not created

Requirement Evidence:
- OP-4821 acceptance criteria: duplicate invoice numbers must not be created.

Code Evidence:
- billing/invoice_summary.go

Validation:
- L2 Code-supported

Missing Dependency:
- tax-service dev API unavailable; fake API required for runtime validation.

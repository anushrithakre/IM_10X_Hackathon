# Validation Levels

TraceFix marks every generated item with the highest validation level currently supported by available evidence.

- L1 Requirement-derived: generated from BRD/OpenProject only.
- L2 Code-supported: mapped to selected repository files or snippets.
- L3 Build-validated: build command succeeded.
- L4 Test-validated: generated or existing tests passed.
- L5 Environment-validated: verified against dev/test environment.

For Go cron repositories with missing dev APIs, L1-L2 is expected. For .NET repositories with a working build, L3 is the first recommended validation target.

## Summary

Describe the change and why it is needed.

## Checklist
- [ ] Code builds and runs locally
- [ ] Tests added or updated
- [ ] Relevant docs updated (if applicable)

## Security / Secrets
- Do not commit secret keys or credentials. If your change requires environment variables, add them to the deployment secret manager or CI, not to the repo.
- If you added a db migration, ensure the SQL does not contain any secrets or credentials.

## Migrations
- If this PR introduces schema changes, add a migration file under `db/migrations/` and document how to apply it.

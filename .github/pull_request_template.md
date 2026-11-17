## Summary

What problem does this PR solve?

## Scope

- Affected area: A / B / C / shared contract / deployment / documentation
- Related PRD or SPEC section:
- Out of scope:

## Verification

- [ ] `$env:LLM_MODE = "mock"; python -m compileall -q mvp ci`
- [ ] `python -m unittest discover -s mvp/tests -v`
- [ ] `python -m unittest discover -s tests/acceptance -v`
- [ ] Contract, migration, or deployment checks where applicable

## Repository hygiene

- [ ] No `.env`, database, log, key, cookie, token, or login-state screenshot
- [ ] No personal study notes, agent working transcript, group-chat draft, or unrelated experiment
- [ ] No machine-specific absolute path, private host address, or local diagnostic script
- [ ] No generated build output or cache

## Risk and rollback

Describe the main risk and how to roll back.

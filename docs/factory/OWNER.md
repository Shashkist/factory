# Waiting for the owner

Items only the owner can do (secrets, DNS, money, account and repository settings). The factory adds an item with the exact steps, labels the issue `status:needs-owner`, and moves on. Tick the box when done.

## Actions

- [ ] **O1 (#10, D40): make three checks required on `main`.** Run once, as the repository admin:
  ```bash
  gh api -X PUT repos/Shashkist/factory/branches/main/protection --input - <<'JSON'
  {"required_status_checks": {"strict": false, "contexts": ["Lint, types, unit tests", "exam-integrity / exam-integrity", "acceptance / gate"]},
   "enforce_admins": false, "required_pull_request_reviews": null, "restrictions": null}
  JSON
  ```
  `enforce_admins: false` keeps the direct `docs/factory/*` state pushes working. Check: `gh api repos/Shashkist/factory/branches/main/protection --jq '.required_status_checks.contexts'` lists the three names.

## Questions

(none yet)

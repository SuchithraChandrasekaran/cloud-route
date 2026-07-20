# Day 1-2 — Foundation & IAM

## Day 1 — Account foundation

- Set a $1 billing alarm as a hard safety net before building anything.
- Decided on a naming convention for environment separation: `migrate-grid-dev-*`,
  `migrate-grid-staging-*`, `migrate-grid-prod-*`.
- Decided on a consistent tag key/value scheme: `Environment` = `dev` / `staging` / `prod`.
- Created an AWS Resource Group (`migrate-grid-all-environments`) using the tag-based
  grouping criteria above, so all tagged resources will be visible in one place going
  forward. Empty for now — no resources tagged yet.

**Why single-account instead of AWS Organizations:** ran into account creation limits
early on. Rather than block progress, switched to a single-account design using tags and
naming conventions for environment separation instead of separate AWS accounts. Documented
as a real design decision, not a workaround glossed over — see `docs/adr/` once written up.

## Day 2 — IAM policy for dev-tagged resources

- Wrote a tag-scoped IAM policy: full access to resources tagged `Environment: dev`, plus
  a separate statement allowing creation of new resources when the request itself carries
  that tag (since a brand-new resource has no tags yet at creation time).
- AWS's built-in policy validator flagged the first draft: using `"Action": "*"` combined
  with `"Resource": "*"` is overly broad, even with a tag condition attached, since it could
  still touch IAM and account-level actions.
- Corrected it by scoping the action list to only the services actually needed for this
  project — EC2, ECS, DynamoDB, CloudWatch Logs, CloudWatch 

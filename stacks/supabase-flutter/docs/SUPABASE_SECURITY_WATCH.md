# Supabase Security Advisor watcher

This stack ships a daily watcher for the hosted project's live Security Advisor. Local
migration guards remain authoritative for code changes; this watcher catches dashboard
drift and additional advisor rules after deployment.

## Enable it

1. Set repository variable `SUPABASE_PROJECT_REF` to the hosted project reference.
2. Create a least-privilege Supabase token with `advisors_read` (or OAuth
   `database:read`) and store it as repository secret `SUPABASE_ACCESS_TOKEN`.
3. Run **Supabase security watch** manually and verify a clean summary or one canonical
   `[security-watch]` issue.

Without the project variable, the cloud scan self-skips so a fresh stamp stays green.
After the variable is set, a missing token, timeout, non-200 response, or malformed
payload fails closed and maintains the canonical watcher-unhealthy issue.

The Management API advisor endpoint is experimental/deprecated and may change. That is
why malformed responses are unhealthy rather than clean. Reviewed infrastructure
exceptions are exact `cache_key` entries in the classifier with a reason beside each;
never suppress by title, substring, schema, or severity.

## Issue and notification semantics

The canonical GitHub issue is the control-plane record. External email, SMS, or webhook
delivery is optional and must report its own proof state: one channel succeeding does
not prove another channel is wired. Never commit recipient addresses, phone numbers,
provider credentials, findings from a private project, or delivery payloads.

# Publishing review links without confusing "unlisted" with "private"

Projects often need to share a preview, storyboard, report, or review build with a
small audience. Choose the exposure level from the content, not from whichever host is
easiest to deploy to.

| Posture | Appropriate content | Required control |
|---|---|---|
| Public | Deliberately public, indexable material | Normal hosting |
| Unlisted | Non-sensitive preview that should stay out of search/discovery | `noindex` headers + `robots.txt` + cryptographically random path |
| Authenticated review | Unpublished findings, reviewer decisions, client/internal data, private status, or competitively sensitive material | Identity-aware access policy with an explicit audience |

**Noindex is not access control.** It asks cooperative crawlers not to index a page;
anyone who obtains the URL can still open it. `robots.txt` is public, caches and link
previews may retain content, and a leaked/reforwarded URL remains usable. If disclosure
would matter, use authenticated review or send an encrypted file directly.

## Unlisted static publishing

Use all of these; none substitutes for another:

1. Generate a cryptographically random path. Do not use a project name, person, email,
   manuscript title, sequential number, or memorable phrase. Never list these paths on
   an index page.
2. Send response headers on **every path**, including directly-requested assets:

   ```text
   X-Robots-Tag: noindex, nofollow, noarchive
   Referrer-Policy: no-referrer
   X-Content-Type-Options: nosniff
   ```

   For a moving review target, also use `Cache-Control: no-store, max-age=0,
   must-revalidate`. Immutable public artifacts usually want the opposite caching
   policy; do not copy `no-store` blindly.
3. Ship `robots.txt` with `User-agent: *` and `Disallow: /`.
4. Probe the **deployed URL**, not only the local files: inspect response headers,
   request `robots.txt`, and confirm no index or sitemap links to the random path.

The `convergent_deploy` add-on includes a copy-ready pair under
`docs/examples/unlisted-site/` for hosts that honor `_headers` files.

### Host mapping

| Host | Where the rules live |
|---|---|
| Cloudflare Pages | `_headers` in the published asset directory |
| Netlify | `_headers` or `netlify.toml` |
| GitHub Pages | Meta tags help, but custom response headers are unavailable; use a fronting proxy or authenticated host for anything sensitive |
| S3/CloudFront | Object/response-header policy metadata |
| Nginx/Caddy | Server response-header directives |

Provider behavior changes; verify the live response after each hosting change.

## Authenticated review: humans and automation are different principals

For sensitive review material, put **every reachable hostname**—custom domain and
provider origin—behind the same identity-aware access boundary. Leaving an anonymous
provider URL available defeats the protected custom domain.

For a Cloudflare Access example:

- Make the policy deny-by-default: place narrow Allow/Service Auth rules ahead of a
  catch-all Block rule, and test both an approved and an unapproved identity.
- Human reviewers may use email one-time PIN, but the **Allow policy must explicitly
  name approved emails or approved domains**. A rule that merely includes the
  `One-time PIN` login method admits any user with a valid email address.
- Email OTP proves mailbox control, not phishing-resistant identity. For high-impact
  or regulated material, require an organization identity provider with MFA (and,
  where available, device posture) instead of relying on email OTP alone.
- Keep the reviewer list in the access provider, not in the repository. Commit only
  the policy shape and setup checklist—never addresses, account IDs, application IDs,
  session cookies, or access tokens.
- Unattended deploy/reconcile jobs use a separate **Service Auth** policy and service
  token. The upload API token and the read-through-Access token are different
  credentials and are not interchangeable.
- Inject both service-token halves at runtime from the owner-managed secret store.
  Never put them in command arguments, generated files, examples, logs, issues, or
  commits. A partial credential is a configuration error, not anonymous access.
- The live-state reader must fail closed on a redirect/login page, rejected token,
  timeout, malformed body, or server error. See `docs/CONVERGENT_DEPLOY.md` when that
  add-on is enabled.
- Keep `X-Robots-Tag: noindex, nofollow, noarchive` and `Cache-Control: no-store` on
  authenticated review responses too; authentication does not prevent browser,
  intermediary, or link-preview retention after a reviewer receives the content.

Email OTP proves control of an approved mailbox; it is not a content-submission
webhook. The source projects used managed access policies and local/copy-back review,
not a custom auth webhook. Add a webhook only when the product genuinely needs server-
side submissions, and then treat it as a separate authenticated API with its own
authorization, input limits, audit trail, and retention policy.

## Publication-safety checklist

- [ ] The content is classified as public, unlisted, or authenticated review.
- [ ] Examples and tests contain only synthetic data—no unpublished findings, real
      reviewer identities, client data, production URLs, account IDs, or secrets.
- [ ] Every hostname and provider origin has the intended access posture.
- [ ] An unapproved identity is denied, and policy ordering cannot bypass the block.
- [ ] Human and machine credentials are separate and least-privileged.
- [ ] The deployed response headers and access challenge were verified live.
- [ ] Revocation is rehearsed: remove a reviewer, rotate the machine credential, and
      remove the deployment without relying on search-engine deindexing.

This pattern is intentionally generic. A project's domain strategy, reviewer roster,
research content, operational identifiers, and unpublished workflow remain in that
project; they are not template material.

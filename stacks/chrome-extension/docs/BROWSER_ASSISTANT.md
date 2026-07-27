# Browser-assistant reference module

`extension/src/browser-assistant/` is the single source of truth for bounded
browser-assistant behavior in this stack. It is a reference boundary, not a
general autonomous agent.

## Module map

| File | Owns |
|---|---|
| `intent.ts` | Explicit command grammar, normalization, and product-owned destination catalog. |
| `navigation.ts` | Typed cross-world request, accessible-link adapter, safe URL filtering, exact matching, and ambiguity handling. |
| `audit.ts` | Metadata-only audit allowlist, redaction, and bounded retention. |
| `index.ts` | Supported integration surface for extension entry points. |
| `*.test.ts` | Grammar, hostile input, ambiguity, permission, URL, and audit invariants. |

The root `content-script.ts` is intentionally thin. Product code should import
from the feature barrel rather than reach into its internals.

## Choose the narrowest browser control

| Mechanism | Use when | Security and delivery cost |
|---|---|---|
| Content script + typed messages | Reading or changing the DOM on explicitly matched or user-approved sites. This is the default. | Narrow host scope; page data is untrusted; isolated-world messaging must be validated. |
| `chrome.debugger` / CDP | A developer tool genuinely needs browser-debugging protocol coverage that content scripts cannot provide. | Broad tab instrumentation, prominent user trust cost, and a non-optional permission. Keep it out of ordinary assistants. |
| Native messaging | A separately installed desktop companion must perform an OS-local capability unavailable to extensions. | Adds an independently secured native host, installer, protocol, update, and audit surface. Never use it merely to bypass extension restrictions. |

Do not mix these into one “just in case” capability set. A product that needs a
stronger mechanism should create a separate reviewed adapter and update its
threat model, permission test, Store disclosure, and rollback plan.

## Deterministic intent and page resolution

1. Accept only the short, single-line grammar in `intent.ts`.
2. Resolve extension destinations through a fixed product-owned alias catalog.
3. Unknown targets fail closed unless a product explicitly opts into page
   resolution.
4. Page resolution considers visible HTTP(S) anchors without embedded
   credentials or `download`.
5. Compare a bounded accessible label exactly after normalization. Do not fuzzy
   match, synthesize selectors, or execute page-provided instructions.
6. Deduplicate responsive copies that lead to one URL. If one label leads to
   multiple URLs, return `ambiguous`.
7. Runtime-sanitize responses and return status/count metadata across the
   message boundary, not page text, user commands, selectors, field values, or
   candidate URLs.
8. Bound hostile-page work: inspect at most 2,000 anchors and retain at most 500
   safe candidates for one resolution request.

The helper implements a bounded accessible-name approximation for anchors:
`aria-labelledby`, `aria-label`, rendered text, then `title`. The browser
accessibility tree is authoritative. Shadow roots, cross-origin frames, custom
widgets, and full Accessible Name computation require an explicit adapter and
their own fixtures; do not pretend this helper covers them.

## Prompt-injection isolation

Treat the user command as control data and every webpage string as untrusted
data. Page content may supply a candidate label only. It cannot add tools,
permissions, destinations, policies, or follow-up instructions. Keep:

- a typed, allowlisted message schema;
- one-way data flow from user intent to exact candidate resolution;
- no `eval`, dynamic code, selector generation, or page-owned click handlers;
- no prompt that combines page prose with privileged tool instructions;
- a synthetic fixture containing hostile instructions, hidden decoys, unsafe
  schemes, repeated links, and ambiguous labels.

## Confirmation, idempotency, and retries

Pressing Enter or an explicit send button is the confirmation for a same-tab
navigation command. A preview-only read needs no second prompt. Writes,
submissions, purchases, messages, permission expansion, downloads, or external
side effects need a fresh summary and explicit confirmation at execution time.
Never reuse a navigation confirmation for a later write.

Resolution is read-only and repeatable. Navigating to the current URL returns
`already-current`. Do not automatically retry a navigation after the page
changes; re-resolve against the new DOM. Mutating adapters should use stable
action IDs/idempotency keys, bounded exponential backoff only for transient
failures, and a final state check before retrying.

## Permission budget

The scaffold requests only `storage` and `sidePanel`, and its example content
script matches local synthetic origins. `manifest-permissions.test.ts` pins that
budget. Replace those local matches with the narrow production origins actually
needed, or use optional host permissions at a user-understandable activation
point. Never add future permissions speculatively.

Google’s current documentation distinguishes API permissions, required host
permissions, content-script matches, and runtime optional permissions, and
recommends optional permissions when the feature permits user choice:
[Declare permissions](https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions)
and
[`chrome.permissions`](https://developer.chrome.com/docs/extensions/reference/api/permissions).

## Profiles and sessions

- Use a disposable persistent profile for extension E2E; never point automation
  at a personal Chrome profile.
- Do not copy cookies, tokens, Secure Preferences, or credential stores between
  profiles.
- Let a human complete native permission/login prompts when the test genuinely
  requires them, then keep that gitignored profile as a local test artifact.
- Log session state as `present`, `missing`, or `expired`; never log credentials,
  tokens, private page text, or full URLs.
- A skipped or blocked authenticated test is not a pass.

## Audit convention

`audit.ts` accepts only event/status/risk identifiers, extension version,
timestamp, field classification, and HTTP(S) origin. It strips URL paths,
queries, fragments, arbitrary nested data, prompts, selectors, and values.
Keep the history bounded and local by default. Export or transmit it only after
a separate privacy review and explicit product disclosure.

## Test and release ladder

1. Unit: parser, exact match, ambiguity, unsafe URL, message schema, audit
   redaction, and permission budget.
2. Compiled content-script E2E: the local hostile fixture verifies real
   isolated-world messaging and layout visibility.
3. Direct extension-page E2E: verifies that the built sidebar renders.
4. Real toolbar-attached acceptance: open the fixture in branded Chrome, click
   the actual toolbar action, and verify the attached panel against that tab.
5. Store candidate: rebuild from the exact clean release commit, inspect the
   archive, compare permissions, and record executed evidence separately from
   blocked or manual evidence.

Directly opening `chrome-extension://<id>/sidebar.html` is not equivalent to a
toolbar-attached panel. It can become the active tab and mask `currentWindow`
bugs. Playwright also cannot reliably click Chrome’s native toolbar or permission
bubbles. Keep the real-toolbar smoke as a distinct human gate.

## Chrome Web Store checklist

- State one clear primary purpose and make browser/page data use necessary to
  that user-facing purpose.
- Request the narrowest required and optional permissions; explain each one.
- Disclose local as well as transmitted user-data handling. Website content,
  browsing activity, authentication information, and health information are
  user data under the Store policy.
- Use secure transport and provide prominent in-product disclosure/consent when
  required.
- Bundle all executable JavaScript/Wasm with the Manifest V3 package; do not
  fetch remote code for execution.
- Keep test instructions, privacy disclosures, screenshots, and permission
  explanations consistent with the shipped binary.

Review the live primary sources before every submission:
[Program Policies](https://developer.chrome.com/docs/webstore/program-policies/policies),
[User Data FAQ](https://developer.chrome.com/docs/webstore/program-policies/user-data-faq),
and
[Manifest V3 remote-hosted-code rule](https://developer.chrome.com/docs/extensions/develop/migrate/remote-hosted-code).

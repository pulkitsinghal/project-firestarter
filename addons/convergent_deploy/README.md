# convergent_deploy add-on

Make static deploys **additive, commutative and fenced**, so several agents can publish
to the same site without waiting for each other and without deleting each other's work.

Stack-agnostic, Python-stdlib-only, no daemon, no service.

```
convergent_deploy/
├── README.md                          # this file (not stamped into projects)
└── common/                            # overlaid when include_convergent_deploy=yes
    ├── scripts/converge.py            # the module: merge → heal → fence
    └── docs/CONVERGENT_DEPLOY.md      # house-style doc that lands in the project
```

## The problem it removes

Every common static deploy mirrors a directory — `wrangler pages deploy`,
`aws s3 sync --delete`, `netlify deploy --prod`, `rsync --delete`, `gh-pages`. Whatever
the live site has and your directory lacks gets **deleted**. Fine with one deployer;
with several it means each agent silently removes the artefacts it does not happen to
hold, and whoever was sent a link gets a 404.

Locking is the wrong fix — it converts data loss into blocking, and blocking is the
thing we are trying to get rid of. Instead the deploy reconciles: it reads the live
manifest, restores what it is missing, merges by id in an order-independent way, and
fences its write with a monotonic token published by the site itself.

Only a genuine 404 means no live state exists. Redirects, access/WAF interstitials,
timeouts, malformed responses and server errors raise `Unreadable`; the deploy never
continues blind. Access-protected sites may provide a Cloudflare service token through
`CF_ACCESS_CLIENT_ID` + `CF_ACCESS_CLIENT_SECRET` without exposing an anonymous origin.

## Relationship to the other concurrency add-ons

| add-on | answers | mechanism |
|---|---|---|
| `work_registry` | *is a peer already working here?* | advisory noticeboard, expiring claims |
| `orchestrator_session` | *who owns this task right now?* | real leases: epoch, heartbeat, takeover |
| **`convergent_deploy`** | *what if two of us publish anyway?* | additive + commutative + fenced writes |

The first two are **discovery**. This one assumes discovery failed — ignored, raced, or
the peer is on another machine entirely — and makes the outcome correct regardless. Use
them together.

## Enable

```bash
python3 bin/generate.py --set include_convergent_deploy=yes …
```

Then see `docs/CONVERGENT_DEPLOY.md` in the generated project for wiring it into your
deploy command. Contract tests: `tests/test_convergent_deploy_contract.py`.

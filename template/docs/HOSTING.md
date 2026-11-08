# Production hosting — where each piece runs

Where to host each part of this project once it leaves your laptop. This is the
*where*, not the *when* or *how*: [HOST_REQUIREMENTS.md](HOST_REQUIREMENTS.md)
lists the dev tools that live on your host, [DEPLOY_POLICY.md](DEPLOY_POLICY.md)
says when a deploy may ship without a separate owner sign-off, and
[GO_LIVE.md](GO_LIVE.md) is the go-live checklist.

Default to **managed commodity hosting** for every piece, and move off it only
when a specific constraint forces you to. You can almost always migrate later,
and most projects never need to.

## The default stack

| Piece | Default managed host | Why / the tradeoff |
|---|---|---|
| Static front end / landing | Cloudflare Pages | Free tier allows commercial use and a global CDN (see guardrail 1). firestarter's `make deploy` already opens a Cloudflare tunnel. |
| Waitlist / email capture | A managed form + a transactional email provider (ESP) | Don't run your own SMTP; deliverability and reputation are a full-time job. |
| Product analytics | A managed, privacy-friendly analytics SaaS | Cookie-light options keep you out of extra consent scope. |
| Always-on worker / API | A container PaaS (Fly, Railway, Render) | Scales to near zero; no servers to patch. firestarter's `fastapi-next` stack targets this. |
| Database | Managed Postgres (Supabase, Neon, RDS, …) | Backups, point-in-time recovery, and failover you don't operate. firestarter's `supabase-flutter` stack assumes this. |
| Object storage | A managed S3-compatible store (R2, S3, …) | Cheap and durable; keep uploads off the app server's disk. |
| Payments | A merchant-of-record (see guardrail 2) | Offload global sales tax / VAT. |
| Domain / DNS | A registrar with a real API, DNS at your CDN/edge | Keep DNS where your edge lives so TLS and routing are one control plane. |

## Guardrails

These four calls are cheap to get right up front and expensive to get wrong.

### 1. A free tier is not always a commercial licence

Vercel's **Hobby** (free) tier is licensed for non-commercial use — a
revenue-generating site needs **Vercel Pro**. Cloudflare Pages' free tier permits
commercial use, which is why it is the default above. Read the current terms of
any free tier before you put a paying product on it: "free" and "allowed for
business use" are different questions, and the answer changes between providers
and over time.

### 2. Take payments through a merchant-of-record

For a solo founder or a small team, prefer a **merchant-of-record** (Lemon
Squeezy, Paddle) over raw Stripe. The merchant-of-record becomes the seller of
record and remits global sales tax / VAT for you; with raw Stripe you are the
merchant and you owe that tax in every jurisdiction you sell into. The checkout
UX is similar; the tax and compliance burden is not.

### 3. Draw the regulated-data (PHI/HIPAA) line deliberately

The commodity stack above is fine until you ingest **regulated data** — PHI,
cardholder data, and the like. The moment you do, hosting changes entirely: you
need provider infrastructure that is eligible for the regime (for example,
HIPAA-eligible services) under a signed agreement (a **BAA** for HIPAA), and most
consumer free tiers do not offer one. Decide which side of this line the project
is on *before* you choose hosts; the cheapest path is usually to keep regulated
data out of scope entirely. Which side you are on is a
[COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) decision — hosting follows from it,
not the other way around.

### 4. Keep a side-product's infrastructure and billing separate

If this is a side product next to a larger "mothership", give it its own
accounts, projects, and billing from day one. Shared infrastructure couples their
blast radius, their invoices, and their access lists; separating later is far more
work than separating now.

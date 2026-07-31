# Sleep Tracking Comparison — Study Design

**Apple Watch vs. WHOOP: is the subscription worth it for better sleep data?**

| | |
|---|---|
| **Status** | Draft — *study design only, no app code yet* |
| **Decision this informs** | Should I keep relying on the Apple Watch I already own, or pay for a WHOOP membership to get meaningfully better sleep tracking? |
| **Design** | Within-subject, repeated-measures, concurrent wear (personal n = 1 study) |
| **Owner** | pulkitsinghal |

> **Where this lives and why.** This repo (`project-firestarter`) is a project
> *generator*, so this is the *design* artifact that would precede a stamped
> project — not the app itself. Section 12 shows the one-command path from this
> doc to a real scaffold when you're ready. Until then, nothing is generated.

---

## TL;DR — set your expectations before you spend a dime

The published validation science (Section 3) says two things you should internalize
*before* running this:

1. **Both** devices are good at the easy part — telling *asleep* from *awake* —
   and only **moderate** at the hard part — labeling **light / deep / REM** stages.
   Neither is "the truth"; only a sleep lab (polysomnography, "PSG") is.
2. Consumer wrist wearables reliably **overestimate total sleep** and
   **underestimate the time you're awake in bed** (WASO), because they're very
   sensitive to sleep but poor at catching quiet wakefulness.

So the honest hypothesis going in is: *WHOOP is probably **not dramatically more
accurate** than the Apple Watch at raw sleep minutes.* Its real value proposition
is the surrounding ecosystem — recovery, HRV trends, strain, a no-nightly-charge
wear model — **not** a big leap in sleep-stage accuracy. This study is designed to
confirm or refute that for *your* body and *your* wrists, and to put a number on
"worth it."

---

## 1. The question

From the voice memo that started this: *"I use an Apple Watch and I don't think
it's very good at telling me how much I slept … there's also WHOOP … they make you
pay so much per month."* Two threads — a **trust** problem and a **cost** problem.

- **Primary question.** Does WHOOP measure my sleep *meaningfully more accurately*
  than my Apple Watch — and by enough to justify its recurring membership cost?
- **Secondary questions.**
  - Which specific metrics diverge most (total sleep? deep? REM? wake?)?
  - Which device is more **consistent** night-to-night (reliability, not just accuracy)?
  - Does either device agree better with how I actually **felt** / behaved
    (sleep diary, subjective quality)?
- **Non-goals.** Not a general-population claim (this is n = 1). Not a medical
  diagnosis. Not a strain/recovery/coaching comparison beyond what's needed to
  judge sleep value-for-money.

---

## 2. What "accurate" even means (background)

The reference standard for sleep measurement is **polysomnography (PSG)** — the
EEG/EOG/EMG setup used in sleep labs. Every consumer device is judged against it.
The vocabulary you'll see throughout:

| Term | Meaning |
|---|---|
| **TIB** (Time in Bed) | Lights-out to final rise. |
| **TST** (Total Sleep Time) | Minutes actually asleep within TIB. |
| **SOL** (Sleep Onset Latency) | Minutes from lights-out to first sleep. |
| **WASO** (Wake After Sleep Onset) | Minutes awake *after* first falling asleep. |
| **Sleep Efficiency** | TST ÷ TIB (%). |
| **Stages** | Light (Apple: *Core*), Deep (slow-wave, *SWS*), REM, Awake. |
| **Sensitivity** | % of true *sleep* epochs the device calls sleep (wearables: high, ≥95%). |
| **Specificity** | % of true *wake* epochs the device calls wake (wearables: **low** — the weak spot). |

The low-specificity problem is *the* headline caveat: because a still-but-awake
body looks like sleep to an accelerometer + heart-rate sensor, wearables tend to
**inflate TST** and **shrink WASO**.

---

## 3. What the literature already says (calibrate expectations)

Recent head-to-head validations against PSG (sources at the bottom):

- **Sleep vs. wake** detection is strong across devices — **sensitivity ≥ 95%** —
  but specificity (catching wakefulness) is much weaker, so most devices
  **significantly differ from PSG on TST, sleep efficiency, WASO, and light
  sleep.**
- **Stage scoring is only moderate.** In a six-device PSG study, per-stage accuracy
  varied widely; e.g. **REM** epochs were correctly classified ~**68.6%** by the
  **Apple Watch (Series 8)** and ~**62.0%** by **WHOOP 4.0**. Apple Watch
  stage-level sensitivity ranged ~**50–86%** with precision ~**73–88%**.
- WHOOP's **own** validation reports "strong agreement" with PSG for sleep/wake,
  REM, and slow-wave sleep — read vendor studies with appropriate skepticism, but
  it's directionally consistent with the independent work.

**Implication for the design:** if you only wear the two devices against *each
other*, you can measure **agreement**, not **accuracy** — neither is ground truth.
To make an accuracy claim you need a reference (Section 4, tiers). Design for the
tier you can actually afford.

---

## 4. Study design

**Type.** Within-subject, repeated-measures, **concurrent wear** — both devices on
the same nights, same body, so night-to-night variability cancels out.

**Wear protocol.**
- Wear **both simultaneously**, one per wrist.
- **Swap wrists weekly** to cancel any wrist/dominance/fit effect.
- Keep band fit snug-but-comfortable and *constant*; log it.
- **Charging windows.** Apple Watch needs a daily top-up and can leave **gaps** if
  it dies overnight — reserve a fixed daytime charge slot and confirm ≥30% at
  bedtime. WHOOP charges on-wrist via a slide-on battery pack (no removal), so its
  gap risk is lower; still verify it's charged.

**Duration & sample.** **≥ 14 nights** minimum for signal, **target 28+** to cover
weekday/weekend and the occasional bad night. More nights = tighter limits of
agreement.

**Reference-standard tiers** (pick what you'll actually do):

| Tier | Ground truth | Cost | What you can claim |
|---|---|---|---|
| **0** | The two devices vs. each other | $0 | **Agreement** only (bias between devices) |
| **1** | + Sleep diary & subjective quality (lights-out, final wake, 1–5 rating) | $0 | Agreement **+** which device tracks behavior/feel better |
| **2** | + A validated **home EEG** headband / home-PSG kit for a subset of nights | $$ | **Accuracy** (bias vs. a real reference) for those nights |

Tier 1 is the recommended floor — it's free and turns "they disagree" into "and
here's which one matches reality." Tier 2 is the only way to say *"X is more
accurate"* rather than *"X and Y disagree by N minutes."*

**Confounds to log every day** (they move sleep more than the device does):
caffeine (last cup time), alcohol, exercise, naps, illness/fever, room temperature,
travel/time-zone, and — critically — **app "sleep schedule" settings and firmware/
app versions**. Freeze OS/app versions for the study window if you can; a mid-study
algorithm update silently breaks comparability.

---

## 5. Metrics & data dictionary

Capture per night, per device. Watch the **definition mismatches** in the notes —
they're the most common way a naïve comparison goes wrong.

| Metric | Apple Health source | WHOOP API source | Caveats |
|---|---|---|---|
| Total Sleep Time | Σ `asleep*` `HKCategoryValueSleepAnalysis` samples | sleep duration / "total in-sleep" | Apple stores **overlapping interval samples** — dedupe before summing |
| Time in Bed | `inBed` (+ `awake`) span | time in bed | Apple `inBed` may be absent if only a stage-writer logged the night |
| Sleep Onset Latency | derived (first `asleep*` − `inBed` start) | sleep latency | Apple often lacks an explicit "lights out" → SOL is noisy |
| WASO | Σ `awake` between first/last sleep | disturbances / wake duration | The metric most likely to disagree — see §2 |
| Sleep Efficiency | TST ÷ TIB | efficiency (%) | Same formula, but only if TIB is defined the same way |
| Light sleep | `asleepCore` | light | Apple **"Core" ≈ light**, not a separate thing |
| Deep sleep | `asleepDeep` | slow-wave (SWS) / deep | Different algorithms; expect divergence |
| REM sleep | `asleepREM` | REM | Moderate accuracy on both (§3) |
| Awakenings (count) | count of `awake` segments | disturbance count | Definitions differ |
| Resting HR | `restingHeartRate` | resting heart rate (recovery) | Comparable |
| **HRV** | `heartRateVariabilitySDNN` (**SDNN**) | HRV (**RMSSD**) | **Not directly comparable — different math.** Compare *trends*, not absolute values |
| Respiratory rate | `respiratoryRate` | respiratory rate (sleep) | Comparable |
| Sleep score | *(none native)* | Sleep Performance Score (0–100) | **No Apple analog** — don't force one |

> Pre-register this table before you look at any data. Deciding what counts *after*
> seeing the numbers is how you accidentally p-hack your own gadget.

---

## 6. Data access & collection

### Apple Watch → Apple Health (HealthKit)

- Sleep lives under **`HKCategoryTypeIdentifier.sleepAnalysis`**, with values
  **`inBed`, `awake`, `asleepCore` (light), `asleepDeep`, `asleepREM`**
  (iOS 16+ / watchOS 9+). Older or third-party writers emit only
  `inBed` / `asleep` / `awake` — no stages.
- Physiology: `heartRateVariabilitySDNN`, `restingHeartRate`, `respiratoryRate`.
- **Two extraction paths:**
  1. **Manual export (Tier 0/1, zero code):** Health app → profile → **"Export All
     Health Data"** → a zip containing **`export.xml`**; parse the
     `Record type="HKCategoryTypeIdentifierSleepAnalysis"` rows.
  2. **A small HealthKit reader app (future scaffold):** structured, ongoing,
     on-device pull — this is the Flutter piece in Section 12.
- **Gotcha:** samples are overlapping intervals, not a tidy per-night row —
  reconcile/merge into one session per night before computing anything.

### WHOOP → Developer API

- **Auth:** OAuth 2.0 with read scopes (e.g. `read:sleep`, `read:recovery`,
  `read:cycles`, `read:profile` — confirm exact scope names in the current docs).
- **Sleep** returns time in bed, sleep duration, **efficiency**, **latency**,
  **disturbances**, **stages (light / SWS-deep / REM)**, **respiratory rate**, and
  a **Sleep Performance Score (0–100)**. **Recovery** returns **HRV (RMSSD)**,
  **resting HR**, and recovery %. It's a **cycle-based** model — sleep hangs off
  physiological cycles.
- **History & freshness:** historical data is paginated; **webhooks** push new
  records; the API is **rate-limited** (check current limits). No-code fallback:
  **CSV export** from the WHOOP web dashboard.
- **Version:** target **API v2** (2025 refresh); **v1 is being deprecated** —
  verify the migration deadline before building anything.

### Alignment (needed for anything beyond nightly totals)

- Normalize everything to a single time zone; snap to **"sleep sessions."**
- For epoch-by-epoch analysis, resample both to a common **30-second epoch** grid
  and align on wall-clock time.

---

## 7. Analysis plan

1. **Descriptives** — mean ± SD per metric per device; plot nightly time series.
2. **Agreement** — **Bland–Altman** (mean bias + 95% limits of agreement) for TST,
   each stage, resting HR, HRV, respiratory rate. This is the right tool for
   "do two methods agree," not a correlation coefficient.
3. **Reliability** — **ICC** (intraclass correlation) and within-device
   coefficient of variation for night-to-night consistency.
4. **Epoch-by-epoch** (if aligned) — sleep/wake **sensitivity, specificity,
   accuracy**, plus per-stage **confusion matrices**. This is where the
   "overestimates sleep" story shows up concretely.
5. **Accuracy (Tier 2 only)** — **bias / MAE / RMSE** of each device vs. the
   reference on the nights you have it.
6. **Pre-registration** — write down your thresholds and primary metric *before*
   analysis (Section 8). No moving goalposts.

---

## 8. Decision framework (this is the whole point)

Turn the vague "is it worth it" into a number **before** you start:

- **If you ran Tier 2 (have a reference):** WHOOP "wins" only if it beats the Apple
  Watch's error on your **primary metric** (suggest **TST**) by a margin you set in
  advance — e.g. *"WHOOP's TST bias must be ≥ 20 min closer to reference **and** its
  REM agreement ≥ 10 percentage points better."*
- **If you ran Tier 0/1 (no reference):** you can't crown an accuracy winner, so
  decide on **(a)** which device better matches your **diary/subjective** nights and
  **(b)** which is more **consistent** — then ask whether that's worth the price.

**Cost side of the ledger** (verify current pricing — WHOOP restructured in
May 2025 and prices drift; Apple has no sleep subscription):

| Option | Recurring cost | Notes |
|---|---|---|
| **Apple Watch** (already owned) | **$0** | Sleep is free; nightly charge is the tax |
| **WHOOP One** | ~$199/yr (~$25/mo) | Entry tier |
| **WHOOP Peak** | ~$239/yr (~$30/mo) | + longevity/health-monitoring features |
| **WHOOP Life** | ~$359/yr (~$40/mo) | + medical-grade hardware/biometrics |

Over three years, Peak is roughly **$700+**. Frame the question as *"is the sleep
improvement (plus recovery/HRV ecosystem) worth ~$240–360 every year, forever?"*

**Don't forget the "do nothing better" option:** Apple Watch **+ a dedicated
third-party sleep app** (e.g. AutoSleep / Sleep++ / Bedtime) can close much of the
*presentation* gap at ~no recurring cost — though it won't fix the underlying
sensor/algorithm accuracy ceiling. Worth a Tier-0 arm if you're cost-sensitive.

---

## 9. Threats to validity / limitations

- **n = 1** — valid for *your* decision, not generalizable.
- **Agreement ≠ accuracy** in Tier 0/1 (no ground truth).
- **Black-box algorithms** on both sides; **firmware/app updates** can shift results
  mid-study (freeze versions).
- **Wrist dominance / band fit** — mitigated by weekly wrist swaps.
- **Expectation bias** — you *want* the expensive one to win (or the free one). Fix
  the primary metric and thresholds up front; don't peek.
- **Charging gaps** (mostly Apple Watch) can silently drop nights — track missingness.

---

## 10. Protocol timeline

| When | Do |
|---|---|
| **Week 0** | Set up both pipelines; freeze OS/app versions; **dry-run** export on 2 nights end-to-end (prove you can get clean data out of *both* before committing 4 weeks) |
| **Weeks 1–4** | Concurrent wear nightly + daily diary; **swap wrists each week**; pull data weekly; log confounds |
| **Week 5** | Reconcile/align data; run Section 7 analysis; apply Section 8 decision rule; write up |

---

## 11. Privacy & data handling

This is your personal health data — treat it like it. Keep raw exports **local**;
if/when this becomes a scaffolded project, HealthKit stays **on device**, WHOOP
**OAuth tokens live in a secret vault** (never in the repo or logs), and any shared
write-up / handoff uses **synthetic or aggregated** figures — no raw PHI. This
mirrors Firestarter's local-first, privacy-split precepts (see the template's
`docs/LOCAL_TLS.md` and `FEATURE_HANDOFF.md`).

---

## 12. From study → project (when you're ready to build)

This design maps cleanly onto a Firestarter stamp. The natural fit is the
**`supabase-flutter`** stack:

- **Flutter app** reads **HealthKit** on-device (Apple Watch sleep + physiology).
- **A scheduled backend job** pulls the **WHOOP API** (OAuth, webhooks).
- **Postgres** stores normalized *one-row-per-night-per-device* records
  (the Section 5 data dictionary becomes the schema).
- **A small dashboard** renders the Bland–Altman / agreement views from Section 7.

When you want it, the one-line kickoff would be an
`examples/sleep-tracking-comparison.answers.json` on `supabase-flutter`, then
`./bin/firestart.sh --values …`. **Design only for now — say the word and I'll
stamp it.**

---

## Sources

- WHOOP pricing (One/Peak/Life; May 2025 restructure): [TrackerVS — WHOOP Pricing 2026](https://trackervs.com/pricing/whoop-pricing/), [TechCrunch — WHOOP subscription launch](https://techcrunch.com/2025/05/11/fitness-tracker-whoop-faces-unhappy-customers-over-upgrade-policy)
- WHOOP developer API (sleep/recovery fields, OAuth, stages, RMSSD): [WHOOP for Developers — WHOOP 101](https://developer.whoop.com/docs/whoop-101/), [Open Wearables — WHOOP API](https://openwearables.io/blog/whoop-api-recovery-strain-sleep-data-for-developers)
- Apple HealthKit sleep model (`asleepCore/Deep/REM`, export): [Apple Developer — HKCategoryValueSleepAnalysis.asleepREM](https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis/asleeprem), [Apple sleep data types (MyDataHelps)](https://support.mydatahelps.org/apple-sleep-device-data-types), [Apple Health export sleep format](https://www.johngoldin.com/blog/apple-health-export/2023-02-sleep-export/)
- PSG validation (sensitivity/specificity, per-stage accuracy): [SLEEP Advances — six-device wrist-wearable validation](https://academic.oup.com/sleepadvances/article/6/2/zpaf021/8090472), [Sensors 2024 — three wearables vs PSG](https://www.mdpi.com/1424-8220/24/20/6532), [WHOOP strap PSG validation](https://www.researchgate.net/publication/343225397_A_validation_study_of_the_WHOOP_strap_against_polysomnography_to_assess_sleep)

*Pricing and API version details drift — verify against the vendors' current docs before building.*

# Sleep-Tracking Device Validation — Pilot Study Design

**Apple Watch vs. WHOOP vs. EEG: how accurately do consumer wearables measure
sleep, judged against an attended overnight EEG read by multiple blinded scorers?**

| | |
|---|---|
| **Status** | Draft — *pilot protocol design; no app code yet* |
| **Design** | Prospective, single-site **pilot** validation. Within-subject **concurrent wear** (both wearables per subject-night) against a **full attended PSG / EEG** reference, with **multiple blinded human readers** scoring each record. |
| **Primary question** | Against an EEG reference, how accurate are the Apple Watch and WHOOP at total sleep, wake, and sleep-stage measurement — and how do they compare head-to-head, **independent of manufacturer funding**? |
| **Companion** | [`literature-review.md`](./literature-review.md) — the evidence base, methodology standards, and conflict-of-interest analysis. **Read it first.** |
| **Owner** | `pulkitsinghal` (repo) · study roles are role-placeholders below |

> **Two altitudes.** This is the study *design*. It began as a personal
> "is WHOOP worth the money?" question (still answered, §11) but has grown into a
> **pilot clinical validation study** with volunteers, an EEG reference, multiple
> readers, and eventual publication. The consumer decision is now a *corollary* of
> the bigger accuracy question.
>
> **Public-repo note.** This file lives in a public repo, so collaborators, the
> institution, and IRB are written as **role placeholders** (`[PI]`,
> `[Institution]`, …). Keep the real names, site, and IRB numbers in a **private**
> copy — don't commit them here.

---

## TL;DR — three things to internalize before designing anything

1. **There is no perfect ground truth.** Even expert human scorers agree on only
   **~82.6%** of EEG epochs, and worse on the stages wearables also miss (N1 ~63%,
   N3/deep ~67%). This sets a **hard ceiling**: no device can match "truth" better
   than two experts match each other — which is exactly why we use **6–10 blinded
   readers** and score devices against their **consensus**, not one person's read.
2. **Both devices are good at the easy question, mediocre at the hard one.**
   Sleep-vs-wake sensitivity ≈ 95%, but wake **specificity is only ~29–52%**, so
   both **overestimate total sleep** and **underestimate wake (WASO)**. Stage
   accuracy is moderate and **worst for deep sleep** (~50%).
3. **The existing literature is partly compromised.** Many single-device
   validations are **manufacturer-funded** and run under best-case conditions. An
   **independent** local study with a **multi-reader** reference is genuinely worth
   doing. (All of this is sourced in [`literature-review.md`](./literature-review.md).)

---

## 1. The question(s)

- **Primary (validation).** Against a full EEG/PSG reference scored by multiple
  blinded readers, how accurate are the **Apple Watch** and **WHOOP** for
  total sleep time, wake/WASO, sleep efficiency, and stage durations — and which is
  more accurate, head-to-head, on the same subject-nights?
- **Secondary.**
  - **Human ceiling:** what is the **inter-reader agreement** on *our own* records
    (so device error is judged against the band where humans also disagree)?
  - **Failure modes:** which metrics/stages diverge most, and do the devices err the
    *same way* humans do (excusable) or differently (a real defect)?
  - **Consumer corollary (§11):** for an individual, is WHOOP's recurring cost
    justified by better accuracy than an already-owned Apple Watch?
- **Non-goals.** Not a diagnostic tool for sleep disorders. Not (yet) a
  definitively powered claim — this is a **pilot** (§9). Not a strain/recovery/
  coaching comparison beyond sleep.

---

## 2. Background — the reference standard, briefly

Full detail (with citations) is in [`literature-review.md` §2–3](./literature-review.md).
The essentials:

- The gold standard is **polysomnography (PSG)**, which records **EEG + EOG + chin
  EMG** (this is what *stages* sleep, in 30-second epochs to AASM rules) **plus**
  ECG, airflow, respiratory effort, SpO₂, and position.
- **"Is a sleep study just an EEG?"** — No. A sleep study (PSG) *includes* EEG, but
  staging also needs **EOG + chin EMG** (to catch REM's eye movements + muscle
  atonia), and PSG adds the cardiorespiratory channels the pulmonologists use for
  apnea. A bare scalp-EEG montage under-scores REM.
- **The reference is itself imperfect:** expert scorers agree ~**82.6%** of the
  time. We therefore treat "truth" as a **multi-reader consensus** and *measure* the
  disagreement rather than pretending it's zero.

**Recommendation:** acquire a **full AASM PSG montage** (so Pulmonary Medicine gets
their clinical read and we capture arousals/respiratory events that may explain
device errors), but base *our* comparison on the **EEG/EOG/EMG staging**.

---

## 3. What the literature already shows (calibrate expectations)

Condensed from [`literature-review.md`](./literature-review.md) — see it for sources:

- **WHOOP** (Miller 2020, vs PSG, 86 sleeps): wake-vs-sleep agreement 89%
  (sensitivity 95%, **wake specificity 51%**, κ 0.49); 4-stage agreement 64%; TST
  **+8.2 ± 32.9 min** (note the huge ±33 min night-to-night spread).
- **Apple Watch** (independent, 2024–2025): best of the wrist wearables,
  **κ ≈ 0.53 (moderate)**; core/light ~83%, REM ~69%, **deep ~50%**.
- **Cross-device:** strong sleep/wake, poor wake specificity → overestimate TST,
  underestimate WASO; staging moderate, **deep worst**; accuracy **degrades** in
  fragmented/older/disordered sleep (most studies use healthy 20–50-year-olds).
- **Manufacturer-funded studies look better than independent ones** — a reason this
  study is independent and pre-registered.

---

## 4. Study design (the core)

**Type.** Prospective, single-site **pilot**; **within-subject concurrent wear**;
each subject sleeps **one night** wearing both devices during an attended PSG.

**Subjects.** ~**12** volunteers (pilot; §9). Inclusion: consenting adults.
Exclusion (for the pilot's "clean" baseline): known untreated sleep disorder,
current shift work, or anything that would confound a single lab night — recorded,
not ignored. Volunteers may include clinicians ("one less call" the night they're a
subject).

**Reference standard.** Full attended overnight **PSG** with the AASM staging
montage (§2); staging analyzed for the device comparison.

**Index devices.** **Apple Watch** and **WHOOP**, worn **concurrently**, one per
wrist.

**Multi-reader scoring (the crux).**
- **6–10 qualified EEG readers** each **independently** score every record
  **blinded** to (a) the device outputs, (b) each other, and (c) subject identity —
  only the de-identified PSG/EEG.
- Recruit **beyond** the pulmonologists (who focus on apnea) — the broader pool of
  EEG readers strengthens the staging read and the reliability estimate.
- From the reader set we derive **(i)** inter-reader reliability (Fleiss' κ) and
  **(ii)** a **consensus/majority hypnogram** used as the reference for scoring
  devices. Pre-specify the consensus rule (majority per epoch; adjudication for ties).

**Wrist assignment & device interference.**
- **One device per wrist** (avoids the electrical/optical/fit interference of
  co-locating two devices on one wrist — a real objection).
- **Counterbalance** assignment across subjects: e.g. **6 subjects** Apple-left /
  WHOOP-right, **6** the reverse — this *balances* wrist/dominance effects across the
  sample far better than "6 people wear WHOOP on the left." Record handedness.
- If a future arm must co-locate devices, treat interference as a documented
  limitation and test for it.

**Shared device pool & the Apple Watch "identity" problem.**
- Buying 12 Apple Watches (~$400 each) and 12 WHOOPs is unnecessary; use a **small
  shared pool**, cleaned/charged between subjects, mapped to each subject-night in a
  **study manifest** (device serial + date → subject ID). The on-device Apple ID is
  irrelevant to analysis *as long as the manifest maps it*.
- **One real caveat:** Apple's sleep-staging algorithm may use the paired profile's
  **demographics (age/sex)**. If the watch "thinks it's the owner," those inputs are
  wrong for the subject and *could* bias staging. **Mitigation:** set the study
  device's profile demographics per subject where possible, or record that they were
  fixed and treat it as a controlled limitation.

**Blinding summary.** Readers blinded to devices/each other/identity; analysts
compute device metrics without seeing reader identities; pre-registered endpoints.

---

## 5. Recruitment, collaboration & regulatory

- **Subjects:** recruit volunteers (§4). Track who/when; a shared spreadsheet of
  available nights (subjects pick a date next month, etc.).
- **Pulmonary Medicine / Sleep Lab (`[Institution]`):** they now operate the lab —
  partner with them for PSG acquisition and room time (either "take it back" in-house
  or collaborate; collaboration is simplest).
- **EEG readers:** enlist **6–10** readers from the broader group who read EEGs, not
  only the pulmonologists.
- **IRB (`[Institution]` IRB):** human-subjects research → **IRB review is required**
  (informed consent, data plan, risk/benefit). Budget time for it.
- **Investigators:** `[PI]`, `[Co-investigator A]`, `[Co-investigator B]` (keep real
  names in the private copy). Confirm authorship/roles early.

---

## 6. Metrics & data dictionary

Per subject-night, capture device metrics **and** the reference (per reader + consensus).

| Metric | Apple Health source | WHOOP API source | EEG/PSG reference | Caveats |
|---|---|---|---|---|
| Total Sleep Time | Σ `asleep*` `HKCategoryValueSleepAnalysis` | sleep duration | Σ non-wake epochs (consensus hypnogram) | Apple stores **overlapping interval samples** — dedupe first |
| Time in Bed | `inBed` (+`awake`) span | time in bed | lights-out → lights-on (tech log) | define TIB identically across sources |
| Sleep Onset Latency | first `asleep*` − `inBed` start | sleep latency | lights-out → first sleep epoch | Apple lacks explicit "lights out" → noisy |
| WASO | Σ `awake` between first/last sleep | disturbances / wake | Σ wake epochs after onset | **most likely to disagree** (§3) |
| Sleep Efficiency | TST ÷ TIB | efficiency (%) | TST ÷ TIB (reference) | only comparable if TIB defined the same |
| Light | `asleepCore` | light | N1 + N2 | Apple **"Core" ≈ light**; map N1+N2→light |
| Deep (SWS) | `asleepDeep` | slow-wave | N3 | weakest stage for both devices |
| REM | `asleepREM` | REM | R | intermediate accuracy |
| Awakenings | count of `awake` segments | disturbance count | arousal/awakening count | definitions differ |
| Resting HR | `restingHeartRate` | resting HR (recovery) | ECG-derived | comparable |
| **HRV** | `heartRateVariabilitySDNN` (**SDNN**) | HRV (**RMSSD**) | ECG-derived (choose method) | **SDNN ≠ RMSSD** — compare trends, not absolute values |
| Respiratory rate | `respiratoryRate` | respiratory rate | airflow/effort-derived | comparable |
| Sleep score | *(none)* | Sleep Performance (0–100) | *(none)* | **no reference analog** — don't force one |
| **Hypnogram (30-s)** | staged series (if extractable) | staged series | **each reader + consensus** | the basis for epoch-by-epoch analysis |

> **Pre-register** this mapping (esp. N1+N2→"light") *before* looking at data.

---

## 7. Data access & collection

### Apple Watch → Apple Health (HealthKit)
- Sleep under **`HKCategoryTypeIdentifier.sleepAnalysis`**: `inBed`, `awake`,
  `asleepCore` (light), `asleepDeep`, `asleepREM` (iOS 16+/watchOS 9+). Physiology:
  `heartRateVariabilitySDNN`, `restingHeartRate`, `respiratoryRate`.
- **Export:** Health app → **"Export All Health Data"** → zip with **`export.xml`**
  (parse `HKCategoryTypeIdentifierSleepAnalysis` rows), or a small HealthKit reader
  app (§14). **Gotcha:** overlapping interval samples — merge to one session/night.

### WHOOP → Developer API
- **OAuth 2.0** (scopes e.g. `read:sleep`, `read:recovery`, `read:cycles` — confirm
  names). Sleep returns TIB, duration, **efficiency, latency, disturbances, stages
  (light/SWS/REM), respiratory rate, Sleep Performance (0–100)**; recovery returns
  **HRV (RMSSD)**, resting HR. Paginated history; webhooks; rate-limited. No-code
  fallback: **CSV export**. **Target API v2** (v1 deprecating — verify).

### PSG / EEG reference
- Export raw **EDF/EDF+** from the PSG system; collect **one hypnogram per reader**
  (blinded) + build the **consensus hypnogram**. Keep the tech's lights-out/on log.
- **De-identify** before readers see records (§12).

### Alignment
- Normalize to one time zone; align device and reference to a common **30-second
  epoch** grid on wall-clock time (device clocks may drift — record a sync marker).

---

## 8. Analysis plan — adopt the standard framework

Use the **accepted open-source pipeline** (Menghini & de Zambotti 2021) so results
are comparable and credible — see [`literature-review.md` §7](./literature-review.md).

1. **Summary-metric agreement (device vs. consensus reference):** **Bland–Altman**
   (bias + 95% limits of agreement) for TST, SE, WASO, SOL, and each stage duration;
   plus **discrepancy analysis**.
2. **Epoch-by-epoch (EBE):** sensitivity / specificity / accuracy and **confusion
   matrices** for sleep-vs-wake and 4-stage, device vs. consensus. Report **Cohen's
   κ** (prevalence-adjusted where appropriate).
3. **Inter-reader reliability:** **Fleiss' κ** across the 6–10 readers, overall and
   per stage — this is the **human ceiling** every device number is shown against.
4. **Head-to-head:** compare Apple Watch vs. WHOOP on the same nights (paired).
5. **Physiology:** resting HR / respiratory rate vs. reference; HRV **trend**
   comparison only (SDNN vs RMSSD are not interchangeable).
6. **Pre-registration:** primary endpoint (suggest **TST bias** and **4-stage κ**
   vs. consensus), secondary endpoints, and the consensus rule — all fixed **before**
   analysis. No moving goalposts.

---

## 9. Sample size & power

- Typical validations run **n ≈ 12–35**, often one night each. A pilot of **~12** is
  right for **estimating variance and feasibility**, not for a confirmatory verdict.
- Its job: produce the **effect-size + between-subject/between-reader variance**
  needed to **power the definitive study** ("if they did thirty, we do a hundred").
- **Pre-register the pilot as feasibility/hypothesis-generating.** Don't over-claim
  from 12 nights.

---

## 10. Threats to validity

- **No perfect ground truth** — mitigated by the multi-reader consensus + reporting
  inter-reader κ (we *measure* the ceiling instead of hiding it).
- **Single night per subject** — first-night effects; no night-to-night reliability
  within subject (a follow-up could add nights).
- **Best-case sample** — healthy adults in a lab overstate field accuracy; note it.
- **Device interference / wrist effects** — mitigated by one-device-per-wrist +
  counterbalancing (§4).
- **Apple demographic-input bias** on a shared device (§4) — control or document.
- **Firmware/app drift** — freeze/record device OS + app versions.
- **Blinding leaks** — enforce de-identification and reader isolation.
- **Pilot generalizability** — small n; explicitly not confirmatory (§9).

---

## 11. Consumer corollary — is WHOOP worth it? (the original question)

The validation results feed the personal decision. Frame "worth it" numerically
**before** analysis, then read it off the data:

- WHOOP "wins for an individual" only if it beats the Apple Watch's error on the
  **primary metric** (suggest TST) by a pre-set margin **and** on 4-stage κ vs. the
  reference — otherwise the free, already-owned watch is the rational choice.

**Cost ledger** (verify current pricing — WHOOP restructured May 2025; Apple has no
sleep subscription):

| Option | Recurring cost | Notes |
|---|---|---|
| **Apple Watch** (already owned) | **$0** | Sleep is free; nightly charge is the tax |
| **WHOOP One** | ~$199/yr (~$25/mo) | Entry tier |
| **WHOOP Peak** | ~$239/yr (~$30/mo) | + longevity/health features |
| **WHOOP Life** | ~$359/yr (~$40/mo) | + medical-grade hardware/biometrics |

Over three years, Peak is **$700+**. If the study finds no meaningful accuracy edge,
the honest consumer takeaway is *"the Apple Watch you own is good enough for sleep;
pay for WHOOP only if you want its recovery/HRV ecosystem."* A near-free middle
option: Apple Watch **+ a third-party sleep app** (AutoSleep / Sleep++).

---

## 12. Privacy, data handling & ethics

- **Human-subjects data → IRB-governed.** Informed consent; a written data-management
  plan; minimal necessary data.
- **De-identify** PSG/EEG before readers and analysts see it; map identities only in
  the access-controlled **study manifest**.
- **No PHI in this repo.** Real names/site/IRB numbers stay in a private copy;
  any shared write-up/handoff uses **synthetic or aggregated** figures. WHOOP OAuth
  tokens live in a **secret vault**, never in the repo or logs. Mirrors Firestarter's
  local-first, privacy-split precepts (`template/docs/LOCAL_TLS.md`,
  `FEATURE_HANDOFF.md`).

---

## 13. Independence & conflict-of-interest stance

- **Not funded by any device manufacturer.** Devices are purchased/owned by the
  study, not provided by Apple or WHOOP.
- **Pre-registered** analysis using the open de Zambotti framework, with a
  **multi-reader** reference — the two things most often missing from
  manufacturer-funded work (see [`literature-review.md` §6](./literature-review.md)).
- Any investigator relationships with device makers will be **disclosed**.

---

## 14. From study → tooling (Firestarter, when ready)

This maps onto a **`supabase-flutter`** stamp — a **data-capture + analysis**
pipeline, not a consumer app:

- **Flutter/companion** ingests the **Apple Health export** (on-device HealthKit) and
  pulls the **WHOOP API**; PSG **hypnograms** (per reader + consensus) are imported
  from EDF.
- **Postgres** stores normalized *epoch-level* and *per-night* records (the §6 data
  dictionary → schema); a manifest table maps device-night → subject.
- An **analysis service** runs the de Zambotti pipeline (EBE, Bland–Altman,
  confusion matrices, Fleiss'/Cohen's κ); a **dashboard** renders them.

Kickoff (when you say so): an `examples/sleep-tracking-comparison.answers.json` on
`supabase-flutter`, then `./bin/firestart.sh --values …`. **Design only for now.**

---

## 15. Open decisions before the protocol is final

- [ ] Full PSG vs. EEG-only staging montage (recommendation: **full PSG**, §2).
- [ ] Consensus rule for readers (majority per epoch vs. adjudicated) + how many
      readers (target 6–10).
- [ ] Wrist counterbalancing scheme confirmed; handedness captured (§4).
- [ ] Apple Watch demographic-input handling on shared devices (§4).
- [ ] Inclusion/exclusion finalized with Pulmonary Medicine + IRB (§5).
- [ ] Confirm funding/COI wording for every cited study (lit-review §6 table).
- [ ] Pre-register primary/secondary endpoints (§8) before any data is scored.

---

## Sources

Device-access + pricing sources are listed below; the **full research bibliography**
(validation studies, inter-scorer reliability, methodology, COI) is in
[`literature-review.md`](./literature-review.md).

- WHOOP pricing (One/Peak/Life; May 2025 restructure): [TrackerVS](https://trackervs.com/pricing/whoop-pricing/), [TechCrunch](https://techcrunch.com/2025/05/11/fitness-tracker-whoop-faces-unhappy-customers-over-upgrade-policy)
- WHOOP developer API: [WHOOP 101](https://developer.whoop.com/docs/whoop-101/), [Open Wearables](https://openwearables.io/blog/whoop-api-recovery-strain-sleep-data-for-developers)
- Apple HealthKit sleep model: [Apple Developer — `asleepREM`](https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis/asleeprem), [Apple sleep data types](https://support.mydatahelps.org/apple-sleep-device-data-types), [Health export format](https://www.johngoldin.com/blog/apple-health-export/2023-02-sleep-export/)

*Pricing and API versions drift — verify against vendors' current docs before building.*

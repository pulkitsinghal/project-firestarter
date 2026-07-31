# Literature Review — Wearable Sleep-Tracking Accuracy vs. EEG/PSG

**Companion to [`README.md`](./README.md) (the study design). This is the starting
point: what's already published, how good it actually is, who paid for it, and the
gap our pilot fills.**

| | |
|---|---|
| **Status** | Draft — living document; expand as full texts are retrieved |
| **Question it serves** | How accurately do the Apple Watch and WHOOP measure sleep vs. an EEG reference — and is the *existing* evidence trustworthy and independent? |
| **Scope** | Wrist wearables (Apple Watch, WHOOP) validated against polysomnography (PSG) / EEG; multi-device comparisons; scoring methodology; **inter-scorer reliability**; conflict-of-interest patterns |

> **Retrieval note.** Several publisher/PMC full texts (NCBI, MDPI, Oxford) block
> automated fetching, so figures below are drawn from abstracts and indexed
> summaries and are cited to the source. **Before we rely on any single number in a
> paper or protocol, pull the full text and confirm it against the paper's own
> tables and its funding/disclosure statement.**

---

## 0. Executive summary — five things the literature already tells us

1. **The reference standard is not "an EEG" — it's PSG, and for *staging* it's a
   specific EEG + EOG + chin-EMG montage** scored in 30-second epochs to AASM
   rules (Section 2). This directly answers the "is a sleep study just an EEG?"
   question: **no** — but the part that *stages* sleep is essentially EEG-based.
2. **Even the gold standard disagrees with itself.** Expert human scorers agree on
   only ~**82.6%** of epochs (AASM inter-scorer reliability), and worse on the
   stages wearables also struggle with (N1 ~63%, N3 ~67%). This sets a **hard
   ceiling**: no device can agree with "truth" better than two experts agree with
   each other (Section 3). It is also the strongest scientific justification for
   your **multiple-blinded-readers** design.
3. **Both devices are good at the easy question and mediocre at the hard one.**
   Sleep-vs-wake sensitivity is ~95%, but **specificity for wake is only ~29–52%**
   across devices → they **overestimate total sleep** and **underestimate wake
   after sleep onset (WASO)**. Stage-by-stage accuracy is moderate and worst for
   **deep** sleep (Sections 4–5).
4. **Independent studies report worse numbers than manufacturer-funded ones.**
   Manufacturer-sponsored, single-night, healthy-young-adult, in-lab studies tend
   to look best; independent multicenter work looks meaningfully worse. Funding is
   a variable, not a footnote (Section 6).
5. **There is an accepted, open-source way to run this analysis** (Menghini &
   de Zambotti's standardized framework: epoch-by-epoch + Bland–Altman +
   discrepancy analysis). Adopting it makes our results comparable and credible
   (Section 7).

---

## 1. Why this review (and why now)

The motivating hunch — *"the Apple Watch isn't very good at telling me how much I
slept"* — turns out to be a researchable, partly-answered question. Two problems
in the existing literature make an **independent** local study worth doing:

- **Trust:** many of the most-cited single-device validations were **funded by the
  device makers**, run under near-best-case conditions (Section 6).
- **Design blind spot:** most studies validate a device against **one** scorer's
  reading of the PSG, treating that reading as perfect truth — when inter-scorer
  agreement is only ~83% (Section 3). Our multi-reader design measures that ceiling
  instead of hiding it.

---

## 2. The reference standard: PSG vs. "an EEG"

**Polysomnography (PSG)** is the accepted gold standard. A full attended PSG
simultaneously records **cortical EEG, electro-oculography (EOG), sub-mental (chin)
EMG, ECG, airflow, respiratory effort, pulse oximetry, and body position** ([AASM /
AAST technical guideline](https://aastweb.org/wp-content/uploads/2025/03/AAST-PSG-Guideline-Final.pdf)).

**Sleep *staging* specifically** needs only three of those signal families —
**EEG + EOG + chin EMG** — scored by a trained scorer in **30-second epochs** to
AASM rules. The AASM **recommended** EEG derivations are **F4-M1, C4-M1, O2-M1**
(frontal/central/occipital referenced to the contralateral mastoid); an
**acceptable** alternative is **Fz-Cz, C4-M1, Oz-Cz**, and the two montages are
comparable for staging and arousal scoring ([AASM montage
comparability](https://jcsm.aasm.org/doi/10.5664/jcsm.3880); [2007 AASM electrode
placement](https://pmc.ncbi.nlm.nih.gov/articles/PMC3001799/)).

**What this means for the protocol:**
- The instinct "set it up like an EEG hookup" is *nearly* right — staging is
  EEG-driven — **but you also need EOG and chin EMG** to distinguish REM (eye
  movements + muscle atonia) from N1/wake. A bare scalp-EEG montage under-scores REM.
- The **respiratory/SpO2 channels** are what **Pulmonary Medicine** cares about
  (apnea). They are **not required to answer our staging question**, but running a
  full PSG (rather than an EEG-only montage) (a) is what the sleep lab already does,
  (b) lets the pulmonologists get their clinical read, and (c) captures arousals/
  respiratory events that may explain device errors. **Recommendation: acquire a
  full AASM PSG montage; analyze the EEG/EOG/EMG-based staging for our comparison.**
- A **full clinical (seizure) EEG** — 21+ electrodes, 10–20 system — is a
  *different* study again; we do **not** need that density for staging.

---

## 3. The reference isn't perfect — inter-scorer reliability (the crux)

This is the most important and most under-appreciated finding for our design.

| Metric | Value | Source |
|---|---|---|
| Overall epoch agreement between expert scorers (AASM ISR program; >2,500 scorers, >3.2M scoring decisions) | **82.6%** | [Rosenberg & Van Hout 2013](https://jcsm.aasm.org/doi/full/10.5664/jcsm.2350) |
| Independent replication (pool of 7 experienced scorers, 72 records) | **~82%** | Danker-Hopfe et al. (via [meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC8807917/)) |
| Stage R (REM) agreement | Highest | AASM ISR |
| Stage N3 (deep) agreement | **67.4%** | AASM ISR |
| Stage N1 (light onset) agreement | **63.0%** (lowest) | AASM ISR |

**Implications — read these before designing anything:**

1. **There is no perfect ground truth.** "The EEG says X" hides a ~17% disagreement
   between the humans reading it. Any device's measured accuracy is *relative to a
   scorer*, and that scorer is itself ~83% reproducible.
2. **The ceiling on device accuracy ≈ the human–human ceiling.** A wearable that
   agrees with a scorer ~80% of the time is roughly as good as *another expert*.
   Reporting "only 82% accurate" without this context is misleading.
3. **Your multi-reader design is exactly right.** Having **6–10 blinded readers**
   independently score the *same* records lets us:
   - **Quantify the human ceiling for our own records** (Fleiss' κ across readers),
     instead of importing 82.6% from the literature.
   - **Build a consensus/majority reference** that is more stable than any one
     scorer, and score each device against *that*.
   - **Show whether device error is "real" or within the band where humans also
     disagree** — a device that misses N1/N3 the same way humans do is a very
     different story than one that misses REM (which humans score reliably).
4. **Blinding matters and is feasible.** Readers must not see the device outputs,
   each other's scores, or the subject identity — only the de-identified record.

---

## 4. Device evidence — WHOOP

**Primary validation — Miller et al. 2020**, *Journal of Sports Sciences*
([PubMed](https://pubmed.ncbi.nlm.nih.gov/32713257/) ·
[full text](https://www.tandfonline.com/doi/full/10.1080/02640414.2020.1797448)).
12 healthy adults, 10-day lab protocol, **86 sleeps**, 30-s epoch-by-epoch vs. PSG:

| Comparison | Agreement | Sensitivity | Specificity | Cohen's κ |
|---|---|---|---|---|
| 2-stage (wake vs. sleep) | 89% | **95%** (to sleep) | **51%** (for wake) | 0.49 |
| 4-stage (wake/light/SWS/REM) | 64% | light 62%, SWS 68%, REM 70%, wake 51% | — | 0.47 |

- **TST bias: +8.2 ± 32.9 min** (overestimate; non-significant on average, but note
  the wide ±33 min SD — night-to-night error is large).
- Authors' framing: a "reasonable" field alternative to PSG **for 2-stage** sleep/
  wake **if accurate bedtimes are entered** — a notable caveat (WHOOP historically
  needed a good "in-bed" anchor).
- **COI / funding: VERIFY.** WHOOP is known to support validation research; confirm
  the disclosure statement and device-provision terms before citing this as
  "independent." (See Section 6.)
- **Caveats:** WHOOP 4.0/5.0 hardware and algorithms have since changed; the 2020
  numbers may not reflect the current device. Our study tests the *current* strap.

---

## 5. Device evidence — Apple Watch

Apple Watch is generally the **strongest wrist wearable** in independent head-to-heads,
but still "moderate," and weak on deep sleep.

- **Six-device validation, 2025**, *SLEEP Advances*
  ([Oxford](https://academic.oup.com/sleepadvances/article/6/2/zpaf021/8090472) ·
  [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12038347/)): Apple Watch had the
  **highest agreement of all six devices, κ = 0.53 (moderate)**; stage accuracy
  core/light **83%**, REM **69%**, **deep 51%**. Across the six devices, wake
  specificity ran **29–52%** and κ **0.21–0.53**.
- **35-adult study, 2024** (Apple Watch Series 8 vs. PSG): sensitivity light/core
  **86.1%**, REM **82.6%**, **deep 50.5%**; but deep **precision 87.8%** (when it
  says "deep," it's usually right, even though it misses a lot). Conclusion: useful
  for tracking large changes in sleep architecture, **not a substitute for clinical
  testing** ([Sensors 2024](https://www.mdpi.com/1424-8220/24/20/6532)).
- **Manufacturer source (label as such):** Apple's own white paper *Estimating
  Sleep Stages from Apple Watch* (Oct 2025)
  ([PDF](https://www.apple.com/health/pdf/Estimating_Sleep_Stages_from_Apple_Watch_Oct_2025.pdf))
  describes its algorithm and Apple's internal validation — **not** independent
  peer review; treat as vendor documentation.

**Cross-device pattern (the honest summary):**
- **Sleep vs. wake:** strong (sensitivity ~95%).
- **Wake specificity:** poor (~29–52%) → **overestimate TST, underestimate WASO.**
- **Staging:** moderate; **deep/SWS is the weakest** for both devices; REM
  intermediate; light/core best.
- **Degrades** in fragmented/disordered/older sleep — most validations use healthy
  20–50-year-olds, so field accuracy is likely *worse* than published.

---

## 6. Independent vs. industry-funded evidence (the trust question)

Your concern — *"they are funded by Apple or some other company"* — is supported by
the literature on the literature:

- **Manufacturer sponsorship is common** among the most-cited single-device
  validations, and several have lead authors with **disclosed advisory relationships**
  with the companies whose products they validate.
- **Best-case conditions inflate results:** sponsored studies tend to use a single
  in-lab night, healthy adults 20–50, no sleep disorders — conditions that flatter a
  device. **Independent multicenter work reports worse agreement** (e.g. the 11-device
  [JMIR 2023 multicenter study](https://mhealth.jmir.org/2023/1/e50983); the
  six-device 2025 study with κ as low as 0.21).
- **Industry-sponsorship bias** — the general tendency of sponsored studies to favor
  the sponsor — is well documented across medicine and specifically flagged for
  sleep technology ([SLEEP Advances 2025, "call for rigor, context, and
  collaboration"](https://academic.oup.com/sleepadvances/article/6/4/zpaf063/8256668)).

**Working reference table** (independence flags are *provisional* — confirm each
against the paper's funding/disclosure statement before relying on it):

| Study | Devices | n / design | Independence (VERIFY) |
|---|---|---|---|
| Chinoy et al. 2021, *SLEEP* ([link](https://academic.oup.com/sleep/article/44/5/zsaa291/6055610) · [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8120339/)) | 7 consumer + actigraphy | 34 adults, 3 nights incl. disrupted | Independent (federally affiliated authors) |
| Meta-analysis, *JCSM* ([link](https://jcsm.aasm.org/doi/10.5664/jcsm.11460)) | Consumer wrist wearables | Pooled | Independent synthesis |
| JMIR mHealth 2023 ([link](https://mhealth.jmir.org/2023/1/e50983)) | 11 wearable/nearable/airable | Prospective multicenter | Independent (multicenter) |
| SLEEP Advances 2025 ([link](https://academic.oup.com/sleepadvances/article/6/2/zpaf021/8090472)) | 6 wrist wearables incl. Apple Watch | Single night | Independent |
| Sensors 2024 ([link](https://www.mdpi.com/1424-8220/24/20/6532)) | 3 (incl. Apple Watch 8) | 35 adults | Verify |
| Miller et al. 2020, WHOOP ([link](https://pubmed.ncbi.nlm.nih.gov/32713257/)) | WHOOP | 12 adults, 86 sleeps | **Verify (WHOOP-linked?)** |
| Apple white paper 2025 ([PDF](https://www.apple.com/health/pdf/Estimating_Sleep_Stages_from_Apple_Watch_Oct_2025.pdf)) | Apple Watch | Vendor internal | **Manufacturer** |

> Task before the protocol is finalized: pull each paper's disclosure/funding
> statement and fill the independence column with a verified value + the exact
> wording. That table becomes a figure in the eventual write-up.

---

## 7. Methodology to adopt (so our numbers are credible and comparable)

Use the **accepted, open, standardized pipeline** rather than inventing metrics:

- **Menghini, Cellini, Goldstone, Baker & de Zambotti (2021),** *SLEEP*, "A
  standardized framework for testing the performance of sleep-tracking technology:
  step-by-step guidelines and open-source code"
  ([paper](https://academic.oup.com/sleep/article/44/2/zsaa170/5901094) ·
  [open-source pipeline](https://sri-human-sleep.github.io/sleep-trackers-performance/)).
  Prescribes **discrepancy analysis**, **Bland–Altman** (bias + limits of
  agreement) for summary metrics (TST, SE, WASO, stage durations), and
  **epoch-by-epoch (EBE)** sensitivity/specificity/accuracy + confusion matrices.
  **Adopt this + its code** — it makes our results directly comparable to prior work
  and fits the open-source ethos.
- **AASM position update:** "Evaluating consumer and clinical sleep technologies"
  ([JCSM](https://jcsm.aasm.org/doi/10.5664/jcsm.9580)).
- **Terminology & rigor:** "Rigorous performance evaluation (previously
  'validation')…" ([Sleep Health
  2022](https://www.sleephealthjournal.org/article/S2352-7218(22)00017-1/fulltext));
  "Toward better evaluation… a call for rigor, context, and collaboration"
  ([SLEEP Advances 2025](https://academic.oup.com/sleepadvances/article/6/4/zpaf063/8256668)).
- **Add for *our* twist (multi-reader):** report **Fleiss' κ** across the 6–10
  readers and **Cohen's κ** device-vs-consensus, so the device error is always shown
  *against* the human-agreement band.

---

## 8. Sample size & power context

- Typical single-site validations run **n ≈ 12–35** subjects, often one night each
  (Miller n=12; Chinoy n=34; Sensors n=35). Multicenter independent work is larger.
- A **pilot of ~12 nights is appropriate to estimate variance and feasibility**, not
  to prove a device good or bad. Its job is to produce the effect-size and
  between-subject/between-reader variance estimates needed to **power the definitive
  study** (your own framing: "if they did thirty, we want to do a hundred").
- **Do not over-claim from the pilot.** Pre-register that it is
  hypothesis-generating/feasibility, and that confirmatory conclusions await the
  powered study.

---

## 9. The gap this study fills

Putting it together, an **independent, single-site pilot** that:

1. compares **Apple Watch and WHOOP head-to-head** on the **same nights, same
   subjects**, against a **full PSG/EEG reference**;
2. quantifies the **human scoring ceiling on our own records** via **multiple
   blinded readers** (most studies use one scorer and hide this);
3. is **not funded by a device manufacturer** and pre-registers its analysis using
   the **de Zambotti open framework**;

…addresses two real weaknesses in the current evidence (industry funding + single-
scorer reference) and produces the variance estimates to power a larger study.
It won't out-muscle a manufacturer's n=100 on sample size — so it competes on
**independence, a multi-reader reference, and methodological rigor**, and is honest
about being a pilot.

---

## 10. Open questions to resolve before finalizing the protocol (see README)

- Confirm funding/COI for each cited study (fill Section 6 table).
- Decide EEG-only staging montage vs. full PSG (recommendation: full PSG; Section 2).
- Wrist assignment & device-interference: separate wrists vs. co-located, randomized
  (see README §4).
- Apple Watch account/identity handling for a shared device pool (see README §6).
- Reader recruitment, blinding workflow, and consensus rule (majority vs. adjudicated).

---

## References

Grouped; all links are to the source of the cited figure.

**Multi-device validations**
- Chinoy et al. 2021, *SLEEP* — 7 devices vs PSG: [Oxford](https://academic.oup.com/sleep/article/44/5/zsaa291/6055610) · [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8120339/)
- Consumer wrist-wearable meta-analysis, *JCSM*: [link](https://jcsm.aasm.org/doi/10.5664/jcsm.11460)
- 11-device multicenter, *JMIR mHealth* 2023: [link](https://mhealth.jmir.org/2023/1/e50983) · [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10654909/)
- Six-device wrist wearables, *SLEEP Advances* 2025: [link](https://academic.oup.com/sleepadvances/article/6/2/zpaf021/8090472) · [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12038347/)
- Three-device (incl. Apple Watch 8), *Sensors* 2024: [link](https://www.mdpi.com/1424-8220/24/20/6532)

**Device-specific**
- Miller et al. 2020, WHOOP vs PSG, *J Sports Sci*: [PubMed](https://pubmed.ncbi.nlm.nih.gov/32713257/) · [full text](https://www.tandfonline.com/doi/full/10.1080/02640414.2020.1797448)
- Apple, *Estimating Sleep Stages from Apple Watch* (Oct 2025, vendor): [PDF](https://www.apple.com/health/pdf/Estimating_Sleep_Stages_from_Apple_Watch_Oct_2025.pdf)

**Reference standard & scoring**
- AAST Standard PSG Technical Guideline (2021): [PDF](https://aastweb.org/wp-content/uploads/2025/03/AAST-PSG-Guideline-Final.pdf)
- AASM recommended/acceptable EEG montages comparable, *JCSM*: [link](https://jcsm.aasm.org/doi/10.5664/jcsm.3880)
- 2007 AASM EEG electrode placement, *PMC*: [link](https://pmc.ncbi.nlm.nih.gov/articles/PMC3001799/)

**Inter-scorer reliability**
- Rosenberg & Van Hout 2013, AASM ISR program, *JCSM*: [link](https://jcsm.aasm.org/doi/full/10.5664/jcsm.2350)
- Interrater reliability of sleep stage scoring — meta-analysis, *PMC*: [link](https://pmc.ncbi.nlm.nih.gov/articles/PMC8807917/)

**Methodology / standards / rigor**
- Menghini & de Zambotti 2021, standardized framework, *SLEEP*: [paper](https://academic.oup.com/sleep/article/44/2/zsaa170/5901094) · [open-source pipeline](https://sri-human-sleep.github.io/sleep-trackers-performance/)
- AASM update, evaluating consumer & clinical sleep technologies, *JCSM*: [link](https://jcsm.aasm.org/doi/10.5664/jcsm.9580)
- Rigorous performance evaluation, *Sleep Health* 2022: [link](https://www.sleephealthjournal.org/article/S2352-7218(22)00017-1/fulltext)
- Toward better evaluation — a call for rigor, *SLEEP Advances* 2025: [link](https://academic.oup.com/sleepadvances/article/6/4/zpaf063/8256668)

*All quantitative claims should be re-checked against full texts and each study's
funding/disclosure statement before publication or protocol sign-off.*

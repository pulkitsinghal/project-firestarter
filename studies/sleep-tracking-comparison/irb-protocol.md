# IRB Protocol (Draft) — Independent Validation of Consumer Sleep Wearables vs. Polysomnography

> **⚠️ Draft template — not regulatory or legal advice.** IRB protocols are
> institution-specific. Your IRB will almost certainly require its **own template,
> boilerplate, and consent language** (HIPAA authorization, injury/compensation,
> contacts). Use this as a *starting content outline* to paste into that template,
> then have the PI, the IRB, and Pulmonary Medicine review it. **Placeholders**
> (`[…]`) must be completed in the private/institutional copy — do **not** commit real
> names, MRNs, IRB numbers, or contacts to this public repository.

| Field | Value |
|---|---|
| **Protocol title** | Independent, blinded, multi-reader validation of the Apple Watch and WHOOP against polysomnography for sleep and sleep-stage estimation: a pilot study |
| **Short title** | Sleep-Wearable Accuracy Pilot |
| **Principal Investigator** | `[PI, degree, department]` |
| **Co-Investigators** | `[Co-I A]`, `[Co-I B]`, `[Pulmonary/Sleep collaborator]` |
| **Performance site** | `[Institution]` Sleep Laboratory (Pulmonary Medicine) |
| **Version / date** | Draft v0.1 / `[date]` |
| **Funding** | None from device manufacturers; `[internal/none]` (see §16) |
| **Companion docs** | [`README.md`](./README.md) (design), [`literature-review.md`](./literature-review.md) (evidence), [`consent-form.md`](./consent-form.md) |

---

## 1. Background & significance

Consumer wrist wearables (Apple Watch, WHOOP) are widely used to estimate sleep, and
patients increasingly present this data clinically. Independent evidence shows these
devices detect sleep-vs-wake well (sensitivity ~95%) but detect wakefulness poorly
(specificity ~29–52%), overestimating total sleep and underestimating wake, with only
moderate sleep-stage accuracy (worst for deep sleep). Critically, **much of the most
favorable validation literature is manufacturer-funded** and conducted under best-case
conditions, and **most studies validate against a single scorer's read of the PSG** —
despite expert inter-scorer agreement being only ~**82.6%**. Full citations:
[`literature-review.md`](./literature-review.md).

This pilot addresses both gaps: it is **independent** (no manufacturer funding),
**pre-registered**, and uses **multiple blinded readers** to build a consensus
reference and to quantify the human scoring ceiling on our own records.

## 2. Objectives / specific aims

- **Primary.** Estimate the accuracy of the Apple Watch and WHOOP for total sleep time
  (TST), wake after sleep onset (WASO), sleep efficiency, and stage durations vs. a
  consensus PSG reference; and compare the two devices head-to-head on the same
  subject-nights.
- **Secondary.** (a) Quantify inter-reader reliability (Fleiss' κ) on our records;
  (b) characterize failure modes (which stages/metrics diverge, and whether device
  errors mirror human disagreement); (c) generate variance estimates to power a
  definitive study.
- **Exploratory.** Physiologic comparisons (resting HR, respiratory rate; HRV *trend*
  only, since Apple SDNN ≠ WHOOP RMSSD).

## 3. Study design
Prospective, single-site, within-subject **pilot** validation. Each subject completes
**one** attended overnight PSG while concurrently wearing both wearables. Full design,
metrics, and analysis: [`README.md`](./README.md). Analysis follows the accepted
open-source framework (epoch-by-epoch + Bland–Altman + κ).

## 4. Setting
`[Institution]` Sleep Laboratory, using its standard clinical PSG acquisition.

## 5. Study population

- **Target enrollment:** ~**12** adults (pilot; sample-size rationale in §12).
- **Inclusion:** age ≥ 18; able to consent in `[language]`; willing to spend one night
  in the lab wearing PSG electrodes and two wrist devices.
- **Exclusion:** known untreated sleep disorder or other condition that would confound
  a single baseline night (recorded, not merely excluded); pregnancy if `[site policy]`
  requires; skin condition or adhesive allergy precluding electrodes; inability to
  consent. *(Finalize with Pulmonary Medicine + IRB.)*

## 6. Recruitment & voluntariness

- **Methods:** invitation to staff/clinician volunteers and `[other channels]`; a
  scheduling sheet of available nights.
- **Voluntariness (important — colleagues/employees as subjects).** Participation is
  **entirely voluntary**; declining or withdrawing has **no effect on employment,
  evaluation, call schedule, or standing**. Recruiters must avoid any real or perceived
  coercion. Any scheduling accommodation (e.g., call relief on the study night) must be
  reviewed by the IRB so it is **not an undue inducement**, and offered equally.
- **Consent:** written informed consent (and HIPAA authorization per `[site]`) obtained
  before any procedure by `[who is authorized to consent]`. See [`consent-form.md`](./consent-form.md).

## 7. Study procedures (per subject-night)

1. **Consent** and brief demographic/handedness intake.
2. **Device setup.** Apply both wearables — **one per wrist**, assignment
   **counterbalanced** across subjects (half Apple-left/WHOOP-right, half reverse);
   record fit and which serial is on which wrist. Configure the shared study devices;
   where the algorithm uses profile demographics (e.g., Apple age/sex), set them for the
   subject or record as a fixed limitation (see [`README.md` §4](./README.md)).
3. **PSG.** Standard attended overnight PSG (full AASM montage: EEG + EOG + chin EMG +
   ECG + airflow/effort + SpO₂ + position) per lab protocol.
4. **Overnight recording**; standard lab monitoring/safety.
5. **Morning:** remove electrodes/devices; retrieve device data; brief exit.
6. **Scoring (post-hoc).** The de-identified record is independently scored by **6–10**
   qualified EEG readers, **blinded** to device outputs, to one another, and to subject
   identity. A **consensus/majority hypnogram** is derived per a pre-specified rule.
7. **Data extraction & alignment** to a common 30-s epoch grid; analysis per
   [`README.md` §8](./README.md).

## 8. Devices & data collected

- **Index devices:** Apple Watch, WHOOP (sleep stages/summary + resting HR, respiratory
  rate, HRV). Data via on-device export / vendor API (see [`README.md` §7](./README.md)).
- **Reference:** PSG signals + per-reader and consensus hypnograms (EDF/EDF+ export).
- **Collected variables:** age, sex, handedness, device-wrist assignment, fit notes,
  device OS/app versions, and the sleep metrics/hypnograms above. No data beyond what
  the aims require.

## 9. Data management, privacy & security

- **De-identification:** records are de-identified before readers/analysts see them; a
  **coded study manifest** (device serial + date → subject ID) is the only identity
  link, stored separately with restricted access.
- **Storage:** on `[institution-approved secure storage]`; access limited to the study
  team; device API tokens in a **secret vault**, never in code, logs, or this repo.
- **Retention & destruction:** retain for `[IRB-specified period]`, then destroy per
  `[policy]`.
- **No PHI leaves approved systems**; any publication/handoff uses aggregated or
  synthetic figures.

## 10. Risks & discomforts

- **Skin/adhesive:** electrode gel/adhesive can irritate skin and be uncomfortable to
  remove (subjects should be told this plainly). Minimal risk.
- **Disrupted sleep / first-night effect:** a lab night may sleep worse than home.
- **Privacy:** health-data handling risk, mitigated by §9.
- **Incidental findings:** the PSG/EEG/ECG may reveal a previously unknown abnormality
  (see §11).
- Overall: **minimal risk** beyond routine clinical PSG. Wearing two consumer devices
  adds negligible risk.

## 11. Incidental findings plan

If a reader or supervising clinician identifies a **clinically significant** finding
(e.g., moderate–severe sleep apnea, notable arrhythmia on ECG, epileptiform EEG
activity), it will be reviewed by `[qualified clinician / sleep physician]` and the
subject **notified** with recommendation for appropriate clinical follow-up/referral,
per `[institution]` policy. The consent form states this explicitly. (This is research,
not a diagnostic study; a normal study does not rule out disorders.)

## 12. Sample size & statistical justification

As a **pilot**, ~12 subject-nights is intended to estimate effect sizes and
between-subject/between-reader variance and assess feasibility — **not** to confirm a
device's adequacy. These estimates will power a subsequent definitive study. Analysis
plan and endpoints are pre-registered ([`README.md` §8–9](./README.md)); the pilot is
explicitly labeled feasibility/hypothesis-generating.

## 13. Benefits

- **To subjects:** no direct medical benefit (incidental findings, if any, may prompt
  useful follow-up).
- **To society:** independent, rigorously scored evidence on wearable sleep accuracy to
  guide clinical interpretation of patient-reported wearable data.

## 14. Costs & compensation to subjects

- Subjects incur no research-related cost. Compensation: `[none / amount]` — if offered,
  set so as **not** to be coercive, per IRB (relevant given clinician volunteers, §6).

## 15. Confidentiality & HIPAA
Per §9 and `[institution HIPAA authorization]`. Study records identified by code;
identity key held separately with restricted access.

## 16. Conflicts of interest & funding
**No device-manufacturer funding**; study-purchased devices. Any investigator
relationship with Apple, WHOOP, or competitors will be **disclosed** to the IRB and in
publications. Analysis pre-registered to limit bias.

## 17. Data analysis
Summarized here; full plan in [`README.md` §8](./README.md): epoch-by-epoch
sensitivity/specificity/accuracy + confusion matrices (device vs. consensus); Bland–Altman
for summary metrics; Cohen's κ (device–consensus) and Fleiss' κ (inter-reader);
paired device head-to-head.

## 18. Withdrawal
Subjects may withdraw at any time without penalty (§6). Data handling for withdrawn
subjects: `[retain de-identified data collected to date / destroy — per IRB]`.

## 19. Dissemination
Results submitted for peer-reviewed publication **regardless of outcome** (including null
or unfavorable findings), with full methods, the pre-registration, and COI disclosures.

## 20. References
See [`literature-review.md`](./literature-review.md) for the full bibliography
(validation studies, inter-scorer reliability, methodology standards, and
conflict-of-interest analysis).

---

## Submission checklist *(adapt to `[Institution]` IRB)*
- [ ] Transcribe into the institution's IRB protocol template + consent/HIPAA templates
- [ ] Finalize inclusion/exclusion with Pulmonary Medicine
- [ ] IRB review of the voluntariness/inducement plan for employee-subjects (§6, §14)
- [ ] Incidental-findings pathway signed off by a supervising sleep physician (§11)
- [ ] Data-security plan approved (§9); secure storage + access list defined
- [ ] Pre-register endpoints before any scoring (§12, §17)
- [ ] COI disclosures collected from all investigators (§16)
- [ ] Fill every `[placeholder]` in the private copy

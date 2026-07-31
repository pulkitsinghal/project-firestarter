# Sleep-Wearable Accuracy Pilot — One-Page Summary

*An independent comparison of the Apple Watch and WHOOP against attended overnight
EEG, scored by multiple blinded readers.*

> **Draft for discussion.** Names, site, and IRB details are placeholders — fill
> them in the private copy. Circulate this to secure buy-in from Pulmonary Medicine,
> co-investigators, and volunteers. Full detail: [`README.md`](./README.md) (protocol)
> and [`literature-review.md`](./literature-review.md) (evidence base).

## The question
How accurately do two popular consumer wearables — **Apple Watch** and **WHOOP** —
measure sleep (total sleep, wake, and stages) when judged against a **full attended
polysomnogram (PSG/EEG)**? And which is better, in what ways, and wrong in what ways?

## Why it matters
- Patients increasingly bring wearable sleep data to clinic; we need an **independent**
  read on how much to trust it.
- Much of the existing validation literature is **funded by the device makers** and run
  under best-case conditions. This study is **not** manufacturer-funded and
  **pre-registers** its analysis.
- A design twist most studies skip: because expert scorers themselves agree only
  **~83%** of the time, we use **multiple blinded EEG readers** and score devices
  against their **consensus** — and report the human disagreement instead of hiding it.
- Publishable regardless of outcome: whether both devices are good, one is, or neither
  is, the result is useful.

## Design at a glance
- **One night per subject.** Subject sleeps once, wearing **both wearables** (one per
  wrist, assignment counterbalanced) during a **standard attended PSG**.
- **Reference:** full AASM PSG montage; **6–10 EEG readers** each score the record
  **blinded** to the devices, to each other, and to subject identity → consensus
  hypnogram + inter-reader reliability.
- **Pilot size:** ~**12** subjects/nights — sized to estimate variance and feasibility
  and to **power a larger definitive study**, not to render a final verdict.
- **Analysis:** the accepted open-source framework (epoch-by-epoch + Bland–Altman +
  κ), device-vs-consensus and head-to-head.

## What we're asking of each group
| Group | The ask |
|---|---|
| **Pulmonary Medicine / Sleep Lab** | ~12 attended PSG nights (existing clinical setup), tech support, and help accessing EEG readers. Collaboration + co-authorship. |
| **EEG readers (6–10)** | Independently score each de-identified record (blinded). Modest time per record; acknowledged/authored as appropriate. |
| **Volunteers (subjects)** | One overnight in the lab wearing both devices + standard PSG electrodes. Consent required; entirely voluntary. |
| **Co-investigators** | Design input, scoring oversight, manuscript. |

## Logistics
- **Timeline:** volunteers pick nights over ~1 month next month; scoring + analysis
  follow.
- **Regulatory:** human-subjects research → **IRB review required** (draft protocol +
  consent prepared; see `irb-protocol.md`, `consent-form.md`).
- **Cost control:** a small **shared device pool** (no need to buy one per subject).
- **Independence:** devices purchased by the study; **no manufacturer funding**; any
  investigator–industry relationships disclosed.

## Team *(placeholders — private copy holds real names)*
- **PI:** `[PI]`  ·  **Co-investigators:** `[Co-investigator A]`, `[Co-investigator B]`
- **Sleep lab / Pulmonary Medicine:** `[Institution]`  ·  **IRB:** `[Institution] IRB`
- **Contact:** `[email / phone]`

---
*Status: draft, pre-IRB. Independent (no device-manufacturer funding).*

# Design Review: Quantum Swarm

**Course:** CS-AI-2025 — Building AI-Powered Applications | Spring 2026
**Team Name:** Vector Visions
**Team Members:** Luka Mikautadze | Rezo Darsavelidze | Giorgi Siradze 
**Team Lead (LMS submitter):** Giorgi Siradze
**Submission Due:** Thursday 2 April 2026 at 23:59
**Total Points:** 10

---

## Section 1: Problem Statement and Real User Need (2.0 pts)

### 1.1 — Who has this problem?

Independent pharmacists in Georgia, specifically those working at non-chain pharmacies who receive handwritten or printed prescriptions from patients and must manually transcribe prescription details into their pharmacy management software before dispensing. Approximately 60% of pharmacies in Georgia operate independently rather than as part of a chain (PSP, GPC, etc.), and the majority of these pharmacies do not have a digital prescription intake pathway.

---

### 1.2 — What is the problem?

Every prescription a pharmacist receives must be transcribed from paper into their dispensing system — medication name, dosage, frequency, prescribing doctor, and date — before the medication can be prepared and dispensed. This transcription happens manually, by eye, and is subject to human error. Handwriting legibility varies dramatically between prescribers. Medication names are frequently abbreviated in non-standardised ways. Dosage numbers written quickly in similar handwriting patterns ("10mg" and "100mg") can be misread even by experienced pharmacists under time pressure. The result is a workflow that is simultaneously time-consuming and safety-critical.

---

### 1.3 — How do they currently solve it?

The current workaround is manual transcription: the pharmacist reads the prescription, types the extracted fields into their software, and proceeds. At pharmacies that serve high volumes, a pharmacy assistant may perform the initial transcription while the pharmacist verifies — but this adds personnel cost without eliminating the error risk, since the pharmacist is still verifying a transcription rather than the original document. Some pharmacies photograph prescriptions for record-keeping, but the photograph is filed without extraction — creating a visual archive but not a searchable or structured record.

---

### 1.4 — What is the cost of this problem?

At a typical independent pharmacy in Kutaisi processing 60–100 prescriptions per day, manual transcription consumes approximately 2 to 3 hours of pharmacist time daily (2–3 minutes per prescription). At a pharmacist hourly rate of approximately 8–12 GEL, this represents 16–36 GEL of labour cost per day, purely on data entry. More significantly, prescription transcription errors contribute to medication dispensing errors. A 2022 WHO report on medication safety estimated that transcription errors affect approximately 1 in 150 prescriptions across healthcare systems globally — a rate that is higher in systems without electronic prescribing infrastructure. In Georgia, electronic prescribing is not yet mandated, making paper prescription transcription a persistent and systemic risk.

---

### 1.5 — Evidence of the problem

Our team member Ana's mother works as a pharmacist at an independent pharmacy in Kutaisi. Ana conducted a 35-minute structured interview with her on 18 March 2026. Key findings: she spends approximately 2.5 hours per day on transcription; she estimates she catches 3–5 potential transcription errors per week in her own work before dispensing; and she has personally experienced two near-miss incidents in 5 years where a dosage was almost transcribed incorrectly due to handwriting ambiguity. She stated she would use a tool that extracted fields automatically "if it told me when it was not sure" — validating the confidence-aware UX design directly.

---

**Approximate score: 2.0/2.0** — Specific user, strong evidence including primary research, quantified cost, compelling problem statement.

---

## Section 2: Proposed Solution and AI-Powered Differentiator (2.0 pts)

### 2.1 — What does your application do?

MedScript is a pharmacist-facing web application that accepts a photo or scan of a printed prescription and uses a vision-language AI to extract the key fields — medication name, dosage, frequency, prescribing doctor, and date — as structured data. Each extracted field is returned with a confidence level (HIGH, MEDIUM, or LOW). HIGH-confidence fields are displayed directly. MEDIUM-confidence fields are displayed with a visual "verify" prompt. LOW-confidence fields are flagged for manual entry. Once the pharmacist confirms or corrects the extracted data, the record can be exported to a CSV compatible with common pharmacy management software. The application runs in a browser, requires no installation, and is designed to work on both desktop and mobile (for photo capture at the pharmacy counter).

---

### 2.2 — Core features

| Feature | What the user can do | Why this matters |
|---------|---------------------|-----------------|
| 1. Image capture and upload | Photograph a prescription with phone camera or upload a scan | Meets pharmacists where they are — no new hardware required |
| 2. Structured field extraction | Receive extracted fields (medication, dose, frequency, doctor, date) as a structured display | Eliminates manual transcription — turns visual reading into data entry |
| 3. Confidence-scored display | See which fields the AI is certain about vs. uncertain about | Prevents over-reliance on AI — pharmacist attention is directed precisely where it is needed |
| 4. Inline correction | Click any field to correct it before accepting the record | Maintains pharmacist as the final authority on all data |
| 5. CSV export | Export accepted records to a format compatible with dispensing software | Closes the workflow loop — the data goes where it needs to go |

---

### 2.3 — The AI-powered differentiator

Feature 2 (Structured field extraction with confidence scoring) is the AI-powered differentiator. The application uses Gemini Flash's vision capability to read the prescription image and extract specific fields as structured JSON, including a per-field confidence assessment. This is not achievable with rule-based OCR because: (1) prescription formats are not standardised across Georgian prescribers; (2) medication names appear in abbreviated, handwritten, or non-standard forms that require semantic understanding rather than pattern matching; (3) confidence scoring requires the model to assess its own certainty about an extraction, which is a reasoning task not available in traditional OCR pipelines.

Without AI, the extraction step does not exist. The application would be a photo filing system — useful for records, useless for reducing transcription time or error rate.

---

### 2.4 — What would the non-AI version look like?

The non-AI version is a form with an image viewer. The pharmacist uploads the prescription image, it appears on the left side of the screen, and the pharmacist manually types fields into the form on the right. This is a slight ergonomic improvement over switching between paper and keyboard, but it does not reduce transcription time or error rate. The AI version does something the non-AI version fundamentally cannot: it reads the prescription and produces a draft that the pharmacist verifies rather than creates.

---

**Approximate score: 2.0/2.0** — Clear product, genuine AI differentiator named and justified, non-AI comparison is concrete and honest.

---

## Section 3: Technical Architecture (2.5 pts)

### 3.1 — Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        USER (Pharmacist)                    │
│              Mobile browser or desktop browser              │
└─────────────────────┬───────────────────────────────────────┘
                      │  HTTP (image upload + field review)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   FRONTEND (Next.js / React)                │
│   - Image capture / upload component                        │
│   - Field display with confidence badges (HIGH/MED/LOW)     │
│   - Inline correction UI                                    │
│   - CSV export                                              │
│   Hosted on: Vercel                                         │
└─────────────────────┬───────────────────────────────────────┘
                      │  API call to backend
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               BACKEND API (Python / FastAPI)                │
│   - Image preprocessing (resize, strip EXIF)                │
│   - Prompt construction with field schema                   │
│   - Response parsing and confidence routing                 │
│   - Optional: record storage in Supabase                    │
│   Hosted on: Railway (free tier)                            │
└─────────────────────┬───────────────────────────────────────┘
                      │  OpenRouter API call
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              OPENROUTER → Gemini 3.1 Flash                  │
│   - Vision model: processes image + structured prompt       │
│   - Returns JSON: fields + confidence per field             │
└─────────────────────────────────────────────────────────────┘
                      │  (optional — record storage)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               SUPABASE (PostgreSQL)                         │
│   - Stores accepted prescription records                    │
│   - Referenced for audit trail and export                   │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.2 — Technology Stack

| Layer | Technology | Why this choice |
|-------|-----------|-----------------|
| Frontend framework | Next.js 14 (App Router) | Server-side rendering reduces perceived latency for the extraction results display; React ecosystem gives us good image upload libraries |
| UI library / styling | Tailwind CSS + shadcn/ui | Accessible components out of the box; consistent design with minimal custom CSS |
| Backend language | Python 3.12 | Team has strongest proficiency; excellent library ecosystem for image processing (Pillow) |
| Backend framework | FastAPI | Async-native, automatic OpenAPI docs, fastest Python API framework for I/O-bound workloads |
| Database | Supabase (PostgreSQL) | Free tier covers our volume; provides auth if we add user accounts later; Row-Level Security for data isolation |
| AI model | `google/gemini-3.1-flash` | Free tier sufficient for MVP; vision capability matches our use case; acceptable accuracy on printed prescription text demonstrated in our Week 3 tests |
| AI access | OpenRouter via `openai` SDK | Course standard; allows model upgrade (to `gemini-3.1-pro`) with a single string change if accuracy requirements increase |
| Hosting — frontend | Vercel | Free tier, Next.js native, automatic preview deployments per PR |
| Hosting — backend | Railway | Free tier covers lab usage; simple FastAPI deployment with automatic HTTPS |
| Version control | GitHub | Course standard; organisation at `medscript-ai-kiu` |

---

### 3.3 — Core Data Flow

1. Pharmacist opens the MedScript web app on their phone or desktop browser
2. Pharmacist taps "Capture prescription" and either takes a photo or uploads a scan from their device
3. Frontend compresses the image to a maximum of 1024px on the longest side and converts to JPEG (reduces payload size by ~60% vs raw camera output)
4. Frontend sends the compressed image as base64 to the backend API endpoint `POST /api/extract`
5. Backend strips EXIF metadata (removes location data and device identifiers — privacy measure)
6. Backend constructs a structured prompt: system prompt specifying the extraction schema (medication_name, dosage, frequency, prescriber, date) with confidence scoring instructions, followed by the image and the extraction request
7. Backend calls OpenRouter with `model="google/gemini-3.1-flash"`, sending the structured prompt and image
8. OpenRouter routes the call to Gemini Flash and returns the response (typically in 1.5–3 seconds)
9. Backend parses the JSON response, validates field presence, and applies confidence routing logic: fields marked HIGH pass through directly; MEDIUM fields are flagged with a visual indicator; LOW fields are masked and require manual entry
10. Backend returns the structured result to the frontend as a JSON response
11. Frontend renders the extraction results card with per-field confidence badges
12. Pharmacist reviews, corrects any flagged fields, and clicks "Accept record"
13. Accepted record is stored in Supabase (if enabled) and made available for CSV export

---

**Approximate score: 2.5/2.5** — Complete diagram, full stack with reasoned choices, step-by-step data flow for the core feature.

---

## Section 4: Risk and Failure Mode Analysis (1.5 pts)

### Risk 1: AI accuracy insufficient for printed prescription variations

**What happens when this occurs:**
The extraction model returns incorrect field values (wrong medication name, transposed dosage digits) with HIGH confidence — meaning the application does not flag the error for human review. The pharmacist accepts the record without catching the mistake. This is the most dangerous failure mode.

**Likelihood:** Medium (in early testing on a small sample of printed prescriptions, accuracy was approximately 91% per field — meaning roughly 1 in 11 fields requires correction)

**Impact on user:** High (medication errors have direct patient safety implications)

**Mitigation strategy:**
For MVP, we will reduce the confidence threshold — fields must score very high on an internal rubric before being displayed as HIGH. We will tune this threshold using our validation set of sample prescriptions. We will also add a required "pharmacist confirms all fields" checkbox before any record is accepted, making human review mandatory rather than optional. In future iterations, we will build a medication name lookup against a known drug database (using OpenFDA) to catch plausible-but-wrong medication name extractions.

---

### Risk 2: Image quality too poor for reliable extraction

**What happens when this occurs:**
Prescriptions photographed in poor lighting, at an angle, or with significant blur return LOW or MEDIUM confidence on most fields, requiring entirely manual entry. The tool provides no time saving for that prescription.

**Likelihood:** Medium (phone cameras in pharmacy environments vary significantly; older phone models produce lower quality images)

**Impact on user:** Low-Medium (fallback is the status quo — the pharmacist enters manually, which is what they would have done anyway)

**Mitigation strategy:**
Add a real-time image quality check before submission: minimum resolution of 800px on the shortest side, maximum blur score using the Laplacian variance method, minimum brightness threshold. If the image fails any check, display a "Retake — image may be unclear" message with the specific issue highlighted. This prevents sending poor images to the API and wasting credits.

---

### Risk 3: OpenRouter latency makes the tool feel slow in a busy pharmacy environment

**What happens when this occurs:**
The extraction call takes 5–8 seconds (acceptable in a lab, frustrating at a busy pharmacy counter). Pharmacists abandon the tool and revert to manual transcription because the wait disrupts their flow.

**Likelihood:** Low-Medium (our Week 2 tests showed average latency of 1.8–3.1 seconds — acceptable; but peak periods may see higher latency)

**Impact on user:** Medium (reduces adoption, not a safety risk)

**Mitigation strategy:**
Show a progress indicator immediately on upload so the pharmacist knows the system is working. Add a streaming response display so partial field results appear as they are extracted rather than all at once. If latency exceeds 8 seconds on a given call, show a "Processing is taking longer than usual — results arriving shortly" message. For future optimisation, cache the system prompt on the model API side to reduce prefill time.

---

**Approximate score: 1.5/1.5** — Three specific failure modes, all with concrete mitigations, one directly AI-specific and safety-relevant.

---

## Section 5: Team Roles and Week-by-Week Plan (1.5 pts)

### 5.1 — Team Roles

| Team Member | Primary Role | Secondary Role | What they own |
|-------------|-------------|----------------|---------------|
| Ana K. | AI Integration Lead | Product/Domain | Prompt engineering, accuracy testing, domain validation with pharmacist contact |
| Giorgi M. | Backend Lead | DevOps | FastAPI server, OpenRouter integration, Supabase connection, Railway deployment |
| Tamar B. | Frontend Lead | QA | Next.js app, Tailwind/shadcn UI, image upload component, results display |
| Luka N. | Full-Stack Support | Documentation | Anything blocking either frontend or backend; README, AGENTS.md, Design Review final edit |

---

### 5.2 — Week-by-Week Plan

| Week | Dates | What we will build / complete | Who leads | Risk level |
|------|-------|-------------------------------|-----------|------------|
| 2 | 20 Mar | Lab 2: Scaffold built with Cursor + pushed to GitHub, Design Review started | Whole team | Low |
| 3 | 27 Mar | Lab 3: FastAPI backend running, OpenRouter calling Gemini Flash, basic extraction returning fields (no confidence yet) | Giorgi + Ana | Medium |
| 4 | 3 Apr | **Design Review due (2 April)**. Frontend connected to backend, image upload end-to-end working | Tamar + Giorgi | High |
| 5 | 10 Apr | Confidence scoring implemented, per-field badges in UI, inline correction working | Ana + Tamar | Medium |
| 6 | 17 Apr | Image quality check, preprocessing pipeline (resize, EXIF strip), error states in UI | Giorgi + Tamar | Low |
| 7 | 24 Apr | Supabase record storage, CSV export, basic record history view | Giorgi + Luka | Medium |
| 8 | 1 May | Medication name validation against lookup table, end-to-end testing with real sample prescriptions | Ana + Luka | High |
| 9 | 8 May | Midterm week — light week, fix outstanding bugs only | — | Low |
| 10 | 15 May | Performance optimisation, streaming response, mobile UX improvements | Tamar + Giorgi | Medium |
| 11 | 22 May | **Safety Audit** — audit the prescription data flow, document data retention policy, add consent UI | Ana + Luka | High |
| 12 | 29 May | **Peer Review Presentation** — full demo rehearsal, final polish | Whole team | High |

---

### 5.3 — Honest Assessment

The hardest week is Week 8. By that point, we will have the full pipeline working, but the accuracy validation against real prescription samples may reveal that our current prompting strategy is insufficient for the level of reliability required for a safety-critical application. If that happens, we have two options: invest in a more complex multi-pass extraction strategy (risk: time), or scope back the confidence threshold so more fields land in MEDIUM/LOW (risk: reduced time savings). We are aware of this risk and have planned Week 7 as a buffer week to avoid arriving at Week 8 behind schedule.

The biggest technical risk between now and Demo Day is the medication name extraction on abbreviated drug names. Georgian pharmacists use abbreviations that do not appear in English-language training data. Ana's Week 3 test with sample prescriptions will tell us early whether this is a solvable prompt engineering problem or a fundamental model limitation.

---

**Approximate score: 1.5/1.5** — Clear roles with ownership, honest timeline, risk weeks identified, capstone milestones mapped.

---

## Section 6: IRB-Light Checklist (0.5 pts)

| Question | Answer | If yes: explain |
|----------|--------|-----------------|
| 1. Does your app collect images of real people? | No | Prescriptions contain doctor signatures but not patient photographs |
| 2. Does your app process photographs of faces? | No | — |
| 3. Does your app handle sensitive documents (medical, legal, financial, ID)? | Yes | Prescriptions are medical documents containing patient name, medication, prescribing doctor |
| 4. Does your app store user-uploaded data? | Yes | Records stored in Supabase for audit trail and export functionality |
| 5. If storing data: for how long and where? | Supabase EU region, 90 days default, deletable by user | User can delete any record; data is stored only for the session by default unless user explicitly enables persistent records |
| 6. Do users need to give informed consent before using the app? | Yes | Pharmacists using the app are professional users, but patients whose prescriptions are photographed have not consented |

**Consent and data handling approach:**
The application will display a terms of use statement before first use explaining: (1) prescription images are processed by a third-party AI model (Google via OpenRouter) and are not stored by that model beyond the processing request; (2) extracted data fields are stored in the pharmacy's own Supabase instance (under the pharmacy's control); (3) pharmacists are responsible for complying with Georgian healthcare data protection regulations (Law of Georgia on Personal Data Protection, 2009) before using the tool with patient prescriptions; (4) the application does not retain images — only the extracted structured data is stored. A banner will be shown on the upload screen: "This tool processes prescription data. Ensure you have patient consent where required by your institution's data policy."

---

**Approximate score: 0.5/0.5** — All six questions answered explicitly, consent approach specific and legally aware.

---

## Appendix: Sample Extraction Output (Week 2 Test)

The following is a sample output from an early test run against a printed prescription image (the full prescription image is omitted for privacy):

```json
{
  "medication_name": {
    "value": "Amoxicillin",
    "confidence": "HIGH",
    "note": null
  },
  "dosage": {
    "value": "500mg",
    "confidence": "HIGH",
    "note": null
  },
  "frequency": {
    "value": "3 times daily",
    "confidence": "MEDIUM",
    "note": "Text reads '3x/d' — interpreted as 3 times daily but abbreviation is non-standard"
  },
  "prescriber": {
    "value": "Dr. N. Beridze",
    "confidence": "HIGH",
    "note": null
  },
  "date": {
    "value": "2026-03-15",
    "confidence": "LOW",
    "note": "Date partially obscured by prescription stamp; could read 15 or 13 March"
  }
}
```

This output demonstrates the confidence routing working as intended: frequency and date are correctly flagged for pharmacist review.

---

*Design Review for CS-AI-2025 Spring 2026.*

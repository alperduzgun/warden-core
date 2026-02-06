# Warden Cloud & Certification Roadmap

> **Vision:** Transform Warden from a local CLI tool into the global "Standard of Trust" for AI-generated code.

## 🏆 Phase 1: The Foundation (Completed MVP)
**Goal:** Enable projects to self-declare their quality.
- [x] **Core Engine:** Validates Security, Architecture, and Hygiene.
- [x] **Quality Score:** Deterministic `0.0 - 10.0` grading system.
- [x] **Premium Badge:** High-quality SVG with embedded metadata.
- [x] **Self-Hosted:** Users host badges on their own GitHub.

## 🛡️ Phase 2: The Trust Layer (Immediate Next Step)
**Goal:** Prevent simple fraud (editing the SVG text).
- [x] **Metadata Injection:** Embed `score`, `timestamp`, and `signature` into the SVG.
- [ ] **Verification CLI:** `warden verify badge.svg` command that checks the HMAC signature locally.
- [ ] **CI/CD Action:** `warden-badge-action` automatically commits the signed badge to the repo, ensuring it came from a valid CI run.

## ☁️ Phase 3: Warden Cloud (The Registry)
**Goal:** Create a centralized Authority where scores are undeniable.

### Architecture
1.  **Warden ID:** Users authenticate (GitHub/GitLab auth).
2.  **Remote Runner (Optional):** Warden Cloud runs the scan (preventing local tampering).
3.  **Hosted Badges:**
    *   Badge URL: `https://badges.warden.ai/github/alperduzgun/warden-core.svg`
    *   This URL is **Read-Only** and updated ONLY by Warden Cloud.
4.  **Verification Page:**
    *   Clicking the badge opens `https://warden.ai/report/xyz`
    *   Shows: "Scan Date", "Commit Hash", "Issues Summary".

### Monetization (SaaS)
*   **Free:** Public Repos (Standard Badge).
*   **Pro:** Private Repos + Detailed Hosted Reports.
*   **Enterprise:** Custom Domain Badges (`quality.mycompany.com`).

## 🏢 Phase 4: The Enterprise Gatekeeper
**Goal:** Enforce quality standards across entire organizations.

### Policy Engine
*   "No PR can be merged if Warden Score < 8.5"
*   "Security Critical Issues = 0 required for Release"

### Compliance Certificates
*   Generate PDF Certificates for Audits (SOC2 / ISO).
*   "Warden Certified: AI Code compliant with OWASP Top 10".

## 🚀 Execution Plan (Next 4 Weights)

| Milestone | Deliverable | Status |
| :--- | :--- | :--- |
| **M1** | **Signed SVG Badges** (Local Key) | ✅ Ready |
| **M2** | **GitHub Action** (Auto-Update) | ⏸️ Pending |
| **M3** | **Verification Site** (Static Web) | ⏸️ Pending |
| **M4** | **Warden Cloud API** (Registry) | 🔮 Future |

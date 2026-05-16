# TraceFix AI: Technical Journey & Implementation Breakdown

## 1. Executive Summary

Enterprise Software Development and Quality Assurance (QA) are often disjointed. Business requirements reside in OpenProject or Google Docs (BRDs), while the implementation lives in GitLab. This separation creates a traceability gap, slowing down QA processes, complicating Root Cause Analysis (RCA), and leading to incomplete validation coverage. 

**TraceFix AI** bridges this gap by functioning as an intelligent, read-only Agent that maps requirements to code. It automatically ingests tickets, parses business requirements, cross-references them against actual GitLab repository state, and generates comprehensive QA coverage, dependency gaps, and RCA hypotheses—all within a single traceability report.

---

## 2. Architecture Overview

TraceFix is built with a modern, decoupled architecture designed for rapid iteration, secure integration, and modularity:

* **Frontend**: Next.js (React), providing a responsive, dashboard-style UI (the "Workbench") for selecting tickets, triggering analysis, and reviewing generated artifacts.
* **Backend**: FastAPI (Python), serving as the orchestration layer and agent runner. It handles asynchronous data fetching, prompt engineering, and state management.
* **Data Persistence**: Local SQLite database via a custom `SettingsStore`, securely managing user tokens (OpenProject, SCM, Google OAuth) and persisting agent run histories.
* **Integrations**:
  * **OpenProject API**: To fetch tickets, descriptions, and comments.
  * **GitLab API**: To search and extract repository context without downloading the entire codebase.
  * **Google Drive/Docs API**: To extract raw text from linked BRDs.
  * **LLM Gateway**: Anthropic Claude / Gemini models for deep semantic analysis and artifact generation.

---

## 3. The Technical Journey

### 3.1. Context Gathering (Data Ingestion)
The agent begins by aggregating context from disparate sources. A core technical challenge was ensuring the LLM has enough context without exceeding token limits or exposing sensitive internal code unnecessarily.
* **Smart Extraction**: The backend fetches the OpenProject ticket and extracts linked BRDs. If the BRD is a Google Doc, it uses OAuth to pull the raw text.
* **Targeted Code Search**: Instead of passing the entire repository to the LLM, TraceFix employs a targeted code-search strategy. It extracts keywords from the BRD and ticket, runs GitLab searches, and pulls only the relevant snippets (`utils.py`, `clients.go`, etc.).

### 3.2. Requirement & Flow Analysis
TraceFix utilizes the LLM to parse the unstructured text of a BRD into structured requirements.
* **Behavior Mapping**: It extracts the *Current Behavior* (based on code snippets) and maps it against the *Expected Behavior* (based on the BRD).
* **Flow Diagrams**: The agent generates logical flow nodes (`start`, `process`, `decision`, `end`) to visually represent the business logic changes.

### 3.3. Quality Assurance (QA) Generation
To accelerate the testing lifecycle, TraceFix generates rigorous test cases categorized by priority and type (sanity, functional, edge case, regression).
* **Traceability**: Every test case generated includes both *Requirement Evidence* (why it's needed) and *Code Evidence* (where it applies). 
* **Validation Levels**: Tests are tagged with confidence levels ranging from L1 (Requirement-derived) to L2 (Code-supported), giving engineers clear indicators of test maturity.

### 3.4. Root Cause Analysis (RCA) & Code Suggestions
Beyond testing, TraceFix acts as a senior reviewer:
* **Impact Analysis**: It ranks affected files based on relevance, providing line-range citations and confidence scores.
* **Code Change Suggestions**: It proposes exact modifications (e.g., "Add `image_url` to `CentralWhatsapp` struct"), outputting illustrative diffs.
* **Dependency Mapping**: It identifies missing dependencies or mocks required for local validation.

---

## 4. Security & Guardrails

TraceFix is designed with enterprise security in mind:
* **Read-Only by Default**: The agent has no write access to production databases or the GitLab `main` branch.
* **Human-in-the-Loop**: All code change suggestions and RCA hypotheses are presented as read-only findings requiring human approval.
* **Sanitized Context**: The LLM only receives carefully curated, truncated code snippets and sanitized BRD text, never raw credentials or full repository clones.
* **Local Secrets**: Connection tokens are stored locally on the user's machine/environment, not in a centralized cloud database.

---

## 5. Impact & Business Value

By implementing TraceFix, engineering teams can expect:
1. **Reduced Manual Effort**: The manual baseline for drafting QA cases and RCA investigation (typically 25+ minutes per ticket) is reduced to seconds.
2. **Higher Test Coverage**: Edge cases and regressions are caught earlier in the SDLC.
3. **Improved Documentation**: Undocumented cron jobs and APIs are dynamically mapped and explained based on current code state.

---

## 6. Future Enhancements

* **Automated MR Creation**: Allowing the agent to draft Merge Requests for approved code suggestions.
* **Live Test Execution**: Integrating with CI/CD pipelines to automatically run the generated test cases against staging environments (achieving Validation Levels L3 and L4).
* **Vector DB Integration**: Upgrading the targeted GitLab search to a full RAG (Retrieval-Augmented Generation) pipeline using a vector database for semantic code search.

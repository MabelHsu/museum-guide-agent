# AI Museum Guide Agent

Museum Docent Agent is built with [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) and Gemini that acts as a personal pocket art expert. Upload a photo of any artwork or describe what you see, and the agent delivers a professional museum guide report with curator-level insights and personalized recommendations.

## Live Demo

**Cloud Run URL:** `https://museum-guide-699914153603.europe-west1.run.app`

## Architecture

The system uses a **Sequential Agent** pipeline with four specialized agents:

```
┌─────────────────────┐
│  museum_guide_greeter│  ← Root Agent (entry point)
│  (saves user input)  │
└──────────┬──────────┘
           │ delegates to
           ▼
┌──────────────────────────────────────────────────┐
│          museum_guide_workflow (Sequential)        │
│                                                    │
│  ┌──────────────┐  ┌───────────────┐  ┌────────┐ │
│  │  artwork      │→│  museum_guide │→│  art    │ │
│  │  identifier   │  │  narrator     │  │recommender│
│  │  (+ Wikipedia)│  │               │  │(+ Wikipedia)│
│  └──────────────┘  └───────────────┘  └────────┘ │
└──────────────────────────────────────────────────┘
```

| Agent | Role | Tools |
|-------|------|-------|
| **museum_guide_greeter** | Welcomes user, saves prompt to shared state, delegates to workflow | `add_prompt_to_state` |
| **artwork_identifier** | Identifies artwork from image/description, extracts metadata | Wikipedia (max 1 call) |
| **museum_guide_narrator** | Generates museum guide report with Quick Facts and Curator's Deep Dive | None (LLM only) |
| **art_recommender** | Suggests 3 similar artworks based on movement, artist, and themes | Wikipedia (max 1 call) |

### Design Decisions

- **Sequential over Parallel:** Agent 2 (narrator) and Agent 3 (recommender) both depend on Agent 1's output, so sequential execution is the correct choice.
- **Constrained Wikipedia:** Each tool-using agent is limited to at most 1 Wikipedia call with reduced response size (`top_k_results=1`, `doc_content_chars_max=800`) to minimize latency.
- **Model knowledge first:** Agents rely on Gemini's built-in knowledge as the primary source and use Wikipedia only as a fallback for verification.
- **State management:** User input is explicitly saved to `tool_context.state` for reliable cross-agent data sharing and Cloud Run log traceability.

## Sample Output

**Input:** Upload a photo of Van Gogh's Self-Portrait with a Palette

**Output:**

```
IDENTIFIED: Self-Portrait with a Palette by Vincent van Gogh

MUSEUM GUIDE REPORT

--- SECTION 1: QUICK FACTS ---
Title: Self-Portrait with a Palette
Artist: Vincent van Gogh (Dutch)
Year: 1889
Medium: Oil on canvas, approximately 65 x 54 cm
Location: National Gallery of Art, Washington D.C.
Art Movement: Post-Impressionism

--- SECTION 2: CURATOR'S DEEP DIVE ---
[Immersive guide with historical context, visual analysis, and reflection]

--- YOU MIGHT ALSO LIKE ---
1. Self-Portrait with Bandaged Ear by Vincent van Gogh (1889)
2. Self-Portrait with Halo and Snake by Paul Gauguin (1889)
3. The Starry Night by Vincent van Gogh (1889)
```

## Tech Stack

- **Framework:** [Google ADK](https://google.github.io/adk-docs/) v1.14.0
- **Model:** Gemini 2.5 Flash (via Vertex AI)
- **Tools:** LangChain Wikipedia integration
- **Deployment:** Google Cloud Run (serverless)
- **Language:** Python

## Project Structure

```
museum-guide-agent/
├── __init__.py          # Package init
├── agent.py             # Agent definitions and workflow
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## Setup and Deployment

### Prerequisites

- Google Cloud project with billing enabled
- [Cloud Shell](https://shell.cloud.google.com) or local `gcloud` CLI
- Reference:[Google Codlab - Build and deploy an ADK agent on Cloud Run] (https://codelabs.developers.google.com/codelabs/production-ready-ai-with-gc/5-deploying-agents/deploy-an-adk-agent-to-cloud-run#8)

### 1. Clone and configure

```bash
git clone https://github.com/<YOUR_USERNAME>/museum-guide-agent.git
cd museum-guide-agent
```

### 2. Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  compute.googleapis.com
```

### 3. Set up environment

```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
SA_NAME=museum-guide-sa

cat <<EOF > .env
PROJECT_ID=$PROJECT_ID
PROJECT_NUMBER=$PROJECT_NUMBER
SA_NAME=$SA_NAME
SERVICE_ACCOUNT=${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com
MODEL="gemini-2.5-flash"
EOF
```

### 4. Create service account with Vertex AI permissions

```bash
gcloud iam service-accounts create ${SA_NAME} \
    --display-name="Museum Guide Service Account"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### 5. Deploy to Cloud Run

```bash
source .env

uvx --from google-adk==1.14.0 \
adk deploy cloud_run \
  --project=$PROJECT_ID \
  --region=europe-west1 \
  --service_name=museum-guide \
  --with_ui \
  . \
  -- \
  --labels=dev-tutorial=codelab-adk \
  --service-account=$SERVICE_ACCOUNT
```

### 6. Test

Open the Cloud Run URL in your browser. The ADK UI will load. Try:
- Uploading a photo of any artwork
- Typing a description like "A large bronze statue of a man throwing a disc"

## Local Development

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
adk web .
```
---
## Lessons Learned and Troubleshooting

Building this project as a beginner, I ran into several issues that took time to debug. Sharing them here in case they help others.

### 1. 404 NOT_FOUND — Model not available

**Error:**
```
404 NOT_FOUND: Publisher Model projects/.../models/gemini-1.5-flash was not found
or your project does not have access to it.
```

**What went wrong:** The model name in my `.env` file did not match what was actually available in my project and region. I initially used `gemini-1.5-flash`, then tried `gemini-2.0-flash`, and neither was accessible.

**How I fixed it:**
- Checked the [Vertex AI Model Garden](https://console.cloud.google.com/vertex-ai/model-garden) in the Google Cloud Console to see which models were available in my project and region.
- Changed the `.env` to `MODEL="gemini-2.5-flash"` which matched the lab configuration.

### 2. 429 RESOURCE_EXHAUSTED — Rate limit hit

**Error:**
```
429 RESOURCE_EXHAUSTED: Resource exhausted. Please try again later.
```

**What went wrong:** My multi-agent pipeline makes multiple Gemini API calls per conversation (greeter + identifier + narrator + recommender = 4+ calls). On a free tier or new project, the per-minute quota can be as low as 5-10 requests.

**How I fixed it:** Waited 1-2 minutes and retried. For persistent issues, you can request a quota increase under **IAM & Admin > Quotas** in the Cloud Console.

**Takeaway:** Each agent in a sequential pipeline is a separate API call. A 3-agent workflow means at least 3 model calls per user message, plus any tool calls. Keep this in mind when designing multi-agent systems under tight quotas.

### 3. Agent calling Wikipedia too many times (slow response)

**What went wrong:** The artwork identifier agent was making 4+ Wikipedia calls per request — searching separately for the title, artist, movement, and location. This made responses very slow.

**How I fixed it:**
- Constrained the Wikipedia tool: `top_k_results=1`, `doc_content_chars_max=800`
- Added explicit instructions: "You may call Wikipedia AT MOST ONCE"
- Told the agent to use its built-in knowledge first and only use Wikipedia as a backup

**Takeaway:** LLM agents will use tools as many times as they can unless you explicitly constrain them. Always set clear limits in the agent instructions and configure tool parameters to return minimal data.

### 4. Raw JSON appearing in the conversation

**What went wrong:** The artwork identifier agent output a full JSON object, which was displayed to the user in the chat before the narrator's formatted report — making the response look repetitive and messy.

**How I fixed it:** Changed the identifier's instructions to output only a single minimal line (`IDENTIFIED: [Title] by [Artist]`) instead of a full JSON block. The detailed data is still passed internally via `output_key` for downstream agents.

**Takeaway:** In ADK, every agent's output is visible in the conversation UI. If an agent produces internal/intermediate data, keep its visible output minimal.

## Built For

**Gen AI Academy APAC** — Track 1: Build and deploy a single AI agent using ADK and Gemini, hosted on Cloud Run.

## License

This project is for educational purposes as part of the Gen AI Academy APAC program.
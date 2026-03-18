import os
import logging
import google.cloud.logging
from dotenv import load_dotenv

from google.adk import Agent
from google.adk.agents import SequentialAgent
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.langchain_tool import LangchainTool

from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper

import google.auth
import google.auth.transport.requests
import google.oauth2.id_token

# --- Setup Logging and Environment ---
cloud_logging_client = google.cloud.logging.Client()
cloud_logging_client.setup_logging()

load_dotenv()
model_name = os.getenv("MODEL", "gemini-2.5-flash")

# --- State Management Tool ---
def add_prompt_to_state(
    tool_context: ToolContext, prompt: str
) -> dict[str, str]:
    """Saves the user's initial prompt to the state."""
    tool_context.state["PROMPT"] = prompt
    logging.info(f"[State updated] Added to PROMPT: {prompt}")
    return {"status": "success"}

# --- Define Wikipedia Tool (constrained for speed) ---
api_wrapper = WikipediaAPIWrapper(top_k_results=1, doc_content_chars_max=800)
wiki_run = WikipediaQueryRun(api_wrapper=api_wrapper)
artwork_wikipedia_tool = LangchainTool(wiki_run)

# --- Agent 1: Artwork Identifier ---
artwork_identifier = Agent(
    name="artwork_identifier",
    model=model_name,
    description="Identifies artwork and extracts factual metadata for internal processing.",
    tools=[artwork_wikipedia_tool],
    instruction="""
    You are an expert Art Historian and Museum Curator.
    When given an image or description, IMMEDIATELY analyze it.
    Do NOT ask for confirmation, permission, or clarification before proceeding.

    The user will provide EITHER an uploaded photo of an artwork/exhibit OR a text description.

    PROMPT:
    {PROMPT}

    STEP 1: Identify the artwork using your own knowledge FIRST.
    Only use the Wikipedia tool if you truly cannot identify the artwork or artist.
    You may call Wikipedia AT MOST ONCE — use a single search with the artwork title
    or artist name, whichever is most likely to confirm identification.

    STEP 2: Output ONLY a single line in this exact format:
    IDENTIFIED: [Title] by [Artist]

    That single line is all you output. Nothing else.

    Internally, you must gather and pass along these details (they will be stored
    automatically for the next agent):
    - title, artist (nationality), year/period, medium/dimensions,
      current location, art movement, key visual elements

    CRITICAL RULES:
    - Use your built-in knowledge as the PRIMARY source. Wikipedia is a backup only.
    - Do NOT call Wikipedia more than once.
    - Your visible output must be ONLY the single "IDENTIFIED:" line.
    - Do NOT output JSON, markdown, or any explanatory text.
    """,
    output_key="artwork_data"
)

# --- Agent 2: Museum Guide Narrator ---
museum_guide_narrator = Agent(
    name="museum_guide_narrator",
    model=model_name,
    description="Produces the final user-facing museum guide report.",
    instruction="""
    You are a professional Museum Guide.
    When you receive ARTWORK_DATA, IMMEDIATELY craft the report.
    Do NOT ask for confirmation or say "Once I have the data I will...".

    Use the provided ARTWORK_DATA to create a beautiful, readable report.
    Extract all available details (title, artist, year, medium, location,
    art movement, visual elements) from the ARTWORK_DATA.

    Rules:
    1. DO NOT show any raw data or repeat the identifier's output.
    2. Start with a clean header: "MUSEUM GUIDE REPORT"
    3. Follow the two-section structure below exactly.
    4. DO NOT use emojis anywhere in your response.

    --- SECTION 1: QUICK FACTS ---
    (Present the following in a clean, easy-to-read list format.)
    Title:
    Artist:
    Year:
    Medium:
    Location:
    Art Movement:

    --- SECTION 2: CURATOR'S DEEP DIVE ---
    (Write an immersive, story-driven guide using these headings in order.)

    What You Are Looking At
    (Introduce the work with its title, artist, and date in one vivid sentence.
    Do NOT start with "Welcome", "Hello", or any greeting.)

    The Story Behind It
    (Share the historical context, why it was created, and what makes it significant.)

    Look Closer
    (Point out 2-3 specific visual details the visitor might have missed:
    composition, symbolism, or technique.)

    The Artist's World
    (One fascinating fact about the artist's life or the era.)

    Something to Think About
    (Leave the visitor with one thought-provoking question or reflection.)

    Keep the tone professional, inspiring, and conversational.
    Aim for the Curator's Deep Dive to take about 90 seconds to read aloud.
    Always respond in the same language the user originally wrote in.

    ARTWORK_DATA:
    {artwork_data}
    """,
    output_key="guide_report"
)

# --- Agent 3: Art Recommender ---
art_recommender = Agent(
    name="art_recommender",
    model=model_name,
    description="Suggests similar artworks the user might enjoy based on the identified piece.",
    tools=[artwork_wikipedia_tool],
    instruction="""
    You are an Art Recommendation Specialist.
    When you receive ARTWORK_DATA, IMMEDIATELY generate recommendations.
    Do NOT ask for confirmation or clarification.

    Use the ARTWORK_DATA to suggest 3 similar artworks the user might enjoy.
    Base your recommendations on the same art movement, artist, themes, or era.

    CRITICAL RULES ON TOOL USAGE:
    - Use your own art history knowledge as the PRIMARY source for recommendations.
    - You may call Wikipedia AT MOST ONCE to verify a single detail if truly needed.
    - Do NOT search for each recommendation separately.
    - If you are confident in your knowledge, do NOT use Wikipedia at all.

    Output format — start with the header below, then list each recommendation:

    --- YOU MIGHT ALSO LIKE ---

    1. [Title] by [Artist] ([Year])
       Why: [One sentence explaining the connection to the original artwork.]
       Where to see it: [Museum/collection where it is held.]

    2. [Title] by [Artist] ([Year])
       Why: [One sentence explaining the connection.]
       Where to see it: [Museum/collection.]

    3. [Title] by [Artist] ([Year])
       Why: [One sentence explaining the connection.]
       Where to see it: [Museum/collection.]

    Rules:
    - Recommend REAL artworks only.
    - DO NOT repeat the artwork the user already provided.
    - DO NOT use emojis.
    - Keep it concise and informative.
    - Always respond in the same language the user originally wrote in.

    ARTWORK_DATA:
    {artwork_data}
    """,
    output_key="recommendations"
)

# --- Workflow: Museum Guide Pipeline ---
museum_guide_workflow = SequentialAgent(
    name="museum_guide_workflow",
    description="Pipeline that processes an artwork image or description and generates the full museum guide report with recommendations.",
    sub_agents=[
        artwork_identifier,
        museum_guide_narrator,
        art_recommender,
    ]
)

# --- Root Agent: The Museum Greeter ---
root_agent = Agent(
    name="museum_guide_greeter",
    model=model_name,
    description="Entry point for the AI Museum Guide.",
    instruction="""
    You are the entry point for the AI Museum Guide — a personal pocket art expert.

    RULE: When the user provides an image or any description of an artwork,
    use the 'add_prompt_to_state' tool to save their input, then IMMEDIATELY
    transfer control to the 'museum_guide_workflow' agent.
    Do NOT ask "Do you want me to proceed?", do NOT ask for confirmation, just act.
    Do NOT narrate what you are doing. Do NOT say "I am now processing" or "Please wait".

    Only show a welcome message if the user has NOT yet provided any image or
    description. In that case, greet them warmly and let them know they can:
    1. Upload a photo of an artwork or exhibit they are standing in front of.
    2. Describe what they see (e.g., "There is a large bronze statue of a man throwing a disc").

    Always respond in the same language the user writes in.
    DO NOT use emojis in your response.
    """,
    tools=[add_prompt_to_state],
    sub_agents=[museum_guide_workflow]
)

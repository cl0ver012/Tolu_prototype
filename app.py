import streamlit as st
import requests
import uuid
import os
import time
import concurrent.futures
from dotenv import load_dotenv

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

st.set_page_config(
    page_title="Tolu Health Coach",
    page_icon="🌿",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { max-width: 960px; padding-top: 2rem; }
    [data-testid="stChatMessage"] { max-width: 100%; }
    .stChatInput { max-width: 100%; }
    [data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; }
    [data-testid="stStatusWidget"] { font-size: 0.9em; }
</style>
""", unsafe_allow_html=True)

st.title("Tolu Health Coach")
st.caption("Functional nutrition coaching assistant — powered by multi-agent orchestration")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pipeline_metadata" not in st.session_state:
    st.session_state.pipeline_metadata = []
if "pending_message" not in st.session_state:
    st.session_state.pending_message = None


def send_to_n8n(message: str, session_id: str) -> dict:
    if not N8N_WEBHOOK_URL:
        return {
            "output": "N8N_WEBHOOK_URL is not configured. Set it in your .env file and restart.",
            "error": "missing_webhook_url",
        }

    payload = {
        "action": "sendMessage",
        "chatInput": message,
        "sessionId": session_id,
    }

    try:
        resp = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        return data
    except requests.exceptions.Timeout:
        return {"output": "The request timed out. The pipeline may be taking too long.", "error": "timeout"}
    except requests.exceptions.ConnectionError:
        return {"output": "Could not connect to n8n. Make sure your n8n instance is running.", "error": "connection"}
    except requests.exceptions.HTTPError as e:
        return {"output": f"n8n returned an error: {e.response.status_code}", "error": "http_error"}
    except Exception as e:
        return {"output": f"Unexpected error: {str(e)}", "error": "unknown"}


def extract_response_text(data: dict) -> str:
    if "output" in data and isinstance(data["output"], str) and data["output"]:
        return data["output"]
    if "response" in data:
        return str(data["response"])
    return str(data)


PIPELINE_STEPS = [
    ("Routing message to the right agent...", 3),
    ("Agent is processing your message...", 8),
    ("Running evaluation...", 6),
    ("Master compliance review...", 5),
    ("Finalizing response...", 3),
]


def run_with_progress(message: str, session_id: str, status_container):
    """Run the pipeline call in a thread while showing progress steps."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(send_to_n8n, message, session_id)

        for step_label, wait_seconds in PIPELINE_STEPS:
            if future.done():
                break
            status_container.update(label=step_label, state="running")
            elapsed = 0.0
            while elapsed < wait_seconds and not future.done():
                time.sleep(0.5)
                elapsed += 0.5

        if not future.done():
            status_container.update(label="Almost there...", state="running")
            future.result(timeout=90)

        status_container.update(label="Pipeline complete", state="complete")
        return future.result(timeout=0)


for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

    if msg["role"] == "assistant" and i < len(st.session_state.pipeline_metadata):
        meta = st.session_state.pipeline_metadata[i]
        if meta:
            score = meta.get("compliance_score")
            violations = meta.get("violations", [])
            warnings = meta.get("warnings", [])
            compliant = meta.get("compliant")

            if score is not None:
                with st.expander("Pipeline details", expanded=False):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Compliance", f"{score}/100")
                    c2.metric("Compliant", "Yes" if compliant else "No")
                    c3.metric("Violations", len(violations))
                    elapsed = meta.get("elapsed_seconds")
                    if elapsed:
                        c4.metric("Pipeline time", f"{elapsed:.1f}s")
                    if violations:
                        st.warning("**Violations:** " + " | ".join(str(v) for v in violations))
                    if warnings:
                        st.info("**Warnings:** " + " | ".join(str(w) for w in warnings))
                    summary = meta.get("review_summary")
                    if summary:
                        st.caption(summary)


prompt = st.chat_input("Type your message...")
if prompt:
    st.session_state.pending_message = prompt

if st.session_state.pending_message:
    active_message = st.session_state.pending_message
    st.session_state.pending_message = None

    st.session_state.messages.append({"role": "user", "content": active_message})
    with st.chat_message("user"):
        st.markdown(active_message)

    with st.chat_message("assistant"):
        t_start = time.time()
        status = st.status("Routing message to the right agent...", expanded=True)
        result = run_with_progress(active_message, st.session_state.session_id, status)
        elapsed = time.time() - t_start

        response_text = extract_response_text(result)
        st.markdown(response_text)

    st.session_state.messages.append({"role": "assistant", "content": response_text})

    meta = {
        "compliance_score": result.get("compliance_score"),
        "compliant": result.get("compliant"),
        "violations": result.get("violations", []),
        "warnings": result.get("warnings", []),
        "review_summary": result.get("review_summary"),
        "elapsed_seconds": elapsed,
    } if "compliance_score" in result else None

    padding = len(st.session_state.messages) - len(st.session_state.pipeline_metadata) - 1
    st.session_state.pipeline_metadata.extend([None] * padding)
    st.session_state.pipeline_metadata.append(meta)

    st.rerun()


with st.sidebar:
    st.markdown("### Settings")

    url_input = st.text_input(
        "n8n Webhook URL",
        value=N8N_WEBHOOK_URL,
        type="password",
        help="The production webhook URL from your n8n Chat Trigger node",
    )
    if url_input != N8N_WEBHOOK_URL:
        N8N_WEBHOOK_URL = url_input
        os.environ["N8N_WEBHOOK_URL"] = url_input
        st.success("Webhook URL updated for this session")

    st.divider()
    st.markdown(f"**Session:** `{st.session_state.session_id[:8]}...`")
    st.markdown(f"**Messages:** {len(st.session_state.messages)}")

    if st.button("New Conversation", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.pipeline_metadata = []
        st.rerun()

    st.divider()
    st.markdown("### Quick Test")
    examples = [
        ("New client", "I've been dealing with chronic fatigue and brain fog for 2 years"),
        ("Daily journal", "Slept 5 hours, woke up groggy. Stomach has been off all morning."),
        ("Coach intake", "I'm a coach — I need intake questions for a client with digestive concerns"),
    ]
    for label, ex in examples:
        if st.button(label, key=f"ex_{hash(ex)}", use_container_width=True, help=ex):
            st.session_state.pending_message = ex
            st.rerun()

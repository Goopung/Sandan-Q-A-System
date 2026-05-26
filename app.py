import html
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

try:
    import resend
except ImportError:
    resend = None

from sandan_rag.bootstrap import configure_utf8
from sandan_rag.config import get_config, get_setting
from sandan_rag.fts_index import SQLiteFTSIndex
from sandan_rag.qa_engine import SandanQAEngine
from sandan_rag.openai_utils import reset_openai_client
from sandan_rag.utils import guess_mime_type, resolve_existing_path


configure_utf8()
APP_ROOT = Path(__file__).resolve().parent
load_dotenv(APP_ROOT / ".env")
load_dotenv()

st.set_page_config(
    page_title="KHU Sandan Q&A System",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_ui_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --primary: #1d4ed8;
            --primary-dark: #1e3a8a;
            --primary-soft: #eff6ff;
            --border: #e5e7eb;
            --muted: #64748b;
            --surface: #ffffff;
            --soft-surface: #f8fafc;
            --success-soft: #ecfdf5;
            --warning-soft: #fffbeb;
            --danger-soft: #fef2f2;
        }

        .main .block-container {
            padding-top: 1.35rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
            border-right: 1px solid var(--border);
        }

        .app-hero {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.3rem;
            padding: 1.35rem 1.45rem;
            border-radius: 20px;
            background:
                radial-gradient(circle at 8% 20%, rgba(37, 99, 235, 0.10), transparent 30%),
                linear-gradient(135deg, #ffffff 0%, #f8fbff 62%, #eef6ff 100%);
            border: 1px solid #dbeafe;
            color: #0f172a;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
            margin-bottom: 1.25rem;
            overflow: hidden;
        }

        .app-hero::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 6px;
            background: linear-gradient(180deg, #2563eb 0%, #38bdf8 100%);
        }

        .hero-kicker {
            display: inline-flex;
            align-items: center;
            padding: 0.28rem 0.65rem;
            border-radius: 999px;
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            color: #1d4ed8;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.01em;
            margin-bottom: 0.55rem;
        }

        .app-hero h1 {
            margin: 0;
            font-size: 2.05rem;
            line-height: 1.18;
            letter-spacing: -0.035em;
            color: #0f172a;
        }

        .app-hero p {
            margin: 0.6rem 0 0;
            color: #475569;
            font-size: 0.96rem;
            line-height: 1.65;
        }

        .hero-panel {
            min-width: 230px;
            padding: 1rem 1.1rem;
            border-radius: 18px;
            background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
            color: #ffffff;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.20);
            text-align: left;
        }

        .hero-panel-link,
        .hero-panel-link:hover,
        .hero-panel-link:visited,
        .hero-panel-link:active {
            color: #ffffff !important;
            text-decoration: none !important;
            cursor: pointer;
            display: block;
        }

        .st-key-issue_report_click_overlay {
            position: relative;
            height: 0;
            min-height: 0;
            max-height: 0;
            margin: 0;
            padding: 0;
            overflow: visible;
            z-index: 30;
        }

        .st-key-issue_report_click_overlay div[data-testid="stButton"] {
            position: absolute;
            right: 1.45rem;
            top: -7.95rem;
            width: 230px;
            height: 6.9rem;
            margin: 0;
            padding: 0;
            z-index: 40;
        }

        .st-key-issue_report_click_overlay div[data-testid="stButton"] > button {
            width: 100%;
            height: 100%;
            min-height: 6.9rem;
            border-radius: 18px;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            opacity: 0;
            cursor: pointer;
            padding: 0 !important;
        }

        .st-key-issue_report_click_overlay div[data-testid="stButton"] > button:hover {
            transform: none !important;
            box-shadow: none !important;
        }

        @media (max-width: 900px) {
            .st-key-issue_report_click_overlay div[data-testid="stButton"] {
                left: 1.45rem;
                right: 1.45rem;
                top: -7.2rem;
                width: auto;
            }
        }

        .hero-panel .panel-label {
            font-size: 0.74rem;
            opacity: 0.82;
            font-weight: 700;
            margin-bottom: 0.45rem;
        }

        .hero-panel .panel-title {
            font-size: 1.08rem;
            font-weight: 900;
            line-height: 1.35;
        }

        .hero-panel .panel-hint {
            margin-top: 0.35rem;
            font-size: 0.78rem;
            opacity: 0.82;
        }

        @media (max-width: 900px) {
            .app-hero {
                flex-direction: column;
                align-items: flex-start;
            }
            .hero-panel {
                width: 100%;
                min-width: 0;
            }
        }

        .status-card {
            border: 1px solid var(--border);
            background: var(--surface);
            border-radius: 18px;
            padding: 1rem 1.05rem;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
            min-height: 92px;
        }

        .status-card .label {
            color: var(--muted);
            font-size: 0.82rem;
            margin-bottom: 0.35rem;
            font-weight: 600;
        }

        .status-card .value {
            color: #0f172a;
            font-size: 1.05rem;
            font-weight: 800;
            margin-bottom: 0.15rem;
        }

        .status-card .hint {
            color: #64748b;
            font-size: 0.8rem;
        }

        .sidebar-card {
            border: 1px solid rgba(148, 163, 184, 0.25);
            background: rgba(255, 255, 255, 0.72);
            border-radius: 16px;
            padding: 0.95rem 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
            margin: 0.6rem 0 1rem;
        }

        .sidebar-card-title {
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 0.35rem;
        }

        .sidebar-card-text {
            color: #475569;
            font-size: 0.86rem;
            line-height: 1.55;
        }

        div[data-testid="stExpander"] {
            border: 1px solid var(--border);
            border-radius: 18px;
            background: var(--surface);
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.045);
            margin-bottom: 1rem;
            overflow: hidden;
        }

        div[data-testid="stExpander"] details summary {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border-radius: 18px;
            font-weight: 800;
            color: #0f172a;
            padding-top: 0.85rem !important;
            padding-bottom: 0.85rem !important;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stDateInput"] input {
            border-radius: 12px;
            border-color: #dbe3ef;
        }

        div.stButton > button,
        div[data-testid="stDownloadButton"] > button {
            border-radius: 12px;
            font-weight: 700;
            border: 1px solid #bfdbfe;
            transition: all 0.18s ease;
        }

        div.stButton > button:hover,
        div[data-testid="stDownloadButton"] > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 8px 18px rgba(37, 99, 235, 0.14);
        }

        div.stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
            border: 0;
            color: white;
        }

        .block-note {
            padding: 0.85rem 1rem;
            border-radius: 14px;
            background: #ffffff;
            border: 1px solid #e5e7eb;
            color: #475569;
            font-size: 0.88rem;
            line-height: 1.55;
            margin-top: 1.25rem;
            margin-bottom: 1rem;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.035);
        }

        .doc-card {
            border: 1px solid #e5e7eb;
            background: #ffffff;
            border-radius: 18px;
            padding: 1rem 1.05rem;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.045);
            margin-bottom: 0.9rem;
        }

        .doc-title {
            font-size: 1rem;
            font-weight: 900;
            color: #0f172a;
            margin-bottom: 0.3rem;
        }

        .doc-meta {
            color: #64748b;
            font-size: 0.83rem;
            line-height: 1.55;
        }


        .update-log-note {
            color: #64748b;
            font-size: 0.82rem;
            margin-top: -0.35rem;
            margin-bottom: 0.45rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <div class="app-hero">
            <div class="hero-text">
                <div class="hero-kicker">Kyung Hee University · Research Administration</div>
                <h1>KHU Sandan Q&A System</h1>
                <p>연구처 및 산학협력단 게시판 첨부자료를 기반으로 규정 문의에 답변하고, 관련 원본 자료를 바로 제공합니다.</p>
            </div>
            <div class="hero-panel">
                <div class="panel-label">Support</div>
                <div class="panel-title">Report an Issue</div>
                <div class="panel-hint">Click here if the system fails or returns incorrect results.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="issue_report_click_overlay"):
        issue_clicked = st.button(
            "Open issue report dialog",
            key="open_issue_report_dialog_btn",
            use_container_width=True,
        )

    if issue_clicked:
        st.session_state["show_issue_report_dialog"] = True



ISSUE_EMAIL_FROM = "Error Issue <onboarding@resend.dev>"


def get_secret_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return str(value)

    try:
        value = st.secrets.get(name, "")
        if value:
            return str(value)
    except Exception:
        pass

    return default


def get_issue_recipient() -> str:
    return (
        get_secret_value("ISSUE_REPORT_TO_EMAIL", "")
        or get_secret_value("RESEND_ISSUE_TO_EMAIL", "")
        or get_secret_value("RESEND_TO_EMAIL", "")
        or "pung@khu.ac.kr"
    )


def close_issue_report_dialog() -> None:
    st.session_state["show_issue_report_dialog"] = False
    st.rerun()


def build_issue_email_body(
    issue_type: str,
    severity: str,
    reporter_name: str,
    reporter_email: str,
    description: str,
    include_context: bool,
) -> tuple[str, str]:
    config = get_config()

    context = {
        "backend": config.backend_label,
        "selected_model": st.session_state.get("runtime_chat_model", ""),
        "mode": st.session_state.get("last_mode", ""),
        "menu_filter": st.session_state.get("last_menu_filter", ""),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    context_text = "\n".join([f"{key}: {value}" for key, value in context.items()]) if include_context else "Not included"

    plain_text = f"""KHU Sandan Q&A System Issue Report

Issue type: {issue_type}
Severity: {severity}
Reporter name: {reporter_name or "Not provided"}
Reporter email: {reporter_email or "Not provided"}

Description:
{description}

Runtime context:
{context_text}
"""

    html_body = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #0f172a;">
        <h2 style="margin-bottom: 8px;">KHU Sandan Q&amp;A System Issue Report</h2>
        <p style="margin-top: 0; color: #475569;">A user submitted an issue report from the Streamlit app.</p>

        <table style="border-collapse: collapse; width: 100%; margin: 16px 0;">
            <tr>
                <td style="border: 1px solid #e5e7eb; padding: 8px; font-weight: bold;">Issue type</td>
                <td style="border: 1px solid #e5e7eb; padding: 8px;">{html.escape(issue_type)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #e5e7eb; padding: 8px; font-weight: bold;">Severity</td>
                <td style="border: 1px solid #e5e7eb; padding: 8px;">{html.escape(severity)}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #e5e7eb; padding: 8px; font-weight: bold;">Reporter name</td>
                <td style="border: 1px solid #e5e7eb; padding: 8px;">{html.escape(reporter_name or "Not provided")}</td>
            </tr>
            <tr>
                <td style="border: 1px solid #e5e7eb; padding: 8px; font-weight: bold;">Reporter email</td>
                <td style="border: 1px solid #e5e7eb; padding: 8px;">{html.escape(reporter_email or "Not provided")}</td>
            </tr>
        </table>

        <h3>Description</h3>
        <div style="white-space: pre-wrap; padding: 12px; border-radius: 10px; background: #f8fafc; border: 1px solid #e5e7eb;">
            {html.escape(description)}
        </div>

        <h3>Runtime context</h3>
        <pre style="white-space: pre-wrap; padding: 12px; border-radius: 10px; background: #f8fafc; border: 1px solid #e5e7eb;">{html.escape(context_text)}</pre>
    </div>
    """

    return plain_text, html_body


def send_issue_report_email(
    issue_type: str,
    severity: str,
    reporter_name: str,
    reporter_email: str,
    description: str,
    include_context: bool,
) -> dict:
    if resend is None:
        raise RuntimeError("The 'resend' package is not installed. Add 'resend' to requirements.txt and redeploy.")

    resend_api_key = get_secret_value("RESEND_API_KEY", "")
    if not resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not configured.")

    recipient = get_issue_recipient()
    if not recipient:
        raise RuntimeError("Issue report recipient email is not configured.")

    text_body, html_body = build_issue_email_body(
        issue_type=issue_type,
        severity=severity,
        reporter_name=reporter_name,
        reporter_email=reporter_email,
        description=description,
        include_context=include_context,
    )

    resend.api_key = resend_api_key

    params = {
        "from": ISSUE_EMAIL_FROM,
        "to": [recipient],
        "subject": f"[KHU Sandan Q&A] {issue_type} Issue Report",
        "html": html_body,
        "text": text_body,
    }

    if reporter_email.strip():
        params["reply_to"] = reporter_email.strip()

    response = resend.Emails.send(params)
    if isinstance(response, dict):
        return response

    return {"response": str(response)}


@st.dialog("Report an Issue", dismissible=False, width="large")
def open_issue_report_dialog() -> None:
    st.caption("Use this form to report system errors, incorrect answers, search failures, or download issues.")

    with st.form("issue_report_form", clear_on_submit=False):
        issue_type = st.selectbox(
            "Issue type",
            [
                "System error",
                "Incorrect answer",
                "Search failure",
                "Download failure",
                "Data update issue",
                "Other",
            ],
            index=0,
        )
        severity = st.selectbox(
            "Severity",
            ["Low", "Medium", "High", "Critical"],
            index=1,
        )

        col1, col2 = st.columns(2)
        with col1:
            reporter_name = st.text_input("Your name", placeholder="Optional")
        with col2:
            reporter_email = st.text_input("Your email", placeholder="Optional")

        description = st.text_area(
            "Issue description *",
            height=180,
            placeholder="Please describe what happened, what you searched or asked, and what result you expected.",
        )
        include_context = st.checkbox(
            "Include basic runtime context",
            value=True,
            help="Includes backend mode, selected model, mode, menu filter, and timestamp.",
        )

        submitted = st.form_submit_button(
            "Send Issue Report",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not description.strip():
            st.warning("Please enter an issue description before sending.")
        else:
            try:
                result = send_issue_report_email(
                    issue_type=issue_type,
                    severity=severity,
                    reporter_name=reporter_name,
                    reporter_email=reporter_email,
                    description=description,
                    include_context=include_context,
                )
                message_id = result.get("id", "") if isinstance(result, dict) else ""
                if message_id:
                    st.success(f"Issue report sent successfully. Resend ID: {message_id}")
                else:
                    st.success("Issue report sent successfully.")
            except Exception as exc:
                st.error(f"Failed to send issue report: {exc}")

    if st.button("Close", use_container_width=True, key="close_issue_report_dialog_btn"):
        close_issue_report_dialog()



def get_engine() -> SandanQAEngine:
    return SandanQAEngine(get_config())


class SupabaseStatsIndex:
    def __init__(self, config):
        self.config = config

    def count_documents(self) -> int:
        from sandan_rag.supabase_store import count_documents
        return count_documents(self.config)

    def count_chunks(self) -> int:
        from sandan_rag.supabase_store import count_chunks
        return count_chunks(self.config)


class VectorStatsIndex:
    def __init__(self, config):
        self.config = config

    def _retriever(self):
        if self.config.use_lancedb:
            from sandan_rag.lancedb_retriever import LanceDBRetriever
            return LanceDBRetriever(self.config)
        if self.config.use_qdrant:
            from sandan_rag.qdrant_retriever import QdrantRetriever
            return QdrantRetriever(self.config)
        return None

    def count_documents(self) -> int:
        retriever = self._retriever()
        if retriever is None:
            return SQLiteFTSIndex(self.config.sqlite_path).count_documents()
        return retriever.count_documents()

    def count_chunks(self) -> int:
        retriever = self._retriever()
        if retriever is None:
            return SQLiteFTSIndex(self.config.sqlite_path).count_chunks()
        return retriever.count_chunks()


@st.cache_resource(show_spinner=False)
def get_stats_index():
    config = get_config()
    if config.use_supabase:
        return SupabaseStatsIndex(config)
    if config.use_lancedb or config.use_qdrant:
        return VectorStatsIndex(config)
    return SQLiteFTSIndex(config.sqlite_path)


def clear_runtime_cache() -> None:
    try:
        get_engine.clear()
    except Exception:
        pass
    try:
        get_stats_index.clear()
    except Exception:
        pass


def reset_runtime_openai_settings() -> None:
    reset_openai_client()
    clear_runtime_cache()


def is_runtime_openai_ready() -> bool:
    return bool(st.session_state.get("runtime_openai_api_key", "").strip())


def render_api_required_notice() -> None:
    st.warning("왼쪽 사이드바에서 본인의 OpenAI API Key를 입력한 뒤 사용해 주세요.")


def _progress_from_log_line(line: str, current_progress: int, phase_base: int, phase_limit: int) -> int:
    stripped = line.strip()

    if not stripped:
        return current_progress

    if "[MENU]" in stripped:
        return max(current_progress, min(phase_limit, phase_base + 8))

    if "[LIST]" in stripped:
        return min(phase_limit, max(current_progress + 1, phase_base + 12))

    if "[SAVE]" in stripped:
        return min(phase_limit, max(current_progress + 1, phase_base + 35))

    if "[DONE]" in stripped:
        return max(current_progress, phase_limit)

    if "records_total" in stripped or "chunks" in stripped or "indexed" in stripped.lower():
        return min(phase_limit, max(current_progress + 2, phase_base + 20))

    return current_progress


def render_update_log(log_placeholder, log_lines: list[str], max_lines: int = 160) -> None:
    visible_lines = log_lines[-max_lines:]
    if not visible_lines:
        visible_lines = ["업데이트 로그가 여기에 표시됩니다."]

    escaped_lines = [html.escape(line) for line in visible_lines]
    lines_html = "".join([f'<div class="log-line">{line}</div>' for line in escaped_lines])

    log_html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background: transparent;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}

            .log-card {{
                height: 260px;
                max-height: 260px;
                min-height: 260px;
                overflow-y: auto;
                overflow-x: auto;
                box-sizing: border-box;
                padding: 0.9rem 1rem;
                border-radius: 16px;
                border: 1px solid #dbeafe;
                background:
                    radial-gradient(circle at 8% 12%, rgba(37, 99, 235, 0.06), transparent 28%),
                    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
                color: #0f172a;
                box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
            }}

            .log-line {{
                font-family: Consolas, Monaco, "Courier New", monospace;
                font-size: 12px;
                line-height: 1.55;
                white-space: pre;
                color: #334155;
                padding: 1px 0;
            }}

            .log-line:first-child {{
                color: #64748b;
            }}

            .log-card::-webkit-scrollbar {{
                width: 9px;
                height: 9px;
            }}

            .log-card::-webkit-scrollbar-thumb {{
                background: #cbd5e1;
                border-radius: 999px;
                border: 2px solid #f8fbff;
            }}

            .log-card::-webkit-scrollbar-thumb:hover {{
                background: #94a3b8;
            }}

            .log-card::-webkit-scrollbar-track {{
                background: #f1f5f9;
                border-radius: 999px;
            }}
        </style>
    </head>
    <body>
        <div id="update-log-box" class="log-card">
            {lines_html}
        </div>
        <script>
            const logBox = document.getElementById("update-log-box");
            if (logBox) {{
                logBox.scrollTop = logBox.scrollHeight;
            }}
        </script>
    </body>
    </html>
    """

    with log_placeholder.container():
        components.html(log_html, height=274, scrolling=False)


def get_update_runtime_dir() -> Path:
    runtime_dir = APP_ROOT / "data" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def get_update_state_path() -> Path:
    return get_update_runtime_dir() / "update_state.json"


def get_update_log_path() -> Path:
    return get_update_runtime_dir() / "update.log"


def write_update_state(**kwargs) -> None:
    state_path = get_update_state_path()
    current = read_update_state()
    current.update(kwargs)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def read_update_state() -> dict:
    state_path = get_update_state_path()
    if not state_path.exists():
        return {
            "status": "idle",
            "progress": 0,
            "message": "대기 중",
            "phase": "idle",
            "started_at": "",
            "ended_at": "",
        }

    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "idle",
            "progress": 0,
            "message": "대기 중",
            "phase": "idle",
            "started_at": "",
            "ended_at": "",
        }


def read_update_log(max_lines: int = 500) -> list[str]:
    log_path = get_update_log_path()
    if not log_path.exists():
        return []

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def append_update_log(line: str) -> None:
    log_path = get_update_log_path()
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(line.rstrip("\n") + "\n")


def _run_update_command_background(
    command: list[str],
    phase_label: str,
    phase_start: int,
    phase_end: int,
) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")

    progress = phase_start
    write_update_state(
        status="running",
        progress=progress,
        message=f"{phase_label} 시작",
        phase=phase_label,
    )
    append_update_log(f"[RUN] {' '.join(command)}")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(APP_ROOT),
        env=env,
        bufsize=1,
    )

    assert process.stdout is not None

    for line in process.stdout:
        clean_line = line.rstrip("\n")
        if not clean_line:
            continue

        append_update_log(clean_line)
        progress = _progress_from_log_line(clean_line, progress, phase_start, phase_end - 3)
        write_update_state(
            status="running",
            progress=progress,
            message=phase_label,
            phase=phase_label,
        )

    return_code = process.wait()
    if return_code != 0:
        write_update_state(
            status="failed",
            progress=100,
            message=f"{phase_label} 실패",
            phase=phase_label,
            ended_at=datetime.now().isoformat(timespec="seconds"),
            return_code=return_code,
        )
        append_update_log(f"[ERROR] Command failed with return code {return_code}")
        raise RuntimeError(f"Command failed: {' '.join(command)}")

    write_update_state(
        status="running",
        progress=phase_end,
        message=f"{phase_label} 완료",
        phase=phase_label,
    )
    append_update_log(f"[DONE] {phase_label}")


def update_worker(full: bool, force_index: bool, max_pages: int) -> None:
    try:
        get_update_log_path().write_text("", encoding="utf-8")
        write_update_state(
            status="running",
            progress=3,
            message="업데이트 명령을 준비하고 있습니다.",
            phase="prepare",
            started_at=datetime.now().isoformat(timespec="seconds"),
            ended_at="",
            return_code=0,
        )
        append_update_log("[START] 데이터 업데이트를 시작합니다.")

        config = get_config()

        collect_command = [
            sys.executable,
            str(APP_ROOT / "scripts" / "collect_data.py"),
            "--max-pages",
            str(max_pages),
        ]
        if full:
            collect_command.append("--full")

        if config.use_supabase:
            index_command = [sys.executable, str(APP_ROOT / "scripts" / "migrate_local_to_supabase.py")]
            if force_index:
                index_command.append("--force")
            index_phase = "2/2 Supabase RAG DB 업데이트 중"
        else:
            index_command = [sys.executable, str(APP_ROOT / "scripts" / "build_index.py")]
            if force_index:
                index_command.append("--force")
            index_phase = f"2/2 {config.vector_store_label} 색인 업데이트 중"

        _run_update_command_background(
            collect_command,
            "1/2 데이터 수집 및 텍스트 추출 중",
            5,
            62,
        )
        _run_update_command_background(
            index_command,
            index_phase,
            63,
            96,
        )

        clear_runtime_cache()
        write_update_state(
            status="done",
            progress=100,
            message="데이터 업데이트와 색인 갱신이 완료되었습니다.",
            phase="done",
            ended_at=datetime.now().isoformat(timespec="seconds"),
            return_code=0,
        )
        append_update_log("[UPDATE DONE]")
    except Exception as exc:
        append_update_log(f"[ERROR] {exc}")
        write_update_state(
            status="failed",
            progress=100,
            message=f"업데이트 실패: {exc}",
            phase="failed",
            ended_at=datetime.now().isoformat(timespec="seconds"),
            return_code=1,
        )


def start_update_background(full: bool, force_index: bool, max_pages: int) -> None:
    state = read_update_state()
    if state.get("status") == "running":
        return

    st.session_state["update_dialog_running"] = True
    st.session_state["update_max_pages"] = int(max_pages)

    thread = threading.Thread(
        target=update_worker,
        kwargs={
            "full": bool(full),
            "force_index": bool(force_index),
            "max_pages": int(max_pages),
        },
        daemon=True,
    )
    thread.start()
    st.session_state["update_thread"] = thread


@st.dialog("데이터 업데이트", dismissible=False, width="large")
def open_data_update_dialog() -> None:
    config = get_config()
    st.caption(f"게시판 첨부자료를 수집한 뒤 {config.backend_label} 색인을 갱신합니다.")

    state = read_update_state()
    is_running = state.get("status") == "running"

    max_pages = st.number_input(
        "최대 페이지",
        min_value=1,
        max_value=1000,
        value=int(st.session_state.get("update_max_pages", 300)),
        step=10,
        key="update_dialog_max_pages",
        disabled=is_running,
    )
    full = st.checkbox("전체 재수집", value=False, key="update_dialog_full", disabled=is_running)
    force_index = st.checkbox("전체 재색인", value=False, key="update_dialog_force_index", disabled=is_running)

    st.markdown(
        """
        <div class="block-note">
            업데이트는 백그라운드에서 실행됩니다. 창을 닫아도 업데이트는 계속 진행되며, 다시 열면 진행 상태를 확인할 수 있습니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

    progress_value = int(state.get("progress", 0) or 0)
    progress_value = max(0, min(100, progress_value))
    progress_text = str(state.get("message", "대기 중"))
    st.progress(progress_value, text=progress_text)

    if state.get("status") == "running":
        st.info(progress_text)
    elif state.get("status") == "done":
        st.success(progress_text)
    elif state.get("status") == "failed":
        st.error(progress_text)
    else:
        st.info("업데이트 대기 중입니다.")

    log_placeholder = st.empty()
    render_update_log(log_placeholder, read_update_log())

    col1, col2 = st.columns(2)
    with col1:
        if is_running:
            st.button(
                "업데이트 중",
                type="primary",
                use_container_width=True,
                key="run_update_dialog_btn_running_async",
                disabled=True,
            )
        else:
            run_clicked = st.button(
                "업데이트 실행",
                type="primary",
                use_container_width=True,
                key="run_update_dialog_btn_idle_async",
            )
            if run_clicked:
                start_update_background(
                    full=full,
                    force_index=force_index,
                    max_pages=int(max_pages),
                )
                st.rerun()

    with col2:
        close_clicked = st.button(
            "닫기",
            use_container_width=True,
            key="close_update_dialog_btn_async",
            disabled=False,
        )

    if close_clicked:
        st.session_state["show_update_dialog"] = False
        st.rerun()

    # Keep the progress/log view fresh while the dialog is open, without blocking buttons.
    if is_running and st.session_state.get("show_update_dialog", False):
        time.sleep(0.8)
        st.rerun()


def render_status_cards() -> None:
    config = get_config()
    openai_ready = bool(st.session_state.get("runtime_openai_api_key", "").strip())
    records_ready = True if (config.use_supabase or config.use_lancedb or config.use_qdrant) else (config.records_jsonl.exists() and config.records_jsonl.stat().st_size > 0)
    try:
        stats = get_stats_index()
        doc_count = stats.count_documents()
        chunk_count = stats.count_chunks()
    except Exception:
        doc_count = 0
        chunk_count = 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
            <div class="status-card">
                <div class="label">OpenAI API</div>
                <div class="value">{'설정 완료' if openai_ready else '확인 필요'}</div>
                <div class="hint">답변 생성 및 임베딩</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="status-card">
                <div class="label">데이터 저장소</div>
                <div class="value">{config.storage_label if records_ready else '미생성'}</div>
                <div class="hint">{config.vector_store_label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
            <div class="status-card">
                <div class="label">색인 문서</div>
                <div class="value">{doc_count:,}개</div>
                <div class="hint">첨부파일 기준</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f"""
            <div class="status-card">
                <div class="label">검색 Chunk</div>
                <div class="value">{chunk_count:,}개</div>
                <div class="hint">Hybrid Retrieval 대상</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_sidebar():
    config = get_config()
    with st.sidebar:

        st.subheader("기본 설정")

        st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-...",
            key="runtime_openai_api_key",
            help="입력한 Key는 현재 브라우저 세션에서만 사용됩니다.",
            on_change=reset_runtime_openai_settings,
        )

        model_options = [
            "gpt-5.5",
            "gpt-5.5-pro",
            "gpt-5.4",
            "gpt-5.4-pro",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
            "직접 입력",]
        
        selected_model = st.selectbox(
            "Model",
            model_options,
            index=0,
            key="runtime_chat_model_choice",
            on_change=reset_runtime_openai_settings,
        )

        if selected_model == "직접 입력":
            custom_model = st.text_input(
                "모델명 직접 입력",
                value=st.session_state.get("runtime_chat_model_custom", ""),
                placeholder="예: gpt-4.1-mini",
                key="runtime_chat_model_custom",
                on_change=reset_runtime_openai_settings,
            ).strip()
            st.session_state["runtime_chat_model"] = custom_model or "gpt-4.1-mini"
        else:
            st.session_state["runtime_chat_model"] = selected_model

        st.session_state["runtime_embedding_model"] = "text-embedding-3-small"

        if is_runtime_openai_ready():
            st.success("API Key 입력 완료")
        else:
            st.warning("API Key 입력 필요")

        st.divider()
        st.subheader("검색 설정")
        mode = st.radio("사용 모드", ["Answer", "Search"], index=0)
        menu_filter = st.selectbox(
            "게시판 범위",
            ["전체", "대외연구비_규정지침", "자료실_서식양식", "산학협력단_규정지침"],
            index=0,
        )

        use_date = st.checkbox("등록일 필터 사용", value=False)
        date_from = None
        date_to = None
        if use_date:
            col1, col2 = st.columns(2)
            with col1:
                date_from = st.date_input("시작일").isoformat()
            with col2:
                date_to = st.date_input("종료일").isoformat()

        st.divider()
        st.subheader("데이터 업데이트")
        if config.enable_update_dialog:
            st.caption("팝업 창에서 수집 및 색인 진행률을 확인할 수 있습니다.")
            if st.button("데이터 업데이트 열기", type="primary", use_container_width=True):
                st.session_state["show_update_dialog"] = True
                st.rerun()
        else:
            st.caption("배포 환경에서는 GitHub Actions 또는 외부 작업자로 업데이트하세요.")

    st.session_state["last_mode"] = mode
    st.session_state["last_menu_filter"] = menu_filter

    return mode, menu_filter, date_from, date_to


def render_source_table(sources) -> None:
    if not sources:
        return
    rows = []
    for src in sources:
        rows.append(
            {
                "출처": src.get("source_id", ""),
                "게시판": src.get("menu_name", ""),
                "등록일": src.get("registered_date", ""),
                "게시글 제목": src.get("post_title", ""),
                "첨부파일": src.get("attachment_name", ""),
                "URL": src.get("detail_url", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_download(doc: dict, index: int) -> None:
    config = get_config()
    file_name = doc.get("attachment_name", "") or f"document_{index}"
    if doc.get("download_url"):
        st.link_button("원본 파일 다운로드", doc["download_url"], type="primary", use_container_width=True)
        return

    file_path = resolve_existing_path(doc.get("attachment_path", ""), config.project_root)
    file_name = doc.get("attachment_name", "") or (file_path.name if file_path else f"document_{index}")
    if file_path is not None:
        try:
            data = file_path.read_bytes()
            st.download_button(
                label="원본 파일 다운로드",
                data=data,
                file_name=file_name,
                mime=guess_mime_type(file_path),
                key=f"download_{index}_{doc.get('attachment_key', '')}_{file_name}",
                type="primary",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"파일을 읽을 수 없습니다: {exc}")
    else:
        url = doc.get("attachment_url", "") or doc.get("detail_url", "")
        if url:
            st.link_button("원문 페이지/첨부 링크 열기", url, use_container_width=True)
        else:
            st.warning("다운로드 가능한 파일 경로가 없습니다.")


def ensure_index_ready() -> bool:
    try:
        stats = get_stats_index()
        return stats.count_chunks() > 0
    except Exception:
        return False


def render_qa_mode(engine: SandanQAEngine, menu_filter, date_from, date_to) -> None:
    st.subheader("Answer Mode")
    st.caption("산단 자료를 근거로 답변하고, 답변 아래에 출처를 표시합니다.")

    if not is_runtime_openai_ready():
        render_api_required_notice()
        return

    if not ensure_index_ready():
        st.warning("아직 색인이 없습니다. 데이터 업데이트를 실행하거나 `scripts/build_index.py`를 먼저 실행하세요. Supabase legacy 모드는 `scripts/update_supabase.py`를 사용하세요.")
        return

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sources"):
                with st.expander("근거 자료 보기"):
                    render_source_table(message["sources"])

    question = st.chat_input("산단 연구비, 서식, 규정에 대해 질문하세요.")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("관련 자료 검색 및 답변 생성 중"):
                try:
                    result = engine.answer(question, menu_filter=menu_filter, date_from=date_from, date_to=date_to)
                except Exception as exc:
                    st.error(f"답변 생성 실패: {exc}")
                    return
            st.markdown(result["answer"])
            with st.expander("근거 자료 보기", expanded=True):
                render_source_table(result.get("sources", []))

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["answer"],
                "sources": result.get("sources", []),
            }
        )


def render_query_mode(engine: SandanQAEngine, menu_filter, date_from, date_to) -> None:
    st.subheader("Search Mode")
    st.caption("관련 자료를 찾아 간단히 요약하고, 원본 파일 다운로드 버튼을 제공합니다.")

    if not ensure_index_ready():
        st.warning("아직 색인이 없습니다. 데이터 업데이트를 실행하거나 `scripts/build_index.py`를 먼저 실행하세요. Supabase legacy 모드는 `scripts/update_supabase.py`를 사용하세요.")
        return

    with st.form("query_form"):
        query = st.text_area(
            "찾고 싶은 자료를 입력하세요",
            height=120,
            placeholder="예: 회의비 식비 사전신청 폐지 관련 규정",
        )
        max_docs = st.slider("제공할 자료 수", min_value=3, max_value=20, value=8)
        submitted = st.form_submit_button("자료 검색", type="primary", use_container_width=True)

    if submitted and query.strip():
        with st.spinner("관련 자료 검색 중"):
            try:
                result = engine.query_documents(
                    query,
                    menu_filter=menu_filter,
                    date_from=date_from,
                    date_to=date_to,
                    max_docs=max_docs,
                )
            except Exception as exc:
                st.error(f"자료 검색 실패: {exc}")
                return

        st.markdown("### 간단 요약")
        st.markdown(result.get("summary", ""))

        documents = result.get("documents", [])
        st.markdown("### 관련 자료 다운로드")
        for idx, doc in enumerate(documents, start=1):
            st.markdown(
                f"""
                <div class="doc-card">
                    <div class="doc-title">{idx}. {doc.get('attachment_name', '')}</div>
                    <div class="doc-meta">게시판: {doc.get('menu_name', '')} · 등록일: {doc.get('registered_date', '')}</div>
                    <div class="doc-meta">게시글 제목: {doc.get('post_title', '')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns([2, 1])
            with col1:
                snippets = doc.get("snippets", [])[:2]
                if snippets:
                    with st.expander("검색된 내용 일부"):
                        for snippet in snippets:
                            st.write(snippet)
                if doc.get("detail_url"):
                    st.caption(f"원문 URL: {doc.get('detail_url')}")
            with col2:
                render_download(doc, idx)


def main() -> None:
    apply_ui_style()
    render_hero()
    render_status_cards()
    st.markdown(
        """
        <div class="block-note">
            이 시스템은 게시판 첨부자료에서 추출한 텍스트를 기반으로 답변합니다. 중요한 행정 처리 전에는 반드시 원문 파일과 게시글 날짜를 함께 확인하세요.
        </div>
        """,
        unsafe_allow_html=True,
    )

    mode, menu_filter, date_from, date_to = render_sidebar()

    if st.session_state.get("show_issue_report_dialog", False):
        open_issue_report_dialog()

    if st.session_state.get("show_update_dialog", False):
        open_data_update_dialog()

    try:
        engine = get_engine()
    except Exception as exc:
        st.error("시스템 초기화 실패")
        st.code(str(exc))
        st.stop()

    if mode == "Answer":
        render_qa_mode(engine, menu_filter, date_from, date_to)
    else:
        render_query_mode(engine, menu_filter, date_from, date_to)


if __name__ == "__main__":
    main()

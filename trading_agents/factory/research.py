"""Research stage — NotebookLM Q&A (Option C: user-supplied notebook) plus the
in-house Whisper+Vision video agent. Both write artifacts into the job dir and
degrade gracefully when node / yt-dlp / ffmpeg / whisper are missing.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from trading_agents.factory import state as st
from trading_agents.factory import youtube as yt

log = logging.getLogger("factory.research")

BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPTS = BASE_DIR / "scripts"


def _node() -> Optional[str]:
    return shutil.which("node") or shutil.which("node.exe")


def _run_node(script: str, args: list[str], timeout: int) -> tuple[int, str, str]:
    node = _node()
    if not node:
        return 1, "", "node not found in PATH"
    try:
        r = subprocess.run([node, str(SCRIPTS / script), *args],
                           capture_output=True, text=True, cwd=str(BASE_DIR),
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"{script} timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{script} error: {e}"


# ── Question generation ────────────────────────────────────────────────────────

def _gen_questions(meta: dict, prior: str, lo: int, hi: int, kind: str) -> list[str]:
    from trading_agents.llm_fallback import chat_resilient
    sys_p = (
        f"You are researching a trading-strategy video to rebuild it for backtesting. "
        f"Produce {lo}-{hi} {kind} questions to ask a NotebookLM grounded on the video's "
        f"transcript. Questions must extract MECHANICAL detail: exact entry trigger, "
        f"stop-loss, take-profit/RR, indicators+settings, timeframes, session/news rules, "
        f"and risk management. Output ONLY a JSON array of question strings."
    )
    user = json.dumps({"title": meta.get("title", ""),
                       "channel": meta.get("channel", ""),
                       "description": (meta.get("description", "") or "")[:2500],
                       "prior_findings": prior[:3000]}, ensure_ascii=False)
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        client = None
    try:
        raw = chat_resilient(client, system=sys_p, user=user, max_tokens=1500,
                             model="claude-opus-4-8", thinking=False,
                             nvidia_tier="HEAVY", label="factory_research_q")
        import re
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        qs = json.loads(m.group(0)) if m else []
        qs = [str(q) for q in qs if isinstance(q, str)][:hi]
        return qs
    except Exception as e:  # noqa: BLE001
        log.warning("question-gen failed (%s) — using fallback set", e)
        return _FALLBACK_Q[:hi] if kind == "discovery" else _FALLBACK_DEEP[:hi]


_FALLBACK_Q = [
    "What is the core idea of this trading strategy in 2-3 sentences?",
    "Which indicators and exact settings does it use?",
    "What timeframes are used for bias, setup, and entry?",
    "What is the precise entry trigger?",
    "Where is the stop-loss placed and how is the take-profit set?",
    "What markets/symbols and sessions is it traded on?",
]
_FALLBACK_DEEP = [
    "Give the complete step-by-step entry checklist a trader follows.",
    "Exact stop-loss rule (price reference and buffer)?",
    "Exact take-profit rule and reward:risk?",
    "How is trend/bias determined, with exact indicator lengths?",
    "What confirms the entry (candle/structure/indicator cross)?",
    "Any session or news filters? Exact times/rules?",
    "Risk per trade, position sizing, and trade management rules?",
    "What conditions invalidate or skip a setup?",
    "Partial exits, break-even, or trailing rules?",
    "What are the most common failure modes the author warns about?",
]


# ── Stage handlers ─────────────────────────────────────────────────────────────

def run_notebook_research(job: dict) -> None:
    """RESEARCH_NB: 5-7 discovery Qs then 10-12 deep Qs via the user-supplied
    NotebookLM notebook, plus the audio overview. Writes artifacts. Degrades to a
    no-op (logged) when no notebook URL or node is available."""
    nb_url = job.get("source", {}).get("notebook_url", "")
    art = st.artifact_dir(job["job_id"])
    meta = job.get("source", {})
    if not nb_url:
        st.append_history(job, st.RESEARCH_NB, "no notebook_url supplied — skipping NotebookLM")
        return
    if not _node():
        st.append_history(job, st.RESEARCH_NB, "node not found — skipping NotebookLM")
        return

    # Round 1: discovery
    disc_q = _gen_questions(meta, "", 5, 7, "discovery")
    (art / "q_discovery.json").write_text(json.dumps(disc_q, indent=2), encoding="utf-8")
    disc_md = art / "discovery.md"
    rc, out, err = _run_node("notebooklm_qa.mjs",
                             ["--notebook-url", nb_url,
                              "--questions", str(art / "q_discovery.json"),
                              "--out", str(disc_md)], timeout=1800)
    session_id = ""
    disc_answers = ""
    if rc == 0:
        job["artifacts"]["discovery_qa"] = str(disc_md)
        try:
            res = json.loads(out.strip().splitlines()[-1])
            session_id = res.get("session_id", "") or ""
            disc_answers = "\n".join(a.get("a", "") for a in res.get("answers", []))
            if session_id:
                job["artifacts"]["nb_session_id"] = session_id
        except Exception:
            pass
    else:
        st.append_history(job, st.RESEARCH_NB, f"discovery Q&A failed: {err[:160]}")

    # Round 2: deep dive (reuse session for sharper grounding)
    deep_q = _gen_questions(meta, disc_answers, 10, 12, "deep")
    (art / "q_deep.json").write_text(json.dumps(deep_q, indent=2), encoding="utf-8")
    deep_md = art / "deep.md"
    qa_args = ["--notebook-url", nb_url, "--questions", str(art / "q_deep.json"),
               "--out", str(deep_md)]
    if session_id:
        qa_args += ["--session", session_id]
    rc2, _, err2 = _run_node("notebooklm_qa.mjs", qa_args, timeout=2400)
    if rc2 == 0:
        job["artifacts"]["deep_qa"] = str(deep_md)
    else:
        st.append_history(job, st.RESEARCH_NB, f"deep Q&A failed: {err2[:160]}")

    # Audio overview (best-effort, slow).
    rc3, out3, _ = _run_node("notebooklm_audio.mjs",
                             ["--notebook-url", nb_url, "--dest-dir", str(art)],
                             timeout=900)
    if rc3 == 0:
        try:
            res = json.loads(out3.strip().splitlines()[-1])
            if res.get("file"):
                job["artifacts"]["audio_overview"] = res["file"]
        except Exception:
            pass
    st.save_job(job)


def run_video_research(job: dict) -> None:
    """RESEARCH_VIDEO: yt-dlp transcript + (if deps available) Whisper+Vision
    strategy extraction. Writes video_spec / transcript artifacts. Degrades to
    transcript-only or no-op."""
    art = st.artifact_dir(job["job_id"])
    url = job.get("source", {}).get("youtube_url", "")

    # Cheap transcript first (no Whisper needed).
    transcript = yt.fetch_transcript(url, art)
    if transcript:
        (art / "transcript.txt").write_text(transcript, encoding="utf-8")
        job["artifacts"]["transcript"] = str(art / "transcript.txt")

    # Full Whisper+Vision extraction (heavy; optional).
    video_path = yt.download_video(url, art)
    if not video_path:
        st.append_history(job, st.RESEARCH_VIDEO,
                          "video download unavailable — transcript-only" if transcript
                          else "no video and no transcript available")
        st.save_job(job)
        return
    job["artifacts"]["video_file"] = str(video_path)
    try:
        from trading_agents.video_analysis_agent import VideoAnalysisAgent
        agent = VideoAnalysisAgent(output_dir=str(art))
        strategy = agent.analyze_video(str(video_path), save_output=True)
        spec_path = art / "video_spec.json"
        spec_path.write_text(json.dumps(strategy, indent=2, ensure_ascii=False), encoding="utf-8")
        job["artifacts"]["video_spec"] = str(spec_path)
    except Exception as e:  # noqa: BLE001
        st.append_history(job, st.RESEARCH_VIDEO, f"Whisper/Vision unavailable: {e}")
    st.save_job(job)

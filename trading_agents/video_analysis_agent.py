"""
Video Analysis Agent — extracts trading strategies from instructional video files.

Pipeline:
  1. Extract audio  → transcribe with faster-whisper (runs fully offline)
  2. Extract keyframes → encode as base64 JPEG
  3. Analyze frames with Claude Vision API (batches of 5)
  4. Synthesize a structured strategy JSON compatible with DEFAULT_PARAMS
  5. Enter an interactive chat loop to discuss findings

Usage:
  python trading_agents/video_analysis_agent.py path/to/video.mp4
  python trading_agents/video_analysis_agent.py path/to/video.mp4 --whisper-model small
  python trading_agents/video_analysis_agent.py path/to/video.mp4 --frames 50 --no-chat
"""

import os
import sys
import json
import base64
import shutil
import logging
import tempfile
import argparse
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# ── optional deps ──────────────────────────────────────────────────────────────
try:
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ── constants ──────────────────────────────────────────────────────────────────
SUPPORTED_FORMATS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}
DEFAULT_TARGET_FRAMES = 30
DEFAULT_WHISPER_MODEL = "base"
DEFAULT_CLAUDE_MODEL  = "claude-sonnet-4-6"
FRAME_BATCH_SIZE = 5          # frames per Claude Vision API call
MAX_HISTORY_TURNS = 40        # conversation history limit (messages, not turns)

# Keys that map directly to DEFAULT_PARAMS in mt5_bridge/config.py
KNOWN_PARAM_KEYS = {
    "EMA_Fast", "EMA_Slow", "RSI_Period", "RSI_OB", "RSI_OS",
    "ATR_Period", "ATR_SL_Multi", "BB_Period", "BB_Deviation",
    "MACD_Fast", "MACD_Slow", "MACD_Signal", "MomCandles",
    "MinCandleBody", "RiskPerTrade", "RewardPerTrade",
    "MaxDrawdownPct", "RequiredScore", "RiskPct",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("video_agent")


# ══════════════════════════════════════════════════════════════════════════════
class VideoAnalysisAgent:
    """Extracts trading strategies from instructional video files."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        whisper_model: str = DEFAULT_WHISPER_MODEL,
        output_dir: str = "trading_agents/extracted_strategies",
        claude_model: str = DEFAULT_CLAUDE_MODEL,
    ):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not found. Run: pip install anthropic"
            )

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY env var or pass --api-key."
            )

        self.client = _anthropic.Anthropic(api_key=resolved_key)
        self.claude_model = claude_model
        self.whisper_model_name = whisper_model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._ffmpeg_path: Optional[str] = None   # resolved lazily
        self._whisper_model: Any = None            # loaded lazily

    # ── public API ─────────────────────────────────────────────────────────────

    def analyze_video(
        self,
        video_path: str,
        target_frames: int = DEFAULT_TARGET_FRAMES,
        save_output: bool = True,
    ) -> Dict:
        """Full pipeline: video → strategy dict. Returns the strategy dict."""
        self._check_ffmpeg()
        video_path = str(Path(video_path).resolve())
        meta = self.validate_video(video_path)

        tmp_dir = tempfile.mkdtemp(prefix="video_agent_")
        log.info(f"Temp directory: {tmp_dir}")

        try:
            # ── Stage 1: audio ──────────────────────────────────────────────
            full_transcript = ""
            transcript_chunks: List[Dict] = []

            if meta["has_audio"]:
                wav_path = os.path.join(tmp_dir, "audio.wav")
                self.extract_audio(video_path, wav_path)
                full_transcript, segments = self.transcribe_audio(wav_path)
                transcript_chunks = self._chunk_transcript_by_time(segments)
                log.info(f"Transcript: {len(full_transcript)} chars in {len(transcript_chunks)} chunks")
            else:
                log.warning("Video has no audio track — skipping transcription")

            # ── Stage 2: frames ─────────────────────────────────────────────
            interval = self._calculate_frame_interval(meta["duration_seconds"], target_frames)
            frame_dir = os.path.join(tmp_dir, "frames")
            os.makedirs(frame_dir, exist_ok=True)
            frame_paths = self.extract_keyframes(video_path, interval, frame_dir)
            log.info(f"Extracted {len(frame_paths)} keyframes (interval={interval}s)")

            # ── Stage 3: Claude Vision ──────────────────────────────────────
            frame_analyses = self.analyze_frames_with_claude(
                frame_paths, transcript_chunks, interval
            )

            # ── Stage 4: synthesis ──────────────────────────────────────────
            strategy = self.synthesize_strategy(frame_analyses, full_transcript)
            strategy["source_video"] = os.path.basename(video_path)
            strategy["analyzed_at"] = datetime.now().isoformat()
            strategy["raw_analysis"] = {
                "frame_count_analyzed": len(frame_analyses),
                "transcript_length_chars": len(full_transcript),
                "frame_analyses": frame_analyses,
            }
            strategy["_internal_transcript"] = full_transcript

            if save_output:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = self.output_dir / f"strategy_{ts}.json"
                self._save_strategy_json(strategy, str(out_path))
                log.info(f"Strategy saved: {out_path}")

            return strategy

        finally:
            self._cleanup_temp_files([tmp_dir])

    def start_chat_loop(
        self,
        strategy: Dict,
        frame_analyses: List[Dict],
        full_transcript: str,
    ) -> None:
        """Interactive REPL to discuss the extracted strategy with the user."""
        system_prompt = self._build_chat_system_prompt(strategy, frame_analyses)
        history: List[Dict] = []

        self._print_summary(strategy)
        print("\nSpecial commands: /export  /params  /frames [n]  /transcript")
        print("Type 'quit' to exit.\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting chat.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            if user_input.startswith("/"):
                self._handle_slash_command(
                    user_input, strategy, frame_analyses, full_transcript
                )
                continue

            history.append({"role": "user", "content": user_input})

            response = self.client.messages.create(
                model=self.claude_model,
                max_tokens=1500,
                system=system_prompt,
                messages=history,
            )
            reply = response.content[0].text
            history.append({"role": "assistant", "content": reply})

            print(f"\nAssistant: {reply}\n")

            # keep context window manageable
            if len(history) > MAX_HISTORY_TURNS:
                history = history[-MAX_HISTORY_TURNS:]

    # ── Stage 0: ffmpeg check ──────────────────────────────────────────────────

    def _check_ffmpeg(self) -> str:
        if self._ffmpeg_path:
            return self._ffmpeg_path

        candidate = shutil.which("ffmpeg")
        if candidate:
            self._ffmpeg_path = candidate
            return candidate

        # common Windows install locations
        for guess in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
            if Path(guess).exists():
                self._ffmpeg_path = guess
                return guess

        raise RuntimeError(
            "ffmpeg not found on PATH.\n"
            "Install steps:\n"
            "  1. Download from https://www.gyan.dev/ffmpeg/builds/ "
            "(ffmpeg-release-essentials.zip)\n"
            "  2. Extract to C:\\ffmpeg\\\n"
            "  3. Add C:\\ffmpeg\\bin to Windows System PATH\n"
            "  4. Restart PowerShell and verify: ffmpeg -version"
        )

    def _ffprobe_path(self) -> str:
        ffmpeg = self._check_ffmpeg()
        probe = Path(ffmpeg).parent / "ffprobe.exe"
        if probe.exists():
            return str(probe)
        alt = shutil.which("ffprobe")
        return alt or "ffprobe"

    # ── Stage 1: video metadata ────────────────────────────────────────────────

    def validate_video(self, video_path: str) -> Dict:
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        suffix = Path(video_path).suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format '{suffix}'. Supported: {', '.join(SUPPORTED_FORMATS)}"
            )
        meta = self._get_video_metadata(video_path)
        log.info(
            f"Video: {Path(video_path).name} | "
            f"{meta['duration_seconds']:.1f}s | "
            f"{meta['width']}x{meta['height']} | "
            f"audio={'yes' if meta['has_audio'] else 'no'}"
        )
        return meta

    def _get_video_metadata(self, video_path: str) -> Dict:
        cmd = [
            self._ffprobe_path(), "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        fmt = data.get("format", {})

        duration = float(fmt.get("duration", 0))
        width = height = fps = 0
        has_audio = False

        for s in streams:
            if s.get("codec_type") == "video":
                width = s.get("width", 0)
                height = s.get("height", 0)
                fps_str = s.get("r_frame_rate", "0/1")
                try:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) else 0
                except Exception:
                    fps = 0
                if not duration:
                    duration = float(s.get("duration", 0))
            elif s.get("codec_type") == "audio":
                has_audio = True

        return {
            "path": video_path,
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "has_audio": has_audio,
            "format": Path(video_path).suffix.lstrip("."),
        }

    def _calculate_frame_interval(self, duration: float, target: int) -> int:
        raw = duration / max(target, 1)
        return int(max(5.0, min(60.0, raw)))

    # ── Stage 2: audio extraction & transcription ──────────────────────────────

    def extract_audio(self, video_path: str, wav_path: str) -> str:
        log.info("Extracting audio...")
        cmd = [
            self._check_ffmpeg(), "-y", "-i", video_path,
            "-ac", "1", "-ar", "16000", "-vn",
            wav_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Audio extraction failed: {result.stderr}")
        return wav_path

    def transcribe_audio(self, wav_path: str) -> Tuple[str, List[Dict]]:
        if not WHISPER_AVAILABLE:
            raise ImportError(
                "faster-whisper not installed. Run: pip install faster-whisper"
            )
        if self._whisper_model is None:
            log.info(
                f"Loading Whisper '{self.whisper_model_name}' model "
                "(first run downloads ~150MB — please wait)..."
            )
            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device="cpu",
                compute_type="int8",
            )

        log.info("Transcribing audio (this may take a minute)...")
        raw_segments, _ = self._whisper_model.transcribe(
            wav_path, beam_size=5, word_timestamps=False
        )

        segments = []
        full_text_parts = []
        for seg in raw_segments:
            segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
            full_text_parts.append(seg.text.strip())

        return " ".join(full_text_parts), segments

    def _chunk_transcript_by_time(
        self, segments: List[Dict], chunk_seconds: int = 60
    ) -> List[Dict]:
        chunks: List[Dict] = []
        current_texts: List[str] = []
        current_start = 0.0
        current_end = 0.0

        for seg in segments:
            current_texts.append(seg["text"])
            current_end = seg["end"]
            if current_end - current_start >= chunk_seconds:
                chunks.append({
                    "start": current_start,
                    "end": current_end,
                    "text": " ".join(current_texts),
                })
                current_start = seg["end"]
                current_texts = []

        if current_texts:
            chunks.append({
                "start": current_start,
                "end": current_end,
                "text": " ".join(current_texts),
            })

        return chunks

    def _get_transcript_for_time(
        self, timestamp_sec: float, chunks: List[Dict], window: float = 60.0
    ) -> str:
        relevant = [
            c["text"] for c in chunks
            if c["start"] <= timestamp_sec + window and c["end"] >= timestamp_sec - window
        ]
        return " ".join(relevant)[:1500]

    # ── Stage 3: keyframe extraction & visual analysis ─────────────────────────

    def extract_keyframes(
        self, video_path: str, interval: int, out_dir: str
    ) -> List[str]:
        log.info(f"Extracting keyframes every {interval}s...")
        cmd = [
            self._check_ffmpeg(), "-y", "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-s", "1280x720",
            "-q:v", "3",
            os.path.join(out_dir, "frame_%04d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Frame extraction failed: {result.stderr}")

        frames = sorted(Path(out_dir).glob("frame_*.jpg"))
        return [str(f) for f in frames]

    def _encode_frame_base64(self, frame_path: str) -> str:
        with open(frame_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def analyze_frames_with_claude(
        self,
        frame_paths: List[str],
        transcript_chunks: List[Dict],
        interval_seconds: int,
    ) -> List[Dict]:
        all_analyses: List[Dict] = []
        batches = [
            frame_paths[i : i + FRAME_BATCH_SIZE]
            for i in range(0, len(frame_paths), FRAME_BATCH_SIZE)
        ]

        log.info(f"Analyzing {len(frame_paths)} frames in {len(batches)} batches via Claude Vision...")

        for batch_idx, batch in enumerate(batches):
            log.info(f"  Batch {batch_idx + 1}/{len(batches)} ({len(batch)} frames)...")

            # build content list: alternating text+image blocks
            content: List[Any] = []
            timestamps = []

            for local_idx, frame_path in enumerate(batch):
                global_idx = batch_idx * FRAME_BATCH_SIZE + local_idx
                ts = global_idx * interval_seconds
                timestamps.append(ts)

                transcript_context = self._get_transcript_for_time(ts, transcript_chunks)

                content.append({
                    "type": "text",
                    "text": (
                        f"=== Frame {global_idx + 1} (timestamp ~{ts}s) ===\n"
                        f"Audio context at this time: {transcript_context or '(no audio)'}\n"
                        "Analyze this trading chart frame:"
                    ),
                })
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": self._encode_frame_base64(frame_path),
                    },
                })

            content.append({
                "type": "text",
                "text": self._build_vision_prompt(len(batch)),
            })

            response = self.client.messages.create(
                model=self.claude_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": content}],
            )

            raw = response.content[0].text
            batch_results = self._parse_frame_analyses(raw, batch, timestamps)
            all_analyses.extend(batch_results)

        return all_analyses

    def _build_vision_prompt(self, frame_count: int) -> str:
        return f"""
You are analyzing {frame_count} trading chart frame(s) from an educational video.
For each frame, extract what you can see and return a JSON array.

Return ONLY valid JSON (no markdown fences). Schema for each element:
{{
  "frame_idx": <int>,
  "timestamp_sec": <float>,
  "chart_type": "<candlestick|bar|line|renko|unknown>",
  "timeframe": "<M1|M5|M15|H1|H4|D1|unknown>",
  "detected_indicators": ["EMA", "RSI", ...],
  "indicator_settings": {{"EMA_Fast": 9, "EMA_Slow": 21, ...}},
  "chart_patterns": ["double top", "breakout", ...],
  "entry_signals": ["price above EMA, RSI > 50 = long entry"],
  "exit_signals": ["RSI > 70 = take profit"],
  "price_action_notes": "<brief description>",
  "market_context": "<trending|ranging|breakout|unknown>",
  "has_trading_content": <true|false>
}}

If the frame is not a trading chart (e.g. a person talking, title slide), set has_trading_content=false
and leave other fields as empty strings/arrays. Return the array even for non-chart frames.
"""

    def _parse_frame_analyses(
        self, raw: str, batch: List[str], timestamps: List[float]
    ) -> List[Dict]:
        json_str = self._extract_json(raw)
        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, list):
                parsed = [parsed]
        except json.JSONDecodeError:
            log.warning("Could not parse frame analysis JSON — using empty stubs")
            parsed = []

        results = []
        for i, frame_path in enumerate(batch):
            if i < len(parsed):
                item = parsed[i]
            else:
                item = {}
            item.setdefault("frame_idx", item.get("frame_idx", i))
            item.setdefault("timestamp_sec", timestamps[i] if i < len(timestamps) else 0)
            item["frame_path"] = frame_path
            results.append(item)

        return results

    # ── Stage 4: strategy synthesis ────────────────────────────────────────────

    def synthesize_strategy(
        self, frame_analyses: List[Dict], full_transcript: str
    ) -> Dict:
        log.info("Synthesizing strategy from all frames + transcript...")
        prompt = self._build_synthesis_prompt(frame_analyses, full_transcript)
        response = self.client.messages.create(
            model=self.claude_model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        return self._parse_strategy_json(raw)

    def _build_synthesis_prompt(
        self, frame_analyses: List[Dict], full_transcript: str
    ) -> str:
        trading_frames = [f for f in frame_analyses if f.get("has_trading_content")]
        analyses_summary = json.dumps(trading_frames[:20], indent=2)  # cap size
        transcript_excerpt = full_transcript[:4000]

        return f"""
You are a professional trading strategy analyst. You have analyzed {len(frame_analyses)} frames
from an educational trading video ({len(trading_frames)} contained actual charts).

VISUAL FINDINGS (frame analyses):
{analyses_summary}

AUDIO TRANSCRIPT (first 4000 chars):
{transcript_excerpt}

Extract a complete trading strategy from this material and return ONLY valid JSON (no markdown fences).
Use this exact schema:

{{
  "schema_version": "video_agent_v1",
  "strategy_name": "<descriptive name>",
  "strategy_type": "<trend_following|mean_reversion|breakout|scalping|swing|other>",
  "timeframes": ["M5", "H1"],
  "symbols": ["EURUSD", "XAUUSD"],
  "parameters": {{
    "EMA_Fast": 9,
    "EMA_Slow": 21,
    "RSI_Period": 14,
    "RSI_OB": 70,
    "RSI_OS": 30,
    "ATR_Period": 14,
    "ATR_SL_Multi": 1.5,
    "BB_Period": 20,
    "BB_Deviation": 2.0,
    "MACD_Fast": 12,
    "MACD_Slow": 26,
    "MACD_Signal": 9,
    "MomCandles": 2,
    "MinCandleBody": 0.3,
    "RiskPerTrade": 1.0,
    "RewardPerTrade": 2.0,
    "RequiredScore": 3,
    "RiskPct": 1.0
  }},
  "entry_rules": ["rule 1", "rule 2"],
  "exit_rules": ["rule 1", "rule 2"],
  "risk_management": {{
    "stop_loss_method": "<ATR-based|fixed_pips|structure|other>",
    "take_profit_method": "<fixed_RR|fixed_pips|trailing|structure|other>",
    "position_sizing": "<fixed_risk_pct|fixed_dollar|other>"
  }},
  "session_preference": "<London|NY|Asian|24h|unknown>",
  "confidence_score": 0.75,
  "extraction_quality": "<high|medium|low>",
  "notes": "<any caveats, ambiguities, or important context>"
}}

Only include parameters you actually observed. For unobserved parameters, use sensible defaults
matching typical scalping/swing strategies. Set confidence_score based on how clearly the strategy
was explained (1.0 = every detail was shown explicitly, 0.3 = mostly inferred).
"""

    def _parse_strategy_json(self, raw: str) -> Dict:
        json_str = self._extract_json(raw)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            log.warning("Strategy JSON parse failed — returning partial result")
            return {
                "schema_version": "video_agent_v1",
                "strategy_name": "Unknown (parse error)",
                "confidence_score": 0.0,
                "extraction_quality": "low",
                "notes": "Could not parse Claude's response as JSON.",
                "raw_response": raw[:2000],
            }

    def _extract_json(self, text: str) -> str:
        # strip ```json ... ``` fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        # try to find the outermost { } block
        start = text.find("{")
        if start == -1:
            start = text.find("[")
        if start != -1:
            return text[start:]
        return text

    # ── Stage 5: interactive chat ──────────────────────────────────────────────

    def _build_chat_system_prompt(
        self, strategy: Dict, frame_analyses: List[Dict]
    ) -> str:
        strategy_display = json.dumps(
            {k: v for k, v in strategy.items() if k not in ("raw_analysis", "_internal_transcript")},
            indent=2,
        )
        trading_count = sum(1 for f in frame_analyses if f.get("has_trading_content"))

        return f"""You are a trading strategy analyst assistant. The user has just analyzed a trading video.

EXTRACTED STRATEGY:
{strategy_display}

VIDEO STATS:
- Total frames analyzed: {len(frame_analyses)}
- Frames with trading charts: {trading_count}
- Confidence score: {strategy.get('confidence_score', 'N/A')}

Your role:
- Explain the extracted strategy clearly
- Answer questions about indicators, entry/exit rules, and parameters
- Suggest how to backtest this strategy using the existing MT5 bot framework
- Point out any gaps or ambiguities in the extracted strategy
- Help the user adapt the strategy to their existing setup (ScalpMaster HFT on EURUSD/XAUUSD/BTCUSD)

Be concise and practical. If the user asks about parameters not clearly shown in the video,
say so honestly rather than inventing values.
"""

    def _print_summary(self, strategy: Dict) -> None:
        name = strategy.get("strategy_name", "Unknown")
        stype = strategy.get("strategy_type", "unknown")
        tfs = ", ".join(strategy.get("timeframes", []))
        syms = ", ".join(strategy.get("symbols", []))
        conf = strategy.get("confidence_score", 0)
        quality = strategy.get("extraction_quality", "unknown")
        frame_count = strategy.get("raw_analysis", {}).get("frame_count_analyzed", "?")

        print("\n" + "=" * 60)
        print("  VIDEO ANALYSIS COMPLETE")
        print("=" * 60)
        print(f"  Strategy : {name}")
        print(f"  Type     : {stype}")
        print(f"  Timeframe: {tfs or 'unknown'}")
        print(f"  Symbols  : {syms or 'unknown'}")
        print(f"  Confidence: {conf:.0%}  |  Quality: {quality}")
        print(f"  Frames analyzed: {frame_count}")
        print("=" * 60)

        params = strategy.get("parameters", {})
        if params:
            print("\n  Key Parameters:")
            for k, v in list(params.items())[:8]:
                print(f"    {k}: {v}")
            if len(params) > 8:
                print(f"    ... and {len(params) - 8} more (use /params to see all)")

        entries = strategy.get("entry_rules", [])
        if entries:
            print("\n  Entry Rules:")
            for r in entries[:3]:
                print(f"    • {r}")

        notes = strategy.get("notes", "")
        if notes:
            print(f"\n  Notes: {notes[:200]}")

    def _handle_slash_command(
        self,
        cmd: str,
        strategy: Dict,
        frame_analyses: List[Dict],
        full_transcript: str,
    ) -> None:
        parts = cmd.strip().split()
        command = parts[0].lower()

        if command == "/export":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = self.output_dir / f"strategy_{ts}.json"
            self._save_strategy_json(strategy, str(out_path))
            print(f"Strategy saved to: {out_path}")

        elif command == "/params":
            params = strategy.get("parameters", {})
            if not params:
                print("No parameters extracted.")
            else:
                print("\nExtracted Parameters:")
                for k, v in params.items():
                    flag = " *" if k in KNOWN_PARAM_KEYS else ""
                    print(f"  {k}: {v}{flag}")
                print("  (* = maps directly to DEFAULT_PARAMS in config.py)")

        elif command == "/frames":
            if len(parts) >= 2:
                try:
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(frame_analyses):
                        f = frame_analyses[idx]
                        print(f"\nFrame {idx + 1} (t={f.get('timestamp_sec', '?')}s):")
                        for k, v in f.items():
                            if k not in ("frame_path", "frame_idx", "timestamp_sec"):
                                print(f"  {k}: {v}")
                    else:
                        print(f"Frame index out of range (1–{len(frame_analyses)})")
                except ValueError:
                    print("Usage: /frames <number>")
            else:
                print(f"Total frames: {len(frame_analyses)}")
                for i, f in enumerate(frame_analyses[:5]):
                    has_chart = f.get("has_trading_content", False)
                    tf = f.get("timeframe", "?")
                    print(f"  [{i + 1}] t={f.get('timestamp_sec', '?')}s  chart={has_chart}  tf={tf}")
                if len(frame_analyses) > 5:
                    print(f"  ... ({len(frame_analyses)} total — use /frames <n> to see a specific one)")

        elif command == "/transcript":
            if full_transcript:
                print(f"\nFull Transcript ({len(full_transcript)} chars):")
                print("-" * 40)
                print(full_transcript[:3000])
                if len(full_transcript) > 3000:
                    print(f"\n... (truncated — {len(full_transcript) - 3000} more chars)")
            else:
                print("No transcript available (video had no audio, or transcription was skipped).")

        else:
            print(f"Unknown command: {command}")
            print("Available: /export  /params  /frames [n]  /transcript")

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _save_strategy_json(self, strategy: Dict, output_path: str) -> None:
        save_strategy = {k: v for k, v in strategy.items() if k != "_internal_transcript"}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(save_strategy, f, indent=2, ensure_ascii=False)

    def _cleanup_temp_files(self, paths: List[str]) -> None:
        for p in paths:
            try:
                if Path(p).is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif Path(p).exists():
                    os.remove(p)
            except Exception as e:
                log.debug(f"Cleanup warning: {e}")


# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Video Analysis Agent — extract trading strategies from video files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python trading_agents/video_analysis_agent.py video.mp4
  python trading_agents/video_analysis_agent.py video.mp4 --whisper-model small
  python trading_agents/video_analysis_agent.py video.mp4 --frames 50 --no-chat
        """,
    )
    parser.add_argument("video", help="Path to video file (mp4, avi, mov, mkv, ...)")
    parser.add_argument(
        "--frames", type=int, default=30,
        help="Target number of keyframes to analyze (default: 30)",
    )
    parser.add_argument(
        "--whisper-model", default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size — larger = more accurate but slower (default: base)",
    )
    parser.add_argument(
        "--output-dir", default="trading_agents/extracted_strategies",
        help="Directory to save extracted strategy JSON",
    )
    parser.add_argument("--no-save", action="store_true", help="Do not save strategy JSON")
    parser.add_argument("--no-chat", action="store_true", help="Skip interactive chat loop")
    parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    agent = VideoAnalysisAgent(
        api_key=args.api_key,
        whisper_model=args.whisper_model,
        output_dir=args.output_dir,
    )

    strategy = agent.analyze_video(
        video_path=args.video,
        target_frames=args.frames,
        save_output=not args.no_save,
    )

    if not args.no_chat:
        agent.start_chat_loop(
            strategy=strategy,
            frame_analyses=strategy.get("raw_analysis", {}).get("frame_analyses", []),
            full_transcript=strategy.get("_internal_transcript", ""),
        )


if __name__ == "__main__":
    main()

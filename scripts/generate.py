"""
Entertainment Law Daily — Daily Lesson Generator (v3)
Reads curriculum.json, determines today's week/day/phase, then uses Claude with
web_search to find REAL entertainment law articles and generate structured JSON.

Outputs:
  data/weekWW/dayD.json   — lesson content (based on real articles)
  data/weekWW/dayD.mp3    — TTS audio of the reading passage
  data/index.json         — updated lesson index (consumed by the frontend)
"""

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import anthropic

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CURRICULUM_PATH = ROOT / "curriculum.json"
DATA_PATH = ROOT / "data"
INDEX_PATH = DATA_PATH / "index.json"

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8000   # Higher limit needed: web_search results + full lesson JSON


# ── Curriculum helpers ─────────────────────────────────────────────────────────

def load_curriculum() -> dict:
    with open(CURRICULUM_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_position(curriculum: dict) -> tuple:
    """Return (week_number, day_in_week 1–5, today) or sys.exit on weekend/pre-start."""
    start = date.fromisoformat(curriculum["start_date"])

    # Allow manual override via env var (useful for workflow_dispatch testing)
    override = os.environ.get("OVERRIDE_DATE", "").strip()
    today = date.fromisoformat(override) if override else date.today()

    if today < start:
        print(f"Course starts on {start}. Nothing to generate yet.")
        sys.exit(0)

    if today.weekday() >= 5:
        print(f"Weekend ({today.strftime('%A')}), skipping generation.")
        sys.exit(0)

    # Count working days elapsed since start_date (0-indexed).
    # Day 1 = first weekday of the course, regardless of which day of week it is.
    working_day = 0
    d = start
    while d < today:
        if d.weekday() < 5:
            working_day += 1
        d += timedelta(days=1)

    week_number = working_day // 5 + 1   # Week 1, 2, …
    day_in_week = working_day % 5 + 1    # Day 1–5
    return week_number, day_in_week, today


def get_phase_config(curriculum: dict, week_number: int) -> dict:
    for phase in curriculum["phases"]:
        if week_number in range(phase["weeks"][0], phase["weeks"][-1] + 1):
            return phase
    return curriculum["phases"][2]   # After week 12 → stay in Phase 3


def get_topic(curriculum: dict, week_number: int) -> dict:
    if 1 <= week_number <= curriculum["total_weeks"]:
        return curriculum["weekly_topics"][week_number - 1]
    return {
        "week": week_number,
        "theme_en": "Entertainment Law Current Events",
        "theme_cn": "娱乐法最新动态",
        "textbook_ref": "自由阅读",
        "key_terms": ["platform liability", "safe harbor", "regulatory convergence"],
        "search_keywords": [
            "entertainment law legal dispute 2025 2026",
            "entertainment industry court ruling settlement 2025",
        ],
    }


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _schema_for_phase(phase_cfg: dict, vocab_count: int) -> dict:
    """Build the expected JSON schema dict based on enabled features."""
    features = phase_cfg["features"]

    schema: dict = {
        "reading": {
            "title": "Actual title of the real article you found",
            "source": "Publication name + date (e.g. 'Hollywood Reporter, Jan 2026')",
            "url": "Actual URL of the source article",
            "text": (
                "A " + phase_cfg["reading_length"] + " excerpt or faithful paraphrase "
                "of the key legal content from the real article. "
                "Do NOT invent facts. Keep all legal terms verbatim. "
                "If paraphrasing, make it flow naturally as a reading passage."
            ),
            "word_count": "integer",
        },
        "vocabulary": [
            {
                "term": f"term #{i+1} — specialist legal/contractual term from the reading",
                "pronunciation": "/IPA notation/",
                "definition_cn": "中文释义（20-40字，聚焦法律含义）",
                "example": "One natural sentence using this term",
            }
            for i in range(vocab_count)
        ],
        "sentence_patterns": [
            {
                "pattern": "Reusable legal-writing template, e.g. '[Party] alleged that [claim], seeking [remedy].'",
                "example": "Sentence from or inspired by the reading",
                "translation_cn": "中文翻译",
            },
            {
                "pattern": "Second pattern",
                "example": "Example",
                "translation_cn": "中文翻译",
            },
            {
                "pattern": "Third pattern",
                "example": "Example",
                "translation_cn": "中文翻译",
            },
        ],
        "summary_cn": "100字以内的中文摘要，概括本篇主要内容",
        "legal_analysis": (
            "200-300字中文法律解读：① 核心法律问题；② 美国法律框架分析；"
            "③ 对中国娱乐法律师的实践启示"
        ),
    }

    if "cn_us_comparison" in features:
        schema["cn_us_comparison"] = (
            "150-250字中文对比分析：本文涉及的美国法律框架与中国相关法律制度的异同"
            "（须具体指出相关中国法律法规名称，如《著作权法》《合同法》等）"
        )

    if "podcast_summary" in features:
        schema["podcast_summary"] = {
            "episode": "Fictional but realistic 'The Hollywood Lawyer' podcast episode title on this topic",
            "description": "播客内容简介（100-150字中文）",
            "takeaways": ["要点1（中文）", "要点2（中文）", "要点3（中文）"],
        }

    if "discussion_prompt" in features:
        schema["discussion_prompt"] = (
            "One thought-provoking English question (1-2 sentences) for critical legal analysis"
        )

    if "writing_exercise" in features:
        schema["writing_exercise"] = {
            "prompt": "English writing prompt: ask the learner to write 2-3 sentences in the style of the reading",
            "model_answer": "Model answer (2-3 sentences demonstrating target sentence patterns)",
        }

    if "youtube_rec" in features:
        schema["youtube_rec"] = {
            "title": "Realistic YouTube video title on this week's legal topic",
            "channel": "Channel name (e.g. LegalEagle, CLE International, Law School Toolbox)",
            "summary_cn": "50-80字中文内容摘要",
        }

    schema["extended_reading"] = [
        {
            "title": "Title of real article #1 found via web search",
            "url": "Real URL found via web search",
            "description_cn": "一句话中文简介",
            "language": "en",
        },
        {
            "title": "Title of real article #2 — prefer academic/law review if possible",
            "url": "Real URL found via web search",
            "description_cn": "一句话中文简介",
            "language": "en",
        },
    ]

    return schema


def build_prompt(week: int, day: int, phase_cfg: dict, topic: dict) -> str:
    phase = phase_cfg["phase"]
    vocab_count = phase_cfg["vocab_count"]
    reading_length = phase_cfg["reading_length"]
    search_kws = topic.get("search_keywords", [])
    key_terms = topic.get("key_terms", [])

    difficulty_map = {
        1: "BEGINNER — clear news-report style; sentence structure is accessible, but VOCABULARY must be specialist legal terms",
        2: "INTERMEDIATE — legal-analysis style; cites case holdings, uses precise legal vocabulary and procedural language",
        3: "ADVANCED — policy-debate framing; critical analysis of emerging issues, sophisticated legal argument",
    }
    difficulty = difficulty_map[phase]

    schema = _schema_for_phase(phase_cfg, vocab_count)
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)

    search_primary = search_kws[0] if search_kws else f"entertainment law {topic['theme_en']}"
    search_fallback = search_kws[1] if len(search_kws) > 1 else f"{topic['theme_en']} legal case 2025"
    key_terms_str = ", ".join(key_terms)

    return f"""You are the content engine for "Entertainment Law Daily" — an English legal learning platform for Chinese entertainment lawyers.

Your job today: find a REAL article, then generate a complete lesson JSON from it.
Output ONLY the final JSON — no markdown, no code fences, no preamble.

━━━ TODAY'S LESSON ━━━
Week: {week}  |  Day: {day}  |  Phase {phase}: {phase_cfg['name']} ({phase_cfg['name_en']})
Theme: {topic['theme_en']} / {topic['theme_cn']}
Difficulty: {difficulty}
Key legal concepts for this week: {key_terms_str}

━━━ STEP 1 — FIND THE MAIN ARTICLE (use web_search) ━━━
Search for a REAL, substantive entertainment law article using:
  Primary query:  {search_primary}
  Fallback query: {search_fallback}

Preferred sources: hollywoodreporter.com, variety.com, law.com, deadline.com,
  billboard.com, thehollywoodlawyer.com, musicweek.com,
  fordhamiplj.org, ssrn.com, law school IP/entertainment law blogs

Prefer articles from 2024–2026. Choose the most legally substantive result
(court rulings, contract disputes, regulatory changes — not just industry gossip).

━━━ STEP 2 — BUILD READING SECTION ━━━
From the real article:
- "title": the actual article title
- "source": publication name + approximate date
- "url": the actual article URL
- "text": {reading_length} excerpt or faithful paraphrase of the core legal content.
  Do NOT fabricate facts. Preserve all legal terms verbatim.
  Write it as a coherent reading passage, not bullet points.

━━━ STEP 3 — PICK VOCABULARY (critical: must be specialist legal terms) ━━━
Select exactly {vocab_count} terms from the reading text.

✅ PICK: contract clauses, legal doctrines, procedural terms, statutory provisions,
   deal structures, remedies, jurisdiction-specific rules, industry-specific legal
   concepts — things a Chinese lawyer must look up in a US contract or court filing.

❌ NEVER PICK these categories (too basic):
   - Generic nouns: streaming, platform, content, industry, entertainment, music, film, video
   - Basic legal words: rights, agreement, contract, deal, IP, law, court, case, lawsuit
   - Everyday business: company, revenue, licensing, distribution, network, service

Each term must be something where a Chinese entertainment lawyer would genuinely
benefit from an English definition and a usage example.

━━━ STEP 4 — FIND EXTENDED READING (use web_search again) ━━━
Search for 2 additional REAL articles related to this week's theme.
Aim for: one practical news/analysis piece + one academic or law review piece.
Provide actual titles and working URLs.

━━━ FORMAT RULES ━━━
1. Every vocabulary "term" must appear verbatim in reading "text".
2. Produce EXACTLY {vocab_count} vocabulary items.
3. Produce EXACTLY 3 sentence_patterns (4 for Phase 2+).
4. All Chinese fields: professional legal/business Chinese.
5. Difficulty: {difficulty}.

━━━ EXPECTED JSON SCHEMA ━━━
{schema_str}

Start your response with {{ and end with }}. Output ONLY the JSON.
"""


# ── Content generation ─────────────────────────────────────────────────────────

def generate_lesson(prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    print(f"Calling {MODEL} with web_search enabled…")

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,   # up to 2 for main article + 3 for extended reading
        }],
        messages=[{"role": "user", "content": prompt}],
    )

    # Collect all text blocks — Anthropic handles web_search server-side;
    # the final answer arrives as one or more text blocks after the search results.
    raw = "".join(
        block.text for block in response.content
        if hasattr(block, "type") and block.type == "text"
    ).strip()

    if not raw:
        raise ValueError("Claude returned no text content (only tool calls, no final answer)")

    # Strip accidental markdown fences
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw.strip())

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(
            f"Could not parse JSON from Claude response.\n--- First 500 chars ---\n{raw[:500]}"
        )


# ── Index management ───────────────────────────────────────────────────────────

def update_index(week: int, day: int, today: date, topic: dict) -> None:
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"lessons": []}

    entry = {
        "week": week,
        "day": day,
        "date": today.isoformat(),
        "theme_en": topic["theme_en"],
        "theme_cn": topic["theme_cn"],
        "file": f"week{week:02d}/day{day}.json",
        "audio": f"week{week:02d}/day{day}.mp3",
    }

    existing_idx = next(
        (i for i, e in enumerate(index["lessons"]) if e["week"] == week and e["day"] == day),
        None,
    )
    if existing_idx is not None:
        index["lessons"][existing_idx] = entry
    else:
        index["lessons"].append(entry)

    index["lessons"].sort(key=lambda x: (x["week"], x["day"]))
    index["last_updated"] = today.isoformat()

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"Updated {INDEX_PATH.relative_to(ROOT)}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    curriculum = load_curriculum()
    week, day, today = calculate_position(curriculum)
    phase_cfg = get_phase_config(curriculum, week)
    topic = get_topic(curriculum, week)

    print(f"Week {week}, Day {day} ({today})  |  Phase {phase_cfg['phase']}: {topic['theme_en']}")

    # 1. Generate lesson JSON (with web search for real articles)
    prompt = build_prompt(week, day, phase_cfg, topic)
    lesson = generate_lesson(prompt)

    # 2. Inject metadata
    lesson.update({
        "week": week,
        "day": day,
        "date": today.isoformat(),
        "phase": phase_cfg["phase"],
        "theme_en": topic["theme_en"],
        "theme_cn": topic["theme_cn"],
        "audio_file": f"week{week:02d}/day{day}.mp3",
    })

    # 3. Save JSON
    week_dir = DATA_PATH / f"week{week:02d}"
    week_dir.mkdir(parents=True, exist_ok=True)

    json_path = week_dir / f"day{day}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(lesson, f, ensure_ascii=False, indent=2)
    print(f"Saved → {json_path.relative_to(ROOT)}")

    # 4. Generate TTS audio
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tts import generate_audio_sync
        audio_path = week_dir / f"day{day}.mp3"
        reading_text = lesson.get("reading", {}).get("text", "")
        if reading_text:
            generate_audio_sync(reading_text, str(audio_path))
        else:
            print("Warning: reading.text is empty, skipping TTS.")
    except Exception as exc:
        print(f"Warning: TTS generation failed ({exc}). Skipping audio.")

    # 5. Update lesson index
    update_index(week, day, today, topic)

    # 6. Export env vars for the GitHub Actions commit message
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"LESSON_WEEK={week}\n")
            f.write(f"LESSON_DAY={day}\n")
            f.write(f"LESSON_TOPIC={topic['theme_en']}\n")

    print("Done.")


if __name__ == "__main__":
    main()

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
from json_repair import repair_json

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


DIFFICULTY = {
    1: "BEGINNER — clear news-report style; accessible sentences, but vocabulary must be specialist legal terms",
    2: "INTERMEDIATE — legal-analysis style; cites holdings, uses precise procedural vocabulary",
    3: "ADVANCED — policy-debate framing; critical analysis, sophisticated legal argument",
}


def build_research_prompt(topic: dict) -> str:
    """Step 1 prompt: web_search only, returns plain text (no JSON)."""
    kws = topic.get("search_keywords", [])
    q1 = kws[0] if kws else f"entertainment law {topic['theme_en']} 2025"
    q2 = kws[1] if len(kws) > 1 else f"{topic['theme_en']} legal ruling 2024"

    return f"""You are a legal research assistant. Search the web and collect real article information.

TASK: Find 3 real, recent entertainment law articles on this topic:
  Theme: {topic['theme_en']} / {topic['theme_cn']}
  Primary search query:  {q1}
  Fallback search query: {q2}

Preferred sources: hollywoodreporter.com, variety.com, law.com, deadline.com,
  billboard.com, thehollywoodlawyer.com, fordhamiplj.org, ssrn.com

For each article found, output in this EXACT plain-text format (no JSON):

MAIN_TITLE: [title of the most legally substantive article]
MAIN_SOURCE: [publication name + date]
MAIN_URL: [article URL]
MAIN_CONTENT: [300-400 word summary of the key legal facts, arguments, and outcomes from the article]

EXT1_TITLE: [title of second article]
EXT1_URL: [URL]
EXT1_DESC: [one sentence about this article]

EXT2_TITLE: [title of third article — prefer academic/law review]
EXT2_URL: [URL]
EXT2_DESC: [one sentence about this article]

Output ONLY this plain text. No JSON, no markdown headers, no extra commentary."""


def build_json_prompt(research: str, week: int, day: int, phase_cfg: dict, topic: dict) -> str:
    """Step 2 prompt: pure JSON generation, no web_search, uses research from step 1."""
    phase = phase_cfg["phase"]
    vocab_count = phase_cfg["vocab_count"]
    reading_length = phase_cfg["reading_length"]
    key_terms_str = ", ".join(topic.get("key_terms", []))
    difficulty = DIFFICULTY[phase]

    schema = _schema_for_phase(phase_cfg, vocab_count)
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)

    return f"""You are generating a JSON lesson for "Entertainment Law Daily".

RESEARCH FINDINGS (from real articles):
{research}

━━━ LESSON PARAMETERS ━━━
Week: {week} | Day: {day} | Phase {phase}: {phase_cfg['name']}
Theme: {topic['theme_en']} / {topic['theme_cn']}
Difficulty: {difficulty}
Key legal concepts: {key_terms_str}

━━━ READING SECTION ━━━
Use MAIN_TITLE, MAIN_SOURCE, MAIN_URL, and MAIN_CONTENT from the research above.
- "text": write {reading_length} as a coherent reading passage based on MAIN_CONTENT.
  Preserve all legal terms verbatim. Do not invent facts.

━━━ VOCABULARY — CRITICAL RULES ━━━
Pick exactly {vocab_count} terms that appear verbatim in your "text".

✅ GOOD: contract clauses, legal doctrines, procedural terms, deal structures,
   statutory provisions, remedies — things needing lookup in a US contract or filing.

❌ BANNED (reject these, too basic):
   streaming, platform, content, industry, entertainment, music, film, video,
   rights, agreement, contract, deal, IP, law, court, case, lawsuit,
   company, revenue, licensing, distribution, network, service

━━━ EXTENDED READING ━━━
Use EXT1 and EXT2 from research above for the extended_reading array.

━━━ FORMAT RULES ━━━
1. Every vocabulary term must appear verbatim in reading text.
2. Exactly {vocab_count} vocabulary items.
3. Exactly 3 sentence_patterns (4 for Phase 2+).
4. All Chinese fields: professional legal/business Chinese.

━━━ JSON SCHEMA ━━━
{schema_str}"""


# ── Content generation (two-step) ──────────────────────────────────────────────

def _collect_text(response) -> str:
    """Collect all text blocks from an Anthropic API response."""
    return "".join(
        block.text for block in response.content
        if hasattr(block, "type") and block.type == "text"
    ).strip()


def _parse_json(raw: str) -> dict:
    """Parse JSON from raw string, with json-repair fallback."""
    # Strip accidental markdown fences
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # json-repair handles unescaped quotes, apostrophes, trailing commas, etc.
        repaired = repair_json(raw, return_objects=True)
        if isinstance(repaired, dict) and repaired:
            print("Note: JSON was repaired (likely unescaped quotes in text)")
            return repaired
        raise ValueError(f"No valid JSON found even after repair.\n--- First 500 chars ---\n{raw[:500]}")


def generate_lesson(week: int, day: int, phase_cfg: dict, topic: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ── Step 1: web_search → plain-text research findings ──────────────────────
    print("Step 1: searching for real articles…")
    research_prompt = build_research_prompt(topic)

    r1 = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": research_prompt}],
    )
    research = _collect_text(r1)
    if not research:
        raise ValueError("Step 1 returned no text content")
    print(f"Step 1 done ({len(research)} chars of research)")

    # ── Step 2: JSON generation (no web_search, system prompt enforces JSON) ───
    print("Step 2: generating lesson JSON…")
    json_prompt = build_json_prompt(research, week, day, phase_cfg, topic)

    r2 = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system="You are a JSON generator. Output ONLY raw JSON — no markdown, no code fences, no explanation. Your entire response must be a single valid JSON object starting with { and ending with }.",
        messages=[{"role": "user", "content": json_prompt}],
    )
    raw = _collect_text(r2)
    print("Step 2 done, parsing JSON…")
    return _parse_json(raw)


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

    # Guard: skip if this lesson already exists (prevents accidental overwrite).
    # Set FORCE_REGENERATE=1 to bypass this check.
    json_path_check = DATA_PATH / f"week{week:02d}" / f"day{day}.json"
    if json_path_check.exists() and not os.environ.get("FORCE_REGENERATE"):
        print(f"Lesson already exists at {json_path_check.relative_to(ROOT)}. Skipping.")
        print("To regenerate, set FORCE_REGENERATE=1 or use OVERRIDE_DATE for a different day.")
        sys.exit(0)

    # 1. Generate lesson JSON (two-step: web_search → plain text → JSON)
    lesson = generate_lesson(week, day, phase_cfg, topic)

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

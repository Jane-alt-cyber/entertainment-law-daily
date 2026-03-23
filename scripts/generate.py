"""
Entertainment Law Daily — Daily content generator
Calls Claude API with web_search to find real entertainment law news,
then generates structured JSON learning cards.
"""

import anthropic
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Content type rotation by weekday
# ---------------------------------------------------------------------------
CONTENT_ROTATION = {
    0: ("case",       "entertainment law case ruling verdict court decision"),
    1: ("news",       "entertainment industry law news legal development"),
    2: ("deal",       "entertainment industry contract deal negotiation license"),
    3: ("ip",         "copyright intellectual property entertainment music film"),
    4: ("regulation", "entertainment industry regulation policy streaming gaming"),
    5: ("case",       "music film TV legal dispute lawsuit settlement"),
    6: ("news",       "streaming gaming digital media entertainment law development"),
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert entertainment law educator creating daily English study materials for Chinese lawyers.

Your task: Search for a REAL, RECENT entertainment law topic using web search, then generate a structured learning card based on it.

CRITICAL REQUIREMENTS:
1. Use web search to find a real, recent story (past 1-3 months preferred)
2. The English reading passage should be exactly 2 paragraphs, 200-300 words total
3. If the source material is long, create a summary + key excerpt approach
4. Extract 6-8 key legal/industry vocabulary terms with Chinese translations
5. Extract 3-4 notable English sentence patterns with Chinese explanations
6. Provide a Chinese legal analysis (法律解读), referencing relevant Chinese law where applicable

RESPOND ONLY WITH THIS EXACT JSON FORMAT (no markdown, no backticks, no code fences):
{
  "date": "YYYY-MM-DD",
  "title_en": "Short English title",
  "title_cn": "中文标题",
  "content_type": "case|news|deal|ip|regulation",
  "source_hint": "Brief source description (e.g. 'Based on Variety reporting, March 2026')",
  "reading": {
    "paragraph1": "First paragraph (100-150 words)...",
    "paragraph2": "Second paragraph (100-150 words)..."
  },
  "vocabulary": [
    {
      "term": "English term",
      "phonetic": "/fəˈnɛtɪk/",
      "cn": "中文释义",
      "example": "Example sentence from or inspired by the passage"
    }
  ],
  "sentence_patterns": [
    {
      "pattern": "English sentence pattern template (use ___ for blanks)",
      "example": "Concrete example from the passage",
      "cn_explanation": "中文句式说明：结构分析 + 使用场景"
    }
  ],
  "legal_analysis": {
    "summary_cn": "中文法律解读（2-3段，覆盖：①本案/新闻的核心法律问题；②美国/国际法律框架分析；③与中国相关法律的对比；④对中国娱乐法实务的启示）",
    "key_laws_referenced": ["Relevant US/international law names", "相关中国法律法规名称"]
  },
  "discussion_question": "A thought-provoking discussion question in English related to the topic"
}"""


def build_user_prompt(today: date, content_type: str, search_hint: str) -> str:
    return (
        f"Today is {today.isoformat()}. "
        f"Please search for a recent {content_type} topic in entertainment law using these keywords: \"{search_hint}\". "
        "Focus on US/international entertainment industry — music, film, TV, gaming, streaming, "
        "talent management, or digital media. Find something from the past 1-3 months if possible. "
        "Generate the complete learning card JSON as instructed."
    )


# ---------------------------------------------------------------------------
# JSON extraction & validation
# ---------------------------------------------------------------------------
def extract_json(text: str) -> dict:
    """Extract and parse JSON from Claude's response text."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Strip possible markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        pass

    # Find the outermost JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group())

    raise ValueError("No valid JSON found in response")


def validate(data: dict) -> None:
    """Basic validation; raises ValueError on failure."""
    reading = data.get("reading", {})
    if not reading.get("paragraph1") or not reading.get("paragraph2"):
        raise ValueError("reading.paragraph1 or paragraph2 is empty")

    vocab = data.get("vocabulary", [])
    if len(vocab) < 4:
        raise ValueError(f"vocabulary has only {len(vocab)} items (need >= 4)")

    if not data.get("title_en"):
        raise ValueError("title_en is missing")

    if not data.get("legal_analysis", {}).get("summary_cn"):
        raise ValueError("legal_analysis.summary_cn is missing")


# ---------------------------------------------------------------------------
# Main generation logic with retry
# ---------------------------------------------------------------------------
def generate(client: anthropic.Anthropic, today: date, content_type: str, search_hint: str) -> dict:
    user_prompt = build_user_prompt(today, content_type, search_hint)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Collect all text blocks
    text_content = ""
    for block in response.content:
        if block.type == "text":
            text_content += block.text

    if not text_content.strip():
        raise ValueError("Claude returned no text content")

    data = extract_json(text_content)
    data["date"] = today.isoformat()  # always enforce correct date
    validate(data)
    return data


def generate_with_retry(client: anthropic.Anthropic, today: date, content_type: str, search_hint: str,
                        max_retries: int = 3, delay: int = 10) -> dict:
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[Attempt {attempt}/{max_retries}] Generating {content_type} content for {today}...")
            data = generate(client, today, content_type, search_hint)
            print(f"  ✓ Success: {data.get('title_en', '(no title)')}")
            return data
        except Exception as e:
            last_error = e
            print(f"  ✗ Attempt {attempt} failed: {e}")
            if attempt < max_retries:
                print(f"  Retrying in {delay}s...")
                time.sleep(delay)

    raise RuntimeError(f"All {max_retries} attempts failed. Last error: {last_error}") from last_error


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    content_type, search_hint = CONTENT_ROTATION[today.weekday()]

    client = anthropic.Anthropic(api_key=api_key)

    try:
        data = generate_with_retry(client, today, content_type, search_hint)
    except RuntimeError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine repo root (script is at scripts/generate.py)
    repo_root = Path(__file__).parent.parent
    data_dir = repo_root / "data"
    archive_dir = data_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    latest_path = data_dir / "latest.json"
    archive_path = archive_dir / f"{today.isoformat()}.json"

    for path in (latest_path, archive_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Written: {path}")

    print("Done.")


if __name__ == "__main__":
    main()

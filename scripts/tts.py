"""
TTS helper using edge-tts (Microsoft Edge Neural voices).
Free, high-quality, no API key required.
"""

import asyncio
import sys
import edge_tts

VOICE = "en-US-JennyNeural"   # Natural female voice, good for legal reading
RATE = "-10%"                  # Slightly slower than default for learning


async def generate_audio(text: str, output_path: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(output_path)
    print(f"[TTS] Audio saved to {output_path}")


def generate_audio_sync(text: str, output_path: str) -> None:
    asyncio.run(generate_audio(text, output_path))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python tts.py <text> <output.mp3>")
        sys.exit(1)
    generate_audio_sync(sys.argv[1], sys.argv[2])

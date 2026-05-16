"""Generate TTS narration + word timestamps using edge-tts."""
import asyncio
import edge_tts
import json

VOICE = 'zh-CN-XiaoyiNeural'
RATE = '+15%'

async def main():
    with open('script.txt', 'r', encoding='utf-8') as f:
        script = f.read()
    communicate = edge_tts.Communicate(script, VOICE, rate=RATE)

    audio_data = b""
    word_times = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            word_times.append({
                "text": chunk["text"],
                "offset": round(chunk["offset"] / 1e7, 3),
                "duration": round(chunk["duration"] / 1e7, 3),
            })

    with open("narration.wav", "wb") as f:
        f.write(audio_data)
    with open("word_timestamps.json", "w", encoding="utf-8") as f:
        json.dump(word_times, f, ensure_ascii=False, indent=2)

    print(f"已生成 narration.wav（{len(audio_data)} bytes, {len(word_times)} 个句段时间戳）")

if __name__ == '__main__':
    asyncio.run(main())

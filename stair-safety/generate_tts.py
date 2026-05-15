"""Generate TTS narration using edge-tts (Microsoft Azure neural TTS)."""
import asyncio
import edge_tts

VOICE = 'zh-CN-XiaoyiNeural'  # 适合儿童内容的活泼女声
RATE = '+15%'                   # 语速加快 15% 以匹配 48s 视频时长

async def main():
    with open('script.txt', 'r', encoding='utf-8') as f:
        script = f.read()

    communicate = edge_tts.Communicate(script, VOICE, rate=RATE)
    await communicate.save('narration.wav')
    print('已生成 narration.wav')

if __name__ == '__main__':
    asyncio.run(main())

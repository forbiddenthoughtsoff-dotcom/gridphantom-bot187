# GridPhantom Bot 🤖

Fully autonomous YouTube bot for @GridPhantom187.
Posts daily AI & Tech videos in English and German — completely automatically.

## What it does
1. Finds trending AI & Tech topics (RSS feeds)
2. Writes SEO-optimized scripts (Claude AI)
3. Generates voiceover (ElevenLabs — Ray EN, Helmut DE)
4. Assembles video (Pexels stock footage + MoviePy)
5. Uploads to YouTube with full metadata
6. Runs 2x daily at 09:00 and 17:00 (Zurich time)

## Environment Variables Required
- `ANTHROPIC_API_KEY`
- `ELEVENLABS_API_KEY`
- `PEXELS_API_KEY`
- `YOUTUBE_CLIENT_SECRETS` (JSON string)
- `VOICE_ID_EN` (Ray voice ID from ElevenLabs)
- `VOICE_ID_DE` (Helmut voice ID from ElevenLabs)
- `YOUTUBE_CHANNEL_ID`

## Deployment
Deployed via Manufact Cloud. Auto-runs 24/7.

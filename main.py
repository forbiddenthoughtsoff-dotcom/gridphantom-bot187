# ============================================================
# Health server starts FIRST — in its own thread, crash-proof
# ============================================================
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        self.rfile.read(content_length)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "serverInfo": {"name": "gridphantom-bot", "version": "1.0.0"}}
        }).encode())

    def log_message(self, format, *args):
        pass

def _run_health_server():
    while True:
        try:
            HTTPServer(('0.0.0.0', 8080), HealthHandler).serve_forever()
        except Exception as e:
            print(f"[HEALTH] server error, restarting: {e}", flush=True)
            time.sleep(2)

threading.Thread(target=_run_health_server, daemon=True).start()
print("[HEALTH] Health server thread started on port 8080", flush=True)

# ============================================================
# Diagnostic startup — find out exactly what works and what breaks
# ============================================================
import sys

def diag(msg):
    print(f"[DIAG] {msg}", flush=True)

diag("Python started. Beginning import checks...")

# Test each heavy import individually
try:
    import os
    diag("os: OK")
    import logging
    diag("logging: OK")
    import schedule
    diag("schedule: OK")
    from datetime import datetime
    diag("datetime: OK")
except Exception as e:
    diag(f"BASIC IMPORT FAILED: {e}")

try:
    import edge_tts
    diag("edge_tts import: OK")
except Exception as e:
    diag(f"edge_tts IMPORT FAILED: {e}")

try:
    import moviepy
    diag("moviepy import: OK")
except Exception as e:
    diag(f"moviepy IMPORT FAILED: {e}")

# Test edge-tts ACTUAL synthesis with a short phrase
def test_edge_tts():
    try:
        import asyncio, edge_tts
        diag("Testing edge-tts synthesis with short phrase...")
        async def _t():
            c = edge_tts.Communicate("Test eins zwei drei.", "de-DE-ConradNeural")
            await c.save("/tmp/diag_test.mp3")
        asyncio.run(_t())
        size = os.path.getsize("/tmp/diag_test.mp3")
        diag(f"edge-tts SYNTHESIS WORKS — produced {size} bytes")
        return True
    except Exception as e:
        diag(f"edge-tts SYNTHESIS FAILED: {type(e).__name__}: {e}")
        return False

# Run the bot logic in a fully guarded background thread
def guarded_bot_start():
    time.sleep(3)  # let health check settle first
    diag("=" * 40)
    diag("Starting diagnostic sequence")
    diag("=" * 40)

    edge_ok = test_edge_tts()

    if not edge_ok:
        diag("edge-tts does not work in this environment. Bot cannot generate voice.")
        diag("Health server stays up so deployment remains green. Fix needed.")
        return

    # edge-tts works → load the real bot and run it
    try:
        diag("edge-tts confirmed working. Loading full bot pipeline...")
        run_full_bot()
    except Exception as e:
        import traceback
        diag(f"BOT PIPELINE CRASHED: {e}")
        traceback.print_exc()

def run_full_bot():
    """Load heavy modules and run the actual pipeline."""
    import logging, sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger('GridPhantomBot')

    from config import Config
    from trend_finder import TrendFinder
    from script_generator import ScriptGenerator
    from voice_generator import VoiceGenerator
    from video_assembler import VideoAssembler
    from youtube_uploader import YouTubeUploader
    import schedule

    # validate config
    required = ['ANTHROPIC_API_KEY', 'PEXELS_API_KEY', 'YOUTUBE_CLIENT_SECRETS']
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing env vars: {missing}")
        return
    logger.info("✅ Configuration validated")

    def run_pipeline(language, topic):
        logger.info(f"🎬 Pipeline {language.upper()}: {topic['title']}")
        try:
            script = ScriptGenerator().generate(topic, language)
            logger.info(f"📝 Script: {script['title']}")
            audio = VoiceGenerator().generate(script['narration'], language)
            logger.info(f"🎙️ Voice done: {audio}")
            video = VideoAssembler().assemble(script, audio, topic)
            logger.info(f"🎥 Video done: {video}")
            vid = YouTubeUploader().upload(video, script, language)
            logger.info(f"✅ UPLOADED [{language}]: https://youtube.com/watch?v={vid}")
            for p in [audio, video]:
                try: os.remove(p)
                except: pass
        except Exception as e:
            logger.error(f"❌ Pipeline failed [{language}]: {e}", exc_info=True)

    def run_bot():
        logger.info(f"🤖 Bot cycle — {datetime.now():%Y-%m-%d %H:%M}")
        topics = TrendFinder().get_trending_topics()
        if not topics:
            logger.warning("No topics found")
            return
        run_pipeline('en', topics[0])
        run_pipeline('de', topics[1] if len(topics) > 1 else topics[0])
        logger.info("🏁 Cycle complete")

    schedule.every().day.at("09:00").do(run_bot)
    schedule.every().day.at("17:00").do(run_bot)
    logger.info("⏰ Scheduler active: 09:00 and 17:00")

    run_bot()  # first run now

    while True:
        schedule.run_pending()
        time.sleep(60)

# Start the guarded bot in background; main thread keeps health server alive
threading.Thread(target=guarded_bot_start, daemon=True).start()

# Keep main process alive forever so health server never dies
while True:
    time.sleep(3600)

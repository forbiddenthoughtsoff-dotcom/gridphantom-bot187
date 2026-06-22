# PIL patch before any moviepy import
try:
    from PIL import Image
    if not hasattr(Image, 'ANTIALIAS'):
        Image.ANTIALIAS = Image.LANCZOS
except Exception:
    pass

# Health server starts FIRST
import json, threading, time, os, sys, logging, schedule
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

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
            print(f"[HEALTH] error, restarting: {e}", flush=True)
            time.sleep(2)

threading.Thread(target=_run_health_server, daemon=True).start()
print("[HEALTH] Health server started on port 8080", flush=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('GridPhantomBot')

def run_pipeline(language: str, topic: dict, mode: str = 'short'):
    """Run full pipeline for one language and mode."""
    os.environ['VIDEO_MODE'] = mode
    logger.info(f"🎬 Pipeline {language.upper()} [{mode}]: {topic['title']}")
    try:
        from script_generator import ScriptGenerator
        from voice_generator import VoiceGenerator
        from video_assembler import VideoAssembler
        from youtube_uploader import YouTubeUploader

        script = ScriptGenerator().generate(topic, language)
        logger.info(f"📝 Script: {script.get('title', '')}")

        audio = VoiceGenerator().generate(script['narration'], language)
        logger.info(f"🎙️ Voice done: {audio}")

        video = VideoAssembler().assemble(script, audio, topic)
        logger.info(f"🎥 Video done: {video}")

        vid = YouTubeUploader().upload(video, script, language)
        logger.info(f"✅ UPLOADED [{language}]: https://youtube.com/watch?v={vid}")

        for p in [audio, video]:
            try: os.remove(p)
            except: pass

        return vid
    except Exception as e:
        logger.error(f"❌ Pipeline failed [{language}/{mode}]: {e}", exc_info=True)
        return None

def run_bot_short():
    """4x daily: 45-second Shorts for reach."""
    logger.info(f"🤖 SHORT cycle — {datetime.now():%Y-%m-%d %H:%M}")
    try:
        from trend_finder import TrendFinder
        topics = TrendFinder().get_trending_topics()
        if not topics:
            logger.warning("No topics found")
            return
        run_pipeline('en', topics[0], mode='short')
        run_pipeline('de', topics[1] if len(topics) > 1 else topics[0], mode='short')
        logger.info("🏁 Short cycle complete")
    except Exception as e:
        logger.error(f"Short cycle error: {e}", exc_info=True)

def run_bot_long():
    """2x daily: 2-3 minute videos for monetization."""
    logger.info(f"🤖 LONG cycle — {datetime.now():%Y-%m-%d %H:%M}")
    try:
        from trend_finder import TrendFinder
        topics = TrendFinder().get_trending_topics()
        if not topics:
            logger.warning("No topics found")
            return
        run_pipeline('en', topics[2] if len(topics) > 2 else topics[0], mode='long')
        run_pipeline('de', topics[3] if len(topics) > 3 else topics[0], mode='long')
        logger.info("🏁 Long cycle complete")
    except Exception as e:
        logger.error(f"Long cycle error: {e}", exc_info=True)

def validate_config():
    required = ['ANTHROPIC_API_KEY', 'PEXELS_API_KEY', 'YOUTUBE_CLIENT_SECRETS']
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing env vars: {missing}")
        sys.exit(1)
    logger.info("✅ Configuration validated")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  GridPhantom Bot — @GridPhantom187")
    logger.info("=" * 60)

    validate_config()

    # 4x Shorts daily
    schedule.every().day.at("07:00").do(run_bot_short)
    schedule.every().day.at("11:00").do(run_bot_short)
    schedule.every().day.at("15:00").do(run_bot_short)
    schedule.every().day.at("20:00").do(run_bot_short)
    # 2x Long-form daily
    schedule.every().day.at("09:00").do(run_bot_long)
    schedule.every().day.at("18:00").do(run_bot_long)
    logger.info("⏰ Shorts: 07 11 15 20 | Long: 09 18")

    # First run immediately in background
    threading.Thread(target=run_bot_short, daemon=True).start()

    while True:
        schedule.run_pending()
        time.sleep(60)

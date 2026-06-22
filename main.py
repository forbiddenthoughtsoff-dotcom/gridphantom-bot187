# --- Health server starts FIRST, before any heavy imports ---
import json
import threading
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
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "gridphantom-bot", "version": "1.0.0"}
            }
        })
        self.wfile.write(response.encode())

    def log_message(self, format, *args):
        pass

def _run_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    server.serve_forever()

# Start health server immediately in a background thread,
# BEFORE importing any heavy modules (moviepy, edge_tts, etc.)
threading.Thread(target=_run_health_server, daemon=True).start()

# --- Now the rest of the imports ---
import schedule
import time
import logging
import os
import sys
from datetime import datetime

from config import Config
from trend_finder import TrendFinder
from script_generator import ScriptGenerator
from voice_generator import VoiceGenerator
from video_assembler import VideoAssembler
from youtube_uploader import YouTubeUploader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/gridphantom-bot.log')
    ]
)
logger = logging.getLogger('GridPhantomBot')

def validate_config():
    """Ensure all required environment variables are set"""
    required = [
        'ANTHROPIC_API_KEY',
        'PEXELS_API_KEY',
        'YOUTUBE_CLIENT_SECRETS',
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing environment variables: {missing}")
        sys.exit(1)
    logger.info("✅ Configuration validated")

def run_pipeline(language: str, topic: dict):
    """Run the full content pipeline for one language"""
    logger.info(f"🎬 Starting pipeline: {language.upper()} | {topic['title']}")

    try:
        logger.info("📝 Generating script...")
        script_gen = ScriptGenerator()
        script = script_gen.generate(topic, language)

        logger.info("🎙️ Generating voice...")
        voice_gen = VoiceGenerator()
        audio_path = voice_gen.generate(script['narration'], language)

        logger.info("🎥 Assembling video...")
        assembler = VideoAssembler()
        video_path = assembler.assemble(script, audio_path, topic)

        logger.info("📤 Uploading to YouTube...")
        uploader = YouTubeUploader()
        video_id = uploader.upload(video_path, script, language)

        for path in [audio_path, video_path]:
            try:
                os.remove(path)
            except:
                pass

        logger.info(f"✅ SUCCESS [{language.upper()}]: https://youtube.com/watch?v={video_id}")
        return video_id

    except Exception as e:
        logger.error(f"❌ Pipeline failed [{language}]: {e}", exc_info=True)
        return None

def run_bot():
    """Main bot cycle — find topics, create and upload videos"""
    logger.info(f"🤖 GridPhantom Bot running — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    trend_finder = TrendFinder()
    topics = trend_finder.get_trending_topics()

    if not topics:
        logger.warning("No trending topics found — retrying next cycle")
        return

    best_topic = topics[0]
    second_topic = topics[1] if len(topics) > 1 else topics[0]

    logger.info(f"📊 Best topic: {best_topic['title']}")

    run_pipeline('en', best_topic)
    run_pipeline('de', second_topic)

    logger.info("🏁 Bot cycle complete")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  GridPhantom Bot — @GridPhantom187")
    logger.info("  Fully Autonomous AI & Tech YouTube Channel")
    logger.info("=" * 60)
    logger.info("🌐 Health server already running on port 8080")

    validate_config()

    schedule.every().day.at("09:00").do(run_bot)
    schedule.every().day.at("17:00").do(run_bot)
    logger.info("⏰ Scheduler active: 09:00 and 17:00 daily")

    # First cycle in background so the scheduler loop stays responsive
    threading.Thread(target=run_bot, daemon=True).start()

    while True:
        schedule.run_pending()
        time.sleep(60)

# -*- coding: utf-8 -*-
# Set timezone to Zurich so schedule times match local expectations
import os as _os, time as _time
_os.environ['TZ'] = 'Europe/Zurich'
try:
    _time.tzset()
except Exception:
    pass

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

def run_pipeline(language: str = 'de'):
    """Run full pipeline: GTA Short des Tages."""
    logger.info(f"🎬 Pipeline {language.upper()}: GTA Short generieren")
    try:
        from script_generator import ScriptGenerator
        from voice_generator import VoiceGenerator
        from video_assembler import VideoAssembler
        from youtube_uploader import YouTubeUploader
        from news_fetcher import fetch_recent_news

        uploader = YouTubeUploader()
        recent = uploader.get_recent_performance()
        recent_titles = [r['title'] for r in recent]
        # Feedback loop: the channel's best-performing recent videos
        # (views/hour) teach the generator which angles and hooks work
        top_performers = sorted(
            [r for r in recent if r['rate'] > 0],
            key=lambda r: r['rate'], reverse=True)[:5]
        if top_performers:
            logger.info("📈 Top performers: " + " | ".join(
                f"{t['title'][:40]} ({t['views']}v)" for t in top_performers))

        # Live GTA news to ground the script (falls back to evergreen if empty)
        try:
            news_items = fetch_recent_news()
        except Exception as e:
            logger.warning(f"News fetch failed, evergreen fallback: {e}")
            news_items = []

        script = ScriptGenerator().generate(language,
                                            avoid_titles=recent_titles,
                                            news_items=news_items,
                                            top_performers=top_performers)
        logger.info(f"📝 Script: {script.get('title', '')}")

        audio = VoiceGenerator().generate(script['narration'], language)
        logger.info(f"🎙️ Voice done: {audio}")
        import voice_generator as _vg
        if _vg.LAST_ENGINE == 'elevenlabs':
            script['voice_credit'] = 'ElevenLabs (elevenlabs.io)'

        # Owner's PS5 clips: pick up anything dropped into the shared Drive
        # folder minutes ago (no-op unless GAMEPLAY_DRIVE_FOLDER is set)
        try:
            from gameplay_sync import sync as sync_gameplay
            sync_gameplay(time_budget=120)
        except Exception as e:
            logger.warning(f"Gameplay sync skipped: {e}")

        video = VideoAssembler().assemble(script, audio)
        logger.info(f"🎥 Video done: {video}")

        vid = uploader.upload(video, script, language)
        if vid:
            logger.info(f"✅ UPLOADED [{language}]: https://youtube.com/watch?v={vid}")
            from community_manager import CommunityManager
            CommunityManager(uploader.service).seed_comment(vid, script)
        else:
            logger.error(f"❌ Upload returned None for [{language}]")

        for p in [audio, video]:
            try: os.remove(p)
            except: pass

        return vid
    except Exception as e:
        logger.error(f"❌ Pipeline failed [{language}]: {e}", exc_info=True)
        return None

def run_bot_short(is_retry: bool = False):
    """Scheduled slot: 1 German GTA Short."""
    logger.info(f"🤖 SHORT cycle — {datetime.now():%Y-%m-%d %H:%M}"
                + (" (retry)" if is_retry else ""))
    vid = None
    try:
        vid = run_pipeline(language='de')
        logger.info("🏁 Short cycle complete")
    except Exception as e:
        logger.error(f"Short cycle error: {e}", exc_info=True)

    # Don't silently lose the slot on a transient failure (API hiccup,
    # rate limit, empty credits that get topped up) — retry once
    if vid is None and not is_retry:
        logger.warning("⏳ Slot failed — retrying once in 30 minutes")

        def _retry():
            run_bot_short(is_retry=True)
            return schedule.CancelJob

        schedule.every(30).minutes.do(_retry)

def run_engagement():
    """Reply to new viewer comments across recent videos."""
    logger.info(f"💬 ENGAGEMENT cycle — {datetime.now():%Y-%m-%d %H:%M}")
    try:
        from youtube_uploader import YouTubeUploader
        from community_manager import CommunityManager
        CommunityManager(YouTubeUploader().service).respond_to_comments()
    except Exception as e:
        logger.error(f"Engagement cycle error: {e}", exc_info=True)

def validate_config():
    required = ['ANTHROPIC_API_KEY', 'YOUTUBE_CLIENT_SECRETS']
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing env vars: {missing} — bot will not post until fixed")
    else:
        logger.info("✅ Configuration validated")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  GridPhantom Bot — @GridPhantom187")
    logger.info("=" * 60)

    validate_config()

    # English only — morning post, midday short, evening post (Zürich time)
    schedule.every().day.at("07:00").do(run_bot_short)
    schedule.every().day.at("12:00").do(run_bot_short)
    schedule.every().day.at("17:00").do(run_bot_short)
    schedule.every().day.at("22:00").do(run_bot_short)
    logger.info("⏰ 4x daily GTA Shorts: 07 | 12 | 17 | 22 (DE)")
    try:
        from trailer_library import ensure_trailers_async
        ensure_trailers_async()  # background prefetch of official GTA VI trailers
    except Exception as e:
        logger.warning(f"Trailer prefetch not started: {e}")
    try:
        from gameplay_sync import sync_async, folder_id
        if folder_id():
            sync_async()  # owner's own PS5 clips from the shared Drive folder
            schedule.every(2).hours.do(sync_async)
            logger.info("🎮 Gameplay sync: shared Drive folder, every 2h")
        else:
            logger.info("🎮 Gameplay sync off (set GAMEPLAY_DRIVE_FOLDER to a shared folder)")
    except Exception as e:
        logger.warning(f"Gameplay sync not started: {e}")

    # Community management: answer viewer comments every 2 hours
    schedule.every(2).hours.do(run_engagement)
    logger.info("💬 Engagement: comment replies every 2h")

    # Immediate post on startup only if explicitly enabled — otherwise every
    # deploy/restart uploads an unscheduled extra video
    if os.environ.get('POST_ON_START', '').lower() in ('1', 'true', 'yes'):
        logger.info("🚀 POST_ON_START enabled — posting immediately")
        threading.Thread(target=run_bot_short, daemon=True).start()
    else:
        logger.info("⏭️ Startup post disabled (set POST_ON_START=true to enable)")

    while True:
        schedule.run_pending()
        time.sleep(60)

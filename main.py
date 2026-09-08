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

# Own PROCESS, not a thread: during a long export the render holds the GIL
# for seconds at a time and a health probe on the thread could time out —
# the platform then restarts the container mid-render. Forked before any
# heavy import, so the child is tiny and immune to the main process' load.
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.get_context('fork').Process(
        target=_run_health_server, daemon=True, name='health').start()
    print("[HEALTH] Health server started on port 8080 (own process)", flush=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('GridPhantomBot')

def owner_brief() -> dict:
    """Owner's assignment for the startup post: TOPIC_BRIEF_JSON holds a
    base64-encoded JSON {"brief": "...", "images": [urls]} — a specific,
    in-depth video with its own footage. Empty dict when not set."""
    raw = os.environ.get('TOPIC_BRIEF_JSON', '').strip()
    if not raw:
        return {}
    try:
        import base64
        data = json.loads(base64.b64decode(raw).decode('utf-8'))
        return data if isinstance(data, dict) and data.get('brief') else {}
    except Exception as e:
        logger.warning(f"TOPIC_BRIEF_JSON unreadable: {e}")
        return {}


def run_pipeline(language: str = 'de', brief: dict = None):
    """Run full pipeline: GTA Short des Tages (or the owner's assignment)."""
    brief = brief or {}
    logger.info(f"🎬 Pipeline {language.upper()}: GTA Short generieren"
                + (" — OWNER ASSIGNMENT" if brief else ""))
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

        # Owner's series "GTA Online Karriere": the midday slot publishes the
        # next tutorial episode (progress is read from the published titles)
        if not brief:
            try:
                from series import is_series_slot, next_episode, brief_for
                if is_series_slot():
                    ep = next_episode(recent_titles)
                    if ep:
                        brief = brief_for(ep)
                        logger.info(f"📚 Serie: Karriere-Tutorial #{ep['n']} – "
                                    f"{ep['career']} Stufe {ep['tier']}")
            except Exception as e:
                logger.warning(f"Series slot skipped: {e}")

        script = ScriptGenerator().generate(language,
                                            avoid_titles=recent_titles,
                                            news_items=news_items,
                                            top_performers=top_performers,
                                            topic_brief=brief.get('brief'))
        if brief.get('images'):
            script['still_images'] = list(brief['images'])
        logger.info(f"📝 Script: {script.get('title', '')}")

        audio = VoiceGenerator().generate(script['narration'], language)
        logger.info(f"🎙️ Voice done: {audio}")
        import voice_generator as _vg
        if _vg.LAST_ENGINE == 'elevenlabs':
            script['voice_credit'] = 'ElevenLabs (elevenlabs.io)'

        # The whole render (trailer/still/gameplay montage + export) gets the
        # box to itself: the background clip sync pauses between jobs while
        # this flag is set (a montage cut timed out behind a proxy job once)
        try:
            from gameplay_sync import RENDER_BUSY
            RENDER_BUSY.set()
        except Exception:
            RENDER_BUSY = None
        # Fresh container (empty /tmp) and no owner stills: pull a few own
        # PS5 clips NOW rather than rendering the first video on stock
        if not script.get('still_images'):
            try:
                from gameplay_sync import ensure_library
                n = ensure_library()
                if n:
                    logger.info(f"🎮 Own-clip library: {n} clip(s) usable")
            except Exception as e:
                logger.warning(f"Just-in-time clip sync skipped: {e}")
        try:
            video = VideoAssembler().assemble(script, audio)
        finally:
            if RENDER_BUSY is not None:
                RENDER_BUSY.clear()
        logger.info(f"🎥 Video done: {video}")

        vid = uploader.upload(video, script, language)
        if vid:
            logger.info(f"✅ UPLOADED [{language}]: https://youtube.com/watch?v={vid}")
            uploader.add_to_series_playlist(vid, script.get('title', ''))
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

def run_bot_short(is_retry: bool = False, brief: dict = None):
    """Scheduled slot: 1 German GTA Short (brief = owner's assignment)."""
    logger.info(f"🤖 SHORT cycle — {datetime.now():%Y-%m-%d %H:%M}"
                + (" (retry)" if is_retry else ""))
    # Whole cycle owns the CPU: the background clip sync must not start a
    # transcode next to script/voice/montage/render on this small box
    try:
        from gameplay_sync import RENDER_BUSY as busy
        busy.set()
    except Exception:
        busy = None
    vid = None
    try:
        vid = run_pipeline(language='de', brief=brief)
        logger.info("🏁 Short cycle complete")
    except Exception as e:
        logger.error(f"Short cycle error: {e}", exc_info=True)
    finally:
        if busy is not None:
            busy.clear()

    # Don't silently lose the slot on a transient failure (API hiccup,
    # rate limit, empty credits that get topped up) — retry once
    if vid is None and not is_retry:
        logger.warning("⏳ Slot failed — retrying once in 30 minutes")

        def _retry():
            run_bot_short(is_retry=True, brief=brief)
            return schedule.CancelJob

        schedule.every(30).minutes.do(_retry)

def run_clip_short(is_retry: bool = False):
    """Raw-highlight slot: one of the owner's own PS5 moments with the
    original game audio — no narration, so it costs no voice credits and
    plays like the clip Shorts that travel furthest in the GTA feed."""
    logger.info(f"🎞️ CLIP SHORT cycle — {datetime.now():%Y-%m-%d %H:%M}"
                + (" (retry)" if is_retry else ""))
    try:
        from gameplay_sync import RENDER_BUSY as busy
        busy.set()
    except Exception:
        busy = None
    vid = None
    try:
        from clip_short import run_clip_short as _run
        vid = _run()
    except Exception as e:
        logger.error(f"Clip short error: {e}", exc_info=True)
    finally:
        if busy is not None:
            busy.clear()
    if vid is None and not is_retry:
        logger.warning("⏳ Clip slot failed — retrying once in 30 minutes")

        def _retry():
            run_clip_short(is_retry=True)
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
    # fifth upload of the day: raw own-gameplay highlight (game audio, no
    # voice). Five uploads keep the day inside the 10 000-unit YouTube quota
    schedule.every().day.at("10:00").do(run_clip_short)
    logger.info("⏰ 4x daily GTA Shorts: 07 | 12 | 17 | 22 (DE) + Clip-Short 10")
    try:
        from trailer_library import ensure_trailers_async
        ensure_trailers_async()  # background prefetch of official GTA VI trailers
    except Exception as e:
        logger.warning(f"Trailer prefetch not started: {e}")
    # Community management: answer viewer comments every 2 hours
    schedule.every(2).hours.do(run_engagement)
    logger.info("💬 Engagement: comment replies every 2h")

    # Immediate post on startup only if explicitly enabled — otherwise every
    # deploy/restart uploads an unscheduled extra video. Started BEFORE the
    # clip sync so the cycle's busy flag is up before any transcode begins.
    if os.environ.get('POST_ON_START', '').lower() in ('1', 'true', 'yes'):
        brief = owner_brief()
        logger.info("🚀 POST_ON_START enabled — posting immediately"
                    + (f" (owner assignment: {brief['brief'][:60]}...)" if brief else ""))
        try:
            from gameplay_sync import RENDER_BUSY
            RENDER_BUSY.set()  # claimed here, cleared by run_bot_short
        except Exception:
            pass
        threading.Thread(target=run_bot_short, kwargs={'brief': brief},
                         daemon=True).start()
    else:
        logger.info("⏭️ Startup post disabled (set POST_ON_START=true to enable)")

    try:
        from gameplay_sync import sync_async, sources
        srcs = sources()
        if srcs:
            sync_async()  # owner's own PS5 clips (waits while a cycle runs)
            schedule.every(2).hours.do(sync_async)
            logger.info(f"🎮 Gameplay sync every 2h: {', '.join(srcs)}")
        else:
            logger.info("🎮 Gameplay sync off (set PSN_NPSSO or GAMEPLAY_DRIVE_FOLDER)")
    except Exception as e:
        logger.warning(f"Gameplay sync not started: {e}")

    while True:
        schedule.run_pending()
        time.sleep(60)

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
        'ELEVENLABS_API_KEY',
        'PEXELS_API_KEY',
        'YOUTUBE_CLIENT_SECRETS',
        'VOICE_ID_EN',
        'VOICE_ID_DE',
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
        # Step 1: Generate script
        logger.info("📝 Generating script...")
        script_gen = ScriptGenerator()
        script = script_gen.generate(topic, language)

        # Step 2: Generate voice
        logger.info("🎙️ Generating voice...")
        voice_gen = VoiceGenerator()
        audio_path = voice_gen.generate(script['narration'], language)

        # Step 3: Assemble video
        logger.info("🎥 Assembling video...")
        assembler = VideoAssembler()
        video_path = assembler.assemble(script, audio_path, topic)

        # Step 4: Upload to YouTube
        logger.info("📤 Uploading to YouTube...")
        uploader = YouTubeUploader()
        video_id = uploader.upload(video_path, script, language)

        # Cleanup temp files
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

    # Find trending topics
    trend_finder = TrendFinder()
    topics = trend_finder.get_trending_topics()

    if not topics:
        logger.warning("No trending topics found — retrying in 1 hour")
        return

    # Use best topic for both languages
    best_topic = topics[0]
    second_topic = topics[1] if len(topics) > 1 else topics[0]

    logger.info(f"📊 Best topic: {best_topic['title']}")

    # Run pipeline for both languages
    run_pipeline('en', best_topic)
    run_pipeline('de', second_topic)

    logger.info("🏁 Bot cycle complete")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  GridPhantom Bot — @GridPhantom187")
    logger.info("  Fully Autonomous AI & Tech YouTube Channel")
    logger.info("=" * 60)

    validate_config()

    # Run immediately on start
    run_bot()

    # Schedule: 2 videos per day (09:00 and 17:00 Zurich time)
    schedule.every().day.at("09:00").do(run_bot)
    schedule.every().day.at("17:00").do(run_bot)

    logger.info("⏰ Scheduler active: 09:00 and 17:00 daily")

    while True:
        schedule.run_pending()
        time.sleep(60)

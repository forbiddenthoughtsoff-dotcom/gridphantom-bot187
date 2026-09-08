# YouTube Data API – Quota Extension Request (GridPhantom)

**Form:** https://support.google.com/youtube/contact/yt_api_form
(Google Cloud project of the OAuth client used by the bot: `708006064698`; log in with the Google account that owns the project.)

Fill the form with the texts below. Answers are in English (the form is reviewed in English).

---

**Project name:** GridPhantom Bot

**Google Cloud project number:** 708006064698

**API Client name:** GridPhantom Bot (installed app OAuth client, refresh-token flow)

**Requested daily quota:** 50,000 units

**Website / channel:** https://www.youtube.com/@GridPhantom187

**Describe your use case (what does the client do?):**

GridPhantom Bot is an internal, single-channel publishing tool for my own YouTube channel @GridPhantom187 (German GTA gaming content). It produces and uploads my channel's own videos (short-form and long-form), sets thumbnails, adds videos to my own playlists, posts a first comment under each new video, and replies to viewer comments on my own videos. It only ever acts on my own channel with my own OAuth credentials. It does not access, scrape, store or display any third-party YouTube data, it has no end users other than me, and it does not offer any functionality to the public.

**Which API methods do you call and how often (per day)?**

- videos.insert: 8-10 uploads per day (each 1,600 units) – this is the reason for the request
- thumbnails.set: 1-2 per day (long-form videos)
- playlistItems.insert / playlists.list: 1-2 per day (own series playlist)
- commentThreads.insert / comments.insert: 5-15 per day (first comment + replies on own videos)
- commentThreads.list: ~150 per day (polling new comments on own recent videos every 2 hours)
- channels.list / playlistItems.list / videos.list: ~30 per day (own upload list and statistics)

Estimated total: 17,000-20,000 units per day; 50,000 requested to leave headroom for retries and a second language channel.

**Why is the default quota not sufficient?**

The default 10,000 units allow at most 5 video uploads per day (1,600 units each) plus minimal metadata calls. My publishing schedule is 6-8 uploads per day (4-5 German Shorts, 1 raw gameplay clip, a daily tutorial episode, and a long-form video twice a week). Failed uploads caused by exceeding the quota already cost me scheduled slots.

**Data handling / compliance:**

- The client stores only its own OAuth refresh token (in the hosting provider's encrypted environment variables) and the metadata of my own uploads. No user data of other people is collected or stored.
- It complies with the YouTube API Services Terms of Service and Developer Policies; it does not automate engagement on other channels, does not manipulate metrics, and every upload is my own original content.
- Privacy policy: the client has no users other than the channel owner; no data is shared with third parties.

**Screenshots to attach (the form asks for them):**
1. The channel page https://www.youtube.com/@GridPhantom187
2. The Google Cloud console "Quotas" page showing the YouTube Data API v3 at 10,000 units/day
3. One screenshot of the bot's log showing a normal upload cycle (the hosting dashboard)

---

After submission Google usually answers within 1-3 weeks by e-mail; they may ask a follow-up question about the use case – answer with the same wording as above.

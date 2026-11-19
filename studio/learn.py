"""Closed-loop learning + niche scouting, all on the free YouTube APIs (no LLM calls, so no Gemini quota).

  learn_from_analytics(): reads this channel's own per-video retention, turns it into (a) a short hint for the writer and
                          (b) memory['genre_weights'] so the genres that hold viewers get picked more often.
  viral_scout():          searches recent Shorts in each niche, ranks them by how far each beat ITS OWN channel
                          (views / subscribers - the yt-viral 'outlier' idea) and hands the best titles over as inspiration.
Both degrade to '' / [] on any error (missing scope, quota, brand-new channel); the pipeline never depends on them.
"""
import datetime as dt

NICHE_QUERIES = {
    "crime": ["true crime heist story", "unsolved mystery shorts", "criminal mastermind story"],
    "thriller": ["scary story animated", "creepy text story", "horror short story"],
    "comedy": ["dumbest criminal story", "funny fail story animated", "storytime comedy"],
}

def learn_from_analytics(creds, memory, days=28):
    """Returns a hint string; side effect: updates memory['genre_weights']."""
    try:
        from googleapiclient.discovery import build
        api = build("youtubeAnalytics", "v2", credentials=creds)
        rep = api.reports().query(
            ids="channel==MINE", startDate=(dt.date.today() - dt.timedelta(days=days)).isoformat(), endDate=dt.date.today().isoformat(),
            metrics="views,averageViewPercentage,averageViewDuration,subscribersGained", dimensions="video", sort="-views", maxResults=25).execute()
    except Exception as e:
        print(f"Analytics learning skipped: {str(e)[:100]}")
        return ""
    pub = memory.get("published_log", {})
    rows = []
    for vid, views, avg_pct, avg_dur, subs in rep.get("rows", []):
        meta = pub.get(vid)
        if meta and meta.get("genre"):
            rows.append(dict(vid=vid, views=views, pct=avg_pct, subs=subs, **{k: meta.get(k) for k in ("title", "genre", "hook")}))
    if not rows:
        return ""
    by_genre = {}
    for r in rows:
        by_genre.setdefault(r["genre"], []).append(r)
    scores = {g: sum(r["pct"] for r in rs) / len(rs) + 8 * sum(r["subs"] for r in rs) / max(1, len(rs)) for g, rs in by_genre.items()}
    if len(scores) >= 2:
        mean = sum(scores.values()) / len(scores)
        memory["genre_weights"] = {g: round(min(2.0, max(0.5, s / mean)), 2) for g, s in scores.items()}
    best = max(rows, key=lambda r: r["pct"])
    worst = min(rows, key=lambda r: r["pct"])
    hint = (f"Best retention: '{best['title']}' [{best['genre']}] {best['pct']:.0f}% watched, hook '{best['hook']}'. "
            f"Worst: '{worst['title']}' {worst['pct']:.0f}% watched, hook '{worst['hook']}' - do not write hooks like that one.")
    memory["last_learning"] = dict(date=dt.date.today().isoformat(), genre_weights=memory.get("genre_weights", {}), best=best["vid"], worst=worst["vid"])
    return hint

def viral_scout(youtube, memory, genre=None, max_titles=6):
    """Outlier hunt. Costs ~100 API units per search; runs at most once per UTC day and caches the result in memory."""
    today = dt.date.today().isoformat()
    cache = memory.get("scout", {})
    if cache.get("date") == today and cache.get("titles"):
        return cache["titles"]
    out = []
    try:
        after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for g, queries in NICHE_QUERIES.items():
            q = queries[dt.date.today().toordinal() % len(queries)]
            res = youtube.search().list(q=q, part="snippet", type="video", videoDuration="short", order="viewCount", publishedAfter=after, maxResults=12, relevanceLanguage="en").execute()
            ids = [i["id"]["videoId"] for i in res.get("items", [])]
            if not ids:
                continue
            vids = youtube.videos().list(part="snippet,statistics", id=",".join(ids)).execute().get("items", [])
            chans = {v["snippet"]["channelId"] for v in vids}
            subs = {c["id"]: int(c["statistics"].get("subscriberCount", 0) or 0)
                    for c in youtube.channels().list(part="statistics", id=",".join(chans)).execute().get("items", [])}
            for v in vids:
                views = int(v["statistics"].get("viewCount", 0) or 0)
                base = max(subs.get(v["snippet"]["channelId"], 0), 1000)         # floor avoids divide-by-tiny inflating ratios
                out.append((views / base, g, v["snippet"]["title"][:90], views))
        out.sort(reverse=True)
        titles = [f"[{g}] '{t}' ({views:,} views, {ratio:.1f}x its channel's size)" for ratio, g, t, views in out[:max_titles]]
        memory["scout"] = dict(date=today, titles=titles)
        return titles
    except Exception as e:
        print(f"Viral scout skipped: {str(e)[:100]}")
        return []

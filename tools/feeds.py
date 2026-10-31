"""Récupère chaque jour les résultats, le calendrier et les classements de championnats de foot
(API publique d'ESPN, sans clé) et les écrit en JSON compact dans feeds/ (branche « feeds »).
Lancé par .github/workflows/feeds.yml. Aucune clé ni mot de passe ici : ce dépôt est public."""
import json, os, sys, time, datetime as dt, urllib.request

LEAGUES = {  # code de l'appli : (championnat ESPN, début saison en cours, fin, début saison précédente, fin)
    "primeira_liga": ("por.1", "2026-07-01", "2027-06-30", "2025-07-01", "2026-06-30"),
    "eredivisie":    ("ned.1", "2026-07-01", "2027-06-30", "2025-07-01", "2026-06-30"),
    "belgian_pro":   ("bel.1", "2026-07-01", "2027-06-30", "2025-07-01", "2026-06-30"),
    "super_lig":     ("tur.1", "2026-07-01", "2027-06-30", "2025-07-01", "2026-06-30"),
    "saudi_pro":     ("ksa.1", "2026-07-01", "2027-06-30", "2025-07-01", "2026-06-30"),
    "liga_mx":       ("mex.1", "2026-07-01", "2026-12-31", "2025-07-01", "2026-06-30"),
    "brasileirao":   ("bra.1", "2026-01-01", "2026-12-31", "2025-01-01", "2025-12-31"),
    "liga_arg":      ("arg.1", "2026-07-01", "2026-12-31", "2025-07-01", "2026-06-30"),
}
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
STAND = "https://site.api.espn.com/apis/v2/sports/soccer/"
OUT = sys.argv[1] if len(sys.argv) > 1 else "feeds"
os.makedirs(OUT, exist_ok=True)
TODAY = dt.date.today()


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (2odds feeds)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            err = e
            time.sleep(2 + 3 * k)
    print("ÉCHEC", url, err)
    return None


def months(a, b):
    a, b = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    cur = a.replace(day=1)
    while cur <= b:
        nxt = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield max(cur, a), min(nxt - dt.timedelta(days=1), b)
        cur = nxt


def stat(comp, name):
    for s in comp.get("statistics") or []:
        if s.get("name") == name:
            try:
                return int(float(s.get("displayValue") or s.get("value")))
            except Exception:
                return None
    return None


def parse(data, teams, events):
    for ev in (data or {}).get("events", []):
        try:
            c = ev["competitions"][0]
            hh = [x for x in c["competitors"] if x.get("homeAway") == "home"][0]
            aa = [x for x in c["competitors"] if x.get("homeAway") == "away"][0]
        except Exception:
            continue
        for x in (hh, aa):
            t = x.get("team") or {}
            teams[str(t.get("id"))] = [t.get("abbreviation") or "", t.get("displayName") or "", t.get("shortDisplayName") or ""]
        st = (c.get("status") or ev.get("status") or {}).get("type") or {}
        state, name = st.get("state"), st.get("name")
        def sc(x):
            try:
                return int(x.get("score")) if state != "pre" else None
            except Exception:
                return None
        cards = {"h": [0, 0], "a": [0, 0]}
        hid = str((hh.get("team") or {}).get("id"))
        for d in c.get("details") or []:
            side = "h" if str((d.get("team") or {}).get("id")) == hid else "a"
            if d.get("redCard"):
                cards[side][1] += 1
            elif d.get("yellowCard"):
                cards[side][0] += 1
        def stats(x, side):
            co, fo = stat(x, "wonCorners"), stat(x, "foulsCommitted")
            if co is None and fo is None:
                return None
            return [co, fo, cards[side][0], cards[side][1]]
        events[str(ev["id"])] = [str(ev["id"]), ev.get("date") or c.get("date"), state, name,
                                 hid, str((aa.get("team") or {}).get("id")), sc(hh), sc(aa),
                                 stats(hh, "h") if state == "post" else None, stats(aa, "a") if state == "post" else None]


def season(lg, a, b):
    teams, events = {}, {}
    end = min(dt.date.fromisoformat(b), TODAY + dt.timedelta(days=14)).isoformat()
    if end < a:
        return None
    for x, y in months(a, end):
        url = f"{BASE}{lg}/scoreboard?dates={x:%Y%m%d}-{y:%Y%m%d}&limit=1000"
        parse(get(url), teams, events)
        time.sleep(0.4)
    return {"lg": lg, "from": a, "to": end, "fetched": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "teams": teams, "events": sorted(events.values(), key=lambda e: e[1] or "")}


def standings(lg):
    data = get(f"{STAND}{lg}/standings")
    rows = []
    def walk(node, group):
        g = node.get("abbreviation") or node.get("name") or group
        for e in ((node.get("standings") or {}).get("entries") or []):
            s = {x.get("name"): x.get("value") for x in e.get("stats") or []}
            t = e.get("team") or {}
            rows.append([g, str(t.get("id")), s.get("rank"), s.get("gamesPlayed"), s.get("wins"), s.get("ties"),
                         s.get("losses"), s.get("pointsFor"), s.get("pointsAgainst"), s.get("points")])
        for ch in node.get("children") or []:
            walk(ch, g)
    if data:
        walk(data, "")
    return rows


for code, (lg, a, b, pa, pb) in LEAGUES.items():
    cur = season(lg, a, b)
    if cur:
        cur["standings"] = standings(lg)
        json.dump(cur, open(os.path.join(OUT, code + ".json"), "w"), ensure_ascii=False, separators=(",", ":"))
        print(code, lg, len(cur["events"]), "matchs,", len(cur["teams"]), "équipes,", len(cur["standings"]), "lignes de classement")
    prev = os.path.join(OUT, code + "_prev.json")
    if not os.path.exists(prev):
        p = season(lg, pa, pb)
        if p:
            json.dump(p, open(prev, "w"), ensure_ascii=False, separators=(",", ":"))
            print(code, "saison précédente :", len(p["events"]), "matchs")

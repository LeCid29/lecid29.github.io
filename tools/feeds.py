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


START = time.time()
BUDGET_S = 11 * 60          # on s'arrête avant la limite du job (20 min) : ce qui est fait est publié
LOG = []


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG.append(line)


def get(url, tries=2):
    err = None
    for k in range(tries):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            log(f"OK {time.time() - t0:.1f}s {len(raw)}o {url.split('/soccer/')[1][:70]}")
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            err = e
            log(f"ERR {time.time() - t0:.1f}s {url.split('/soccer/')[1][:70]} {str(e)[:120]}")
            time.sleep(2)
    return None


def out_of_time():
    return time.time() - START > BUDGET_S


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


def cal_dates(data):
    out = set()
    for L in (data or {}).get("leagues") or []:
        for c in L.get("calendar") or []:
            v = c if isinstance(c, str) else (c.get("startDate") or c.get("value") or "")
            if isinstance(v, str) and len(v) >= 10:
                out.add(v[:10])
    return out


def day_url(lg, d):
    return f"{BASE}{lg}/scoreboard?dates={d.replace('-', '')}"


def season(lg, a, b, old=None, recent_only=False):
    """Matchs de la saison [a, b] (jusqu'à J+14). ESPN n'accepte qu'un jour par requête : on lit d'abord le calendrier
    (dates où il y a des matchs) puis on interroge seulement ces jours. old = fichier existant : mise à jour des jours récents."""
    teams, events = {}, {}
    if old:
        teams.update(old.get("teams") or {})
        for e in old.get("events") or []:
            events[e[0]] = e
    end = min(dt.date.fromisoformat(b), TODAY + dt.timedelta(days=14)).isoformat()
    if end < a:
        return None
    days = set()
    mid = (dt.date.fromisoformat(a) + (dt.date.fromisoformat(end) - dt.date.fromisoformat(a)) / 2).isoformat()
    for probe_day in sorted({a, mid, end, TODAY.isoformat() if a <= TODAY.isoformat() <= end else a}):
        data = get(day_url(lg, probe_day))
        parse(data, teams, events)
        days |= cal_dates(data)
        time.sleep(0.2)
    days = {d for d in days if a <= d <= end}
    if not days:  # pas de calendrier : tous les jours
        x = dt.date.fromisoformat(a)
        while x.isoformat() <= end:
            days.add(x.isoformat()); x += dt.timedelta(days=1)
        log(lg, "pas de calendrier ESPN : interrogation jour par jour")
    if recent_only:
        lo = (TODAY - dt.timedelta(days=5)).isoformat()
        days = {d for d in days if d >= lo}
    for d in sorted(days):
        if out_of_time():
            log("temps écoulé : arrêt", lg)
            break
        parse(get(day_url(lg, d)), teams, events)
        time.sleep(0.15)
    return {"lg": lg, "from": a, "to": end, "fetched": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "teams": teams, "events": sorted(events.values(), key=lambda e: e[1] or ""), "days": len(days)}


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


for code, (lg, a, b, pa, pb) in LEAGUES.items():   # 1) saisons en cours (prioritaires)
    fp = os.path.join(OUT, code + ".json")
    try:
        old = json.load(open(fp)) if os.path.exists(fp) else None
    except Exception:
        old = None
    full = not old or len(old.get("events") or []) < 20 or old.get("from") != a or TODAY.weekday() == 0  # complet le lundi
    cur = season(lg, a, b, None if full else old, recent_only=not full)
    if cur and cur["events"]:
        cur["standings"] = standings(lg)
        json.dump(cur, open(os.path.join(OUT, code + ".json"), "w"), ensure_ascii=False, separators=(",", ":"))
        log(code, lg, len(cur["events"]), "matchs,", len(cur["teams"]), "équipes,", len(cur["standings"]), "lignes de classement,", cur["days"], "jours lus", "(complet)" if full else "(jours récents)")
for code, (lg, a, b, pa, pb) in LEAGUES.items():   # 2) saisons précédentes (une seule fois, pour les priors)
    prev = os.path.join(OUT, code + "_prev.json")
    try:
        have = len(json.load(open(prev))["events"]) if os.path.exists(prev) else 0
    except Exception:
        have = 0
    if have < 50 and not out_of_time():   # absente ou ratée (moins de 50 matchs) : on la refait
        p = season(lg, pa, pb)
        if p and len(p["events"]) >= 50:
            json.dump(p, open(prev, "w"), ensure_ascii=False, separators=(",", ":"))
            log(code, "saison précédente :", len(p["events"]), "matchs")
open(os.path.join(OUT, "_log.txt"), "w").write(dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ") + "\n" + "\n".join(LOG) + "\n")

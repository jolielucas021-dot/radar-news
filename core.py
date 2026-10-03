# -*- coding: utf-8 -*-
"""
core.py — fonctions partagées par l'app (app.py) et le robot d'alertes (alerts.py).
Aucune dépendance à Streamlit.
"""
import hashlib
import html
import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests

PARIS = ZoneInfo("Europe/Paris")
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (RadarNews)"}

# ===========================================================================
# 1. NEWS (flux RSS)
# ===========================================================================
FEEDS = {
    "US": [
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml"),
    ],
    "Macro": [
        ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
        ("BCE", "https://www.ecb.europa.eu/rss/press.html"),
        ("BLS (emploi, inflation US)", "https://www.bls.gov/feed/bls_latest.rss"),
        ("CNBC Économie", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ],
    "Crypto": [
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Cointelegraph", "https://cointelegraph.com/rss"),
    ],
}

NEWS_PROMPT = """Tu es un analyste marchés senior (actions US, macro, crypto). On te donne des news
(titre + court résumé). Pour CHACUNE, produis une analyse factuelle et prudente, en français.

Règles strictes :
- Base-toi UNIQUEMENT sur le texte fourni et sur des connaissances générales des marchés.
  N'invente aucun chiffre, aucune citation, aucun fait. Si le texte est vague : confiance "faible".
- Aucune recommandation d'achat ou de vente : décris l'impact PROBABLE et son mécanisme.
- Une news publique est souvent déjà intégrée dans les prix en quelques secondes ; dis-le si pertinent.

Échelle d'importance :
5 = peut faire bouger tout le marché (décision Fed/BCE, CPI ou emploi US très surprenant,
    krach, faillite systémique, régulation crypto majeure, choc géopolitique)
4 = impact fort sur un secteur, une méga-cap ou le Bitcoin
3 = impact notable sur une valeur ou une crypto importante
2 = mineur
1 = bruit (opinion, publicité, liste "top 5", rumeur sans source)

Réponds UNIQUEMENT par un tableau JSON, sans texte autour :
[{"id": "...", "importance": 1-5, "theme": "US|Macro|Crypto|Autre",
  "actifs": ["SPY", "AAPL", "BTC", ...],
  "impact": "haussier|baissier|neutre|incertain",
  "horizon": "intraday|jours|semaines",
  "confiance": "faible|moyenne|élevée",
  "resume": "une phrase",
  "analyse": "2-3 phrases : pourquoi ça compte, le mécanisme, ce qui est déjà dans les prix"}]"""

TRIAGE_PROMPT = """Note l'importance pour les marchés (actions US, macro, crypto) de chaque titre :
5 = peut faire bouger tout le marché ; 4 = fort sur un secteur, une méga-cap ou le Bitcoin ;
3 = notable ; 2 = mineur ; 1 = bruit. Réponds UNIQUEMENT par un tableau JSON
[{"id": "...", "importance": n}]"""


def clean(text, n=400):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:n]


def parse_feed(content, source, theme):
    items = []
    for e in feedparser.parse(content).entries[:30]:
        title = clean(e.get("title"), 300)
        if not title:
            continue
        t = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
        link = e.get("link", "")
        items.append(dict(id=hashlib.sha1((link or title).encode()).hexdigest()[:12],
                          title=title, summary=clean(e.get("summary")), link=link,
                          source=source, theme=theme, time=dt))
    return items


def fetch_feeds(themes):
    items, errors = [], []
    for theme in themes:
        for source, url in FEEDS[theme]:
            try:
                r = requests.get(url, timeout=10, headers=UA)
                r.raise_for_status()
                got = parse_feed(r.content, source, theme)
                if not got:
                    errors.append(f"{source} : flux vide")
                items += got
            except Exception as ex:
                errors.append(f"{source} : {type(ex).__name__}")
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: x["time"], reverse=True):
        key = re.sub(r"\W+", "", it["title"].lower())[:80]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return unique, errors


# ===========================================================================
# 2. CLAUDE
# ===========================================================================
def parse_json_array(text):
    text = re.sub(r"```(json)?", "", text or "")
    a, b = text.find("["), text.rfind("]")
    try:
        return json.loads(text[a:b + 1]) if a >= 0 and b > a else []
    except json.JSONDecodeError:
        return []


def parse_json_object(text):
    text = re.sub(r"```(json)?", "", text or "")
    a, b = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[a:b + 1]) if a >= 0 and b > a else {}
    except json.JSONDecodeError:
        return {}


# Fournisseurs d'IA : Claude (Anthropic) ou ChatGPT (OpenAI), au choix
DEFAULT_MODELS = {"claude": "claude-haiku-4-5-20251001", "openai": "gpt-5-mini"}
PRICES = {"claude": (1.0, 5.0), "openai": (0.25, 2.0)}        # $ par million (entrée, sortie)


def llm_config(get):
    """Choisit le fournisseur à partir des secrets. `get(nom)` lit un secret ou renvoie None.
    Priorité : LLM_PROVIDER s'il est défini ; sinon OPENAI_API_KEY ; sinon ANTHROPIC_API_KEY
    (une clé qui ne commence pas par sk-ant- est traitée comme une clé OpenAI)."""
    okey, akey = get("OPENAI_API_KEY"), get("ANTHROPIC_API_KEY")
    provider = (get("LLM_PROVIDER") or "").lower().strip()
    if provider not in ("claude", "openai"):
        if okey:
            provider = "openai"
        else:
            provider = "claude" if (akey or "").startswith("sk-ant-") else "openai"
    key = (okey or akey) if provider == "openai" else (akey or okey)
    model = get("MODEL") or DEFAULT_MODELS[provider]
    pin, pout = PRICES[provider]
    return dict(provider=provider, key=key, model=model,
                price_in=float(get("PRICE_IN") or pin), price_out=float(get("PRICE_OUT") or pout))


def llm_call(cfg, system, user, max_tokens=3000, web=False, max_uses=3):
    """Appel unique, quel que soit le fournisseur. Renvoie dict(text, sources, tok_in, tok_out, searches)."""
    if not cfg.get("key"):
        raise RuntimeError("aucune clé API (ANTHROPIC_API_KEY ou OPENAI_API_KEY)")
    if cfg["provider"] == "openai":
        return _openai_call(cfg["key"], system, user, cfg["model"], max_tokens, web)
    return _claude_call(cfg["key"], system, user, cfg["model"], max_tokens, web, max_uses)


def _claude_call(api_key, system, user, model, max_tokens, web, max_uses):
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    kw = dict(model=model, max_tokens=max_tokens, system=system,
              messages=[{"role": "user", "content": user}])
    if web:
        kw["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}]
    msg = client.messages.create(**kw)
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    sources = []
    for b in msg.content:
        if getattr(b, "type", "") == "web_search_tool_result" and isinstance(b.content, list):
            sources += [(getattr(x, "title", ""), getattr(x, "url", "")) for x in b.content]
    stu = getattr(msg.usage, "server_tool_use", None)
    return dict(text=text, sources=sources[:5], tok_in=msg.usage.input_tokens,
                tok_out=msg.usage.output_tokens,
                searches=(getattr(stu, "web_search_requests", 0) or 0) if stu else 0)


def _openai_call(api_key, system, user, model, max_tokens, web):
    from openai import BadRequestError, OpenAI
    client = OpenAI(api_key=api_key)
    # Les modèles GPT-5 "réfléchissent" avant de répondre : cette réflexion consomme aussi
    # des tokens de sortie, d'où une marge plus large et un effort de réflexion faible.
    kw = dict(model=model, instructions=system, input=user,
              max_output_tokens=max(max_tokens * 3, 8000))
    if web:
        kw["tools"] = [{"type": "web_search"}]
    try:
        resp = client.responses.create(reasoning={"effort": "low"}, **kw)
    except BadRequestError:
        resp = client.responses.create(**kw)          # modèle sans réglage de réflexion
    sources, searches = [], 0
    for item in resp.output or []:
        t = getattr(item, "type", "")
        if t == "web_search_call":
            searches += 1
        elif t == "message":
            for c in getattr(item, "content", None) or []:
                for a in getattr(c, "annotations", None) or []:
                    if getattr(a, "type", "") == "url_citation":
                        src = (getattr(a, "title", "") or "", getattr(a, "url", "") or "")
                        if src not in sources:
                            sources.append(src)
    u = resp.usage
    return dict(text=resp.output_text or "", sources=sources[:5],
                tok_in=getattr(u, "input_tokens", 0), tok_out=getattr(u, "output_tokens", 0),
                searches=searches)


# ===========================================================================
# 3. CALENDRIER MACRO (Forex Factory : consensus + précédent)
# ===========================================================================
FF_URLS = {"Cette semaine": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
           "Semaine prochaine": "https://nfs.faireconomy.media/ff_calendar_nextweek.json"}


def fetch_macro():
    events, errors = [], []
    for label, url in FF_URLS.items():
        try:
            r = requests.get(url, timeout=12, headers=UA)
            r.raise_for_status()
            for e in r.json():
                dt = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
                eid = hashlib.sha1(f"{e['title']}{e['country']}{e['date']}".encode()).hexdigest()[:12]
                events.append(dict(id=eid, title=e.get("title", ""), country=e.get("country", ""),
                                   impact=e.get("impact", ""), time=dt,
                                   forecast=e.get("forecast") or "", previous=e.get("previous") or ""))
        except Exception as ex:
            errors.append(f"Calendrier {label} : {type(ex).__name__}")
    uniq = {e["id"]: e for e in events}
    return sorted(uniq.values(), key=lambda e: e["time"]), errors


EXPECT_PROMPT = """Tu es un économiste de marché. Pour chaque événement économique prévu, explique
en français, simplement, ce que le marché attend et comment il réagirait selon le résultat.
Le consensus ("forecast") et la valeur précédente ("previous") sont fournis : utilise-les tels quels.
Un bloc "contexte_recent" liste les news importantes des derniers jours : sers-t'en pour situer
l'enjeu. N'invente AUCUN autre contexte, chiffre ou citation.
Pour un discours ou une réunion sans chiffre, décris ce que le marché guettera.
Réponds UNIQUEMENT par un tableau JSON :
[{"id": "...",
  "attente": "ce que signifie le consensus, en une phrase claire",
  "enjeu": "pourquoi le marché y prête attention en ce moment",
  "si_superieur": "au-dessus du consensus : lecture + impact actions US / dollar / taux / crypto",
  "si_inferieur": "en dessous du consensus : idem",
  "si_conforme": "conforme : idem"}]"""

EXPECT_WEB_PROMPT = """Tu es un économiste de marché. Utilise la recherche web pour lire les
avant-papiers RÉCENTS sur l'événement ci-dessous (ce que les analystes attendent, ce que le marché
guette, le contexte du moment). Le consensus et le précédent fournis font foi.
N'invente rien : si tu ne trouves rien de récent, dis-le dans "enjeu".
Réponds en français, UNIQUEMENT par un objet JSON :
{"attente": "une phrase", "enjeu": "contexte actuel et ce que guette le marché (2-3 phrases)",
 "si_superieur": "...", "si_inferieur": "...", "si_conforme": "..."}"""

RESULT_PROMPT = """Tu es un économiste de marché. Utilise la recherche web pour trouver la valeur
PUBLIÉE de l'indicateur ci-dessous, pour CETTE date précise (sources officielles ou grands médias).
Compare-la au consensus fourni. Distingue la lecture pour l'économie et pour les marchés.
Si tu ne trouves pas la valeur, mets "actual": null : n'invente rien.
Réponds en français, UNIQUEMENT par un objet JSON :
{"actual": "valeur publiée ou null", "consensus": "...", "ecart": "écart chiffré",
 "verdict": "au-dessus du consensus|en dessous du consensus|conforme",
 "intensite": "légère|nette|forte",
 "lecture_economie": "1-2 phrases", "lecture_marches": "1-2 phrases",
 "reaction_observee": "réaction rapportée par les sources, sinon null",
 "confiance": "faible|moyenne|élevée"}"""


# ===========================================================================
# 4. CHIFFRES OFFICIELS (API du BLS) — résultat automatique, sans IA
# ===========================================================================
# Titre Forex Factory -> série BLS, calcul, famille d'interprétation
BLS_SPECS = {
    "CPI m/m": ("CUSR0000SA0", "pct1", "inflation"),
    "Core CPI m/m": ("CUSR0000SA0L1E", "pct1", "inflation"),
    "CPI y/y": ("CUUR0000SA0", "pct12", "inflation"),
    "Core CPI y/y": ("CUUR0000SA0L1E", "pct12", "inflation"),
    "PPI m/m": ("WPSFD4", "pct1", "inflation"),
    "Core PPI m/m": ("WPSFD49104", "pct1", "inflation"),
    "Average Hourly Earnings m/m": ("CES0500000003", "pct1", "inflation"),
    "Non-Farm Employment Change": ("CES0000000001", "diff", "emploi"),
    "Unemployment Rate": ("LNS14000000", "level", "chomage"),
}

INTERPRET = {
    "inflation": {
        1: "🔥 Inflation plus forte que prévu : les baisses de taux deviennent moins probables. "
           "Souvent négatif pour les actions, les obligations et la crypto ; positif pour le dollar.",
        -1: "❄️ Inflation plus faible que prévu : les baisses de taux deviennent plus probables. "
            "Souvent positif pour les actions, les obligations et la crypto ; négatif pour le dollar.",
        0: "➡️ Conforme : réaction souvent limitée ; le marché regarde le détail des composantes."},
    "emploi": {
        1: "💪 Emploi plus fort que prévu : bon pour l'économie, mais peut éloigner les baisses de "
           "taux (taux et dollar en hausse). Réaction des actions ambiguë.",
        -1: "🥶 Emploi plus faible que prévu : l'économie ralentit, baisses de taux plus probables "
            "(taux et dollar en baisse). Positif pour les actions sauf si la récession inquiète.",
        0: "➡️ Conforme : regarde aussi les révisions des mois précédents et les salaires."},
    "chomage": {
        1: "📈 Chômage plus élevé que prévu : ralentissement, baisses de taux plus probables "
           "(taux et dollar en baisse).",
        -1: "📉 Chômage plus bas que prévu : marché du travail solide, baisses de taux moins probables.",
        0: "➡️ Conforme aux attentes."},
}


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", (s or "").replace(",", ""))
    return float(m.group()) if m else None


def _decimals(s):
    m = re.search(r"\d+\.(\d+)", s or "")
    return len(m.group(1)) if m else 0


def fetch_bls(api_key, titles):
    """Télécharge les séries BLS utiles. Renvoie {series_id: [(année, mois, valeur), ...] récent d'abord}."""
    ids = sorted({BLS_SPECS[t][0] for t in titles if t in BLS_SPECS})
    if not ids:
        return {}
    y = datetime.now(timezone.utc).year
    payload = {"seriesid": ids, "startyear": str(y - 2), "endyear": str(y)}
    if api_key:
        payload["registrationkey"] = api_key
        url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    else:
        url = "https://api.bls.gov/publicAPI/v1/timeseries/data/"   # 25 requêtes/jour sans clé
    r = requests.post(url, json=payload, timeout=20, headers=UA)
    r.raise_for_status()
    out = {}
    for s in (r.json().get("Results") or {}).get("series", []):
        pts = []
        for d in s.get("data", []):
            if d.get("period", "").startswith("M") and d["period"] != "M13":
                try:
                    pts.append((int(d["year"]), int(d["period"][1:]), float(d["value"])))
                except ValueError:
                    pass                                   # valeur "-" (non publiée)
        out[s["seriesID"]] = sorted(pts, reverse=True)
    return out


def official_result(event, bls):
    """Résultat officiel comparé au consensus, ou None si pas (encore) disponible."""
    spec = BLS_SPECS.get(event["title"])
    if not spec or event["country"] != "USD":
        return None
    sid, calc, kind = spec
    pts = bls.get(sid) or []
    if len(pts) < 2:
        return None
    rel = event["time"].astimezone(NY)
    exp_y, exp_m = (rel.year, rel.month - 1) if rel.month > 1 else (rel.year - 1, 12)
    y0, m0, v0 = pts[0]
    if (y0, m0) != (exp_y, exp_m):
        return None                                        # pas encore publié (ou décalage)
    v1 = pts[1][2]
    if calc == "pct1":
        val, unit = (v0 / v1 - 1) * 100, "%"
    elif calc == "pct12":
        prev = [v for (y, m, v) in pts if (y, m) == (y0 - 1, m0)]
        if not prev:
            return None
        val, unit = (v0 / prev[0] - 1) * 100, "%"
    elif calc == "diff":
        val, unit = v0 - v1, "K"
    else:
        val, unit = v0, "%"
    f = num(event["forecast"])
    dec = _decimals(event["forecast"]) if f is not None else (0 if unit == "K" else 1)
    a = round(val, dec)
    disp = f"{a:.{dec}f}{unit}"
    res = dict(actual=disp, consensus=event["forecast"] or "—", source="BLS (officiel)",
               periode=f"{m0:02d}/{y0}")
    if f is None:
        res.update(direction=None, verdict="pas de consensus", lecture="")
        return res
    diff = round(a - f, dec)
    direction = 0 if abs(diff) < 10 ** (-dec) / 2 else (1 if diff > 0 else -1)
    res.update(direction=direction, ecart=f"{diff:+.{dec}f}{unit}",
               verdict={1: "au-dessus du consensus", -1: "en dessous du consensus",
                        0: "conforme"}[direction],
               lecture=INTERPRET[kind][direction])
    return res


# ===========================================================================
# 5. RÉSULTATS D'ENTREPRISES (API Finnhub, offre gratuite)
# ===========================================================================
LARGE_CAPS = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "META": "Meta", "AVGO": "Broadcom", "TSLA": "Tesla", "BRK.B": "Berkshire Hathaway",
    "JPM": "JPMorgan", "LLY": "Eli Lilly", "V": "Visa", "MA": "Mastercard", "UNH": "UnitedHealth",
    "XOM": "Exxon Mobil", "CVX": "Chevron", "ORCL": "Oracle", "COST": "Costco", "WMT": "Walmart",
    "HD": "Home Depot", "PG": "Procter & Gamble", "JNJ": "Johnson & Johnson", "NFLX": "Netflix",
    "BAC": "Bank of America", "WFC": "Wells Fargo", "C": "Citigroup", "GS": "Goldman Sachs",
    "MS": "Morgan Stanley", "BLK": "BlackRock", "SCHW": "Charles Schwab", "AXP": "American Express",
    "ABBV": "AbbVie", "MRK": "Merck", "PFE": "Pfizer", "ABT": "Abbott", "TMO": "Thermo Fisher",
    "ISRG": "Intuitive Surgical", "KO": "Coca-Cola", "PEP": "PepsiCo", "MCD": "McDonald's",
    "SBUX": "Starbucks", "NKE": "Nike", "DIS": "Disney", "CRM": "Salesforce", "ADBE": "Adobe",
    "NOW": "ServiceNow", "INTU": "Intuit", "IBM": "IBM", "CSCO": "Cisco", "AMD": "AMD",
    "INTC": "Intel", "MU": "Micron", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "AMAT": "Applied Materials", "PLTR": "Palantir", "UBER": "Uber", "GE": "GE Aerospace",
    "CAT": "Caterpillar", "BA": "Boeing", "LMT": "Lockheed Martin", "VZ": "Verizon", "T": "AT&T",
    "PYPL": "PayPal", "COIN": "Coinbase", "MSTR": "Strategy", "TSM": "TSMC", "ASML": "ASML",
}


def fetch_earnings(api_key, d_from, d_to, symbols):
    """Calendrier Finnhub filtré sur `symbols`. Renvoie (lignes, erreurs)."""
    if not api_key:
        return [], ["Clé FINNHUB_API_KEY manquante"]
    try:
        r = requests.get("https://finnhub.io/api/v1/calendar/earnings", timeout=15, headers=UA,
                         params={"from": str(d_from), "to": str(d_to), "token": api_key})
        r.raise_for_status()
        cal = r.json().get("earningsCalendar") or []
    except Exception as ex:
        return [], [f"Finnhub : {type(ex).__name__}"]
    wanted = {s.upper() for s in symbols}
    rows = []
    for e in cal:
        sym = (e.get("symbol") or "").upper()
        if sym not in wanted:
            continue
        rows.append(dict(id=f"{sym}-{e.get('date')}", symbol=sym, name=LARGE_CAPS.get(sym, sym),
                         date=date.fromisoformat(e["date"]), hour=e.get("hour") or "",
                         eps_est=e.get("epsEstimate"), eps=e.get("epsActual"),
                         rev_est=e.get("revenueEstimate"), rev=e.get("revenueActual"),
                         quarter=e.get("quarter"), year=e.get("year")))
    return rows, []


def surprise_pct(actual, est):
    if actual is None or est in (None, 0):
        return None
    return (actual - est) / abs(est) * 100


def fmt_rev(x):
    return "—" if x is None else f"{x / 1e9:,.1f} Md$" if x >= 1e9 else f"{x / 1e6:,.0f} M$"


HOURS = {"bmo": "avant l'ouverture", "amc": "après la clôture", "dmh": "pendant la séance"}

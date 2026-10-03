# -*- coding: utf-8 -*-
"""
crypto_core.py — données et score de sérieux des nouveaux lancements crypto.
Sources gratuites : DefiLlama (protocoles, frais, levées de fonds) et CoinGecko (token, tendances).
"""
import json
import math
import re
import time

import requests

import core
from core import UA

LLAMA = "https://api.llama.fi"
GECKO = "https://api.coingecko.com/api/v3"

# Investisseurs "de premier plan" (liste indicative, modifiable)
TIER1 = ["a16z", "andreessen", "paradigm", "polychain", "pantera", "coinbase ventures", "binance labs",
         "yzi labs", "sequoia", "multicoin", "dragonfly", "framework", "founders fund", "electric capital",
         "jump", "hack vc", "galaxy", "delphi", "spartan", "placeholder", "variant", "1kx", "robot ventures",
         "blockchain capital", "lightspeed", "haun", "ribbit", "tiger", "animoca", "okx ventures"]

EXCLUDED_CATEGORIES = {"CEX", "Chain"}

# Médias crypto et communiqués (utilisés pour les levées de fonds et les annonces de lancement)
PRESS_FEEDS = {
    "Chainwire (communiqués)": "https://chainwire.org/feed/",
    "The Block": "https://www.theblock.co/rss.xml",
    "Decrypt": "https://decrypt.co/feed",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Blockworks": "https://blockworks.co/feed",
}

RAISE_KEYWORDS = re.compile(r"\brais(e|es|ed|ing)\b|funding|seed round|pre-seed|series [a-e]\b|"
                            r"strategic round|led by|investment from|backed by", re.I)

RAISE_PROMPT = """Tu lis des titres et résumés d'articles crypto. Garde UNIQUEMENT les annonces de
LEVÉE DE FONDS d'un projet crypto / web3 précis (seed, série A, tour stratégique...).
IGNORE : flux des ETF, rachats d'entreprises, levées de sociétés non crypto, hausses de prix.
N'invente rien : null si absent. Montant en MILLIONS de dollars (nombre).
Réponds UNIQUEMENT par un tableau JSON (vide [] si rien) :
[{"id": "...", "projet": "...", "montant_musd": 12.5, "tour": "Seed|Série A|...|null",
  "investisseurs_principaux": ["..."], "autres_investisseurs": ["..."],
  "categorie": "DeFi|Infrastructure|IA|Jeux|Paiements|...", "resume": "1 phrase en français"}]"""


def _get(url, params=None, headers=None, timeout=30):
    r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Collecte
# ---------------------------------------------------------------------------
def fetch_protocols(days):
    """Protocoles ajoutés à DefiLlama depuis `days` jours."""
    cutoff = time.time() - days * 86400
    out = []
    for p in _get(f"{LLAMA}/protocols"):
        if (p.get("listedAt") or 0) >= cutoff and p.get("category") not in EXCLUDED_CATEGORIES:
            out.append(p)
    return out


def fetch_fees():
    """Frais générés sur 30 jours par protocole (= usage réel). Clés : slug et nom en minuscules."""
    data = _get(f"{LLAMA}/overview/fees",
                {"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true"})
    fees = {}
    for p in data.get("protocols", []):
        v = p.get("total30d")
        if v is None:
            continue
        for k in (p.get("slug"), (p.get("name") or "").lower(), (p.get("displayName") or "").lower()):
            if k:
                fees[k] = v
    return fees


def fetch_raises(days):
    """Levées de fonds DefiLlama. ATTENTION : réservé à l'offre Pro depuis 2026 (erreur sinon)."""
    data = _get(f"{LLAMA}/raises")
    cutoff = time.time() - days * 86400
    return [r for r in data.get("raises", []) if (r.get("date") or 0) >= cutoff]


def press_items(days=7):
    """Articles récents des médias crypto. Renvoie (articles, erreurs)."""
    items, errors = [], []
    cutoff = time.time() - days * 86400
    for label, url in PRESS_FEEDS.items():
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            items += [i for i in core.parse_feed(r.content, label, "Crypto") if i["time"].timestamp() >= cutoff]
        except Exception as ex:
            errors.append(f"{label} : {type(ex).__name__}")
    return items, errors


def raises_from_news(llm_cfg, cache, items):
    """Repère les levées de fonds dans les articles grâce à l'IA (résultats mis en cache par article).
    Renvoie des levées au même format que DefiLlama (montant en M$, investisseurs...)."""
    cands = [i for i in items if RAISE_KEYWORDS.search(f"{i['title']} {i['summary']}")]
    todo = [i for i in cands if i["id"] not in cache]
    for k in range(0, len(todo), 15):
        batch = todo[k:k + 15]
        payload = [dict(id=i["id"], titre=i["title"], resume=i["summary"]) for i in batch]
        r = core.llm_call(llm_cfg, RAISE_PROMPT, json.dumps(payload, ensure_ascii=False), max_tokens=2500)
        found = {o["id"]: o for o in core.parse_json_array(r["text"]) if isinstance(o, dict) and o.get("id")}
        for i in batch:
            cache[i["id"]] = found.get(i["id"])          # None = pas une levée de fonds
    out, seen = [], set()
    for i in cands:
        o = cache.get(i["id"])
        if not o or not o.get("projet"):
            continue
        key = re.sub(r"\W+", "", o["projet"].lower())
        if key in seen:                                   # même levée reprise par plusieurs médias
            continue
        seen.add(key)
        try:
            amount = float(o.get("montant_musd")) if o.get("montant_musd") is not None else None
        except (TypeError, ValueError):
            amount = None
        out.append(dict(date=i["time"].timestamp(), name=o["projet"], round=o.get("tour"), amount=amount,
                        leadInvestors=o.get("investisseurs_principaux") or [],
                        otherInvestors=o.get("autres_investisseurs") or [],
                        category=o.get("categorie"), chains=[], source=i["link"],
                        source_name=i["source"], resume=o.get("resume")))
    return sorted(out, key=lambda r: r["date"], reverse=True)


def fetch_markets(gecko_ids, api_key=None):
    """Données de marché CoinGecko pour une liste d'identifiants (par lots de 100)."""
    hdr = {"x-cg-demo-api-key": api_key} if api_key else None
    out = {}
    ids = [i for i in dict.fromkeys(gecko_ids) if i]
    for k in range(0, len(ids), 100):
        for c in _get(f"{GECKO}/coins/markets", {"vs_currency": "usd", "ids": ",".join(ids[k:k + 100])}, hdr):
            out[c["id"]] = c
    return out


def fetch_trending(api_key=None):
    hdr = {"x-cg-demo-api-key": api_key} if api_key else None
    return [c["item"] for c in _get(f"{GECKO}/search/trending", headers=hdr).get("coins", [])]


# ---------------------------------------------------------------------------
# Score de sérieux (transparent, critère par critère)
# ---------------------------------------------------------------------------
def is_tier1(investors):
    """Investisseurs de premier plan présents dans la liste (noms d'origine)."""
    return [inv for inv in investors if any(t in (inv or "").lower() for t in TIER1)]


def match_raise(p, raises):
    name = (p.get("name") or "").lower()
    pid = str(p.get("id", ""))
    best = None
    for r in raises:
        if str(r.get("defillamaId", "")) == pid or (r.get("name") or "").lower() == name:
            if best is None or (r.get("amount") or 0) > (best.get("amount") or 0):
                best = r
    return best


def _lin(x, lo, hi, pts):
    """Échelle logarithmique : 0 point à `lo`, `pts` points à `hi`."""
    if not x or x <= 0:
        return 0.0
    return max(0.0, min(pts, pts * (math.log10(x) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))))


def score(p, fees30, rz, mkt, raises_known=True):
    """Renvoie (score 0-100, détail des points, signaux positifs, drapeaux rouges)."""
    tvl = p.get("tvl") or 0
    ch7 = p.get("change_7d")
    try:
        audits = int(p.get("audits") or 0)
    except (TypeError, ValueError):
        audits = 0
    pts, good, red = {}, [], []

    pts["Argent déposé (TVL)"] = _lin(tvl, 1e6, 1e9, 25)
    pts["Revenus réels (frais 30 j)"] = _lin(fees30, 1e4, 1e7, 20)
    if fees30 and fees30 > 1e5:
        good.append("Génère de vrais revenus (frais payés par des utilisateurs)")
    elif not fees30:
        red.append("Aucun revenu mesuré : l'usage réel n'est pas prouvé")

    if ch7 is None:
        pts["Croissance 7 j"] = 0
    elif 0 < ch7 <= 100:
        pts["Croissance 7 j"] = 10
        good.append(f"TVL en hausse de {ch7:.0f} % sur 7 jours")
    elif ch7 > 100:
        pts["Croissance 7 j"] = 5
        red.append(f"TVL +{ch7:.0f} % en 7 j : souvent dopée par des récompenses temporaires (farming)")
    else:
        pts["Croissance 7 j"] = 0
        if ch7 < -30:
            red.append(f"TVL en chute de {ch7:.0f} % sur 7 jours")

    pts["Audit de sécurité"] = 15 if audits > 0 else 0
    if audits > 0:
        good.append("Audit de sécurité publié")
    else:
        red.append("Aucun audit de sécurité publié")

    pts["Investisseurs"] = 0
    if rz:
        investors = (rz.get("leadInvestors") or []) + (rz.get("otherInvestors") or [])
        t1 = is_tier1(investors)
        pts["Investisseurs"] = 10 + (5 if t1 else 0)
        amt = rz.get("amount")
        good.append(f"Levée de fonds{f' de {amt:g} M$' if amt else ''}"
                    + (f" avec {', '.join(sorted(set(t1)))}" if t1 else ""))

    pts["Token liquide"] = 0
    if mkt:
        vol, mc, fdv = mkt.get("total_volume") or 0, mkt.get("market_cap") or 0, mkt.get("fully_diluted_valuation") or 0
        if vol > 1e6:
            pts["Token liquide"] = 5
        if mc and fdv and fdv / mc >= 4:
            pts["Token liquide"] -= 5
            red.append(f"Valorisation totale = {fdv / mc:.0f}× la capitalisation : beaucoup de tokens "
                       "restent à débloquer (pression vendeuse future)")

    if p.get("forkedFrom"):
        red.append(f"Copie (fork) de {', '.join(p['forkedFrom'][:2])}")
        pts["Pénalité fork"] = -5
    if tvl < 5e6:
        red.append("Moins de 5 M$ déposés : projet encore très petit")

    total = sum(pts.values())
    if not raises_known:                       # données de levées indisponibles : on ne pénalise pas
        pts.pop("Investisseurs", None)
    denom = 90 if raises_known else 75
    return max(0, min(100, round(total / denom * 100))), pts, good, red


def build(days, min_tvl, gecko_key=None):
    """Assemble tout. Renvoie (projets triés par score, erreurs)."""
    errors = []
    protos = [p for p in fetch_protocols(days) if (p.get("tvl") or 0) >= min_tvl]
    try:
        fees = fetch_fees()
    except Exception as ex:
        fees, _ = {}, errors.append(f"Frais DefiLlama : {type(ex).__name__}")
    try:
        raises, raises_known = fetch_raises(720), True
    except Exception:
        raises, raises_known = [], False      # réservé à l'offre Pro : le score s'en passe
    try:
        mkts = fetch_markets([p.get("gecko_id") for p in protos], gecko_key)
    except Exception as ex:
        mkts, _ = {}, errors.append(f"CoinGecko : {type(ex).__name__}")
    out = []
    for p in protos:
        f30 = fees.get(p.get("slug")) or fees.get((p.get("name") or "").lower())
        rz = match_raise(p, raises)
        mkt = mkts.get(p.get("gecko_id"))
        sc, pts, good, red = score(p, f30, rz, mkt, raises_known)
        out.append(dict(p=p, fees30=f30, raise_=rz, mkt=mkt, score=sc, pts=pts, good=good, red=red,
                        age=int((time.time() - p["listedAt"]) / 86400)))
    return sorted(out, key=lambda x: x["score"], reverse=True), errors


ANALYSIS_PROMPT = """Tu es un analyste crypto sceptique et rigoureux. Utilise la recherche web pour
analyser ce projet crypto récemment lancé. Cherche : l'équipe (publique ou anonyme), les investisseurs,
les audits, la tokenomics (part en circulation, calendrier de déblocage, allocation équipe/investisseurs),
l'usage réel, les controverses, piratages ou signes d'arnaque. Les données chiffrées fournies font foi.
N'invente rien : si une information est introuvable, dis-le. Aucun conseil d'achat ou de vente.
Réponds en français, UNIQUEMENT par un objet JSON :
{"resume": "ce que fait le projet, en 2 phrases simples",
 "equipe": "1 phrase", "investisseurs": "1 phrase",
 "tokenomics": "1-2 phrases (circulation, déblocages à venir)",
 "points_forts": ["..."], "risques": ["..."], "drapeaux_rouges": ["..."],
 "serieux": "faible|moyen|élevé", "a_surveiller": "prochains événements clés (déblocages, listings…)"}"""

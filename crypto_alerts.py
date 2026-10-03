# -*- coding: utf-8 -*-
"""
crypto_alerts.py — veille des lancements crypto, appelée par alerts.py toutes les 10 min.

Sources surveillées :
  1. Canaux Telegram OFFICIELS des plateformes (version web publique t.me/s/...) :
     nouvelles cotations, launchpools, airdrops, ventes de tokens, Binance Alpha...
     -> l'IA ne garde que les vrais lancements et en extrait token, plateforme, date
  2. Nouvelles paires sur Coinbase et Upbit (API publiques, détection par différence)
  3. Nouveaux protocoles DefiLlama avec un bon score de sérieux
  4. Grosses levées de fonds (≥ 20 M$ ou investisseur de premier plan)
  5. Communiqués de presse et médias crypto : annonces de date de lancement de token (TGE),
     d'airdrop, de fin de programme de points, de vente publique... (ex. Aster, 9 jours avant)
Chaque lancement détecté est enrichi avec CoinGecko (prix, capitalisation, tokens à débloquer).
"""
import json
import re
import time
from datetime import datetime, timezone

import requests

import core
import crypto_core as cc
from core import PARIS, UA

# Canaux d'annonces officiels (modifiables). Un canal introuvable est simplement ignoré.
CHANNELS = {
    "binance_announcements": "Binance",
    "Bybit_Announcements": "Bybit",
    "OKXAnnouncements": "OKX",
    "Bitget_Announcements": "Bitget",
}

CLASSIFY_PROMPT = """Tu analyses des annonces officielles de plateformes d'échange crypto.
Garde UNIQUEMENT les annonces qui concernent le LANCEMENT ou la première arrivée d'un token :
cotation spot d'un nouveau token, launchpool/launchpad, airdrop (ex. HODLer Airdrops),
vente de tokens, pré-marché, ajout à Binance Alpha, première cotation en contrats à terme d'un token récent.
IGNORE : retraits de cotation, maintenance, promotions, concours, nouvelles paires de tokens anciens
et connus, mises à jour de réseau, annonces générales.
Pour chaque annonce gardée, extrais les informations SANS RIEN INVENTER (null si absent).
Importance : 5 = cotation spot d'un nouveau token sur Binance/Coinbase ou launchpool majeur ;
4 = cotation spot ou airdrop sur Bybit/OKX/Bitget ; 3 = Alpha, pré-marché, contrats à terme ; 2 = mineur.
Réponds UNIQUEMENT par un tableau JSON (vide [] si rien) :
[{"id": "...", "token": "nom", "symbole": "ABC", "plateforme": "...",
  "type": "cotation spot|launchpool|airdrop|vente|pré-marché|alpha|futures",
  "date": "date et heure annoncées, ou null", "resume": "1 phrase en français",
  "importance": 1-5}]"""

MIN_LAUNCH_IMPORTANCE = 3

PRESS_FEEDS = cc.PRESS_FEEDS   # liste partagée avec l'app (crypto_core.py)

# Pré-filtre gratuit par mots-clés, pour ne payer l'IA que sur les articles pertinents
KEYWORDS = re.compile(
    r"\bTGE\b|token generation|airdrop|token launch|launch(es|ing)? (its |a |the )?(native )?token|"
    r"native token|points? (program|campaign|season)|season \d|snapshot|claim|tokenomics|"
    r"\bICO\b|\bIDO\b|presale|public sale|token sale|launchpool|launchpad|lists? on|listing|"
    r"pre-market|genesis", re.I)

PRESS_PROMPT = """Tu analyses des communiqués de presse et articles crypto. Garde UNIQUEMENT ceux qui
annoncent un événement de LANCEMENT DE TOKEN à venir ou tout juste survenu pour un projet précis :
date de lancement du token (TGE), airdrop ou date de réclamation, snapshot ou fin d'un programme de
points, vente publique, première cotation annoncée.
IGNORE : analyses de prix, actualité générale, tokens déjà anciens, articles d'opinion, piratages.
Sois sévère avec les communiqués promotionnels de petits projets inconnus (sans investisseurs
reconnus ni utilisateurs) : importance 1 ou 2. N'invente rien (null si absent).
Importance : 5 = projet déjà gros ou soutenu par de grands investisseurs, date précise annoncée ;
4 = projet crédible avec date ; 3 = projet crédible sans date précise ; 1-2 = petit projet promotionnel.
Réponds UNIQUEMENT par un tableau JSON (vide [] si rien) :
[{"id": "...", "projet": "...", "symbole": "ABC ou null",
  "evenement": "lancement du token|airdrop|snapshot / fin des points|vente publique|cotation",
  "date": "date annoncée ou null", "investisseurs": "si mentionnés, sinon null",
  "resume": "1-2 phrases en français", "importance": 1-5}]"""


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def read_channel(channel):
    """Derniers messages d'un canal public, via sa page web t.me/s/<canal>."""
    from bs4 import BeautifulSoup
    r = requests.get(f"https://t.me/s/{channel}", headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []
    for m in soup.select("div.tgme_widget_message[data-post]"):
        txt = m.select_one("div.tgme_widget_message_text")
        tm = m.select_one("time[datetime]")
        if not txt:
            continue
        posts.append(dict(id=m["data-post"], text=txt.get_text(" ", strip=True)[:1200],
                          time=tm["datetime"] if tm else None,
                          link=f"https://t.me/{m['data-post']}"))
    return posts


def coinbase_assets():
    data = requests.get("https://api.exchange.coinbase.com/products", headers=UA, timeout=20).json()
    return sorted({p["base_currency"] for p in data if p.get("status") == "online"})


def upbit_markets():
    data = requests.get("https://api.upbit.com/v1/market/all", headers=UA, timeout=20).json()
    return sorted({d["market"] for d in data})


def gecko_info(symbol, name=None):
    """Cherche le token sur CoinGecko et renvoie ses données de marché (ou None)."""
    try:
        q = requests.get(f"{cc.GECKO}/search", params={"query": symbol or name}, headers=UA, timeout=15).json()
        coins = q.get("coins", [])
        pick = next((c for c in coins if (c.get("symbol") or "").upper() == (symbol or "").upper()), None)
        pick = pick or (coins[0] if coins else None)
        if not pick:
            return None
        m = cc.fetch_markets([pick["id"]])
        return m.get(pick["id"])
    except Exception:
        return None


def find_protocol(name, protocols):
    """Cherche un protocole DefiLlama par son nom (pour afficher argent déposé et revenus)."""
    n = re.sub(r"\W+", "", (name or "").lower())
    if len(n) < 3:
        return None
    for p in protocols:
        if re.sub(r"\W+", "", (p.get("name") or "").lower()) == n:
            return p
    return None


def market_line(m):
    if not m:
        return "Pas encore de données de marché sur CoinGecko."
    mc, fdv = m.get("market_cap") or 0, m.get("fully_diluted_valuation") or 0
    line = f"Prix {m.get('current_price')} $ · capi {mc / 1e6:,.0f} M$ · valo totale {fdv / 1e6:,.0f} M$"
    if mc and fdv and fdv / mc >= 4:
        line += f"\n⚠️ Valo totale = {fdv / mc:.0f}× la capi : beaucoup de tokens restent à débloquer"
    return line


# ---------------------------------------------------------------------------
# Veille
# ---------------------------------------------------------------------------
def run(state, send, esc, llm_cfg, first=False):
    """`state` : dict persistant ; `send(texte_html)` ; `esc` : échappement HTML."""
    seen = set(state.get("crypto_seen", []))
    errors = []

    # --- 1. Canaux officiels -------------------------------------------------
    fresh = []
    for ch, platform in CHANNELS.items():
        try:
            for p in read_channel(ch):
                if p["id"] not in seen:
                    p["platform"] = platform
                    fresh.append(p)
        except Exception as ex:
            errors.append(f"canal {ch} : {type(ex).__name__}")
    if fresh and not first:
        for k in range(0, len(fresh), 15):
            batch = fresh[k:k + 15]
            payload = [dict(id=p["id"], plateforme=p["platform"], texte=p["text"]) for p in batch]
            r = core.llm_call(llm_cfg, CLASSIFY_PROMPT, json.dumps(payload, ensure_ascii=False), max_tokens=2500)
            byid = {p["id"]: p for p in batch}
            for o in core.parse_json_array(r["text"]):
                if not isinstance(o, dict) or int(o.get("importance") or 0) < MIN_LAUNCH_IMPORTANCE:
                    continue
                src = byid.get(o.get("id"))
                if not src:
                    continue
                m = gecko_info(o.get("symbole"), o.get("token"))
                imp = int(o["importance"])
                send(f"🚀 <b>{'🔥 ' if imp >= 5 else ''}{esc(o.get('plateforme'))} · {esc(o.get('type'))}</b>\n"
                     f"<b>{esc(o.get('token'))}</b>"
                     + (f" ({esc(o.get('symbole'))})" if o.get("symbole") else "")
                     + (f"\n🗓️ {esc(o['date'])}" if o.get("date") else "")
                     + f"\n{esc(o.get('resume'))}\n\n{esc(market_line(m))}\n"
                     f"<i>Annonce officielle :</i> {esc(src['link'])}\n"
                     f"<i>Vérifie le sérieux dans le Radar Lancements Crypto avant toute décision.</i>")
    seen |= {p["id"] for p in fresh}

    # --- 2. Nouvelles paires Coinbase / Upbit ---------------------------------
    for key, fn, label in (("coinbase_assets", coinbase_assets, "Coinbase"),
                           ("upbit_markets", upbit_markets, "Upbit")):
        try:
            now_list = fn()
            before = set(state.get(key, []))
            if before and not first:
                for a in sorted(set(now_list) - before):
                    sym = a.split("-")[-1]
                    send(f"🆕 <b>Nouvelle cotation sur {label}</b> : <b>{esc(a)}</b>\n"
                         f"{esc(market_line(gecko_info(sym)))}")
            state[key] = now_list
        except Exception as ex:
            errors.append(f"{label} : {type(ex).__name__}")

    # --- 3. Nouveaux protocoles sérieux (DefiLlama) ---------------------------
    try:
        items, _ = cc.build(days=3, min_tvl=5e6)
        for x in items:
            pid = f"llama-{x['p'].get('slug')}"
            if pid in seen or x["score"] < 60:
                continue
            seen.add(pid)
            if first:
                continue
            p = x["p"]
            send(f"🧪 <b>Nouveau protocole sérieux : {esc(p.get('name'))}</b> · score {x['score']}/100\n"
                 f"{esc(p.get('category'))} · {esc(', '.join((p.get('chains') or [])[:3]))}\n"
                 f"Déposé : {(p.get('tvl') or 0) / 1e6:,.0f} M$\n"
                 + "\n".join(f"✅ {esc(g)}" for g in x["good"][:3])
                 + ("\n" if x["red"] else "") + "\n".join(f"⚠️ {esc(r)}" for r in x["red"][:3])
                 + f"\n{esc('https://defillama.com/protocol/' + str(p.get('slug')))}")
    except Exception as ex:
        errors.append(f"DefiLlama protocoles : {type(ex).__name__}")

    # --- 4. Grosses levées de fonds -------------------------------------------
    try:
        for r in cc.fetch_raises(days=2):
            rid = f"raise-{r.get('name')}-{r.get('date')}"
            if rid in seen:
                continue
            seen.add(rid)
            inv = (r.get("leadInvestors") or []) + (r.get("otherInvestors") or [])
            t1 = cc.is_tier1(inv)
            if first or not ((r.get("amount") or 0) >= 20 or t1):
                continue
            send(f"🏦 <b>Levée de fonds : {esc(r.get('name'))}</b> · {esc(r.get('amount') or '?')} M$ "
                 f"({esc(r.get('round') or 'tour non précisé')})\n"
                 f"{esc(r.get('category') or r.get('sector') or '')}\n"
                 f"Menée par : {esc(', '.join(r.get('leadInvestors') or []) or 'non précisé')}"
                 + (f"\n⭐ Investisseurs de premier plan : {esc(', '.join(t1[:4]))}" if t1 else "")
                 + "\n<i>Projet à surveiller : un token peut suivre, sans garantie.</i>")
    except Exception:
        pass        # levées DefiLlama réservées à l'offre Pro : on passe par les médias (section 5)

    # --- 5. Communiqués de presse et médias crypto -----------------------------
    press_first = first or not state.get("press_started")
    items, perr = cc.press_items(days=2)
    errors += [f"presse {e}" for e in perr]
    new_items = []
    for it in items:
        pid = "press-" + it["id"]
        if pid not in seen:
            seen.add(pid)
            new_items.append(it)
    cands = [it for it in new_items if KEYWORDS.search(f"{it['title']} {it['summary']}")]

    # levées de fonds repérées dans les médias (≥ 20 M$ ou investisseur de premier plan)
    if new_items and not press_first:
        try:
            for rz in cc.raises_from_news(llm_cfg, {}, new_items):
                rk = "raisename-" + re.sub(r"\W+", "", rz["name"].lower())
                if rk in seen:
                    continue
                seen.add(rk)
                t1 = cc.is_tier1(rz["leadInvestors"] + rz["otherInvestors"])
                if not ((rz["amount"] or 0) >= 20 or t1):
                    continue
                amt = f"{rz['amount']:g} M$" if rz["amount"] is not None else "montant non communiqué"
                send(f"🏦 <b>Levée de fonds : {esc(rz['name'])}</b> · {esc(amt)} ({esc(rz['round'] or 'tour non précisé')})\n"
                     f"{esc(rz.get('category') or '')}\n"
                     f"Menée par : {esc(', '.join(rz['leadInvestors']) or 'non précisé')}"
                     + (f"\n⭐ Investisseurs de premier plan : {esc(', '.join(t1[:4]))}" if t1 else "")
                     + (f"\n{esc(rz['resume'])}" if rz.get("resume") else "")
                     + f"\n<i>Source : {esc(rz['source_name'])}</i> {esc(rz['source'])}"
                     + "\n<i>Projet à surveiller : un token peut suivre, sans garantie.</i>")
        except Exception as ex:
            errors.append(f"levées (médias) : {type(ex).__name__}")
    state["press_started"] = True
    if cands and not press_first:
        try:
            protocols = requests.get(f"{cc.LLAMA}/protocols", headers=UA, timeout=40).json()
        except Exception:
            protocols = []
        try:
            fees = cc.fetch_fees()
        except Exception:
            fees = {}
        for k in range(0, len(cands), 15):
            batch = cands[k:k + 15]
            payload = [dict(id=i["id"], source=i["source"], titre=i["title"], resume=i["summary"]) for i in batch]
            r = core.llm_call(llm_cfg, PRESS_PROMPT, json.dumps(payload, ensure_ascii=False), max_tokens=2500)
            byid = {i["id"]: i for i in batch}
            for o in core.parse_json_array(r["text"]):
                if not isinstance(o, dict) or int(o.get("importance") or 0) < MIN_LAUNCH_IMPORTANCE:
                    continue
                src = byid.get(o.get("id"))
                if not src:
                    continue
                p = find_protocol(o.get("projet"), protocols)
                lines = []
                if p:
                    f30 = fees.get(p.get("slug")) or fees.get((p.get("name") or "").lower())
                    sc, _, good, red = cc.score(p, f30, None, None)
                    lines.append(f"📊 Déjà actif : {(p.get('tvl') or 0) / 1e6:,.0f} M$ déposés"
                                 + (f", {f30 / 1e6:,.1f} M$ de revenus sur 30 j" if f30 else "")
                                 + f" · score {sc}/100")
                    lines += [f"⚠️ {r_}" for r_ in red[:2]]
                else:
                    lines.append("📊 Pas (encore) suivi par DefiLlama : prudence, usage réel non vérifiable.")
                imp = int(o["importance"])
                send(f"📣 <b>{'🔥 ' if imp >= 5 else ''}Annonce de lancement : {esc(o.get('projet'))}</b>"
                     + (f" ({esc(o.get('symbole'))})" if o.get("symbole") else "")
                     + f"\n🎯 {esc(o.get('evenement'))}"
                     + (f" · 🗓️ {esc(o['date'])}" if o.get("date") else "")
                     + f"\n{esc(o.get('resume'))}"
                     + (f"\n🏦 {esc(o['investisseurs'])}" if o.get("investisseurs") else "")
                     + "\n" + "\n".join(esc(l) for l in lines)
                     + f"\n<i>Source : {esc(src['source'])}</i> {esc(src['link'])}")

    state["crypto_seen"] = list(seen)[-8000:]
    return errors

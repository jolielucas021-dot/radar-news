# -*- coding: utf-8 -*-
"""
🚀 Radar Lancements Crypto
  - Nouveaux projets : protocoles récents (DefiLlama) notés sur des critères vérifiables
  - Levées de fonds : qui finance quoi (souvent un signe avant-coureur d'un futur token)
  - Tendances : les cryptos les plus recherchées sur CoinGecko (attention : hype ≠ qualité)
  - Analyse IA à la demande (recherche web)

Secrets Streamlit : OPENAI_API_KEY (ou ANTHROPIC_API_KEY), APP_PASSWORD
Facultatif : COINGECKO_API_KEY (clé "Demo" gratuite sur coingecko.com/api)
"""
import json
import os
from datetime import datetime, timezone

import streamlit as st

import core
import crypto_core as cc

TEST_MODE = os.environ.get("RADAR_TEST") == "1"


def secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.environ.get(name, default)


def md(t):
    return str(t).replace("$", r"\$").replace("[", "(").replace("]", ")")


def usd(x):
    if x is None:
        return "—"
    for div, suf in ((1e9, " Md\\$"), (1e6, " M\\$"), (1e3, " k\\$")):
        if abs(x) >= div:
            return f"{x / div:,.1f}{suf}"
    return f"{x:,.0f} \\$"


def price(x):
    if x is None:
        return "—"
    return f"{x:,.2f} \\$" if x >= 1 else f"{x:.4g} \\$"


@st.cache_resource
def analyses():
    return {}


@st.cache_data(ttl=1800, show_spinner=False)
def load_projects(days, min_tvl):
    return cc.build(days, min_tvl, secret("COINGECKO_API_KEY"))


@st.cache_data(ttl=1800, show_spinner=False)
def load_raises(days):
    return cc.fetch_raises(days)


@st.cache_data(ttl=900, show_spinner=False)
def load_trending():
    return cc.fetch_trending(secret("COINGECKO_API_KEY"))


def ai_analysis(x):
    cache = analyses()
    key = x["p"].get("slug") or x["p"]["name"]
    if key not in cache:
        p, m = x["p"], x["mkt"] or {}
        facts = dict(nom=p.get("name"), symbole=p.get("symbol"), categorie=p.get("category"),
                     chaines=p.get("chains"), site=p.get("url"), twitter=p.get("twitter"),
                     description=p.get("description"), tvl_usd=p.get("tvl"), frais_30j_usd=x["fees30"],
                     capitalisation=m.get("market_cap"), valorisation_totale=m.get("fully_diluted_valuation"),
                     levee=x["raise_"])
        cfg = core.llm_config(lambda k: secret(k))
        r = core.llm_call(cfg, cc.ANALYSIS_PROMPT, json.dumps(facts, ensure_ascii=False, default=str),
                          max_tokens=2000, web=True)
        obj = core.parse_json_object(r["text"]) or {"resume": "Analyse indisponible."}
        obj["sources"] = r["sources"]
        cache[key] = obj
    return cache[key]


def project_card(x, i):
    p, m, rz = x["p"], x["mkt"], x["raise_"]
    sc = x["score"]
    badge = "🟢" if sc >= 70 else "🟡" if sc >= 40 else "🔴"
    with st.container(border=True):
        st.markdown(f"{badge} **{sc}/100** · **{md(p['name'])}**"
                    + (f" ({md(p.get('symbol'))})" if p.get("symbol") not in (None, "-", "") else "")
                    + f"  \n{md(p.get('category', ''))} · {md(', '.join((p.get('chains') or [])[:3]))}"
                    + f" · lancé il y a {x['age']} j")
        ch7 = p.get("change_7d")
        st.markdown(f"💰 Déposé : **{usd(p.get('tvl'))}**"
                    + (f" ({ch7:+.0f} % / 7 j)" if ch7 is not None else "")
                    + f" · 💵 Revenus 30 j : **{usd(x['fees30'])}**")
        if m:
            pc = m.get("price_change_percentage_24h")
            st.markdown(f"🪙 Token : {price(m.get('current_price'))}"
                        + (f" ({pc:+.1f} % / 24 h)" if pc is not None else "")
                        + f" · capi {usd(m.get('market_cap'))} · valo totale {usd(m.get('fully_diluted_valuation'))}")
        else:
            st.markdown("🪙 Pas de token coté pour l'instant")
        if rz:
            leads = ", ".join(rz.get("leadInvestors") or []) or "investisseurs non précisés"
            st.markdown(f"🏦 Levée : {md(rz.get('amount') or '?')} M\\$ ({md(rz.get('round') or '')}) · {md(leads)}")
        for g in x["good"]:
            st.markdown(f"✅ {md(g)}")
        for r in x["red"]:
            st.markdown(f"⚠️ {md(r)}")
        links = [(l, u) for l, u in (("Site", p.get("url")),
                                     ("X", f"https://x.com/{p['twitter']}" if p.get("twitter") else None),
                                     ("DefiLlama", f"https://defillama.com/protocol/{p.get('slug')}")) if u]
        st.caption(" · ".join(f"[{l}]({u})" for l, u in links))
        with st.expander("Détail du score"):
            st.write("\n".join(f"- {k} : {v:+.0f} pts" for k, v in x["pts"].items()))
            if p.get("description"):
                st.caption(md(p["description"][:400]))

        key = p.get("slug") or p["name"]
        res = analyses().get(key)
        if res is None and st.button("🧠 Analyse IA approfondie (≈ 0,03 $)", key=f"ai_{i}"):
            with st.spinner("Recherche sur le web…"):
                try:
                    res = ai_analysis(x)
                except Exception as ex:
                    st.warning(f"Analyse impossible ({type(ex).__name__}: {str(ex)[:100]}).")
        if res:
            lvl = res.get("serieux", "")
            st.markdown(f"**🧠 Analyse IA** · sérieux estimé : **{md(lvl)}**  \n{md(res.get('resume', ''))}")
            for lab, k in (("👥 Équipe", "equipe"), ("🏦 Investisseurs", "investisseurs"),
                           ("📊 Tokenomics", "tokenomics"), ("👀 À surveiller", "a_surveiller")):
                if res.get(k):
                    st.markdown(f"{lab} : {md(res[k])}")
            for lab, k in (("👍", "points_forts"), ("⚠️", "risques"), ("🚩", "drapeaux_rouges")):
                for item in res.get(k) or []:
                    st.markdown(f"{lab} {md(item)}")
            if res.get("sources"):
                st.caption(" · ".join(f"[{md(t[:35]) or 'source'}]({u})" for t, u in res["sources"] if u))


def tab_projects(days, min_tvl, min_score, cats):
    with st.spinner("Chargement des nouveaux projets…"):
        try:
            items, errors = load_projects(days, min_tvl)
        except Exception as ex:
            st.error(f"DefiLlama indisponible ({type(ex).__name__}). Réessaie dans quelques minutes.")
            return
    for e in errors:
        st.caption(f"⚠️ {e}")
    all_cats = sorted({x["p"].get("category") or "Autre" for x in items})
    chosen = cats or all_cats
    shown = [x for x in items if x["score"] >= min_score and (x["p"].get("category") or "Autre") in chosen]
    st.caption(f"{len(shown)} projet(s) lancés depuis {days} jours avec au moins {usd(min_tvl)} déposés · "
               f"mis à jour à {datetime.now(core.PARIS):%H:%M}")
    with st.expander("ℹ️ Comment lire le score"):
        st.markdown("Le score (0-100) additionne des critères **vérifiables** : argent déposé, revenus "
                    "réels, croissance, audit, investisseurs, liquidité du token. Il mesure le **sérieux "
                    "apparent**, pas le potentiel de hausse. Un bon score n'est pas un conseil d'achat : "
                    "beaucoup de projets bien financés chutent fortement après leur lancement, notamment "
                    "quand de nombreux tokens restent à débloquer.")
    if not shown:
        st.info("Aucun projet avec ces filtres. Baisse le score minimum ou le montant déposé.")
    for i, x in enumerate(shown[:60]):
        project_card(x, i)
    return all_cats


def tab_raises(min_amount):
    try:
        raises = load_raises(60)
    except Exception as ex:
        st.error(f"Levées de fonds indisponibles ({type(ex).__name__}).")
        return
    rows = sorted([r for r in raises if (r.get("amount") or 0) >= min_amount],
                  key=lambda r: r.get("date") or 0, reverse=True)
    st.caption(f"{len(rows)} levée(s) d'au moins {min_amount:g} M\\$ sur 60 jours. Un projet qui lève "
               "des fonds sans avoir encore de token peut en lancer un plus tard, mais rien n'est garanti.")
    for r in rows[:80]:
        inv = (r.get("leadInvestors") or []) + (r.get("otherInvestors") or [])
        t1 = cc.is_tier1(inv)
        d = datetime.fromtimestamp(r["date"], timezone.utc).astimezone(core.PARIS)
        with st.container(border=True):
            st.markdown(f"{'⭐ ' if t1 else ''}**{md(r.get('name'))}** · **{md(r.get('amount'))} M\\$** "
                        f"({md(r.get('round') or 'tour non précisé')}) · {d:%d/%m/%Y}  \n"
                        f"{md(r.get('category') or r.get('sector') or '')} · "
                        f"{md(', '.join((r.get('chains') or [])[:3]))}")
            if r.get("leadInvestors"):
                st.markdown(f"Menée par : **{md(', '.join(r['leadInvestors']))}**")
            if r.get("otherInvestors"):
                st.caption("Avec : " + md(", ".join(r["otherInvestors"][:8])))
            if r.get("valuation"):
                st.caption(f"Valorisation : {md(r['valuation'])} M\\$")
            if r.get("source"):
                st.caption(f"[Source]({r['source']})")


def tab_trending():
    try:
        coins = load_trending()
    except Exception as ex:
        st.error(f"CoinGecko indisponible ({type(ex).__name__}).")
        return
    st.caption("Les cryptos les plus recherchées sur CoinGecko ces dernières 24 h. Mesure l'attention du "
               "public, pas la qualité : les pics de recherche précèdent souvent des chutes.")
    for c in coins:
        d = c.get("data") or {}
        pc = (d.get("price_change_percentage_24h") or {}).get("usd")
        with st.container(border=True):
            st.markdown(f"🔥 **{md(c.get('name'))}** ({md(c.get('symbol'))}) · rang capi "
                        f"{c.get('market_cap_rank') or '—'}"
                        + (f" · {pc:+.1f} % / 24 h" if pc is not None else "")
                        + f"  \nCapi : {md(d.get('market_cap', '—'))} · Volume : {md(d.get('total_volume', '—'))}")
            st.caption(f"[CoinGecko](https://www.coingecko.com/fr/pi%C3%A8ces/{c.get('id')})")


def password_ok():
    pw = None if TEST_MODE else secret("APP_PASSWORD")
    if not pw or st.session_state.get("auth"):
        return True
    entered = st.text_input("Mot de passe", type="password")
    if entered == pw:
        st.session_state.auth = True
        st.rerun()
    elif entered:
        st.error("Mot de passe incorrect")
    return False


def main():
    st.set_page_config(page_title="Lancements Crypto", page_icon="🚀", layout="centered")
    st.title("🚀 Radar Lancements Crypto")
    if not password_ok():
        st.stop()
    with st.sidebar:
        days = st.select_slider("Lancés depuis", [14, 30, 60, 90, 180], value=60, format_func=lambda d: f"{d} j")
        min_tvl = st.select_slider("Argent déposé minimum", [1e6, 5e6, 20e6, 100e6], value=5e6,
                                   format_func=lambda v: f"{v / 1e6:.0f} M$")
        min_score = st.slider("Score minimum", 0, 100, 30)
        cats = st.multiselect("Catégories (vide = toutes)", st.session_state.get("cats", []))
        min_amount = st.select_slider("Levées : montant minimum", [1, 5, 10, 25, 50], value=5,
                                      format_func=lambda v: f"{v} M$")
        if st.button("🔄 Actualiser les données"):
            load_projects.clear(), load_raises.clear(), load_trending.clear()
    t1, t2, t3 = st.tabs(["🚀 Nouveaux projets", "🏦 Levées de fonds", "🔥 Tendances"])
    with t1:
        all_cats = tab_projects(days, min_tvl, min_score, cats)
        if all_cats and st.session_state.get("cats") != all_cats:
            st.session_state["cats"] = all_cats
    with t2:
        tab_raises(min_amount)
    with t3:
        tab_trending()
    st.caption("Données : DefiLlama, CoinGecko. Outil d'information, pas un conseil en investissement. "
               "La crypto est très risquée : ne mise que ce que tu peux te permettre de perdre.")


main()

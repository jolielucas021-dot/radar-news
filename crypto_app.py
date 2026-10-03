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
import html
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


def h(t):
    """Texte sûr pour du HTML (et sans déclencher les formules mathématiques de Streamlit)."""
    return html.escape(str(t or "")).replace("$", "&#36;")


def fr(x, dec=1):
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def usd(x):
    if x is None:
        return "—"
    for div, suf in ((1e9, " Md$"), (1e6, " M$"), (1e3, " k$")):
        if abs(x) >= div:
            v = x / div
            return f"{fr(v, 1 if abs(v) < 10 else 0)}{suf}"
    return f"{fr(x, 0)} $"


def price(x):
    if x is None:
        return "—"
    return f"{fr(x, 2)} $" if x >= 1 else f"{x:.4g} $".replace(".", ",")


MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def jour(ts):
    d = datetime.fromtimestamp(ts, timezone.utc).astimezone(core.PARIS)
    return f"{d.day} {MOIS[d.month - 1]}"


CATS = {"Derivatives": "Dérivés", "Lending": "Prêts", "Dexs": "Échange décentralisé", "Yield": "Rendement",
        "Liquid Staking": "Staking liquide", "Liquid Restaking": "Restaking liquide", "Restaking": "Restaking",
        "Bridge": "Pont", "Yield Aggregator": "Agrégateur de rendement", "CDP": "Stablecoin adossé",
        "RWA": "Actifs réels", "Launchpad": "Launchpad", "Gaming": "Jeux", "Payments": "Paiements",
        "Prediction Market": "Marché de prédiction", "Options": "Options", "Perps": "Dérivés"}


def cat(c):
    return CATS.get(c, c or "")


def pct(x, dec=0):
    return f"{x:+.{dec}f}".replace(".", ",") + " %"


def grade(score):
    """Note façon agence de notation + famille de couleur."""
    for lim, g in ((85, "AAA"), (75, "AA"), (65, "A"), (55, "BBB"), (45, "BB"), (35, "B")):
        if score >= lim:
            return g, ("a" if g.startswith("A") else "b")
    return "C", "c"


def html_block(s):
    st.markdown(s, unsafe_allow_html=True)


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap');
:root{--ink:#14213D;--paper:#F3F5F8;--card:#FFFFFF;--line:#DCE2EA;--muted:#5B6678;--cobalt:#2F5BEA;
--good:#1F8A5B;--good-bg:#E3F3EB;--warn:#A86B05;--warn-bg:#FBF0DA;--bad:#C2412D;--bad-bg:#FBE6E2;}
.stApp{background:var(--paper);color:var(--ink);font-family:'Atkinson Hyperlegible',system-ui,sans-serif;}
#MainMenu,footer,header[data-testid="stHeader"]{visibility:hidden;height:0;}
.block-container{max-width:720px;padding:1.2rem 1rem 3rem;}
.stApp p,.stApp li,.stApp label{font-family:'Atkinson Hyperlegible',system-ui,sans-serif;}
a,.stApp a{color:var(--cobalt)!important;text-decoration:none!important;font-weight:700;}
a:hover{text-decoration:underline;}
a:focus-visible,button:focus-visible{outline:3px solid var(--cobalt);outline-offset:2px;}
.rd-hero{padding:0 0 1.1rem;}
.rd-hero h1{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;font-size:2.4rem;line-height:1;
letter-spacing:-.02em;margin:0 0 .5rem;color:var(--ink);padding:0;}
.rd-hero p{color:var(--muted);font-size:1.02rem;line-height:1.45;margin:0 0 1rem;max-width:34em;}
.rd-scale{display:flex;gap:4px;align-items:stretch;}
.rd-scale span{flex:1;text-align:center;font-family:'Bricolage Grotesque',sans-serif;font-weight:700;
font-size:.85rem;padding:.35rem 0;border-radius:6px;}
.rd-scale .a{background:var(--good-bg);color:var(--good);}
.rd-scale .b{background:var(--warn-bg);color:var(--warn);}
.rd-scale .c{background:var(--bad-bg);color:var(--bad);}
.rd-scale-legend{display:flex;justify-content:space-between;color:var(--muted);font-size:.8rem;margin-top:.3rem;}
.stTabs [role="tablist"]{gap:.35rem;border-bottom:none!important;box-shadow:none!important;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;}
.stTabs [role="tablist"]::after,.stTabs [role="tablist"]::before{display:none!important;}
.stTabs [data-testid="stTab"]{background:#E4E9F0;border-radius:999px;padding:.4rem .85rem;height:auto;white-space:nowrap;
color:var(--ink);border:none!important;box-shadow:none!important;}
.stTabs [data-testid="stTab"] p{font-weight:700;font-size:.88rem;margin:0;}
.stTabs [data-testid="stTab"][aria-selected="true"]{background:var(--ink);}
.stTabs [data-testid="stTab"][aria-selected="true"] p{color:#fff;}
.stTabs [data-testid="stTab"]::after,.stTabs [data-testid="stTab"]::before{display:none!important;}
.stTabs .react-aria-SelectionIndicator{display:none!important;}
.stButton button{border-radius:10px;border:1.5px solid var(--ink);background:var(--card);color:var(--ink);
font-weight:700;padding:.45rem 1rem;}
.stButton button:hover{background:var(--ink);color:#fff;border-color:var(--ink);}
[data-testid="stExpander"]{border:1px solid var(--line);border-radius:12px;background:var(--card);}
[data-testid="stExpander"] summary p{font-weight:700;}
.rd-count{color:var(--muted);font-size:.9rem;margin:.6rem 0 .8rem;}
.rd-card{display:flex;gap:1rem;background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:1rem;margin:0 0 .5rem;}
.rd-grade{flex:0 0 74px;border-radius:12px;display:flex;flex-direction:column;align-items:center;
justify-content:center;padding:.6rem 0;align-self:flex-start;}
.rd-grade b{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;font-size:1.7rem;line-height:1;letter-spacing:-.02em;}
.rd-grade small{font-size:.75rem;margin-top:.25rem;opacity:.85;}
.rd-grade.a{background:var(--good);color:#fff;}
.rd-grade.b{background:var(--warn);color:#fff;}
.rd-grade.c{background:var(--bad);color:#fff;}
.rd-body{flex:1;min-width:0;}
.rd-name{font-family:'Bricolage Grotesque',sans-serif;font-weight:700;font-size:1.3rem;line-height:1.15;color:var(--ink);}
.rd-sym{font-family:'Atkinson Hyperlegible',sans-serif;font-weight:400;font-size:.85rem;color:var(--muted);margin-left:.35rem;}
.rd-meta{color:var(--muted);font-size:.9rem;margin:.2rem 0 .7rem;}
.rd-metrics{display:grid;grid-template-columns:1fr 1fr;gap:.45rem;margin-bottom:.7rem;}
.rd-metrics div{background:var(--paper);border-radius:10px;padding:.5rem .65rem;}
.rd-metrics b{display:block;font-family:'Bricolage Grotesque',sans-serif;font-size:1.1rem;color:var(--ink);}
.rd-metrics span{font-size:.78rem;color:var(--muted);line-height:1.3;display:block;}
.rd-signals{list-style:none;padding:0;margin:0 0 .6rem;}
.rd-signals li{position:relative;padding-left:1.4rem;margin:.25rem 0;font-size:.93rem;line-height:1.35;}
.rd-signals li::before{position:absolute;left:0;top:0;font-weight:700;}
.rd-signals li.ok::before{content:"✓";color:var(--good);}
.rd-signals li.ko::before{content:"!";color:var(--bad);left:.25rem;}
.rd-links a{margin-right:1rem;font-size:.9rem;}
.rd-dossier{background:var(--card);border-left:4px solid var(--cobalt);border-radius:0 12px 12px 0;
padding:.9rem 1rem;margin:.3rem 0 1.4rem;}
.rd-dossier h4{font-family:'Bricolage Grotesque',sans-serif;margin:0 0 .4rem;font-size:1.05rem;color:var(--ink);}
.rd-dossier p{margin:.3rem 0;font-size:.93rem;line-height:1.45;}
.rd-dossier .lvl{font-weight:700;}
.rd-row{display:flex;justify-content:space-between;gap:1rem;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:.85rem 1rem;margin-bottom:.5rem;}
.rd-row .rd-name{font-size:1.1rem;}
.rd-amount{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;font-size:1.35rem;white-space:nowrap;color:var(--ink);}
.rd-inv{font-size:.9rem;margin-top:.3rem;}
.rd-star{color:var(--warn);margin-left:.3rem;}
.rd-rank{font-family:'Bricolage Grotesque',sans-serif;font-weight:800;font-size:1.3rem;color:#B6C0CE;min-width:1.8rem;}
.rd-up{color:var(--good);font-weight:700;}
.rd-down{color:var(--bad);font-weight:700;}
.stApp .rd-note{color:var(--muted);font-size:.82rem!important;line-height:1.45;margin:1.5rem 0 0;}
@media (max-width:480px){.rd-hero h1{font-size:2rem;}.rd-card{flex-direction:column;gap:.7rem;padding:.9rem;}
.rd-grade{flex-direction:row;gap:.6rem;align-self:stretch;justify-content:flex-start;padding:.5rem .8rem;flex-basis:auto;}
.rd-grade small{margin:0;}.rd-grade b{font-size:1.5rem;}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;}}
</style>
"""


@st.cache_resource
def analyses():
    return {}


@st.cache_data(ttl=1800, show_spinner=False)
def load_projects(days, min_tvl):
    return cc.build(days, min_tvl, secret("COINGECKO_API_KEY"))


@st.cache_resource
def raise_cache():
    return {}


@st.cache_data(ttl=3600, show_spinner=False)
def load_raises(days):
    """DefiLlama si disponible (offre Pro), sinon levées repérées par l'IA dans les médias crypto."""
    try:
        return cc.fetch_raises(days), "DefiLlama"
    except Exception:
        items, _ = cc.press_items(days=min(days, 14))
        cfg = core.llm_config(lambda k: secret(k))
        return cc.raises_from_news(cfg, raise_cache(), items), "médias"


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
    g, fam = grade(x["score"])
    chains = ", ".join((p.get("chains") or [])[:3])
    age = "lancé aujourd'hui" if x["age"] == 0 else f"lancé il y a {x['age']} jour{'s' if x['age'] > 1 else ''}"
    sym = p.get("symbol") if p.get("symbol") not in (None, "-", "") else None
    ch7 = p.get("change_7d")
    metrics = [(usd(p.get("tvl")), "déposés" + (f", {pct(ch7)} sur 7 j" if ch7 is not None else "")),
               (usd(x["fees30"]), "de revenus sur 30 j")]
    if m:
        pc = m.get("price_change_percentage_24h")
        metrics.append((price(m.get("current_price")), "prix du token" + (f", {pct(pc, 1)} en 24 h" if pc is not None else "")))
        if m.get("market_cap") and m.get("fully_diluted_valuation"):
            metrics.append((usd(m.get("fully_diluted_valuation")), f"valeur totale, dont {usd(m.get('market_cap'))} en circulation"))
    else:
        metrics.append(("Pas de token", "rien n'est encore coté"))
    if rz:
        leads = ", ".join(rz.get("leadInvestors") or []) or "investisseurs non précisés"
        metrics.append((f"{rz['amount']:g} M$" if rz.get("amount") else "Levée", f"levés, menée par {leads}"))
    sig = "".join(f'<li class="ok">{h(s)}</li>' for s in x["good"]) + \
          "".join(f'<li class="ko">{h(s)}</li>' for s in x["red"])
    links = [(l, u) for l, u in (("Site", p.get("url")),
                                 ("X", f"https://x.com/{p['twitter']}" if p.get("twitter") else None),
                                 ("DefiLlama", f"https://defillama.com/protocol/{p.get('slug')}")) if u]
    html_block(
        f'<div class="rd-card"><div class="rd-grade {fam}"><b>{g}</b><small>{x["score"]}/100</small></div>'
        f'<div class="rd-body"><div class="rd-name">{h(p["name"])}'
        + (f'<span class="rd-sym">{h(sym)}</span>' if sym else "") + '</div>'
        f'<div class="rd-meta">{h(cat(p.get("category")))}{" sur " + h(chains) if chains else ""}, {age}</div>'
        '<div class="rd-metrics">' + "".join(f"<div><b>{h(v)}</b><span>{h(l)}</span></div>" for v, l in metrics) + '</div>'
        f'<ul class="rd-signals">{sig}</ul>'
        '<div class="rd-links">' + "".join(f'<a href="{h(u)}" target="_blank" rel="noopener">{l}</a>' for l, u in links)
        + '</div></div></div>')

    with st.expander("Détail de la note"):
        st.write("\n".join(f"- {k} : {v:+.0f} pts" for k, v in x["pts"].items()))
        if p.get("description"):
            st.caption(md(p["description"][:400]))
    key = p.get("slug") or p["name"]
    res = analyses().get(key)
    if res is None and st.button("Demander l'avis de l'IA (≈ 0,03 $)", key=f"ai_{i}"):
        with st.spinner("L'IA enquête sur le web…"):
            try:
                res = ai_analysis(x)
            except Exception as ex:
                st.warning(f"Analyse impossible : {type(ex).__name__}. Vérifie la clé API et le crédit.")
    if res:
        parts = [f'<h4>Avis de l\'IA <span class="lvl">sérieux {h(res.get("serieux", "?"))}</span></h4>',
                 f'<p>{h(res.get("resume", ""))}</p>']
        for lab, k in (("Équipe", "equipe"), ("Investisseurs", "investisseurs"),
                       ("Tokenomics", "tokenomics"), ("À surveiller", "a_surveiller")):
            if res.get(k):
                parts.append(f"<p><b>{lab}.</b> {h(res[k])}</p>")
        items = [f'<li class="ok">{h(t)}</li>' for t in res.get("points_forts") or []] + \
                [f'<li class="ko">{h(t)}</li>' for t in (res.get("risques") or []) + (res.get("drapeaux_rouges") or [])]
        if items:
            parts.append(f'<ul class="rd-signals">{"".join(items)}</ul>')
        if res.get("sources"):
            parts.append('<p class="rd-links">' + "".join(
                f'<a href="{h(u)}" target="_blank" rel="noopener">{h((t or "Source")[:30])}</a>'
                for t, u in res["sources"] if u) + "</p>")
        html_block(f'<div class="rd-dossier">{"".join(parts)}</div>')
    else:
        html_block('<div style="height:1rem"></div>')


def tab_projects():
    with st.expander("Filtres"):
        c1, c2 = st.columns(2)
        days = c1.select_slider("Lancés depuis", [14, 30, 60, 90, 180], value=60, format_func=lambda d: f"{d} jours")
        min_tvl = c2.select_slider("Déposé au minimum", [1e6, 5e6, 20e6, 100e6], value=5e6,
                                   format_func=lambda v: f"{v / 1e6:.0f} M$")
        min_score = st.slider("Note minimum (sur 100)", 0, 100, 30)
        cats = st.multiselect("Catégories (vide = toutes)", st.session_state.get("cats", []), format_func=cat)
        if st.button("Actualiser les données"):
            load_projects.clear()
    with st.spinner("Chargement des nouveaux projets…"):
        try:
            items, errors = load_projects(days, min_tvl)
        except Exception as ex:
            st.error(f"DefiLlama ne répond pas ({type(ex).__name__}). Réessaie dans quelques minutes.")
            return
    st.session_state["cats"] = sorted({x["p"].get("category") or "Autre" for x in items})
    shown = [x for x in items if x["score"] >= min_score
             and (not cats or (x["p"].get("category") or "Autre") in cats)]
    html_block(f'<div class="rd-count">{len(shown)} projet{"s" if len(shown) > 1 else ""} lancé'
               f'{"s" if len(shown) > 1 else ""} ces {days} derniers jours, avec au moins {h(usd(min_tvl))} déposés.</div>')
    for e in errors:
        st.caption(f"Source indisponible : {e}")
    if not shown:
        st.info("Aucun projet ne passe ces filtres. Baisse la note minimum ou le montant déposé dans « Filtres ».")
    for i, x in enumerate(shown[:60]):
        project_card(x, i)


def tab_raises():
    min_amount = st.select_slider("Montant minimum", [0, 1, 5, 10, 25, 50], value=1,
                                  format_func=lambda v: "tous" if v == 0 else f"{v} M$")
    with st.spinner("Recherche des levées de fonds dans les médias…"):
        try:
            raises, src = load_raises(60)
        except Exception as ex:
            st.error(f"Levées de fonds indisponibles : {type(ex).__name__}. Vérifie la clé API.")
            return
    rows = [r for r in raises if r.get("amount") is None or r["amount"] >= min_amount]
    rows.sort(key=lambda r: r.get("date") or 0, reverse=True)
    origin = ("repérées par l'IA dans les médias crypto ces derniers jours" if src == "médias"
              else "recensées par DefiLlama sur 60 jours")
    html_block(f'<div class="rd-count">{len(rows)} levée{"s" if len(rows) > 1 else ""} de fonds {origin}. '
               "★ signale un investisseur de premier plan.</div>")
    if not rows:
        st.info("Aucune levée récente avec ce montant. Choisis « tous » ou reviens plus tard.")
    for r in rows[:80]:
        inv_l, inv_o = r.get("leadInvestors") or [], r.get("otherInvestors") or []
        star = '<span class="rd-star">★</span>' if cc.is_tier1(inv_l + inv_o) else ""
        amt = f"{fr(r['amount'], 0) if r['amount'] >= 10 else fr(r['amount'])} M$" if r.get("amount") else "n.c."
        meta = ", ".join(x for x in (r.get("round"), r.get("category"), jour(r["date"]) if r.get("date") else None) if x)
        inv = ""
        if inv_l:
            inv = "Menée par " + h(", ".join(inv_l)) + (f", avec {h(', '.join(inv_o[:5]))}" if inv_o else "")
        elif inv_o:
            inv = "Avec " + h(", ".join(inv_o[:6]))
        src_link = (f' <a href="{h(r["source"])}" target="_blank" rel="noopener">{h(r.get("source_name") or "Source")}</a>'
                    if r.get("source") else "")
        html_block(f'<div class="rd-row"><div><div class="rd-name">{h(r.get("name"))}{star}</div>'
                   f'<div class="rd-meta" style="margin-bottom:0">{h(meta)}</div>'
                   + (f'<div class="rd-inv">{inv}</div>' if inv else "")
                   + (f'<div class="rd-meta" style="margin:.3rem 0 0">{h(r.get("resume"))}{src_link}</div>'
                      if r.get("resume") or src_link else "")
                   + f'</div><div class="rd-amount">{h(amt)}</div></div>')


def tab_trending():
    try:
        coins = load_trending()
    except Exception as ex:
        st.error(f"CoinGecko ne répond pas ({type(ex).__name__}). Réessaie dans quelques minutes.")
        return
    html_block('<div class="rd-count">Les cryptos les plus recherchées sur CoinGecko ces dernières 24 h. '
               "C'est une mesure de l'attention, pas de la qualité : les pics de recherche précèdent souvent des chutes.</div>")
    for n, c in enumerate(coins, 1):
        d = c.get("data") or {}
        pc = (d.get("price_change_percentage_24h") or {}).get("usd")
        chg = f'<span class="{"rd-up" if pc >= 0 else "rd-down"}">{pct(pc, 1)}</span>' if pc is not None else ""
        rank = f"rang {c['market_cap_rank']} en capitalisation" if c.get("market_cap_rank") else "non classé"
        html_block(f'<div class="rd-row" style="align-items:center"><div class="rd-rank">{n}</div>'
                   f'<div style="flex:1"><div class="rd-name">{h(c.get("name"))}'
                   f'<span class="rd-sym">{h(c.get("symbol"))}</span></div>'
                   f'<div class="rd-meta" style="margin:0">{h(rank)}, capi {h(d.get("market_cap", "—"))}</div></div>'
                   f'<div style="text-align:right">{chg}<br><a href="https://www.coingecko.com/fr/pi%C3%A8ces/{h(c.get("id"))}" '
                   'target="_blank" rel="noopener">Voir</a></div></div>')


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
    st.set_page_config(page_title="Radar lancements", page_icon="🚀", layout="centered",
                       initial_sidebar_state="collapsed")
    html_block(CSS)
    html_block('<div class="rd-hero"><h1>Radar lancements</h1>'
               "<p>Les nouveaux projets crypto, notés comme le ferait une agence de notation : "
               "sur ce qu'ils prouvent, pas sur ce qu'ils promettent.</p>"
               '<div class="rd-scale"><span class="a">AAA</span><span class="a">AA</span><span class="a">A</span>'
               '<span class="b">BBB</span><span class="b">BB</span><span class="b">B</span><span class="c">C</span></div>'
               '<div class="rd-scale-legend"><span>Solide</span><span>À surveiller</span><span>Fragile</span></div></div>')
    if not password_ok():
        st.stop()
    t1, t2, t3 = st.tabs(["Projets", "Levées", "Tendances"])
    with t1:
        tab_projects()
    with t2:
        tab_raises()
    with t3:
        tab_trending()
    html_block('<p class="rd-note">Données DefiLlama et CoinGecko, levées repérées dans les médias crypto. '
               "La note mesure le sérieux apparent d'un projet, pas son potentiel de hausse : ce n'est pas un "
               "conseil en investissement. Ne mise que ce que tu peux te permettre de perdre.</p>")


main()

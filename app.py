# -*- coding: utf-8 -*-
"""
📡 Radar News Marchés — US, Macro, Crypto
  📰 News   : flux RSS analysés par Claude (importance 1-5, impact probable)
  📅 Agenda : événements macro (consensus Forex Factory, chiffres officiels BLS),
              résultats d'entreprises (Finnhub), ce qu'attend le marché

Secrets Streamlit (Settings > Secrets) — UNE des deux clés d'IA suffit :
    OPENAI_API_KEY    = "sk-..."       # ChatGPT (modèle par défaut : gpt-5-mini)
    ANTHROPIC_API_KEY = "sk-ant-..."   # Claude (modèle par défaut : claude-haiku-4-5)
    APP_PASSWORD      = "..."
    BLS_API_KEY       = "..."      # gratuit : data.bls.gov/registrationEngine
    FINNHUB_API_KEY   = "..."      # gratuit : finnhub.io/register
Optionnels : MODEL, MAX_ANALYSES_JOUR (400), MAX_RECHERCHES_JOUR (20)
"""
import json
import os
from datetime import datetime, timedelta, timezone

import streamlit as st

import core
from core import PARIS

TEST_MODE = os.environ.get("RADAR_TEST") == "1"   # tests hors ligne uniquement

EMOJI_IMP = {5: "🔴", 4: "🟠", 3: "🟡", 2: "⚪", 1: "⚫"}
EMOJI_IMPACT = {"haussier": "📈", "baissier": "📉", "neutre": "➖", "incertain": "❓"}
FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺"}
JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# Mémoire du serveur + appels Claude avec suivi des coûts
# ---------------------------------------------------------------------------
@st.cache_resource
def store():
    return {"analyses": {}, "items": {}, "expect": {}, "results": {},
            "day": None, "count": 0, "tok_in": 0, "tok_out": 0, "searches": 0}


def new_day():
    s = store()
    today = datetime.now(PARIS).date()
    if s["day"] != today:
        s.update(day=today, count=0, tok_in=0, tok_out=0, searches=0)
    return s


def llm():
    return core.llm_config(lambda k: secret(k))


def cost_today():
    s, c = new_day(), llm()
    return s["tok_in"] / 1e6 * c["price_in"] + s["tok_out"] / 1e6 * c["price_out"] + s["searches"] * 0.01


def ask(system, user, max_tokens=3000, web=False):
    s = new_day()
    if TEST_MODE:
        return dict(text=os.environ.get("RADAR_FAKE", "[]"), sources=[])
    if web and s["searches"] >= int(secret("MAX_RECHERCHES_JOUR", 20)):
        raise RuntimeError("plafond quotidien de recherches web atteint")
    r = core.llm_call(llm(), system, user, max_tokens=max_tokens, web=web)
    s["tok_in"] += r["tok_in"]
    s["tok_out"] += r["tok_out"]
    s["searches"] += r["searches"]
    return r


# ---------------------------------------------------------------------------
# NEWS
# ---------------------------------------------------------------------------
@st.cache_data(ttl=120, show_spinner=False)
def fetch_news(themes):
    return core.fetch_feeds(themes)


def analyze(items, limit=60):
    s = new_day()
    cap = int(secret("MAX_ANALYSES_JOUR", 400))
    todo = [it for it in items if it["id"] not in s["analyses"]][:limit]
    todo = todo[: max(0, cap - s["count"])]
    for k in range(0, len(todo), 12):
        batch = todo[k:k + 12]
        payload = [dict(id=it["id"], source=it["source"], titre=it["title"], resume=it["summary"])
                   for it in batch]
        try:
            if TEST_MODE:
                res = [dict(id=it["id"], importance=4, theme=it["theme"], actifs=["SPY"],
                            impact="neutre", resume="Test.", analyse="Test.") for it in batch]
            else:
                res = core.parse_json_array(ask(core.NEWS_PROMPT, json.dumps(payload, ensure_ascii=False),
                                                max_tokens=4000)["text"])
        except Exception as ex:
            st.warning(f"Analyse indisponible ({type(ex).__name__}: {str(ex)[:120]}). Vérifie la clé API et le crédit.")
            return
        for r in res:
            if isinstance(r, dict) and r.get("id"):
                s["analyses"][r["id"]] = r
        for it in batch:
            s["items"][it["id"]] = (it["title"], it["time"])
        s["count"] += len(batch)


def recent_context(hours=48, n=15):
    """Titres des news importantes (≥ 4/5) récentes : contexte pour les scénarios."""
    s = store()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = [(t, ti) for i, (ti, t) in s["items"].items()
            if t >= cutoff and int(s["analyses"].get(i, {}).get("importance", 0)) >= 4]
    return [ti for t, ti in sorted(rows, reverse=True)[:n]]


def md_safe(t):
    return str(t).replace("$", r"\$").replace("[", "(").replace("]", ")")


def ago(dt):
    m = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    return f"il y a {m} min" if m < 60 else f"il y a {m // 60} h" if m < 1440 else dt.astimezone(PARIS).strftime("%d/%m %H:%M")


def jour(d):
    return f"{JOURS[d.weekday()]} {d:%d/%m}"


def news_card(it, a):
    with st.container(border=True):
        if a:
            imp = int(a.get("importance", 1))
            impact = a.get("impact", "incertain")
            st.markdown(f"{EMOJI_IMP.get(imp, '⚪')} **{imp}/5** · {EMOJI_IMPACT.get(impact, '❓')} "
                        f"{impact} · {it['theme']} · {it['source']} · {ago(it['time'])}")
        else:
            st.markdown(f"⏳ non analysé · {it['theme']} · {it['source']} · {ago(it['time'])}")
        st.markdown(f"**[{md_safe(it['title'])}]({it['link']})**")
        if a:
            st.markdown(md_safe(a.get("resume", "")))
            with st.expander("Analyse"):
                st.markdown(md_safe(a.get("analyse", "")))
                st.caption(f"Actifs : {', '.join(a.get('actifs', [])) or '—'} · "
                           f"Horizon : {a.get('horizon', '—')} · Confiance : {a.get('confiance', '—')}")


def section_news():
    with st.sidebar:
        themes = st.multiselect("Thèmes", list(core.FEEDS), default=list(core.FEEDS))
        hours = st.select_slider("Fenêtre", [3, 6, 12, 24, 48], value=12, format_func=lambda h: f"{h} h")
        min_imp = st.slider("Importance minimum", 1, 5, 3)
        impacts = st.multiselect("Impact", list(EMOJI_IMPACT), default=list(EMOJI_IMPACT))
        auto = st.toggle("Rafraîchissement auto", value=True)
        every = st.selectbox("Toutes les", [5, 10, 15, 30], index=1, format_func=lambda m: f"{m} min")

    def render():
        if not themes:
            st.info("Choisis au moins un thème.")
            return
        items, errors = fetch_news(tuple(themes))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        items = [it for it in items if it["time"] >= cutoff]
        with st.spinner("Analyse des nouvelles news…"):
            analyze(items)
        A = store()["analyses"]
        shown = [it for it in items if (a := A.get(it["id"])) is None
                 or (int(a.get("importance", 1)) >= min_imp and a.get("impact") in impacts)]
        shown.sort(key=lambda it: (int(A.get(it["id"], {}).get("importance", 0)), it["time"]), reverse=True)
        major = sum(1 for it in items if int(A.get(it["id"], {}).get("importance", 0)) >= 4)
        st.caption(f"Mis à jour à {datetime.now(PARIS):%H:%M} · {len(items)} news sur {hours} h · "
                   f"{major} majeure(s) · dépense du jour ≈ {cost_today():.2f} $")
        if errors:
            with st.expander(f"⚠️ {len(errors)} source(s) en erreur"):
                st.write("\n".join(f"- {e}" for e in errors))
        if not shown:
            st.info("Aucune news ne correspond aux filtres.")
        for it in shown[:80]:
            news_card(it, A.get(it["id"]))

    st.fragment(run_every=timedelta(minutes=every) if auto else None)(render)()
    if st.button("🔄 Actualiser maintenant"):
        fetch_news.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# AGENDA — MACRO
# ---------------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def fetch_macro():
    return core.fetch_macro()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_bls(titles):
    if TEST_MODE:
        return json.loads(os.environ.get("RADAR_FAKE_BLS", "{}"), object_hook=None)
    return core.fetch_bls(secret("BLS_API_KEY"), list(titles))


def ensure_context():
    """Si la section News n'a pas tourné récemment, on analyse les news US + Macro pour le contexte."""
    if not recent_context():
        items, _ = fetch_news(("US", "Macro"))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        analyze([it for it in items if it["time"] >= cutoff], limit=48)


def expectations(events):
    cache = store()["expect"]
    now = datetime.now(timezone.utc)
    # (a) événements majeurs dans les 36 h : avant-papiers lus sur le web
    for e in [e for e in events if e["impact"] == "High" and e["time"] < now + timedelta(hours=36)]:
        if e["id"] in cache:
            continue
        user = json.dumps(dict(evenement=e["title"], zone=e["country"],
                               date=e["time"].astimezone(PARIS).strftime("%d/%m/%Y %H:%M (Paris)"),
                               consensus=e["forecast"], precedent=e["previous"]), ensure_ascii=False)
        try:
            r = ask(core.EXPECT_WEB_PROMPT, user, max_tokens=1500, web=True)
            obj = core.parse_json_object(r["text"])
            if obj:
                obj["sources"], obj["web"] = r["sources"], True
                cache[e["id"]] = obj
        except Exception:
            break                                  # plafond atteint ou recherche désactivée
    # (b) les autres : un appel groupé, avec le contexte des news récentes
    todo = [e for e in events if e["id"] not in cache]
    ctx = recent_context()
    for k in range(0, len(todo), 8):
        batch = [dict(id=e["id"], evenement=e["title"], zone=e["country"],
                      date=e["time"].astimezone(PARIS).strftime("%d/%m %H:%M"),
                      forecast=e["forecast"], previous=e["previous"]) for e in todo[k:k + 8]]
        try:
            r = ask(core.EXPECT_PROMPT, json.dumps({"contexte_recent": ctx, "evenements": batch},
                                                   ensure_ascii=False))
            for o in core.parse_json_array(r["text"]):
                if isinstance(o, dict) and o.get("id"):
                    cache[o["id"]] = o
        except Exception as ex:
            st.warning(f"Attentes indisponibles ({type(ex).__name__}).")
            return


def web_result(e):
    cache = store()["results"]
    if e["id"] not in cache:
        user = json.dumps(dict(evenement=e["title"], zone=e["country"],
                               date_publication=e["time"].astimezone(PARIS).strftime("%Y-%m-%d %H:%M (Paris)"),
                               consensus=e["forecast"], precedent=e["previous"]), ensure_ascii=False)
        r = ask(core.RESULT_PROMPT, user, max_tokens=1500, web=True)
        obj = core.parse_json_object(r["text"]) or {"actual": None}
        obj["sources"] = r["sources"]
        cache[e["id"]] = obj
    return cache[e["id"]]


def countdown(dt):
    m = int((dt - datetime.now(timezone.utc)).total_seconds() // 60)
    if m < 0:
        return "publié"
    return f"dans {m} min" if m < 60 else f"dans {m // 60} h {m % 60:02d}" if m < 1440 else f"dans {m // 1440} j"


def sources_line(src):
    return " · ".join(f"[{md_safe(t[:40]) or 'lien'}]({u})" for t, u in src if u)


def macro_card(e, exp, official, released):
    with st.container(border=True):
        local = e["time"].astimezone(PARIS)
        st.markdown(f"{'🔴' if e['impact'] == 'High' else '🟠'} {FLAGS.get(e['country'], '')} "
                    f"**{md_safe(e['title'])}**  \n{jour(local)} · {local:%H:%M} · {countdown(e['time'])}")
        if e["forecast"] or e["previous"]:
            st.markdown(f"Consensus : **{md_safe(e['forecast'] or '—')}** · Précédent : {md_safe(e['previous'] or '—')}")

        if official:                                # chiffre officiel BLS : automatique
            icon = {1: "⬆️", -1: "⬇️", 0: "➡️"}.get(official.get("direction"), "📊")
            st.markdown(f"{icon} **Publié : {official['actual']}** vs {md_safe(official['consensus'])} "
                        f"({official.get('ecart', '')}) → **{official['verdict']}**")
            if official.get("lecture"):
                st.markdown(official["lecture"])
            st.caption(f"Source : {official['source']}, période {official['periode']}. "
                       "Lecture standard : le contexte peut changer la réaction du marché.")
        elif released:                              # sinon : recherche web à la demande
            res = store()["results"].get(e["id"])
            if res is None and st.button("📊 Résultat vs attentes", key=f"res_{e['id']}"):
                with st.spinner("Recherche du chiffre publié…"):
                    try:
                        res = web_result(e)
                    except Exception as ex:
                        st.warning(f"Recherche impossible ({ex}).")
            if res:
                if not res.get("actual"):
                    st.info("Chiffre publié introuvable pour l'instant.")
                else:
                    st.markdown(f"📊 **Publié : {md_safe(res['actual'])}** vs "
                                f"{md_safe(res.get('consensus') or e['forecast'])} ({md_safe(res.get('ecart', ''))}) "
                                f"→ **{res.get('verdict', '')}**, surprise {res.get('intensite', '')}")
                    st.markdown(f"🏭 Économie : {md_safe(res.get('lecture_economie', ''))}  \n"
                                f"📈 Marchés : {md_safe(res.get('lecture_marches', ''))}")
                    if res.get("reaction_observee"):
                        st.markdown(f"👀 Réaction : {md_safe(res['reaction_observee'])}")
                    st.caption(f"Confiance : {res.get('confiance', '—')} · {sources_line(res.get('sources', []))}")

        if exp and not released:
            st.markdown(f"🎯 {md_safe(exp.get('attente', ''))}")
            with st.expander("Ce qu'attend le marché" + (" (lu sur le web)" if exp.get("web") else "")):
                st.markdown(f"**Enjeu :** {md_safe(exp.get('enjeu', ''))}\n\n"
                            f"⬆️ **Au-dessus du consensus :** {md_safe(exp.get('si_superieur', ''))}\n\n"
                            f"⬇️ **En dessous :** {md_safe(exp.get('si_inferieur', ''))}\n\n"
                            f"➡️ **Conforme :** {md_safe(exp.get('si_conforme', ''))}")
                if exp.get("sources"):
                    st.caption(sources_line(exp["sources"]))


# ---------------------------------------------------------------------------
# AGENDA — ENTREPRISES
# ---------------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def fetch_earnings(symbols):
    today = datetime.now(PARIS).date()
    if TEST_MODE:
        rows = json.loads(os.environ.get("RADAR_FAKE_EARN", "[]"))
        for r in rows:
            r["date"] = today + timedelta(days=r.pop("offset"))
        return rows, []
    return core.fetch_earnings(secret("FINNHUB_API_KEY"), today - timedelta(days=4),
                               today + timedelta(days=10), symbols)


def earnings_card(r):
    with st.container(border=True):
        st.markdown(f"🏢 **{md_safe(r['symbol'])}** · {md_safe(r['name'])}  \n"
                    f"{jour(r['date'])} · {core.HOURS.get(r['hour'], 'heure non précisée')}")
        est = f"{r['eps_est']:.2f} \\$" if r["eps_est"] is not None else "—"
        st.markdown(f"Attendu : BPA **{est}** · CA **{md_safe(core.fmt_rev(r["rev_est"]))}**")
        if r["eps"] is not None:
            parts = []
            for label, a, e, f in (("BPA", r["eps"], r["eps_est"], lambda x: f"{x:.2f} \\$"),
                                   ("CA", r["rev"], r["rev_est"], lambda x: md_safe(core.fmt_rev(x)))):
                if a is None:
                    continue
                sp = core.surprise_pct(a, e)
                icon = "✅" if sp and sp > 0.5 else "❌" if sp and sp < -0.5 else "➖"
                parts.append(f"{icon} {label} **{f(a)}**" + (f" ({sp:+.1f} %)" if sp is not None else ""))
            st.markdown("Publié : " + " · ".join(parts))


# ---------------------------------------------------------------------------
def section_agenda():
    with st.sidebar:
        zones = st.multiselect("Zones", ["USD", "EUR"], default=["USD", "EUR"],
                               format_func=lambda z: f"{FLAGS[z]} {z}")
        lvl = st.radio("Importance", ["Forte seulement", "Forte + moyenne"])
        wl = st.text_area("Entreprises suivies (tickers)", ", ".join(core.LARGE_CAPS), height=120)
    impacts = ["High"] if lvl == "Forte seulement" else ["High", "Medium"]
    symbols = tuple(sorted({s.strip().upper() for s in wl.replace("\n", ",").split(",") if s.strip()}))

    tab_macro, tab_earn = st.tabs(["🏛️ Macro", "🏢 Résultats d'entreprises"])
    with tab_macro:
        events, errors = fetch_macro()
        events = [e for e in events if e["country"] in zones and e["impact"] in impacts]
        now = datetime.now(timezone.utc)
        upcoming = [e for e in events if e["time"] > now]
        released = [e for e in events if e["time"] <= now][::-1]
        bls, bls_err = {}, None
        titles = tuple(sorted({e["title"] for e in released if e["title"] in core.BLS_SPECS}))
        if titles:
            try:
                bls = fetch_bls(titles)
            except Exception as ex:
                bls_err = f"BLS : {type(ex).__name__}"
        if errors or bls_err:
            with st.expander("⚠️ Source(s) en erreur"):
                st.write("\n".join(f"- {x}" for x in errors + ([bls_err] if bls_err else [])))
        with st.spinner("Préparation des attentes du marché…"):
            if not TEST_MODE:
                ensure_context()
            expectations([e for e in upcoming if e["time"] < now + timedelta(days=8)][:24])
        exp = store()["expect"]
        st.subheader(f"À venir ({len(upcoming)})")
        if not upcoming:
            st.info("Aucun événement à venir avec ces filtres.")
        for e in upcoming[:30]:
            macro_card(e, exp.get(e["id"]), None, released=False)
        st.subheader(f"Déjà publiés ({len(released)})")
        st.caption("Inflation, emploi, chômage, salaires US : résultat officiel automatique (BLS). "
                   "Autres : bouton « Résultat vs attentes » (≈ 0,03 $).")
        for e in released[:20]:
            macro_card(e, exp.get(e["id"]), core.official_result(e, bls), released=True)
        st.caption(f"Dépense du jour ≈ {cost_today():.2f} $")
    with tab_earn:
        rows, errors = fetch_earnings(symbols)
        for x in errors:
            st.warning(x)
        today = datetime.now(PARIS).date()
        up = sorted([r for r in rows if r["eps"] is None and r["date"] >= today], key=lambda r: r["date"])
        done = sorted([r for r in rows if r["eps"] is not None], key=lambda r: r["date"], reverse=True)
        st.caption("Le BPA n'est qu'une partie de l'histoire : les prévisions (guidance) "
                   "pèsent souvent plus sur le cours que le chiffre du trimestre.")
        st.subheader(f"À venir ({len(up)})")
        for r in up[:40]:
            earnings_card(r)
        st.subheader(f"Publiés ({len(done)})")
        for r in done[:30]:
            earnings_card(r)


# ---------------------------------------------------------------------------
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
    st.set_page_config(page_title="Radar News", page_icon="📡", layout="centered")
    st.title("📡 Radar News Marchés")
    if not password_ok():
        st.stop()
    section = st.radio("Section", ["📰 News", "📅 Agenda"], horizontal=True, label_visibility="collapsed")
    if section == "📰 News":
        section_news()
    else:
        section_agenda()
    st.caption(f"IA : {llm()['provider']} · modèle {llm()['model']}. Outil d'information, pas un conseil en investissement. Les flux ont quelques minutes "
               "de retard et une IA peut se tromper : vérifie toujours la source.")


main()

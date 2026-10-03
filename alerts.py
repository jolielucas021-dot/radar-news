# -*- coding: utf-8 -*-
"""
alerts.py — robot d'alertes Telegram, lancé toutes les 10 min par GitHub Actions.

Envoie :
  1. les news notées ≥ MIN_IMPORTANCE (5 par défaut), avec résumé et analyse
  2. un rappel ~1 h avant chaque événement macro majeur (consensus + scénarios)
  3. le résultat officiel BLS (inflation, emploi, chômage, salaires) vs consensus, dès sa publication
  4. les résultats des grandes entreprises (BPA et CA vs attentes)

Secrets GitHub (Settings > Secrets and variables > Actions) :
  ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, BLS_API_KEY, FINNHUB_API_KEY
  TELEGRAM_CHAT_ID (facultatif : détecté automatiquement après ton /start au bot)
Variables facultatives : MIN_IMPORTANCE (5), ZONES ("USD,EUR")
"""
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import core
from core import PARIS

STATE = Path("state/alerts_state.json")
ENV = os.environ.get
TOKEN = ENV("TELEGRAM_BOT_TOKEN", "")
MIN_IMP = int(ENV("MIN_IMPORTANCE") or 5)
ZONES = [z.strip() for z in (ENV("ZONES") or "USD,EUR").split(",")]
NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- état
def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(s):
    for k in ("news", "pre", "macro", "earn"):
        s[k] = s.get(k, [])[-3000:]                  # on borne la taille
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s))


# --------------------------------------------------------------------------- Telegram
def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params, timeout=15)
    return r.json()


def chat_id(state):
    cid = ENV("TELEGRAM_CHAT_ID") or state.get("chat_id")
    if cid:
        return cid
    upd = tg("getUpdates").get("result", [])
    for u in reversed(upd):
        msg = u.get("message") or u.get("channel_post") or {}
        if msg.get("chat", {}).get("id"):
            state["chat_id"] = msg["chat"]["id"]
            return state["chat_id"]
    return None


def send(cid, text):
    tg("sendMessage", chat_id=cid, text=text[:4000], parse_mode="HTML",
       disable_web_page_preview=True)


def esc(x):
    return html.escape(str(x or ""))


# --------------------------------------------------------------------------- 1. news
def alert_news(state, cid, key):
    seen = set(state.get("news", []))
    items, _ = core.fetch_feeds(tuple(core.FEEDS))
    fresh = [it for it in items if it["id"] not in seen and it["time"] > NOW - timedelta(minutes=90)]
    if not fresh:
        return
    # tri rapide (peu coûteux) puis analyse complète des seules news importantes
    scores = {}
    for k in range(0, len(fresh), 40):
        batch = fresh[k:k + 40]
        r = core.claude_call(key, core.TRIAGE_PROMPT,
                             json.dumps([dict(id=i["id"], titre=i["title"]) for i in batch],
                                        ensure_ascii=False), max_tokens=1500)
        scores.update({o["id"]: int(o.get("importance", 1)) for o in core.parse_json_array(r["text"])
                       if isinstance(o, dict) and o.get("id")})
    top = [it for it in fresh if scores.get(it["id"], 0) >= MIN_IMP]
    if top:
        payload = [dict(id=i["id"], source=i["source"], titre=i["title"], resume=i["summary"]) for i in top]
        r = core.claude_call(key, core.NEWS_PROMPT, json.dumps(payload, ensure_ascii=False), max_tokens=3000)
        full = {o["id"]: o for o in core.parse_json_array(r["text"]) if isinstance(o, dict)}
        for it in top:
            a = full.get(it["id"], {})
            imp = int(a.get("importance", scores[it["id"]]))
            if imp < MIN_IMP:
                continue
            icon = {"haussier": "📈", "baissier": "📉", "neutre": "➖"}.get(a.get("impact"), "❓")
            send(cid, f"{'🔴' if imp == 5 else '🟠'} <b>{imp}/5</b> · {icon} {esc(a.get('impact', ''))} · "
                      f"{esc(it['source'])}\n<b>{esc(it['title'])}</b>\n\n{esc(a.get('resume', ''))}\n"
                      f"<i>{esc(a.get('analyse', ''))}</i>\n"
                      f"Actifs : {esc(', '.join(a.get('actifs', [])) or '—')}\n{esc(it['link'])}")
    state["news"] = list(seen | {it["id"] for it in fresh})


# --------------------------------------------------------------------------- 2-3. macro
def alert_macro(state, cid):
    events, _ = core.fetch_macro()
    events = [e for e in events if e["impact"] == "High" and e["country"] in ZONES]
    pre, done = set(state.get("pre", [])), set(state.get("macro", []))

    for e in events:                                     # rappel ~1 h avant
        mins = (e["time"] - NOW).total_seconds() / 60
        if 0 < mins <= 70 and e["id"] not in pre:
            local = e["time"].astimezone(PARIS)
            txt = (f"⏰ <b>Dans {int(mins)} min ({local:%H:%M})</b> · {esc(e['country'])}\n"
                   f"<b>{esc(e['title'])}</b>\nConsensus : <b>{esc(e['forecast'] or '—')}</b> · "
                   f"Précédent : {esc(e['previous'] or '—')}")
            spec = core.BLS_SPECS.get(e["title"]) if e["country"] == "USD" else None
            if spec:
                txt += (f"\n\n⬆️ Au-dessus : {esc(core.INTERPRET[spec[2]][1])}"
                        f"\n⬇️ En dessous : {esc(core.INTERPRET[spec[2]][-1])}")
            send(cid, txt)
            pre.add(e["id"])

    recent = [e for e in events if NOW - timedelta(hours=3) <= e["time"] <= NOW
              and e["id"] not in done and e["title"] in core.BLS_SPECS and e["country"] == "USD"]
    if recent:                                           # résultat officiel BLS
        bls = core.fetch_bls(ENV("BLS_API_KEY"), [e["title"] for e in recent])
        for e in recent:
            res = core.official_result(e, bls)
            if not res:
                continue                                 # pas encore en ligne : on réessaiera
            icon = {1: "⬆️", -1: "⬇️", 0: "➡️"}.get(res.get("direction"), "📊")
            send(cid, f"{icon} <b>{esc(e['title'])}</b> (US, {esc(res['periode'])})\n"
                      f"Publié : <b>{esc(res['actual'])}</b> · consensus {esc(res['consensus'])} "
                      f"({esc(res.get('ecart', ''))})\n→ <b>{esc(res['verdict'])}</b>\n\n"
                      f"{esc(res.get('lecture', ''))}\n<i>Source : BLS (officiel)</i>")
            done.add(e["id"])
    state["pre"], state["macro"] = list(pre), list(done)


# --------------------------------------------------------------------------- 4. résultats
def alert_earnings(state, cid):
    today = NOW.astimezone(PARIS).date()
    rows, _ = core.fetch_earnings(ENV("FINNHUB_API_KEY"), today - timedelta(days=2), today,
                                  list(core.LARGE_CAPS))
    sent = set(state.get("earn", []))
    for r in rows:
        if r["eps"] is None or r["id"] in sent:
            continue
        lines = []
        for label, a, e, f in (("BPA", r["eps"], r["eps_est"], lambda x: f"{x:.2f} $"),
                               ("CA", r["rev"], r["rev_est"], core.fmt_rev)):
            if a is None:
                continue
            sp = core.surprise_pct(a, e)
            icon = "✅" if sp and sp > 0.5 else "❌" if sp and sp < -0.5 else "➖"
            lines.append(f"{icon} {label} <b>{esc(f(a))}</b> vs {esc(f(e) if e is not None else '—')}"
                         + (f" ({sp:+.1f} %)" if sp is not None else ""))
        send(cid, f"🏢 <b>{esc(r['symbol'])}</b> · {esc(r['name'])} — résultats publiés\n" + "\n".join(lines)
                  + "\n<i>La réaction dépend aussi beaucoup des prévisions (guidance).</i>")
        sent.add(r["id"])
    state["earn"] = list(sent)


# --------------------------------------------------------------------------- main
def main():
    state = load_state()
    cid = chat_id(state)
    if not cid:
        print("Aucun chat Telegram : envoie /start à ton bot puis relance.")
        save_state(state)
        return
    first = not state.get("started")
    key = ENV("ANTHROPIC_API_KEY")
    errors = []
    for name, fn in (("news", lambda: alert_news(state, cid, key)),
                     ("macro", lambda: alert_macro(state, cid)),
                     ("résultats", lambda: alert_earnings(state, cid))):
        if first and name == "news":                     # 1er passage : pas d'avalanche
            items, _ = core.fetch_feeds(tuple(core.FEEDS))
            state["news"] = [i["id"] for i in items]
            continue
        try:
            fn()
        except Exception as ex:
            errors.append(f"{name} : {type(ex).__name__}: {ex}")
    if first:
        state["started"] = True
        send(cid, "✅ <b>Radar connecté.</b> Tu recevras ici les news majeures, les rappels avant les "
                  "annonces macro, les chiffres officiels et les résultats d'entreprises.")
    for e in errors:
        print("ERREUR", e)
    save_state(state)


if __name__ == "__main__":
    main()

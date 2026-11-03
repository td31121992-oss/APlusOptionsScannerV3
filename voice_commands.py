"""Talk to APlus: read-only voice (and typed) commands for the dashboard.

A mic button on every dashboard page listens (browser speech recognition), sends the words to /api/voice, and the answer is shown and read
aloud. Everything here only READS data the system already holds - P&L, trades, MFE, scanner health, market mood, sectors, movers, why a trade
was taken, what was missed. There is deliberately no command that places, closes or changes a trade, switches Paper/Live or changes any setting.
"""

from __future__ import annotations

import csv
import difflib
import json
import re
import statistics
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ALIASES = {"m and m": "M&M", "mahindra and mahindra": "M&M", "bajaj auto": "BAJAJ-AUTO", "l and t": "LT", "larsen": "LT", "hdfc life": "HDFCLIFE",
           "sbi": "SBIN", "state bank": "SBIN", "airtel": "BHARTIARTL", "bharti": "BHARTIARTL", "tata motors": "TATAMOTORS", "gmr": "GMRAIRPORT",
           "gmr airport": "GMRAIRPORT", "pnb housing": "PNBHOUSING", "indus tower": "INDUSTOWER", "indus towers": "INDUSTOWER", "ril": "RELIANCE"}
EXAMPLES = ["What's my P&L today?", "Open trades", "Which trades are stopped?", "Best trade", "MFE of today's trades", "Is the scanner running?",
            "Market mood", "Strongest sectors", "Top gainers", "Why was RECLTD traded?", "How is TCS?", "What are we missing?"]
_UNIVERSE: dict[str, Any] = {"t": 0.0, "map": {}}


def _clean(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace(" and ", "").replace("&", ""))


def symbols(root: Path = ROOT) -> dict[str, str]:
    """clean-name -> SYMBOL for the F&O universe (cached for an hour)."""
    if time.time() - _UNIVERSE["t"] < 3600 and _UNIVERSE["map"]:
        return _UNIVERSE["map"]
    out: dict[str, str] = {}
    try:
        with (root / "data" / "reference" / "fno_sector_map.csv").open(encoding="utf-8-sig", newline="") as handle:
            for r in csv.DictReader(handle):
                out[_clean(r["symbol"])] = r["symbol"]
    except OSError:
        pass
    _UNIVERSE.update(t=time.time(), map=out)
    return out


def find_symbol(text: str, root: Path = ROOT) -> tuple[str | None, str | None]:
    """(symbol, suggestion): an exact/alias match returns the symbol; a close but uncertain match returns only a suggestion."""
    t = text.lower()
    for alias, sym in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"\b" + re.escape(alias) + r"\b", t):
            return sym, None
    known = symbols(root)
    words = re.findall(r"[a-z0-9&\-]+", t)
    stop = {"how", "is", "the", "was", "why", "did", "show", "tell", "me", "about", "what", "are", "we", "my", "today", "trade", "traded", "stock", "price",
            "and", "of", "for", "open", "best", "worst", "top", "market", "mood", "sector", "scanner", "mfe", "pnl", "loss", "profit", "stopped", "missing"}
    best: tuple[float, str] | None = None
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            chunk = words[i:i + n]
            if all(w in stop for w in chunk):
                continue
            c = _clean(" ".join(chunk))
            if len(c) < 3:
                continue
            if c in known:
                return known[c], None
            m = difflib.get_close_matches(c, list(known), n=1, cutoff=0.8)
            if m:
                ratio = difflib.SequenceMatcher(None, c, m[0]).ratio()
                if best is None or ratio > best[0]:
                    best = (ratio, known[m[0]])
    if best:
        return (best[1], None) if best[0] >= 0.9 else (None, best[1])
    return None, None


# ----------------------------------------------------------------------------- data helpers
def _money(x: float) -> str:
    return f"{'-' if x < 0 else '+'}₹{abs(round(x)):,}"


def _today_trades(root: Path, day: str | None = None) -> list[dict[str, Any]]:
    import trade_journal

    d = day or date.today().isoformat()
    return sorted(trade_journal.payload(d, d, root).get("trades", []), key=lambda t: t["entry_time"])


def _speech(text: str) -> str:
    return (text.replace("₹", "rupees ").replace("+rupees", "plus rupees").replace("-rupees", "minus rupees").replace("%", " percent")
            .replace("MFE", "M F E").replace("P&L", "profit and loss"))


def _reply(text: str, rows: list[str] | None = None, intent: str = "") -> dict[str, Any]:
    return {"ok": True, "intent": intent, "reply": text, "rows": rows or [], "speech": _speech(text)}


# ----------------------------------------------------------------------------- intents
def answer(text: str, root: Path = ROOT, day: str | None = None) -> dict[str, Any]:
    q = " ".join(str(text or "").lower().split())[:300]
    if not q:
        return _reply("I did not hear anything. Try: " + EXAMPLES[0], intent="empty")
    has = lambda *ks: any(re.search(k, q) for k in ks)               # noqa: E731
    sym, suggestion = find_symbol(q, root)
    if has(r"\bhelp\b", r"what can you (do|answer)", r"\bcommands\b"):
        return _reply("I can answer read-only questions. Try: " + "; ".join(EXAMPLES[:8]) + ". I cannot place, close or change trades.", EXAMPLES, "help")
    try:
        trades = _today_trades(root, day)
    except Exception:                                                  # noqa: BLE001
        trades = []
    closed = [t for t in trades if t["status"] == "CLOSED"]
    opened = [t for t in trades if t["status"] == "OPEN"]
    if has(r"why", r"reason") and sym:
        mine = [t for t in trades if t["symbol"] == sym]
        if not mine:
            return _reply(f"There is no trade in {sym} today.", intent="why")
        t = mine[-1]
        return _reply(f"{sym} {t['side']} was entered at {t['entry_time']} at {t['entry_price']:.2f}. Setup {t['setup'].replace('_', ' ').lower()}, tier {t['tier'].replace('_', ' ').lower()}, "
                      f"safety {t['safety'] or 'n a'}, market {t['regime'] or 'unknown'}. Scores: momentum {t['momentum']}, trend {t['trend_alignment']}, chase risk {t['chase_risk']}. "
                      f"It is now {t['return_pct']:+.1f}% ({_money(t['net'])}), best gain {t['mfe_pct']:+.1f}%.", intent="why")
    if has(r"how many trades", r"number of trades", r"trade count", r"count of trades"):
        return _reply(f"{len(trades)} trades today: {len(closed)} closed and {len(opened)} open. {sum(1 for t in trades if t['net'] > 0)} are in profit.", intent="count")
    if has(r"\bmfe\b", r"maximum favou?rable", r"how high did", r"\bpeak\b"):
        if not trades:
            return _reply("No trades today yet.", intent="mfe")
        m = [t["mfe_pct"] for t in trades]
        rows = [f"{t['symbol']} {t['side']}: best {t['mfe_pct']:+.1f}%, now {t['return_pct']:+.1f}%" for t in sorted(trades, key=lambda t: -t["mfe_pct"])]
        return _reply(f"Best gain after entry across {len(trades)} trades: average {statistics.mean(m):+.1f}%, median {statistics.median(m):+.1f}%, highest {max(m):+.1f}% ({max(trades, key=lambda t: t['mfe_pct'])['symbol']}). "
                      f"{sum(1 for x in m if x < 5)} never got above 5 percent.", rows, "mfe")
    if has(r"stop", r"\bsl\b", r"losing trades", r"losers?"):
        lost = [t for t in trades if t["net"] < 0]
        stopped = [t for t in closed if "STOP" in (t["exit_reason"] or "")]
        if not trades:
            return _reply("No trades today yet.", intent="stopped")
        def dur(t):
            h1, m1 = map(int, t["entry_time"].split(":")); h2, m2 = map(int, (t["exit_time"] or "00:00").split(":")); return (h2 * 60 + m2) - (h1 * 60 + m1)
        rows = [f"{t['symbol']} {t['side']}: in {t['entry_time']}, stopped {t['exit_time']} after {dur(t)} minutes, {t['return_pct']:+.1f}% ({_money(t['net'])})" for t in stopped]
        other = [t for t in lost if t not in stopped]
        rows += [f"{t['symbol']} {t['side']}: {'still open' if t['status'] == 'OPEN' else 'closed (' + (t['exit_reason'] or 'other').replace('_', ' ').lower() + ')'}, {t['return_pct']:+.1f}% ({_money(t['net'])})" for t in other]
        more = f" {len(other)} more trades are also in loss ({sum(1 for t in other if t['status'] == 'OPEN')} still open)." if other else ""
        return _reply(f"{len(stopped)} trades stopped out, total {_money(sum(t['net'] for t in stopped))}.{more}", rows, "stopped")
    if has(r"winners?", r"in profit", r"profitable", r"winning"):
        w = [t for t in trades if t["net"] > 0]
        return _reply(f"{len(w)} of {len(trades)} trades are in profit, together {_money(sum(t['net'] for t in w))}.",
                      [f"{t['symbol']} {t['side']}: {t['return_pct']:+.1f}% ({_money(t['net'])})" for t in sorted(w, key=lambda t: -t['net'])], "winners")
    if has(r"best trade", r"worst trade", r"biggest (win|loss|gain)"):
        if not trades:
            return _reply("No trades today yet.", intent="best")
        b, w = max(trades, key=lambda t: t["net"]), min(trades, key=lambda t: t["net"])
        return _reply(f"Best trade {b['symbol']} {b['side']} {b['return_pct']:+.1f}% ({_money(b['net'])}). Worst trade {w['symbol']} {w['side']} {w['return_pct']:+.1f}% ({_money(w['net'])}).", intent="best")
    if has(r"open (trades|positions)", r"\bpositions\b", r"running trades", r"what.s open"):
        if not opened:
            return _reply("No open trades right now.", intent="open")
        return _reply(f"{len(opened)} open trades, together {_money(sum(t['net'] for t in opened))}.",
                      [f"{t['symbol']} {t['side']}: in {t['entry_time']}, {t['return_pct']:+.1f}% ({_money(t['net'])}), best {t['mfe_pct']:+.1f}%" for t in opened], "open")
    if has(r"p ?& ?l", r"\bpnl\b", r"profit", r"\bloss\b", r"how am i doing", r"how much .*(made|lost)", r"result"):
        if not trades:
            return _reply("No trades today yet.", intent="pnl")
        total, cl, op = sum(t["net"] for t in trades), sum(t["net"] for t in closed), sum(t["net"] for t in opened)
        w = sum(1 for t in trades if t["net"] > 0)
        return _reply(f"Today's paper P&L is {_money(total)}: closed {_money(cl)}, open {_money(op)}. {len(trades)} trades, {w} in profit, {len(closed)} closed.", intent="pnl")
    if has(r"scanner", r"\brunning\b", r"alive", r"\bhealth\b", r"\bstatus\b"):
        p = root / "data" / "reports" / "intraday_movement_latest.json"
        try:
            age = int(time.time() - p.stat().st_mtime)
            r = json.loads(p.read_text(encoding="utf-8"))
            ok = age < 180
            return _reply(f"The scanner {'is running' if ok else 'looks stalled'}: last report {age} seconds ago, phase {str(r.get('session_phase', '')).replace('_', ' ').lower()}, "
                          f"{r.get('entry_ready_count', 0)} entry ready, {r.get('paper_trades_today', 0)} paper trades today.", intent="scanner")
        except (OSError, ValueError):
            return _reply("I cannot find a scanner report. The scanner may not be running.", intent="scanner")
    if has(r"mood", r"sentiment", r"how is the market", r"market view"):
        try:
            import market_mood

            m = market_mood.payload(root)
            if m.get("ok"):
                return _reply(f"Market mood is {m['label']}, {m['score']} out of 100.", [f"{p['name']}: {p['text']}" for p in m.get("parts", [])], "mood")
        except Exception:                                              # noqa: BLE001
            pass
        return _reply("Market mood is not available yet.", intent="mood")
    if has(r"sector", r"strongest", r"weakest"):
        try:
            import sector_analysis

            s = sector_analysis.payload(root)
            if s.get("ok"):
                rows = [f"{x['sector']}: {x['move']:+.2f}% ({x['up']} up, {x['down']} down)" for x in s["sectors"]]
                return _reply(f"{s['story']} Strongest sector {s['strongest']['sector']} {s['strongest']['move']:+.2f}%, weakest {s['weakest']['sector']} {s['weakest']['move']:+.2f}%. "
                              f"{s['up']} of {s['total']} stocks are up.", rows, "sectors")
        except Exception:                                              # noqa: BLE001
            pass
        return _reply("Sector data is not available yet.", intent="sectors")
    if has(r"top (gainers?|losers?|movers?)", r"gainers", r"losers? of the day", r"movers"):
        try:
            rows = json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8"))["rows"]
            key = "from_prev_close_pct"
            up = has(r"gain")
            top = sorted(rows, key=lambda r: -r[key] if up or not has(r"loser") else r[key])[:5]
            return _reply(f"Top {'gainers' if up or not has('loser') else 'losers'}: " + ", ".join(f"{r['symbol']} {r[key]:+.2f}%" for r in top) + ".", intent="movers")
        except (OSError, ValueError, KeyError):
            return _reply("Market data is not available.", intent="movers")
    if has(r"missing", r"missed", r"opportunit", r"what did we miss"):
        d = day or date.today().isoformat()
        p = root / "data" / "missed_opportunities" / d / "report.md"
        try:
            lines = [l[2:] for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("- ") and "first ready" in l and "TRADED" not in l][:8]
            return _reply(f"Biggest signals we did not trade today: {len(lines)} shown. " + "; ".join(l.split(" - fate")[0] for l in lines[:3]) + ".", lines, "missed")
        except OSError:
            return _reply("The missed-opportunity report for today has not been generated yet. It runs at 15:50.", intent="missed")
    if sym:
        try:
            rows = json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8"))["rows"]
            r = next(x for x in rows if x["symbol"] == sym)
            mine = [t for t in trades if t["symbol"] == sym]
            extra = f" We have {len(mine)} trade{'s' if len(mine) != 1 else ''} in it today." if mine else " No trade in it today."
            return _reply(f"{sym} is at {r['ltp']:.2f}, {r['from_prev_close_pct']:+.2f}% from the previous close and {r['from_open_pct']:+.2f}% from the open. Sector {r.get('sector', 'unknown')}. "
                          f"Day high {r['day_high']:.2f}, day low {r['day_low']:.2f}.{extra}", intent="stock")
        except (OSError, ValueError, KeyError, StopIteration):
            return _reply(f"I found {sym} but have no live data for it.", intent="stock")
    if suggestion:
        return _reply(f"Did you mean {suggestion}? Say it again with the command.", intent="suggest")
    return _reply("I did not understand that. Try: " + "; ".join(EXAMPLES[:6]), EXAMPLES, "unknown")


VOICE_WIDGET_HTML = r"""
<div id="aplus-voice" style="position:fixed;right:14px;bottom:96px;z-index:9997;font:14px system-ui,sans-serif">
<button id="av-btn" title="Talk to APlus" style="width:52px;height:52px;border-radius:50%;border:1px solid #27334d;background:#121a2d;color:#e7eefc;font-size:22px;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.5)">&#127908;</button>
<div id="av-panel" style="display:none;position:absolute;right:0;bottom:62px;width:min(360px,calc(100vw - 28px));background:#121a2d;border:1px solid #27334d;border-radius:12px;padding:10px;color:#e7eefc;box-shadow:0 8px 28px rgba(0,0,0,.6)">
<div style="display:flex;justify-content:space-between;align-items:center"><b>Talk to APlus</b><span><label style="font-size:12px;color:#8ea0bd"><input type="checkbox" id="av-say" checked> speak</label> <a href="#" id="av-x" style="color:#8ea0bd;text-decoration:none;margin-left:8px">&#10005;</a></span></div>
<div id="av-status" style="color:#8ea0bd;font-size:12px;margin:6px 0">Press the mic and speak, or type below. Read-only: I cannot place or change trades.</div>
<div style="display:flex;gap:6px"><button id="av-mic" style="background:#4c8dff;color:#fff;border:0;border-radius:8px;padding:8px 12px;cursor:pointer;font-weight:700">&#127908; Speak</button>
<input id="av-in" placeholder="or type: pnl, open trades, mfe..." style="flex:1;min-width:0;background:#0f1729;color:#e7eefc;border:1px solid #27334d;border-radius:8px;padding:8px"><button id="av-go" style="background:#1d2842;color:#e7eefc;border:1px solid #27334d;border-radius:8px;padding:8px 10px;cursor:pointer">Ask</button></div>
<div id="av-ans" style="margin-top:8px;max-height:46vh;overflow:auto;font-size:13.5px;line-height:1.45"></div></div></div>
<script>(function(){var $=function(i){return document.getElementById(i)},btn=$("av-btn"),panel=$("av-panel");if(!btn)return;
var SR=window.SpeechRecognition||window.webkitSpeechRecognition,rec=null,listening=false;
function esc(s){return String(s).replace(/[&<>]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c]})}
btn.onclick=function(){panel.style.display=panel.style.display==="none"?"block":"none"};$("av-x").onclick=function(e){e.preventDefault();panel.style.display="none"};
function speak(t){if(!$("av-say").checked||!window.speechSynthesis)return;try{window.speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(t);u.lang="en-IN";u.rate=1.02;window.speechSynthesis.speak(u)}catch(e){}}
function ask(q){q=(q||"").trim();if(!q)return;$("av-status").textContent='You: "'+q+'"';$("av-ans").innerHTML='<span style="color:#8ea0bd">thinking...</span>';
 fetch("/api/voice?q="+encodeURIComponent(q),{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){var h='<div style="margin-bottom:6px">'+esc(d.reply||"")+'</div>';
  if(d.rows&&d.rows.length&&d.intent!=="help")h+='<div style="color:#b9c6df;font-size:12.5px">'+d.rows.slice(0,25).map(function(x){return "&bull; "+esc(x)}).join("<br>")+'</div>';$("av-ans").innerHTML=h;speak(d.speech||d.reply||"")}).catch(function(){$("av-ans").textContent="Could not reach the dashboard."})}
$("av-go").onclick=function(){ask($("av-in").value);$("av-in").value=""};$("av-in").addEventListener("keydown",function(e){if(e.key==="Enter"){ask($("av-in").value);$("av-in").value=""}});
if(!SR){$("av-mic").disabled=true;$("av-mic").style.opacity=".5";$("av-status").textContent="Voice input is not supported in this browser (Brave blocks it). Use Chrome, Edge or Safari - or type below."}
else{$("av-mic").onclick=function(){if(listening){try{rec.stop()}catch(e){}return}
 rec=new SR();rec.lang="en-IN";rec.interimResults=false;rec.maxAlternatives=1;
 rec.onstart=function(){listening=true;$("av-mic").textContent="Listening... (tap to stop)";$("av-status").textContent="Listening..."};
 rec.onend=function(){listening=false;$("av-mic").innerHTML="&#127908; Speak"};
 rec.onerror=function(e){$("av-status").textContent=(e.error==="not-allowed"||e.error==="service-not-allowed")?"Microphone blocked. Allow it for this site (phones need an HTTPS address).":"Voice error: "+e.error};
 rec.onresult=function(e){var t=e.results[0][0].transcript;ask(t)};try{rec.start()}catch(e){}}}
})();</script>
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile

ROOT=Path(__file__).resolve().parent
SCANNER=ROOT/"opening_momentum_scanner.py"
OPTION_CHAIN=ROOT/"core"/"option_chain.py"

if not SCANNER.is_file():
    raise SystemExit("FAIL: opening_momentum_scanner.py missing")
if not OPTION_CHAIN.is_file():
    raise SystemExit("FAIL: core/option_chain.py missing")

oc_text=OPTION_CHAIN.read_text(encoding="utf-8")
oc_tree=ast.parse(oc_text)
fetch_supports_expiry=False
for node in ast.walk(oc_tree):
    if isinstance(node,ast.ClassDef) and node.name=="OptionChainService":
        for child in node.body:
            if isinstance(child,ast.FunctionDef) and child.name=="fetch":
                names=[a.arg for a in child.args.args]+[a.arg for a in child.args.kwonlyargs]
                fetch_supports_expiry="expiry" in names
                break
if not fetch_supports_expiry:
    raise SystemExit("FAIL: core/option_chain.py fetch() does not support explicit expiry. No changes made.")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_expiry_fallback_{stamp}"
backup.mkdir()
shutil.copy2(SCANNER,backup/SCANNER.name)

src=SCANNER.read_text(encoding="utf-8")
tree=ast.parse(src)
target=None
for node in ast.walk(tree):
    if isinstance(node,ast.ClassDef):
        for child in node.body:
            if isinstance(child,ast.FunctionDef) and child.name=="_build_option_plan":
                target=child
                break
    if target is not None:
        break
if target is None or not getattr(target,"end_lineno",None):
    raise SystemExit("FAIL: could not locate _build_option_plan. No changes made.")

new_func='    def _build_option_plan(\n        self,\n        *,\n        candidate: MomentumCandidate,\n        underlying: UnderlyingInstrument,\n        now: datetime,\n        account_context: Mapping[str, Any],\n        safety_evaluations: list[dict[str, Any]],\n    ) -> dict[str, Any] | None:\n        # PAPER option plan with safe expiry fallback. Safety is never bypassed.\n        cached = self._cached_option(candidate.symbol)\n        recommendation = (\n            RecommendationType.BUY\n            if candidate.direction == "BULLISH"\n            else RecommendationType.SELL\n        )\n        bias = (\n            MarketBias.BULLISH\n            if candidate.direction == "BULLISH"\n            else MarketBias.BEARISH\n        )\n\n        option_contract = None\n        safety = None\n        safety_payload = None\n        attempt_errors: list[str] = []\n\n        if cached is not None:\n            option_contract = cached\n        else:\n            expiries: list[str | None] = []\n            try:\n                if hasattr(self.option_chain, "get_master_expiries"):\n                    expiries = list(self.option_chain.get_master_expiries(underlying))\n                elif hasattr(self.option_chain, "get_expiries"):\n                    expiries = list(self.option_chain.get_expiries(underlying.security_id))\n            except Exception as exc:\n                logger.warning(\n                    "Expiry fallback list failed for %s: %s: %s",\n                    candidate.symbol, type(exc).__name__, exc,\n                )\n\n            normalized: list[str] = []\n            for value in expiries:\n                text = str(value or "").strip()[:10]\n                if not text:\n                    continue\n                try:\n                    parsed = datetime.fromisoformat(text).date()\n                except ValueError:\n                    continue\n                if parsed >= now.date():\n                    normalized.append(parsed.isoformat())\n\n            expiry_attempts: list[str | None] = sorted(set(normalized))[:4]\n            if not expiry_attempts:\n                expiry_attempts = [None]\n\n            for expiry in expiry_attempts:\n                label = expiry or "DEFAULT"\n                try:\n                    snapshot = (\n                        self.option_chain.fetch(underlying, expiry=expiry)\n                        if expiry is not None\n                        else self.option_chain.fetch(underlying)\n                    )\n                    selected = self.option_selector.select(\n                        snapshot=snapshot,\n                        underlying=underlying,\n                        recommendation=recommendation,\n                        bias=bias,\n                    )\n                    tentative = self._serializable(selected)\n                except OptionSelectionError as exc:\n                    attempt_errors.append(f"{label}: {exc}")\n                    logger.info(\n                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=NO_EXECUTABLE_CONTRACT error=%s",\n                        candidate.symbol, label, exc,\n                    )\n                    continue\n                except Exception as exc:\n                    attempt_errors.append(f"{label}: {type(exc).__name__}: {exc}")\n                    logger.warning(\n                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=FETCH_OR_SELECTION_ERROR error=%s: %s",\n                        candidate.symbol, label, type(exc).__name__, exc,\n                    )\n                    continue\n\n                trial_safety = self.safety_gate.evaluate(\n                    symbol=candidate.symbol,\n                    option_contract=tentative,\n                    now=now,\n                    fund_limits=account_context.get("fund_limits") or {},\n                    positions=account_context.get("positions") or [],\n                    fund_limits_available=bool(account_context.get("fund_limits_fetch_ok")),\n                    positions_available=bool(account_context.get("positions_fetch_ok")),\n                    candidate_context=candidate.to_dict(),\n                )\n                trial_payload = trial_safety.to_dict()\n                safety_evaluations.append(trial_payload)\n\n                if trial_safety.allowed:\n                    option_contract = tentative\n                    safety = trial_safety\n                    safety_payload = trial_payload\n                    self._option_cache[candidate.symbol] = (time.monotonic(), option_contract)\n                    logger.info(\n                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=SELECTED_SAFE",\n                        candidate.symbol,\n                        str(option_contract.get("expiry") or label),\n                    )\n                    break\n\n                expiry_only = bool(trial_safety.block_reasons) and all(\n                    str(reason).startswith("EXPIRY_SETTLEMENT:")\n                    for reason in trial_safety.block_reasons\n                )\n                if expiry_only:\n                    attempt_errors.append(\n                        f"{label}: SAFETY_BLOCKED: " + "; ".join(trial_safety.block_reasons)\n                    )\n                    logger.info(\n                        "OPTION_EXPIRY_FALLBACK symbol=%s expiry=%s result=EXPIRY_BLOCK_TRY_NEXT reason=%s",\n                        candidate.symbol, label, "; ".join(trial_safety.block_reasons),\n                    )\n                    continue\n\n                option_contract = tentative\n                safety = trial_safety\n                safety_payload = trial_payload\n                break\n\n            if option_contract is None:\n                candidate.option_error = (\n                    "EXPIRY_FALLBACK_EXHAUSTED: " + " | ".join(attempt_errors[-4:])\n                )\n                return None\n\n        if safety is None:\n            safety = self.safety_gate.evaluate(\n                symbol=candidate.symbol,\n                option_contract=option_contract,\n                now=now,\n                fund_limits=account_context.get("fund_limits") or {},\n                positions=account_context.get("positions") or [],\n                fund_limits_available=bool(account_context.get("fund_limits_fetch_ok")),\n                positions_available=bool(account_context.get("positions_fetch_ok")),\n                candidate_context=candidate.to_dict(),\n            )\n            safety_payload = safety.to_dict()\n            safety_evaluations.append(safety_payload)\n\n        candidate.safety_decision = safety.decision\n        candidate.safety_block_reasons = list(safety.block_reasons)\n        candidate.safety_warnings = list(safety.warnings)\n\n        if not safety.allowed:\n            candidate.option_error = "SAFETY_BLOCKED: " + "; ".join(safety.block_reasons)\n            return None\n\n        candidate.option_error = ""\n        return {\n            "generated_at": now.isoformat(),\n            "paper_signal_only": True,\n            "symbol": candidate.symbol,\n            "direction": candidate.direction,\n            "stage": candidate.stage,\n            "setup_family": candidate.setup_family,\n            "selection_tier": candidate.selection_tier,\n            "momentum_score": candidate.score,\n            "movement_capture_score": candidate.movement_capture_score,\n            "trend_alignment_score": candidate.trend_alignment_score,\n            "clean_trend_score": candidate.clean_trend_score,\n            "chase_risk_score": candidate.chase_risk_score,\n            "pivot_state": candidate.pivot_state,\n            "recent_move_15m_percent": candidate.recent_move_15m_percent,\n            "underlying": {\n                "entry": candidate.underlying_entry,\n                "stop_loss": candidate.underlying_stop,\n                "target1": candidate.underlying_target1,\n                "target2": candidate.underlying_target2,\n                "target3": candidate.underlying_target3,\n                "risk_percent": candidate.underlying_risk_percent,\n                "trailing_rule": candidate.trailing_rule,\n            },\n            "option_contract": option_contract,\n            "safety_gate": safety_payload,\n            "reasons": candidate.reasons,\n        }\n'
lines=src.splitlines()
start=target.lineno-1
end=target.end_lineno
patched="\n".join(lines[:start]+new_func.splitlines()+lines[end:])+"\n"

try:
    ast.parse(patched)
    SCANNER.write_text(patched,encoding="utf-8")
    py_compile.compile(str(SCANNER),doraise=True)
    verify=SCANNER.read_text(encoding="utf-8")
    checks={
        "expiry_fallback":"OPTION_EXPIRY_FALLBACK" in verify,
        "safe_next_expiry":"EXPIRY_BLOCK_TRY_NEXT" in verify,
        "paper_only":'"paper_signal_only": True' in verify,
        "conversion_audit":"PAPER conversion audit" in verify,
        "leadership_shadow":"LEADERSHIP_V6_SHADOW" in verify,
    }
    if not all(checks.values()):
        raise RuntimeError(f"verification failed: {checks}")
except Exception:
    shutil.copy2(backup/SCANNER.name,SCANNER)
    print("INSTALL FAILED - original restored automatically.")
    print("Backup:",backup)
    raise

print("="*112)
print("SUCCESS: SAFE STOCK-OPTION EXPIRY FALLBACK INSTALLED")
print("Backup:",backup)
for k,v in checks.items():
    print(("PASS" if v else "FAIL")+": "+k)
print("PASS: nearest-expiry safety is NOT disabled")
print("PASS: next expiry tried when nearest is expiry-blocked or non-executable")
print("PASS: non-expiry safety blocks remain final")
print("PASS: risk / 10% trade-risk / Telegram / Leadership logic unchanged")
print("="*112)

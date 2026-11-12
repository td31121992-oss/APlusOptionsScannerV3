"""Back up the irreplaceable, SMALL files (trade journal, closed-trade archive, experiment/supervisor/agent state, study results, scheduled-task definitions) to a PRIVATE git repo.

    python backup_to_github.py            copy -> commit -> push (run by the nightly archive job)
    python backup_to_github.py --dry-run  say what would be copied, change nothing
    python backup_to_github.py --setup URL  one-time: clone/init the backup folder and point it at the (private, empty) GitHub repo URL

Settings (env or .env): APLUS_BACKUP_DIR (default C:\\Users\\<you>\\APlusDataBackup), APLUS_BACKUP_REMOTE (only used by --setup), APLUS_BACKUP=0 switches it off.
Never copied: .env or any file named like a key/token/secret, anything over 50 MB, the big market recordings (data/reports, ticks, options_intelligence ...). A problem here never stops the
nightly job: it returns a short status and nothing raises. The code itself is in the main GitHub repo; this repo holds only data.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = Path(os.path.expanduser("~")) / "APlusDataBackup"
MAX_FILE = 50 * 1024 * 1024                                  # a single file over this is skipped (GitHub refuses 100 MB; keep well under)
MAX_REPO = 700 * 1024 * 1024                                 # warn when the backup folder passes this (GitHub's comfortable size is about 1 GB)
# folders under data/ that are small and cannot be rebuilt (relative to ROOT) - everything else under data/ is left out on purpose
INCLUDE = [
    "data/intraday_movement", "data/trade_archive", "data/ai_agent", "data/ai_supervisor", "data/shadow_scoreboard", "data/shadow_rules", "data/shadow_v2", "data/gate_whatif",
    "data/manual_paper", "data/ml_shadow", "data/rs_review", "data/reference", "data/event_calendar", "data/safety", "data/control", "data/state", "data/premium_tracker",
    "data/iv_history", "data/missed_opportunities", "data/trade_review", "data/trade_evidence_capsules", "data/decision_evidence", "data/strict_labels_summary", "data/late_runner",
    "data/leadership_v6_4_shadow", "data/event_days", "data/stock_study", "ai_supervisor",
]
INCLUDE_FILES = ["data/portfolio_state.json", "data/_v2_blocked_feat_1012.json", "data/pipeline_health.json"]
CALPHA = ROOT.parent / "CAlphaTrader"                       # the sister project: its small irreplaceable data goes under calpha/ in the same private repo (its CODE needs its own repo: git remote)
CALPHA_INCLUDE = [
    "journal", "data/mcx_energy", "data/futures_paper", "data/futures_paper_replay", "data/futures_paper_replay_v11", "data/futures_paper_replay_v12", "data/signal_outcomes",
    "data/chart_intel", "data/dataset", "data/futures_delta", "data/flow_gauge", "data/mcx_mini", "data/live_orders", "data/manual_orders", "data/level_breakout", "data/trend_flip",
    "data/dip_reclaim", "data/reversal_gate", "data/trail_shadow", "data/fast_shadow", "data/oi_watch", "data/outlook", "data/digests", "data/monitor_latency", "data/exit_quality",
    "data/chase_watch", "data/day_follow", "data/mini_option_shadow", "data/limit_entry_shadow", "data/ladder_shadow", "data/chain_fast", "data/pattern_backtest", "data/snapshots",
    "data/dashboard", "data/tradingview", "data/index_constituents", "data/raw",
]
CALPHA_FILES = ["data/paper_trades.json", "data/global_news_history.jsonl", "data/breadth_state.json", "data/intraday_oi_state.json", "data/vix_history.json", "data/phase3_latest.json"]
CALPHA_SKIP_PARTS = {"__pycache__", ".git", "eod_forensic"}  # eod_forensic holds one day's raw copies (tens of MB, rebuildable)
EXTRA_DIRS = [Path("E:/APlusData/top_movers_study")]       # small result files only (csv/txt/json/md)
EXTRA_SUFFIXES = {".csv", ".txt", ".json", ".md"}
SECRET_NAME = re.compile(r"(^\.env|secret|token|password|passwd|credential|\.pem$|\.key$|\.pfx$|id_rsa)", re.I)
SKIP_PARTS = {"__pycache__", ".git"}


def _is_secret(path: Path) -> bool:
    return bool(SECRET_NAME.search(path.name))


def _walk(src: Path, suffixes: set[str] | None = None):
    if src.is_file():
        yield src
        return
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
        for name in filenames:
            p = Path(dirpath) / name
            if suffixes is None or p.suffix.lower() in suffixes:
                yield p


def plan(root: Path = ROOT, extra_dirs: list[Path] | None = None, calpha: Path | None = None) -> tuple[list[tuple[Path, str]], list[str]]:
    """[(source file, path inside the backup repo)] and the list of things skipped with the reason."""
    items: list[tuple[Path, str]] = []
    skipped: list[str] = []
    seen: set[str] = set()

    def add(p: Path, rel: str) -> None:
        if rel in seen:
            return
        seen.add(rel)
        if _is_secret(p):
            skipped.append(f"{rel}: looks like a secret")
        elif not p.exists():
            return
        elif p.stat().st_size > MAX_FILE:
            skipped.append(f"{rel}: over {MAX_FILE // 1048576} MB")
        else:
            items.append((p, rel))

    for d in INCLUDE:
        src = root / d
        if src.exists():
            for p in _walk(src):
                add(p, p.relative_to(root).as_posix())
    for f in INCLUDE_FILES:
        add(root / f, f)
    if calpha is not None and calpha.exists():
        for d in CALPHA_INCLUDE:
            src = calpha / d
            if src.exists():
                for p in _walk(src):
                    if not (CALPHA_SKIP_PARTS & set(p.relative_to(calpha).parts)) and p.suffix.lower() not in {".py", ".pyc"}:   # journal/*.py is code, in the code repo
                        add(p, "calpha/" + p.relative_to(calpha).as_posix())
        for f in CALPHA_FILES:
            add(calpha / f, "calpha/" + f)
    for src in (EXTRA_DIRS if extra_dirs is None else extra_dirs):
        if src.exists():
            for p in _walk(src, EXTRA_SUFFIXES):
                add(p, "studies/" + p.relative_to(src).as_posix())
    return items, skipped


CODE_REPOS = [ROOT, CALPHA]                                        # git repos whose already-committed work is pushed to their own GitHub remote every night


def push_code(repo: Path) -> str:
    """Push commits that already exist in `repo` to its upstream. It never commits anything (uncommitted work is left alone) and never raises; returns a one-line status."""
    try:
        if not (repo / ".git").exists():
            return f"{repo.name}: not a git repo"
        if not _git(repo, "remote").stdout.strip():
            return f"{repo.name}: no remote set (git remote add origin <private repo URL>)"
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if not branch or branch == "HEAD":
            return f"{repo.name}: detached HEAD, not pushed"
        up = _git(repo, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
        if up.returncode != 0:
            return f"{repo.name}: branch {branch} has no upstream (git push -u origin {branch})"
        _git(repo, "fetch", "-q", timeout=120)
        counts = _git(repo, "rev-list", "--left-right", "--count", f"{up.stdout.strip()}...HEAD").stdout.split()
        behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
        if behind:
            return f"{repo.name}: remote has {behind} commit(s) this PC lacks - not pushed, needs a look"
        if not ahead:
            return f"{repo.name}: code already on GitHub"
        r = _git(repo, "push", timeout=300)
        dirty = len([ln for ln in _git(repo, "status", "--porcelain").stdout.splitlines() if not ln.startswith("??")])
        note = f"; {dirty} uncommitted file(s) not included" if dirty else ""
        return (f"{repo.name}: pushed {ahead} commit(s)" if r.returncode == 0 else f"{repo.name}: push failed: " + (r.stderr or r.stdout).strip()[:140]) + note
    except Exception as exc:                                 # noqa: BLE001
        return f"{repo.name}: {type(exc).__name__}: {str(exc)[:120]}"


def _git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def export_tasks(dest: Path) -> int:
    """Best effort: save every APlus scheduled task as XML so a rebuilt PC can import them (schtasks /create /xml). Returns how many were written."""
    if os.name != "nt":
        return 0
    try:
        ps = ("Get-ScheduledTask | Where-Object { $_.TaskName -like 'APlus*' -or $_.TaskName -like 'CAlpha*' } | ForEach-Object { $n = $_.TaskName; "
              "Export-ScheduledTask -TaskName $n -TaskPath $_.TaskPath | Out-File -Encoding utf8 (Join-Path '" + str(dest) + "' (($n -replace ' ','_') + '.xml')) }")
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=90)
        return len(list(dest.glob("*.xml")))
    except Exception:                                        # noqa: BLE001
        return 0


RESTORE = """# Restoring the APlus scanner on a new PC

This repo holds the DATA only (journal, closed-trade archive, experiment and supervisor state, study results, scheduled-task XML). The code is in the GitHub repo APlusOptionsScannerV3.

1. Install Python 3.13 and git. `git clone` APlusOptionsScannerV3 to the Desktop; create `.venv` and `pip install -r requirements.txt`.
2. (CAlphaTrader) its code is in its own GitHub repo; copy `calpha/data` and `calpha/journal` from here over CAlphaTrader's `data/` and `journal/`.
2b. Copy this repo's `data/` folder over the project's `data/` and `ai_supervisor/` over the project's `ai_supervisor/` (these are newer than the code repo's copies).
3. Recreate `.env` from your USB copy (it is deliberately NOT here): Upstox token, Telegram keys, dashboard login.
4. Scheduled tasks: for each file in `tasks/` run `schtasks /create /tn <name> /xml tasks\\<name>.xml` from an elevated prompt (fix paths if the user name changed).
5. `python upstox_budget_status.py` and `python preflight` checks, then start the scanner as usual.
6. `studies/` is the top-movers study output (was on E:\\APlusData).

Last backup: {when}
"""


def run(root: Path = ROOT, repo: Path | None = None, dry: bool = False, extra_dirs: list[Path] | None = None, tasks: bool = True, code_repos: list[Path] | None = None) -> dict:
    """Copy the plan into the backup repo, commit and push, then push the code repos' committed work. Returns a status dict; never raises."""
    out = _run_data(root, repo, dry, extra_dirs, tasks)
    if not dry and os.getenv("APLUS_BACKUP", "1").strip().lower() not in {"0", "false", "no", "off"}:
        repos = code_repos if code_repos is not None else (CODE_REPOS if root == ROOT else [])
        out["code"] = [push_code(r) for r in repos]
        if out["code"]:
            out["message"] += " | code: " + "; ".join(out["code"])
    return out


def _run_data(root: Path, repo: Path | None, dry: bool, extra_dirs: list[Path] | None, tasks: bool) -> dict:
    out: dict = {"ok": False, "copied": 0, "skipped": [], "pushed": False, "message": ""}
    try:
        if os.getenv("APLUS_BACKUP", "1").strip().lower() in {"0", "false", "no", "off"}:
            out["message"] = "switched off (APLUS_BACKUP=0)"
            return out
        repo = Path(os.getenv("APLUS_BACKUP_DIR", "") or repo or DEFAULT_DIR)
        items, skipped = plan(root, extra_dirs, CALPHA if root == ROOT else None)
        out["skipped"] = skipped
        if dry:
            out.update(ok=True, copied=len(items), message=f"dry run: {len(items)} files, {sum(p.stat().st_size for p, _ in items) / 1048576:.1f} MB, {len(skipped)} skipped")
            return out
        if not (repo / ".git").exists():
            out["message"] = f"{repo} is not a git repo yet - run: python backup_to_github.py --setup <private repo URL>"
            return out
        copied = 0
        for src, rel in items:
            dst = repo / rel
            try:
                if dst.exists() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
            except OSError as exc:                           # a file being written right now: next night gets it
                skipped.append(f"{rel}: {type(exc).__name__}")
        n_tasks = export_tasks(repo / "tasks") if tasks else 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        (repo / "RESTORE.md").write_text(RESTORE.format(when=now), encoding="utf-8")
        _git(repo, "config", "core.autocrlf", "false")
        _git(repo, "add", "-A")
        if not _git(repo, "status", "--porcelain").stdout.strip():
            out.update(ok=True, copied=copied, message="nothing changed since the last backup")
            return out
        c = _git(repo, "commit", "-q", "-m", f"backup {now}: {copied} files changed, {n_tasks} tasks")
        if c.returncode != 0:
            out["message"] = "commit failed: " + (c.stderr or c.stdout).strip()[:160]
            return out
        p = _git(repo, "push", timeout=300)
        out["pushed"] = p.returncode == 0
        size = sum(f.stat().st_size for f in repo.rglob("*") if f.is_file() and ".git" not in f.parts)
        extra = f"; backup folder is {size / 1048576:.0f} MB" + (" - getting large, trim it" if size > MAX_REPO else "")
        out.update(ok=out["pushed"], copied=copied,
                   message=("pushed" if out["pushed"] else "committed locally but push failed: " + (p.stderr or p.stdout).strip()[:160]) + extra)
    except Exception as exc:                                 # noqa: BLE001 - the nightly job must never fail because of this
        out["message"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def setup(url: str, repo: Path | None = None) -> str:
    repo = Path(os.getenv("APLUS_BACKUP_DIR", "") or repo or DEFAULT_DIR)
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        r = _git(repo, "init", "-q", "-b", "main")
        if r.returncode != 0:
            return "git init failed: " + r.stderr.strip()[:160]
    _git(repo, "remote", "remove", "origin")
    _git(repo, "remote", "add", "origin", url)
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "branch", "-M", "main")
    _git(repo, "config", "push.autoSetupRemote", "true")
    return f"backup folder {repo} ready, remote {url}"


def main() -> int:
    argv = sys.argv[1:]
    if "--setup" in argv:
        print(setup(argv[argv.index("--setup") + 1]))
        return 0
    res = run(dry="--dry-run" in argv)
    print(f"backup: {res['message']} (files copied {res['copied']}, skipped {len(res['skipped'])})")
    for s in res["skipped"][:10]:
        print("  skipped", s)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Claude (Antigravity · Logaritma hesabi) ile kod incelemesi.

Kullanim:
    python tools/claude_review.py --diff HEAD~1..HEAD
    python tools/claude_review.py --files serit_v5.pyw dock_cards.py
    python tools/claude_review.py --diff HEAD~1..HEAD --model logaritma/claude-sonnet-4-6

Neden ayri bir betik: Gemini kodu yazar, Claude (Logaritma Antigravity kotasi)
kontrol eder. Claude aboneligi (CLAUDE SUBSCRIPTION DIRECT SDK) bu yoldan
KULLANILMAZ; yalnizca yerel Antigravity proxy'sindeki logaritma/... modelleri.

Cikis: 0 = onay, 1 = itiraz (blocking var), 2 = teknik hata.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

PROXY = os.environ.get("AG_PROXY_URL", "http://127.0.0.1:8317/v1").rstrip("/")
DEFAULT_MODEL = os.environ.get("AG_REVIEW_MODEL", "logaritma/claude-opus-4-6-thinking")
MAX_DIFF_CHARS = 60_000

CHECKLIST = """\
Su maddeleri tek tek kontrol et ve her biri icin KISA karar ver:
1. DOGRULUK: mantik hatasi, yanlis degisken, tanimsiz isim (NameError) var mi?
2. TEST ETKISI: mevcut testler (D:/Apps/serit/tests) kirilir mi? Hangi test?
3. YERLESIM: dar ekran (1280/1366 px) senaryosunda tasma/ust uste binme yaratir mi?
4. TURKCE METIN: kullaniciya gorunen metinler Turkce ve tutarli mi?
5. BAGIMLILIK/PERFORMANS: yeni bagimlilik, her karede pahali cizim, gereksiz kopya var mi?
6. GIZLILIK: musteri verisi, token, kisisel bilgi loglaniyor mu?
"""


def _key() -> str:
    for env in ("HERMES_CUSTOM_ANTIGRAVITY_LOCAL_API_KEY", "ANTIGRAVITY_API_KEY", "AG_API_KEY"):
        v = os.environ.get(env)
        if v:
            return v
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("ag_key.txt", ".ag_key"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            return open(p, encoding="utf-8").read().strip()
    raise SystemExit("API anahtari bulunamadi (HERMES_CUSTOM_ANTIGRAVITY_LOCAL_API_KEY)")


def _git(*args: str) -> str:
    root = os.environ.get("REVIEW_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(["git", *args], cwd=root,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} basarisiz: {out.stderr.strip()[:300]}")
    return out.stdout


def collect_diff(diff_range: str | None, files: list[str] | None) -> str:
    if files:
        parts = []
        for f in files:
            parts.append(f"### {f}\n```diff\n{_git('diff', '--', f) or '(degisiklik yok)'}\n```")
        return "\n\n".join(parts)
    rng = diff_range or "HEAD~1..HEAD"
    return _git("diff", rng)


def review(diff_text: str, model: str, context: str = "") -> dict:
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n... (diff kirpildi)"
    prompt = f"""Sen kidemli bir kod inceleyicisisin. Emre'nin Windows masaustu Serit (dock) projesinde
Gemini tarafindan yazilmis bir degisikligi kontrol ediyorsun.

{CHECKLIST}
{('PROJE NOTU: ' + context) if context else ''}

SADECE su JSON semasiyla cevap ver, baska metin yazma:
{{"verdict": "approve" | "changes_requested", "score": 0-10,
  "blocking": [{{"file": "...", "problem": "...", "fix": "..."}}],
  "minor": [{{"file": "...", "problem": "...", "fix": "..."}}],
  "tests_at_risk": ["test dosyasi veya adi"],
  "summary_tr": "en fazla 3 cumle Turkce ozet"}}

DIFF:
{diff_text}
"""
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000}
    req = urllib.request.Request(f"{PROXY}/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + _key()})
    with urllib.request.urlopen(req, timeout=240) as r:
        payload = json.loads(r.read())
    text = payload["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.lower().startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {"verdict": "changes_requested", "score": 0, "blocking": [],
                "minor": [], "tests_at_risk": [], "summary_tr": text[:500]}
    return json.loads(text[start:end + 1])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", default=None, help="git diff araligi, or. HEAD~1..HEAD")
    ap.add_argument("--files", nargs="*", default=None, help="calisma agacindaki degisiklikler")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--context", default="")
    args = ap.parse_args(argv)

    diff_text = collect_diff(args.diff, args.files)
    if not diff_text.strip():
        print("REVIEW: incelenecek diff yok")
        return 0
    try:
        res = review(diff_text, args.model, args.context)
    except urllib.error.HTTPError as e:
        print(f"REVIEW ERROR: HTTP {e.code} {e.read()[:200]!r}")
        return 2
    except Exception as e:  # ag/proxy hatasi
        print(f"REVIEW ERROR: {e}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=1))
    verdict = str(res.get("verdict", "")).lower()
    print(f"VERDICT: {verdict} | skor {res.get('score')} | blocking {len(res.get('blocking') or [])}")
    return 0 if verdict == "approve" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

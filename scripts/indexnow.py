#!/usr/bin/env python3
"""Pings IndexNow (Bing, Yandex, Seznam, Naver...) with every URL in the live sitemap.xml.

The key is the name of the <key>.txt file at the site root; IndexNow fetches
that file to confirm we own the host. Run after the site has been deployed.

Usage: python3 scripts/indexnow.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST = "pbarcelona-ai.github.io"


def main() -> int:
    keys = [p.stem for p in REPO_ROOT.glob("*.txt") if re.fullmatch(r"[0-9a-f]{32}", p.stem)]
    if not keys:
        print("[indexnow] no key file found, skipping")
        return 0
    # the deployed sitemap lists the generated /ip/ pages; the committed copy may lag behind
    try:
        with urllib.request.urlopen(f"https://{HOST}/sitemap.xml", timeout=30) as resp:
            sitemap = resp.read().decode("utf-8")
    except urllib.error.URLError:
        sitemap = (REPO_ROOT / "sitemap.xml").read_text(encoding="utf-8")
    urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    body = json.dumps({"host": HOST, "key": keys[0], "keyLocation": f"https://{HOST}/{keys[0]}.txt",
                       "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"[indexnow] submitted {len(urls)} URLs: HTTP {resp.status}")
    except urllib.error.HTTPError as err:
        # 4xx here (e.g. key not yet reachable) should not fail the deploy
        print(f"[indexnow] HTTP {err.code}: {err.read().decode(errors='replace')[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

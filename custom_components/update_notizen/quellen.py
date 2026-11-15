"""Holt die Änderungsnotizen zu offenen Updates.

Quellen:
- Add-ons/Apps: Änderungsprotokoll über die Supervisor-API (nur Home Assistant OS/Supervised)
- GitHub-Release-Links (HACS, Supervisor, OS, viele Integrationen): Text des GitHub-Releases
- Home Assistant Core: Patch-Notizen von GitHub; bei neuer Hauptversion zusätzlich der Abschnitt
  „Backward-incompatible changes“ aus dem Release-Blog, gefiltert auf die installierten Integrationen

Alles ist Fremdtext; er wird gekürzt und nur weitergereicht.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re
import time

import aiohttp

FASSUNG = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))["version"]
USER_AGENT = f"HomeAssistant-update_notizen/{FASSUNG} (+https://github.com/Celestial0579/ha-update-notizen)"


class GithubGesperrt(Exception):
    """GitHub hat das Ratenlimit gemeldet; bis `bis` (Unix-Zeit) nicht mehr fragen."""

    def __init__(self, bis: float) -> None:
        super().__init__(f"GitHub-Ratenlimit bis {time.strftime('%H:%M', time.localtime(bis))}")
        self.bis = bis


def _sperre_bis(kopf) -> float:
    """Ende der Sperre aus Retry-After oder X-RateLimit-Reset, sonst eine Stunde."""
    jetzt = time.time()
    try:
        if kopf.get("Retry-After"):
            return jetzt + min(float(kopf["Retry-After"]), 6 * 3600)
        if kopf.get("X-RateLimit-Reset"):
            return min(float(kopf["X-RateLimit-Reset"]), jetzt + 6 * 3600)
    except ValueError:
        pass
    return jetzt + 3600
_ZEIT = aiohttp.ClientTimeout(total=30)

ALLGEMEIN = {
    "authentication", "conditions", "condition", "triggers", "trigger", "templates", "template",
    "automations", "automation", "scripts", "script", "recorder", "frontend", "assist", "backup",
    "dashboards", "dashboard", "blueprints", "blueprint",
}


def kuerzen(text: str | None, laenge: int) -> str:
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    return text if len(text) <= laenge else text[:laenge] + " […]"


async def _holen(sitzung: aiohttp.ClientSession, url: str, kopf: dict[str, str] | None = None) -> str:
    kopf = {"User-Agent": USER_AGENT, **(kopf or {})}
    async with sitzung.get(url, headers=kopf, timeout=_ZEIT) as antwort:
        antwort.raise_for_status()
        return await antwort.text(errors="replace")


async def github_release(sitzung: aiohttp.ClientSession, url: str) -> str | None:
    """Text eines GitHub-Releases aus einem Release-Link."""
    treffer = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases/(?:tag/)?([^/?#]+)", url or "")
    if not treffer:
        return None
    eigner, repo, tag = treffer.groups()
    async with sitzung.get(
        f"https://api.github.com/repos/{eigner}/{repo}/releases/tags/{tag}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        timeout=_ZEIT,
    ) as antwort:
        if antwort.status == 404:
            return None
        if antwort.status == 429 or (antwort.status == 403 and antwort.headers.get("X-RateLimit-Remaining") == "0"):
            raise GithubGesperrt(_sperre_bis(antwort.headers))
        antwort.raise_for_status()
        daten = await antwort.json()
    if not isinstance(daten, dict):
        raise ValueError("Antwort von GitHub ist kein Objekt")
    return str(daten.get("body") or "")


async def addon_aenderungen(sitzung: aiohttp.ClientSession, slug: str, installiert: str) -> str | None:
    """Neue Einträge im Änderungsprotokoll eines Add-ons (oberhalb der installierten Fassung)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    text = await _holen(
        sitzung, f"http://{os.environ.get('SUPERVISOR', 'supervisor')}/addons/{slug}/changelog",
        {"Authorization": f"Bearer {token}"},
    )
    zeilen = text.splitlines()
    if installiert:
        # Die Fassung als ganzes Wort: „1.2.1“ steckt nicht in „1.2.10“ oder „11.2.1“.
        muster = re.compile(rf"(?<![0-9])(?<![0-9]\.){re.escape(installiert)}(?![0-9])(?!\.[0-9])")
        for nummer, zeile in enumerate(zeilen):
            if nummer and zeile.lstrip().startswith("#") and muster.search(zeile):
                return "\n".join(zeilen[:nummer])
    return text


async def blog_html(sitzung: aiohttp.ClientSession) -> str:
    return await _holen(sitzung, "https://www.home-assistant.io/latest-release-notes/")


def uebersprungene_hauptversionen(installiert: str, neu: str) -> list[str]:
    """Hauptversionen (JJJJ.M) zwischen der installierten und der neuen, ohne beide."""
    try:
        a_jahr, a_monat = (int(x) for x in installiert.split(".")[:2])
        n_jahr, n_monat = (int(x) for x in neu.split(".")[:2])
    except ValueError:
        return []
    von, bis = a_jahr * 12 + a_monat - 1, n_jahr * 12 + n_monat - 1
    return [f"{m // 12}.{m % 12 + 1}" for m in range(von + 1, bis)][:24]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def blog_brueche(seite: str, integrationen: list[str], laenge: int = 3500) -> str:
    """Abschnitt „Backward-incompatible changes“, gefiltert auf das, was hier installiert ist (blockierend).

    Jeder Eintrag wird nach `laenge` (max_zeichen) gekürzt: ein Fünftel für installierte, ein Siebtel für allgemeine.
    """
    positionen = [m.start() for m in re.finditer(r"<h2", seite)]
    teil = ""
    for nummer, pos in enumerate(positionen):
        # Nur die Überschrift selbst prüfen, nicht den Text danach (eine kurze Vorgängerüberschrift träfe sonst).
        ende = seite.find("</h2>", pos)
        if "Backward-incompatible changes" in re.sub(r"<[^>]+>", "", seite[pos:ende if ende > 0 else pos + 400]):
            teil = seite[pos:positionen[nummer + 1]] if nummer + 1 < len(positionen) else seite[pos:]
            break
    if not teil:
        return ""
    domaenen = [_norm(d) for d in integrationen if len(_norm(d)) >= 3]
    treffer, allgemein, andere = [], [], []
    for block in re.findall(r"<details.*?</details>", teil, re.S):
        kopf = re.search(r"<summary[^>]*>(.*?)</summary>", block, re.S)
        name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", kopf.group(1))).strip() if kopf else "?"
        block = re.sub(r'(?s)<span class="terminology-tooltip">.*?</span>', "", block)
        block = re.sub(r"(?s)<summary.*?</summary>", "", block)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", block))).strip()
        nn = _norm(name)
        if any(nn == d or (len(d) >= 4 and nn.startswith(d)) or (len(nn) >= 5 and d.startswith(nn)) for d in domaenen):
            treffer.append(f"- {name}: {kuerzen(text, laenge // 5)}")
        elif set(re.findall(r"[a-z]+", name.lower())) & ALLGEMEIN:
            allgemein.append(f"- {name}: {kuerzen(text, laenge // 7)}")
        else:
            andere.append(name)
    titel = re.search(r"<title>(.*?)</title>", seite, re.S)
    ausgabe = [f"Release-Blog: {titel.group(1).strip() if titel else '?'}"]
    ausgabe.append(
        "Inkompatible Änderungen an HIER INSTALLIERTEN Integrationen:\n" + ("\n".join(treffer) if treffer else "- keine")
    )
    if allgemein:
        ausgabe.append("Allgemeine inkompatible Änderungen (betreffen jede Installation):\n" + "\n".join(allgemein))
    if andere:
        ausgabe.append("Außerdem betroffen, hier NICHT installiert: " + ", ".join(andere))
    return "\n\n".join(ausgabe)

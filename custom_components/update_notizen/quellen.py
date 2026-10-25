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
import os
import re

import aiohttp

USER_AGENT = "HomeAssistant-update_notizen/0.1 (+https://github.com/Celestial0579/ha-update-notizen)"
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
        antwort.raise_for_status()
        daten = await antwort.json()
    return daten.get("body") or ""


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
    for nummer, zeile in enumerate(zeilen):
        if nummer and installiert and zeile.lstrip().startswith("#") and installiert in zeile:
            return "\n".join(zeilen[:nummer])
    return text


async def blog_html(sitzung: aiohttp.ClientSession) -> str:
    return await _holen(sitzung, "https://www.home-assistant.io/latest-release-notes/")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def blog_brueche(seite: str, integrationen: list[str]) -> str:
    """Abschnitt „Backward-incompatible changes“, gefiltert auf das, was hier installiert ist (blockierend)."""
    positionen = [m.start() for m in re.finditer(r"<h2", seite)]
    teil = ""
    for nummer, pos in enumerate(positionen):
        if "Backward-incompatible changes" in re.sub(r"<[^>]+>", "", seite[pos:pos + 400]):
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
            treffer.append(f"- {name}: {text[:700]}")
        elif set(re.findall(r"[a-z]+", name.lower())) & ALLGEMEIN:
            allgemein.append(f"- {name}: {text[:500]}")
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

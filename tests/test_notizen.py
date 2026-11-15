"""Quellen und Sammler ohne GitHub, Blog und Supervisor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.update_notizen import quellen
from custom_components.update_notizen.const import DOMAIN
from custom_components.update_notizen.sammler import Sammler

PROTOKOLL = "# Changelog\n## 1.2.15\n- neu\n## 1.2.10\n- mittel\n## v1.2.1\n- alt\n## 1.2.0\n"
RELEASE = "https://api.github.com/repos/o/r/releases/tags/v2"


@pytest.mark.usefixtures("socket_enabled")
async def test_aenderungsprotokoll_an_der_richtigen_fassung(hass: HomeAssistant, aiohttp_server, monkeypatch) -> None:
    from aiohttp import web

    app = web.Application()
    async def protokoll(_request: web.Request) -> web.Response:
        return web.Response(text=PROTOKOLL)

    app.router.add_get("/addons/{slug}/changelog", protokoll)
    server = await aiohttp_server(app)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    monkeypatch.setenv("SUPERVISOR", f"127.0.0.1:{server.port}")
    text = await quellen.addon_aenderungen(async_get_clientsession(hass), "x", "1.2.1")
    assert "1.2.10" in text and "- alt" not in text


def test_uebersprungene_hauptversionen() -> None:
    assert quellen.uebersprungene_hauptversionen("2026.9.3", "2026.11.1") == ["2026.10"]
    assert quellen.uebersprungene_hauptversionen("2025.11.0", "2026.2.0") == ["2025.12", "2026.1"]
    assert quellen.uebersprungene_hauptversionen("2026.10.4", "2026.11.0") == []
    assert quellen.uebersprungene_hauptversionen("dev", "2026.11.0") == []


def test_blog_brueche_und_kuerzen() -> None:
    seite = (
        "<title>2026.11: Neu</title><h2>Neues</h2><h2>Backward-incompatible changes</h2>"
        "<details><summary>Ecovacs</summary><p>Weg &amp; anders</p></details>"
        "<details><summary>Automations</summary><p>Allgemein</p></details>"
        "<details><summary>Hue</summary><p>x</p></details><h2>Danach</h2>"
    )
    text = quellen.blog_brueche(seite, ["ecovacs", "mqtt"])
    assert "- Ecovacs: Weg & anders" in text
    assert "Allgemeine inkompatible Änderungen" in text and "Automations" in text
    assert "hier NICHT installiert: Hue" in text
    assert quellen.kuerzen("a\n\n\n\nb", 100) == "a\n\nb"
    assert quellen.kuerzen("x" * 20, 5) == "xxxxx […]"


async def test_github_unerwartete_antwort_und_sperre(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    sitzung = async_get_clientsession(hass)
    aioclient_mock.get(RELEASE, json=[1, 2])
    with pytest.raises(ValueError):
        await quellen.github_release(sitzung, "https://github.com/o/r/releases/tag/v2")
    aioclient_mock.clear_requests()
    aioclient_mock.get(RELEASE, status=403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4102444800"})
    with pytest.raises(quellen.GithubGesperrt):
        await quellen.github_release(sitzung, "https://github.com/o/r/releases/tag/v2")


def _update(hass: HomeAssistant, entity_id: str, plattform: str, kennung: str, url: str = "") -> None:
    er.async_get(hass).async_get_or_create("update", plattform, kennung, suggested_object_id=entity_id.split(".")[1])
    hass.states.async_set(entity_id, "on", {"installed_version": "2026.9.3", "latest_version": "2026.11.1", "release_url": url})


async def test_fehlschlag_wird_gemerkt_und_sperre_geachtet(hass: HomeAssistant) -> None:
    eintrag = MockConfigEntry(domain=DOMAIN)
    eintrag.add_to_hass(hass)
    sammler = Sammler(hass, eintrag)
    for n in (1, 2):
        _update(hass, f"update.integration_{n}", "hacs", f"k{n}", f"https://github.com/o/r{n}/releases/tag/v2")
    abruf = AsyncMock(side_effect=quellen.GithubGesperrt(4102444800))
    with patch.object(quellen, "github_release", abruf):
        erste = await sammler.async_notizen()
        await sammler.async_notizen()
    assert abruf.await_count == 1  # danach gesperrt, und der Fehlschlag ist gemerkt
    assert all(u["quelle"].startswith("fehler: GitHub-Ratenlimit") for u in erste["updates"].values())


async def test_core_an_der_kennung_erkannt(hass: HomeAssistant) -> None:
    eintrag = MockConfigEntry(domain=DOMAIN)
    eintrag.add_to_hass(hass)
    sammler = Sammler(hass, eintrag)
    _update(hass, "update.umbenannt", "hassio", "home_assistant_core_version_latest")
    with (
        patch.object(quellen, "blog_html", AsyncMock(return_value="")),
        patch.object(quellen, "github_release", AsyncMock(return_value="x" * 300)),
    ):
        antwort = await sammler.async_notizen()
    notiz = antwort["updates"]["update.umbenannt"]
    assert notiz["quelle"] == "github+blog"
    assert "Übersprungene Hauptversionen: 2026.10" in notiz["notizen"]


def test_user_agent_nennt_die_fassung() -> None:
    assert f"/{quellen.FASSUNG} " in quellen.USER_AGENT


@pytest.mark.parametrize(
    "link",
    [
        "https://github.com/../r/releases/tag/v2",
        "https://github.com/o/../releases/tag/v2",
        "https://github.com/o/./releases/tag/v2",
        "https://github.com/o/r/releases/tag/..",
        "https://github.com/o?x=1/r/releases/tag/v2",
        "https://github.com/o#x/r/releases/tag/v2",
        "https://github.com/o/r/releases/tag/v2/../../../../users/x",
        "https://github.com/-o/r/releases/tag/v2",
        "https://example.com/o/r/releases/tag/v2",
    ],
)
async def test_ungueltige_release_links_werden_nicht_abgefragt(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, link: str
) -> None:
    """#14: Eigentümer, Repo und Tag nur als gültige Namen; kein anderer Pfad der API."""
    assert await quellen.github_release(async_get_clientsession(hass), link) is None
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("link", "tag"),
    [
        ("https://github.com/o/r.js/releases/tag/v2", "v2"),
        ("https://github.com/o-1/r_2/releases/v2.0.1", "v2.0.1"),
        ("https://github.com/o/r/releases/tag/v2?x=1#y", "v2"),
        ("https://github.com/o/r/releases/tag/v2%2B1", "v2%2B1"),
        ("https://github.com/o/r/releases/tag/v2+1", "v2%2B1"),
    ],
)
async def test_gueltige_release_links(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, link: str, tag: str) -> None:
    eigner, repo = link.split("/")[3:5]
    aioclient_mock.get(f"https://api.github.com/repos/{eigner}/{repo}/releases/tags/{tag}", json={"body": "Notiz"})
    assert await quellen.github_release(async_get_clientsession(hass), link) == "Notiz"

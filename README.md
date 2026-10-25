# Update-Notizen für Home Assistant

Holt zu **jedem offenen Update** die Änderungsnotizen – Home Assistant Core, OS und Supervisor, Add-ons/Apps
und **HACS** – und löst in einem **einstellbaren Takt** einen Bericht aus. Gedacht als Grundlage für eine
Update-Übersicht, etwa mit KI-Einschätzung („unkritisch / prüfen / Achtung“) per Push.

*English summary below.*

## Was es liefert

| | |
|---|---|
| Aktion **`update_notizen.abrufen`** | gibt die Notizen als Antwort zurück: `anzahl`, `updates` (je Entität Name, installierte und neue Version, `notizen`, `quelle`) und `integrationen` (installierte Integrationen) |
| Ereignis **`update_notizen_bericht`** | wird im eingestellten Takt ausgelöst: `anzahl`, `updates` (Liste der Entitäten), `geaendert` |
| Sensor **Offene Updates** | Anzahl, Attribute `updates`, `letzter_bericht`, `naechster_bericht` |
| Knopf **Bericht jetzt** | löst das Ereignis sofort aus |

**Quellen der Notizen**

- Add-ons/Apps: Änderungsprotokoll über die Supervisor-API (nur der Teil oberhalb der installierten Fassung)
- GitHub-Release-Links (HACS-Repos, Supervisor, OS, viele Integrationen): Text des Releases
- Home Assistant Core: Patch-Notizen; bei neuer Hauptversion zusätzlich die „Backward-incompatible changes“
  aus dem Release-Blog, **gefiltert auf die hier installierten Integrationen**

Notizen zu einer Version werden zwischengespeichert und nicht bei jedem Bericht neu geholt (GitHub erlaubt
ohne Anmeldung 60 Abfragen pro Stunde).

## Einrichtung

1. HACS › drei Punkte › **Benutzerdefinierte Repositories** › diese Repository-URL, Typ **Integration**.
2. „Update-Notizen“ installieren, Home Assistant neu starten.
3. **Einstellungen › Geräte & Dienste › Integration hinzufügen › Update-Notizen**.
4. Unter **Konfigurieren**: Uhrzeit und Abstand (Vorgabe täglich 10:00), „nur bei Änderung melden“, Länge je Update.

## Beispiel: Bericht per Automation

```yaml
triggers:
  - trigger: event
    event_type: update_notizen_bericht
actions:
  - action: update_notizen.abrufen
    response_variable: notizen
  - action: notify.mobile_app_handy
    data:
      title: "{{ notizen.anzahl }} Updates offen"
      message: >-
        {% for u in notizen.updates.values() %}{{ u.name }}: {{ u.installiert }} → {{ u.neu }}
        {% endfor %}
```

Die Notizen sind Fremdtext. Wer sie an eine KI gibt, sollte sie ausdrücklich als Daten kennzeichnen.

---

## English summary

Fetches the release notes for every pending update (Home Assistant Core/OS/Supervisor, add-ons/apps and HACS)
via the action `update_notizen.abrufen` (response) and fires the event `update_notizen_bericht` on a configurable
schedule (time + interval, default daily 10:00). Core notes include the backward-incompatible changes of the
release blog, filtered to the integrations installed. Notes are cached per version. Set up from the UI after
installing via HACS as a custom repository (type *Integration*).

Lizenz / License: MIT

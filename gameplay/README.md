# Gameplay-Bibliothek

Eigene GTA-Gameplay-Clips (oder ausdrücklich zur freien Nutzung freigegebene),
die der Bot als themenpassenden Video-Hintergrund verwendet.

**Niemals fremdes Material ohne ausdrückliche Freigabe hier ablegen** —
Copyright-Strikes killen den Kanal.

## Clip hinzufügen

1. MP4 in diesen Ordner legen (ideal: vertikal 9:16 oder 1080p+, 20–60 s,
   ohne Musik/HUD-Overlays von Drittinhalten)
2. Eintrag in `manifest.json` ergänzen:

```json
[
  {
    "file": "driving_night.mp4",
    "tags": ["auto", "fahren", "driving", "car", "nacht", "stadt", "verfolgungsjagd"]
  },
  {
    "file": "heist_shootout.mp4",
    "tags": ["heist", "raub", "schiesserei", "shooting", "waffe", "mission", "geld"]
  }
]
```

Der Bot matcht die Tags gegen Titel, Sätze und Tags des generierten Skripts
und nimmt den Clip mit der besten Übereinstimmung (bei Gleichstand zufällig).
Ist der Ordner leer, fällt er automatisch auf Pexels-Stock zurück.

## Automatisch von der PS5 / PS App (Google Drive)

Es gibt keine offizielle Schnittstelle zu den Aufnahmen der PS App. Der Weg
über Google Drive braucht nur das Handy:

1. Einmalig: In Google Drive einen Ordner `GridPhantom Gameplay` anlegen und
   per Link freigeben ("Jeder, der über den Link verfügt" – Betrachter).
   Den Link beim Bot als `GAMEPLAY_DRIVE_FOLDER` hinterlegen.
2. Pro Clip: PS App → Spielebibliothek → Aufnahmen → Clip → Teilen →
   Google Drive → Ordner `GridPhantom Gameplay`.
3. Der Bot prüft den Ordner beim Start, alle 2 Stunden und direkt vor jedem
   Video (`gameplay_sync.py`). Neue Clips werden einmal geladen, in ein
   vertikales 1080x1920-Proxy (24 fps, ohne Ton, Mittenausschnitt)
   umgerechnet und ab dann als Hintergrund verwendet. Aus einem langen Clip
   wird jedes Mal ein anderer zufälliger Ausschnitt genommen.

Tipps:

- Dateiname = Thema: `heist_cayo_nacht.mp4` ergibt die Tags `heist`, `cayo`,
  `nacht`. Passt ein Tag zu Titel oder Text des Videos, gewinnt dieser Clip.
  Ohne Treffer wird zufällig aus allen eigenen Clips gewählt (GTA-5/Online-
  Themen). Die Standardnamen der PS5 (`Grand Theft Auto V_2026...`) ergeben
  keine Tags, funktionieren aber trotzdem.
- Bei GTA-6-Themen hat die offizielle Trailer-Montage Vorrang, ausser ein
  Clip ist z. B. mit `gta6` im Namen markiert.
- HUD und Minimap möglichst ausblenden, 20–90 s pro Clip, keine fremde Musik
  im Clip (der Bot legt Stimme und Musikbett selbst darüber).


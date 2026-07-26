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

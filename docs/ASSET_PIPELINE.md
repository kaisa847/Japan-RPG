# Asset-Pipeline: Layered Sprites (Baukasten)

Spezifikation für die Produktion echter Charakter-Assets (z. B. per
Stable Diffusion in einer lokalen Session). Die Engine rendert
Charaktere mit `manifest.json` als **zwei Ebenen**: Pose-Körper +
Gesichts-Patch. Alles hier beschreibt, was die Pipeline liefern muss,
damit das Spiel es ohne Code-Änderung frisst.

## Zielstruktur pro Charakter

```
assets/characters/aoi/
├── manifest.json
├── poses/
│   ├── stand.png            # Ganzkörper, Gesicht NEUTRAL/leer gehalten
│   ├── wave.png
│   ├── arms_crossed.png
│   ├── hands_clasped.png
│   ├── pointing.png
│   └── phone.png
├── faces/
│   ├── neutral.png          # Gesichts-Patch, wird am Anker überlagert
│   ├── happy.png
│   ├── … (alle 16 Expressions)
│   └── blink.png            # Augen zu → aktiviert Blinzel-Animation
└── neutral.png …            # (Legacy-Einzelsprites, optional als Fallback)
```

## Formate & Maße

| Asset | Format | Maß | Hinweise |
|---|---|---|---|
| Pose-Körper | PNG, RGBA (transparent) | 400×800 min., empfohlen 800×1600 generieren und auf 400×800 skalieren | Alle Posen: gleiche Bildgröße, gleiche Fußlinie, gleiche Kopfposition! |
| Gesichts-Patch | PNG, RGBA | quadratisch, Breite = `anchor.w` × Körperbreite (bei w=0.375 und 400px Körper → 150×150) | Alle Faces einer Pose-Familie: identischer Ausschnitt |
| Hintergrund | PNG/JPG/WEBP | 1920×1080 | wie bisher |

## manifest.json (Version 1)

```json
{
  "version": 1,
  "default_pose": "stand",
  "default_face": "neutral",
  "blink_face": "blink",
  "poses": {
    "stand": {
      "body": "poses/stand.png",
      "anchor": { "x": 0.5, "y": 0.15, "w": 0.375 }
    }
  },
  "faces": ["neutral", "happy", "..."]
}
```

**Anker-Definition:** relativ zu den Körperbild-Dimensionen.
`x`/`y` = Mittelpunkt des Gesichts-Patches (0–1), `w` = Patch-Breite
als Anteil der Körperbreite. Die Engine setzt den Patch per CSS auf
`left: x·100%; top: y·100%; width: w·100%` mit `translate(-50%,-50%)`.
Jede Pose hat ihren eigenen Anker (der Kopf sitzt je Pose woanders).

`blink_face` ist optional; wenn gesetzt, blinzelt der Charakter alle
2,5–6 s für ~130 ms. Weglassen → kein Blinzeln.

## Posen-Set (semantische Namen — die KI wählt danach)

| Pose | Bedeutung | OpenPose-Hinweis |
|---|---|---|
| `stand` | neutraler Stand, Default | Arme locker seitlich |
| `wave` | begrüßen/winken | rechter Arm erhoben |
| `arms_crossed` | skeptisch/trotzig/frierend | Arme verschränkt |
| `hands_clasped` | schüchtern/bittend/nervös | Hände vor dem Körper |
| `pointing` | zeigt etwas („guck mal!") | Arm ausgestreckt seitlich |
| `phone` | am Handy (LINE-Nachricht, Anruf — Story-Beats!) | Hand mit Phone am Ohr/vor Gesicht |

Neue Posen: einfach Datei + Manifest-Eintrag ergänzen — Backend liest
das Manifest, listet die Pose automatisch im Prompt, Engine rendert sie.

## SD-Workflow (Kurzreferenz für die lokale Session)

1. **Kanonisches Design:** Kandidaten nach `data/characters/aoi.visual.md`
   generieren → eine Version festlegen (User entscheidet). Seed + Prompt
   notieren; optional LoRA auf ~20 Bildern trainieren (größter
   Konsistenz-Hebel), sonst IP-Adapter/Reference.
2. **Pose-Körper:** pro Pose ein OpenPose-Skelett mit IDENTISCHER
   Kopfposition und Fußlinie (Skelette einmal bauen, wiederverwenden).
   ControlNet OpenPose + Referenz → Körper generieren, Gesicht neutral.
   Freistellen (rembg), auf Zielmaß skalieren.
3. **Gesichts-Patches:** pro Pose-Familie EIN Körperbild nehmen,
   Gesichtsregion maskieren (Maske = Ankerbereich aus dem Manifest),
   je Expression inpainten (Denoise ~0.5–0.7, nur Maske). Patch aus dem
   Ergebnis ausschneiden — dadurch pixelgenau deckungsgleich.
4. **QC:** jedes Asset sichten (Hände! Kanten! Stilbruch!), Patch-
   Deckung per Overlay-Diff prüfen, Manifest schreiben, im Spiel testen
   (`python generate_placeholders.py` erzeugt eine Platzhalter-Version
   dieses gesamten Layouts zum Gegentesten der Engine).

## Engine-Verhalten (zur Erinnerung)

- Kein Manifest → Legacy-Modus (Einzelsprite pro Expression) — die
  Migration kann pro Charakter erfolgen.
- Unbekannte Pose → `default_pose`; unbekannte Expression → `default_face`;
  fehlende Datei → „Missing"-Label statt Crash.
- Gesichtswechsel bei gleicher Pose = schneller Crossfade nur des
  Patches; Posenwechsel = normaler Fade des ganzen Charakters.
- `<staging>`: `left`/`center`/`right` + `near` (Zoom 1.18, animiert).

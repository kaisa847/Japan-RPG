# Handover: Asset-Produktion mit Stable Diffusion (lokale Session)

Dieses Dokument übergibt die Asset-Produktion an eine **lokale
Claude-Code-Session** mit Zugriff auf Stable Diffusion. Es enthält
alles Nötige — die lokale Session braucht kein Wissen aus früheren
Gesprächen.

## Kontext in 5 Sätzen

„Japanese Life: Tokyo Stories" ist ein KI-getriebenes Visual Novel zum
Japanischlernen (FastAPI-Backend + Vanilla-JS-Frontend, Claude
generiert die Szenen). Die Engine wurde gerade auf ein
**Layered-Sprite-System** umgebaut: Charaktere werden aus Pose-Körper +
Gesichts-Patch komponiert statt aus Ganzkörper-Einzelsprites. Die
komplette technische Spezifikation steht in `docs/ASSET_PIPELINE.md` —
**zuerst lesen**. Aktuell laufen Platzhalter-Grafiken
(`generate_placeholders.py` erzeugt sie, inkl. Baukasten-Layout zum
Gegentesten). Auftrag dieser Session: **echte Assets für Aoi und die
18 Hintergründe produzieren.**

## Vorbedingungen prüfen

1. **Branch:** Das Sprite-System liegt auf
   `claude/projekt-review-game-language-rcaj4z` (Commit „Add layered
   sprite system"). Falls noch nicht in `main` gemergt: diesen Branch
   auschecken, sonst fehlen Manifest-Support und Engine-Rendering.
2. **Stable Diffusion:** A1111 WebUI mit `--api` erreichbar (Standard:
   `http://127.0.0.1:7860`). Prüfen: `GET /sdapi/v1/sd-models`.
   Gewünscht: Anime-Checkpoint, ControlNet mit OpenPose-Modell,
   idealerweise IP-Adapter. Was fehlt, beim User erfragen — nicht raten.
3. **Python-Tools:** `pip install requests pillow rembg onnxruntime`
   (rembg fürs Freistellen).
4. **Starter-Skript:** `scripts/sd_asset_pipeline.py` — ungetestetes
   Gerüst für A1111-Aufrufe, Freistellen, Patch-Extraktion und
   Manifest-Schreiben. Als Ausgangspunkt nutzen, bei Bedarf umbauen.

## Referenzen im Repo

| Datei | Inhalt |
|---|---|
| `docs/ASSET_PIPELINE.md` | **Die Spezifikation**: Dateilayout, Maße, Anker, Posen-Set, Workflow |
| `data/characters/aoi.visual.md` | Aois Aussehen + fertiges SD-Prompt-Template inkl. Expression-Tags |
| `data/locations.json` | Alle 18 Orte mit deutschen Namen (für Hintergrund-Prompts) |
| `assets/characters/aoi/manifest.json` | Beispiel-Manifest (von den Platzhaltern erzeugt) |
| `generate_placeholders.py` | Erzeugt das Ziel-Layout als Platzhalter — nützlich als Struktur-Referenz |

## Arbeitsplan

Reihenfolge einhalten — jeder Schritt baut auf dem vorigen auf.

### Schritt 1: Kanonisches Design festlegen (MIT dem User)
Mit dem Prompt-Template aus `aoi.visual.md` 6–8 Kandidaten generieren
(txt2img, `stand`-Pose, neutral). **Dem User zeigen, wählen lassen.**
Seed + exakten Prompt der Gewinner-Version notieren — sie ist ab jetzt
die Referenz für ALLES. Optional (großer Konsistenz-Hebel, wenn
VRAM/Zeit da): LoRA auf ~20 Varianten des gewählten Designs trainieren.

### Schritt 2: Die 6 Pose-Körper
Posen laut Spez: `stand, wave, arms_crossed, hands_clasped, pointing,
phone`. Ein OpenPose-Skelett-Set mit IDENTISCHER Kopfposition und
Fußlinie bauen (einmalig), dann pro Pose via ControlNet + Referenz
(IP-Adapter/LoRA/Seed) generieren. Gesicht dabei neutral halten.
Freistellen (rembg), Kanten prüfen, auf einheitliche Größe bringen
(gleiche Bildmaße für alle Posen!). Kaputte Hände = neu generieren,
nicht durchwinken.

### Schritt 3: Gesichts-Patches per Inpainting
Pro Pose-Familie das `stand`-Bild nehmen, Gesichtsregion maskieren
(Region = Anker aus dem Manifest; Skript hilft), je Expression
inpainten (Denoise 0.5–0.7, only masked). Patch ausschneiden →
pixelgenau deckungsgleich. 16 Expressions laut `aoi.visual.md` +
`blink` (Augen geschlossen, sonst neutral). Anker im Manifest an die
echten Bilder anpassen (x/y/w relativ zum Körperbild, siehe Spez).

### Schritt 4: Hintergründe (kann parallel laufen)
18 Orte aus `data/locations.json`, 1920×1080, einheitlicher
Anime-Hintergrund-Stil (ein gemeinsamer Style-Prompt, KEINE Personen).
Pro Ort 2–3 Kandidaten, besten nehmen. Stil einmal vom User abnicken
lassen (erste 3 Orte zeigen), dann durchziehen.

### Schritt 5: Einbau + Abnahme
Dateien nach `assets/characters/aoi/` bzw. `assets/backgrounds/`
legen, Manifest schreiben, Server starten (`python run.py`), im
Browser prüfen: Posenwechsel, Gesichtswechsel (Crossfade), Blinzeln,
Staging (`near`-Zoom!), alle Hintergründe. Screenshot-Runde für den
User. WICHTIG: `assets/` ist gitignored — Assets werden NICHT
committet, sondern direkt aufs Deployment kopiert (User fragen, wohin).

## Interaktionspunkte mit dem User (nicht überspringen)

1. Design-Auswahl Aoi (Schritt 1) — Pflicht.
2. Stil-Freigabe Hintergründe (Schritt 4, nach den ersten 3).
3. Bei hartnäckigen Posen/Expressions: 2–3 Varianten zeigen statt
   endlos allein iterieren.
4. Zielort für die fertigen Assets (VPS-Pfad).

## QC-Checkliste pro Asset

- [ ] Charakter konsistent mit Referenz (Haare, Outfit, Proportionen)
- [ ] Hände/Finger in Ordnung
- [ ] Sauber freigestellt, keine Halo-Kanten
- [ ] Posen: gleiche Bildgröße, Fußlinie und Kopfposition
- [ ] Patches: deckungsgleich über der Gesichtsregion (Overlay-Diff)
- [ ] Stil einheitlich über alle Assets

## A1111-API-Kurzreferenz

- `POST /sdapi/v1/txt2img` — body: prompt, negative_prompt, seed,
  width, height, steps, cfg_scale, sampler_name;
  ControlNet über `alwayson_scripts.controlnet.args`
- `POST /sdapi/v1/img2img` — zusätzlich init_images (base64),
  mask (base64), denoising_strength, inpainting_fill,
  inpaint_full_res für „only masked"
- `GET /sdapi/v1/options` / `POST` — Checkpoint wechseln
- Bilder kommen base64-codiert in `images[]`

---

## Startprompt für die lokale Session (kopieren & einfügen)

> Lies zuerst `docs/HANDOVER_ASSET_SESSION.md` und
> `docs/ASSET_PIPELINE.md` im Repo Japan-RPG und folge dem dortigen
> Arbeitsplan: Produziere mit der lokalen Stable-Diffusion-API
> (A1111, http://127.0.0.1:7860) die Layered-Sprite-Assets für Aoi
> (6 Posen, 17 Gesichts-Patches, manifest.json) und die 18
> Hintergründe. Halte die Interaktionspunkte ein — Design-Auswahl und
> Stil-Freigabe entscheide ich. Prüfe zuerst die Vorbedingungen
> (Branch, SD-API, ControlNet) und sag mir, was fehlt.

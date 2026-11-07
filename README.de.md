# kicad-pcb2gcode

Ein Plugin für KiCad 9/10, das das im Leiterplatteneditor geöffnete Board mit
[pcb2gcode](https://github.com/pcb2gcode/pcb2gcode) in CNC-G-Code umwandelt:
Isolationsfräsen, Bohren und Platinenkontur, mit Voreinstellungen für
GRBL-Fräsen.

*English: [README.md](README.md)*

Ein Klick auf den Toolbar-Button öffnet ein Einstellungsfenster.
**G-Code erzeugen** dann

1. exportiert Kupferlagen, `Edge.Cuts` und Bohrdatei mit `kicad-cli` – aus
   einer Kopie des Boards, wie es gerade in KiCad offen ist. Ungespeicherte
   Änderungen sind also dabei, und deine Datei bleibt unangetastet.
2. erkennt, welche Kupferseiten tatsächlich Leiterbahnen haben,
3. schreibt eine `millproject`-Datei und startet pcb2gcode,
4. legt den G-Code im Ordner `gcode/` neben dem Board ab.

## Voraussetzungen

| | |
|---|---|
| KiCad | 9.0 oder neuer, mit aktivierter API (siehe unten) |
| pcb2gcode | 2.5 oder neuer (3.x empfohlen) – [Releases](https://github.com/pcb2gcode/pcb2gcode/releases), `apt install pcb2gcode`, `brew install pcb2gcode` |
| nur Linux | wxPython aus dem System für das Einstellungsfenster, z. B. `sudo apt install python3-wxgtk4.0` (meist schon durch KiCad installiert) |

Das Plugin ist reines Python. KiCad legt die Python-Umgebung selbst an und
installiert `kicad-python` automatisch.

## Installation

1. `kicad-pcb2gcode-<version>.zip` aus den
   [Releases](https://github.com/brln-devlabs/kicad-pcb2gcode/releases)
   herunterladen und in den Plugin-Ordner von KiCad entpacken:

   | System | Ordner |
   |---|---|
   | Windows | `Dokumente\KiCad\<version>\plugins\` |
   | macOS | `~/Documents/KiCad/<version>/plugins/` |
   | Linux | `~/.local/share/kicad/<version>/plugins/` |

   Danach muss es `…/plugins/kicad-pcb2gcode/plugin.json` geben.
   Alternativ das Repository klonen und `python scripts/install.py` ausführen.
2. In KiCad: **Einstellungen → Einstellungen → Plugins → KiCad-API aktivieren**.
3. KiCad neu starten. Beim ersten Start richtet KiCad kurz die
   Python-Umgebung des Plugins ein. Danach erscheint der Button **pcb2gcode**
   in der Toolbar des Leiterplatteneditors.

## Benutzung

Board öffnen, Toolbar-Button drücken, Einstellungen prüfen,
**G-Code erzeugen** klicken. Die Reiter:

* **Allgemein** – welche Kupferseiten gefräst werden (automatisch, oben,
  unten, beide), Bohren und Kontur an/aus, Ausgabeordner, Nullpunkt,
  Sicherheits- und Werkzeugwechselhöhe, Pfad zu pcb2gcode.
* **Isolation** – verfügbare Fräserdurchmesser (die Breite, die dein
  Werkzeug in der Frästiefe schneidet; einer oder mehrere), Tiefe,
  Vorschübe, Isolationsbreite, Überlappung (Prozent oder Länge),
  Voronoi-Modus – dieselben Felder wie in pcb2gcodeGUI.
* **Bohren** – Tiefe, Vorschub, verfügbare Bohrergrößen, große Löcher fräsen.
* **Kontur** – Fräser, Zustellung pro Durchgang, Haltestege.
* **Maschine** – G-Code-Dialekt und zusätzliche pcb2gcode-Optionen.

Die Voreinstellungen passen für eine kleine GRBL-Fräse (3018-Klasse) mit
einem V-Bit, das in 0,08 mm Tiefe 0,15 mm breit schneidet, und einem
1-mm-Fräser. **Prüfe die Werte immer gegen deine Werkzeuge und
fahre neue Einstellungen zuerst in der Luft ab.**

### Ausgabe

```
mein-board/
  mein-board.kicad_pcb
  mein-board.pcb2gcode.json   Einstellungen dieses Boards (mit ins Repo nehmen)
  gcode/
    mein-board_back.ngc       Isolationsfräsen Unterseite
    mein-board_drill.ngc      Bohren
    mein-board_outline.ngc    Kontur
    millproject               die verwendete pcb2gcode-Konfiguration
    cam/                      exportierte Gerber- und Bohrdateien
```

Die Dateien nacheinander im G-Code-Sender (Candle, UGS, bCNC, CNCjs …)
abarbeiten und dazwischen das Werkzeug wechseln. Der Autoleveller von
pcb2gcode unterstützt GRBL nicht; nutze stattdessen die Höhenkarte deines
Senders.

### Hinweise zu GRBL

Die Voreinstellungen schalten ab, was GRBL nicht kennt: `G64`
(Bahnüberschleifen), `G81` (Bohrzyklus), `G91.1` und `M6`
(Werkzeugwechsel). Mit grblHAL und Werkzeugwechsler lässt sich `M6` im Reiter
**Maschine** wieder einschalten.

### Nullpunkt und doppelseitige Platinen

Mit **Platinenecke auf X0/Y0** (Voreinstellung) liegt die linke untere Ecke
der Platinenkontur (`Edge.Cuts`, Linienmitte) in jeder Datei genau auf X0/Y0.
Die Unterseite wird um die Mittelachse der Platine gespiegelt – links/rechts
oder oben/unten, Reiter **Doppelseitig** – und liegt damit im selben Rechteck
wie die Oberseite. pcb2gcodes eingebautes `zero-start` wird dafür nicht
verwendet: Es lässt einen Rand von einem Fräserdurchmesser und spiegelt die
Unterseite in den negativen X-Bereich.

#### Wenderahmen

Für doppelseitige Platinen ohne Passstifte: Einen Rahmen (oder eine
ausgefräste Tasche) genau in der Größe der Platinenkontur auf der Maschine
befestigen und X0/Y0 auf seine linke untere Ecke setzen. Den Rohling auf
dieselbe Größe zuschneiden. Mit **Im Wenderahmen fräsen**

* wird die Kontur nicht gefräst (der Rohling hat schon seine Endgröße),
* werden alle Löcher von oben gebohrt, vor dem Wenden,
* steht der Ablauf im Protokoll und in `gcode/ABLAUF.txt`:

```
1. board_front.ngc   Oberseite
2. board_drill.ngc   Bohren
3. Platine im Rahmen links/rechts wenden – Nullpunkt bleibt
4. board_back.ngc    Unterseite
```

Bei nicht rechteckigen Platinen hat der Rahmen die Größe des umschließenden
Rechtecks der Kontur. Die Ausrichtung folgt pcb2gcodes Koordinatenformeln, die
`tests/test_placement.py` nachbildet; trotzdem zuerst an einem Reststück
prüfen.

### Boards mit mehr als zwei Kupferlagen

Isolationsfräsen kann nur Ober- und Unterseite herstellen. Vor dem Export
prüft das Plugin den Lagenaufbau:

* Innenlagen mit Leiterbahnen oder Flächen brechen den Lauf mit einer Meldung
  ab. Mit **Nur Außenlagen fräsen** (Reiter Allgemein) werden `F.Cu`/`B.Cu`
  trotzdem gefräst; die Verbindungen auf den Innenlagen fehlen dann.
* Leere Innenlagen ergeben nur einen Hinweis im Protokoll.
* Blind-, Buried- und Micro-Vias brechen immer ab, weil sie sich nicht bohren
  lassen.

## Einstellungsdateien

* Pro Board: `<board>.pcb2gcode.json` neben dem Board, bei jedem Lauf
  geschrieben.
* Standard für neue Boards und pcb2gcode-Pfad: **Als Standard speichern**
  schreibt `config.json` nach `%APPDATA%\kicad-pcb2gcode` (Windows),
  `~/Library/Application Support/kicad-pcb2gcode` (macOS) bzw.
  `~/.config/kicad-pcb2gcode` (Linux).

## Kommandozeile

Dieselbe Verarbeitung läuft ohne KiCad auf einem gespeicherten Board:

```
cd kicad-pcb2gcode/plugin
python -m kicad_pcb2gcode pfad/zum/board.kicad_pcb [--sides back] [--no-outline] [--gui]
```

`python -m kicad_pcb2gcode --help` zeigt alle Optionen.

## Fehlersuche

* **Kein Toolbar-Button** – prüfen, ob die API aktiviert ist und
  `plugins/kicad-pcb2gcode/plugin.json` existiert. Unter Linux schlägt das
  Anlegen der Plugin-Umgebung bei KiCad 9.0.x manchmal fehl; dann
  **Einstellungen → Plugins → Plugin-Umgebung neu erstellen** ausprobieren und
  sicherstellen, dass `python3 -m venv` auf dem System funktioniert.
* **„pcb2gcode nicht gefunden“** – den Programmpfad im Reiter **Allgemein**
  eintragen.
* **Kein Fenster** – ohne wxPython läuft das Plugin mit den gespeicherten
  Einstellungen und schreibt `gcode/kicad-pcb2gcode.log`. wxPython
  installieren (Linux: `python3-wxgtk4.0`).
* **pcb2gcode lehnt eine Option ab** – dein pcb2gcode ist älter als 2.5.
  Aktualisieren oder die Option (z. B. *Kein M6*) im Reiter **Maschine**
  abwählen: abgewählte Optionen werden gar nicht erst geschrieben.

## Entwicklung

```
python -m pip install pytest
python -m pytest            # Unit-Tests und ein kompletter Lauf mit Test-Doubles
python scripts/install.py --link   # Arbeitskopie per Symlink in KiCad einbinden
python scripts/package.py          # Release-Zip bauen
```

Der Code liegt in `plugin/kicad_pcb2gcode/`: `settings` (Modell und JSON),
`millproject` (pcb2gcode-Konfiguration), `export` (kicad-cli-Befehle),
`job` (Ablauf), `kicad_bridge` (IPC-API), `gui` (wxPython-Fenster).

## Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE).

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
* **Isolation** – V-Bit (Winkel, Spitzenbreite; die effektive Schnittbreite
  bei der gewählten Tiefe wird berechnet) oder Schaftfräser, Tiefe, Vorschübe,
  Isolationsbreite und Überlappung, Voronoi-Modus.
* **Bohren** – Tiefe, Vorschub, verfügbare Bohrergrößen, große Löcher fräsen.
* **Kontur** – Fräser, Zustellung pro Durchgang, Haltestege.
* **Maschine** – G-Code-Dialekt und zusätzliche pcb2gcode-Optionen.

Die Voreinstellungen passen für eine kleine GRBL-Fräse (3018-Klasse) mit
30°-V-Bit und 1-mm-Fräser. **Prüfe die Werte immer gegen deine Werkzeuge und
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

### Doppelseitige Platinen

Bei **Beide Seiten** spiegelt pcb2gcode die Unterseite. Wie genau beide Seiten
zueinander passen, hängt von deiner Aufspannung ab. Bohre Passlöcher und teste
an einem Reststück, bevor du eine echte Platine fräst.

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

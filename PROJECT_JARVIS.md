# MindHome Assistant - Ausgelagert in eigenes Repository

> MindHome Assistant wurde in ein **eigenstaendiges Projekt** ausgelagert,
> da es auf einem separaten Server laeuft und eine eigene Codebasis hat.

## Neues Repository

```
GitHub: https://github.com/Goifal/mindhome-assistant
Lokal:  mindhome-assistant/   (in diesem Branch als Vorbereitung)
```

## Warum getrennt?

| MindHome | MindHome Assistant |
|----------|-------------------|
| Home Assistant Add-on | Eigenstaendiger Server |
| Laeuft auf HAOS (NUC) | Laeuft auf separatem PC |
| Python Add-on | Docker + FastAPI |
| HA Store Installation | git clone + install.sh |

## Verbindung

MindHome Assistant kommuniziert mit MindHome ueber die REST API im lokalen Netzwerk:

```
Assistant-PC  ──── REST API (<1ms LAN) ────>  Home Assistant + MindHome
```

## Quick Start (auf dem Assistant-PC)

```bash
# Option 1: Aus dem MindHome Assistant Repo (sobald auf GitHub)
git clone https://github.com/Goifal/mindhome-assistant.git
cd mindhome-assistant
./install.sh

# Option 2: Aus diesem Branch
cp -r mindhome-assistant ~/mindhome-assistant
cd ~/mindhome-assistant
./install.sh
```

## Vollstaendige Dokumentation

Siehe `mindhome-assistant/README.md` in diesem Branch oder das MindHome Assistant Repository.

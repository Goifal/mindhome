# Project Jarvis - Ausgelagert in eigenes Repository

> Jarvis wurde in ein **eigenstaendiges Projekt** ausgelagert,
> da es auf einem separaten Server laeuft und eine eigene Codebasis hat.

## Neues Repository

```
GitHub: https://github.com/Goifal/jarvis
Lokal:  jarvis-project/   (in diesem Branch als Vorbereitung)
```

## Warum getrennt?

| MindHome | Jarvis |
|----------|--------|
| Home Assistant Add-on | Eigenstaendiger Server |
| Laeuft auf HAOS (NUC) | Laeuft auf separatem PC |
| Python Add-on | Docker + FastAPI |
| HA Store Installation | git clone + install.sh |

## Verbindung

Jarvis kommuniziert mit MindHome ueber die REST API im lokalen Netzwerk:

```
Jarvis-PC  ──── REST API (<1ms LAN) ────>  Home Assistant + MindHome
```

## Quick Start (auf dem Jarvis-PC)

```bash
# Option 1: Aus dem Jarvis-Repo (sobald auf GitHub)
git clone https://github.com/Goifal/jarvis.git
cd jarvis
./install.sh

# Option 2: Aus diesem Branch
cp -r jarvis-project ~/jarvis
cd ~/jarvis
./install.sh
```

## Vollstaendige Dokumentation

Siehe `jarvis-project/README.md` in diesem Branch oder das Jarvis-Repository.

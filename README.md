# VoiceBuilder

Outil local d'**écriture et de production audio multi-voix** basé sur le moteur
**CosyVoice3** (`Fun-CosyVoice3-0.5B`).

Taguez un texte dans un éditeur Markdown, associez chaque réplique à une voix
(définie par un échantillon `.wav` + sa transcription `.txt`), puis générez un
montage dans lequel chaque personnage parle avec **son** timbre — sans perte de
contenu et avec une tonalité cohérente.

> Le moteur actif est **CosyVoice3** (multilingue : français, en, zh, ja…).
> CosyVoice2 reste trop faible en français (cf. `PROJET.md` §7).

---

## Architecture

```
VoiceBuilder/
├── PROJET.md        # brief produit (format, pipeline, contraintes)
├── TODO.md          # liste de tâches détaillée
├── ROADMAP.md       # jalons orientés produit
├── CHANGELOG.md     # historique des livrables
├── engine/          # backend — moteur CosyVoice + logique
│   ├── cosyvoice_engine.py  # wrapper AutoModel + zero_shot
│   ├── adaptive.py          # blocs adaptatifs vérifiés
│   ├── verifier.py          # vérification Whisper
│   ├── multi.py             # pipeline multi-voix
│   ├── voix.py              # voix.txt
│   ├── tagging.py           # parse du format taggé
│   └── config.py            # chemins + valeurs par défaut
├── app/
│   ├── server.py     # GUI : serveur HTTP local (FastAPI) + API REST/SSE
│   └── web/          # frontend statique (HTML/CSS/JS + éditeur CodeMirror)
├── voix/            # voix.txt + paires .wav/.txt
├── texte/           # documents taggés + <nom>.map (personnages→voix, CSV)
├── output/          # montages produits
└── tools/
    ├── gen_multi_voix.py    # CLI génération multi-voix
    └── create_voix.py       # assistant de création de voix
```

Le backend est exposé en bibliothèque (`engine/`), piloté indifféremment par une
CLI ou par la **GUI serveur FastAPI** (`app/server.py`, interface de référence),
le frontend Gradio (`app/web_app.py`) restant disponible en alternative.

---

## Prérequis

- Python 3.10+
- Les dépendances dans `requirements.txt` :
  `numpy`, `soundfile`, `librosa`, `openai-whisper`, `torch`.
- Le dépôt CosyVoice (`~/Projets/CosyVoice`) et son venv, contenant le modèle
  `Fun-CosyVoice3-0.5B`. Les chemins sont dans `engine/config.py`.

---

## Les voix (`voix/`)

Chaque voix = un couple de fichiers **définissant l'échantillon de référence** :

- **`.wav`** — échantillon à cloner (~5–30 s, sans musique).
- **`.txt`** — sa transcription exacte (format horodaté accepté : `[0000.00 - 0005.28] texte`).

Fichier de listage `voix/voix.txt`, une entrée par ligne :

```
# [NomVoix], wav, txt[, pause_pré][, vitesse]
[LeNarrateur],  superama_phrase_01.wav, superama_phrase_01.txt
[Thepromisedneverland],  Thepromisedneverland_phrase_01.wav, …phrase_01.txt
[Thepromisedneverland_2], Thepromisedneverland_phrase_02.wav, …phrase_02.txt
[Thepromisedneverland_3], Thepromisedneverland_phrase_03.wav, …phrase_03.txt
```

Si plusieurs fichiers portent le même nom, ils sont automatiquement **numérotés**
(`Nom`, `Nom_2`, `Nom_3`, …) pour rester tous sélectionnables.

Au clonage, le prompt TTS =
`"You are a helpful assistant.<|endofprompt|>" + texte_du_txt`.

### Où ranger les fichiers .wav / .txt

Le dossier contenant les **fichiers `wav`/`txt`** des voix se configure via la
variable d'environnement `VOICEBUILDER_AUDIO_DIR` (défaut : `~/Partages/voice`).

```bash
export VOICEBUILDER_AUDIO_DIR=~/Partages/voice   # par exemple
python -m tools.gen_multi_voix texte/x.md
```

Les chemins listés dans `voix.txt` sont alors résolus, dans l'ordre, parmi :
`PROJECT_ROOT`, `voix/` (racine du projet), puis `VOICEBUILDER_AUDIO_DIR`
(cf. `config.VOIX_SEARCH_DIRS`).

---

## Personnages & voix (mapping par document)

Le texte se balise par **personnage** (`[Narrateur]: …`), et chaque personnage
peut être associé à une voix. Le mapping est défini dans une **modal
« Personnages »** (un bouton par personnage apparaît dans la barre d'outils) et
sauvegardé **par document** dans `texte/<nomdutexte>.map` (CSV) :

```
voix,personnage
Astronogeek,Narrateur
Gmilgram,Roi
```

À la génération, chaque réplique est lue par la voix de son personnage (résolu
silencieusement par le moteur).

## Format du texte taggé

- **Attribution de réplique** — en tête de ligne `[Personnage]: texte`.
- **Prose / locuteur courant** — une ligne sans balise est lue par la voix en
  cours (dernier personnage cité) ; **aucune ligne de contenu n'est ignorée**.
- **Tags non-verbaux** — conservés inline (`[sigh]`, `[question-en]`, …).
- `[stop]` — arrête la génération (le reste est ignoré).
- Lignes vides et `#` — commentaires, hors montage.

---

## Usage

### GUI serveur (interface de référence — FastAPI)

```bash
python -m app.server --host 0.0.0.0 --port 8000
# puis ouvrir http://127.0.0.1:8000
```

L'éditeur est **plein écran** : barre d'outils avec un bouton par personnage,
ouverte de documents (projet ou **fichier local**), boutons **＋ Nouveau** et
**💾 Enregistrer dans le projet**, réglages / aide / personnages en modales.
L'onglet **Montage** se débloque après une génération. Thème clair/sombre
via `🌙`.

### GUI web (Gradio — alternative)

```bash
python -m app.web_app --host 127.0.0.1 --port 7860
# puis ouvrir http://127.0.0.1:7860
```

Onglets : **Éditeur** (texte taggé + montage), **Réglages** (pause, vitesse,
taille de bloc, Whisper, `device`), **Assistant voix** (extraction +
transcription d'un extrait). Options CLI : `--host`, `--port`, `--share`.

### Génération multi-voix (M1, CLI)

```bash
python -m tools.gen_multi_voix texte/chapitre.md \
    -o output/montage.wav \
    --pause 0.45 --vitesse 1.0 --max-chars 260
```

Options : `--voix`, `--pause`, `--vitesse`, `--max-chars`, `--no-verify`,
`--texte-dir`.

### Création d'une voix (M2)

```bash
python -m tools.create_voix SOURCE.wav \
    --nom LeNarrateur --start 12.5 --stop 30
```

Extrait le segment, le transcrit avec Whisper, écrit le `.wav`+`.txt` dans `voix/`
et ajoute l'entrée dans `voix.txt`.

> Les exemples supposent d'utiliser l'interpréteur du venv CosyVoice
> (`~/Projets/CosyVoice/venv/bin/python`).

---

## Ressources

- `docs/UTILISATION.md` — guide d'utilisation complet (CLI, GUI, format de texte
  taggé, **tags non-verbaux / émotions CosyVoice3**).
- `PROJET.md` — brief complet (vision, pipeline, contraintes, étapes).
- `engine/tests` — (à venir) tests unitaires du pipeline.
- Moteur : `CosyVoice3` (voir `~/Projets/CosyVoice`).
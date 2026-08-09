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
│   └── web_app.py    # GUI web (Gradio)
├── voix/            # voix.txt + paires .wav/.txt
├── texte/           # projets d'écriture taggés
├── output/          # montages produits
└── tools/
    ├── gen_multi_voix.py    # CLI génération multi-voix
    └── create_voix.py       # assistant de création de voix
```

Le backend est exposé en bibliothèque (`engine/`), piloté indifféremment par une
CLI ou par la **GUI web** (`app/web_app.py`, Gradio).

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
# [NomPersonnage] wav, txt[, pause_pré][, vitesse]
[LeNarrateur],  Partages/voice/superama.wav, Partages/voice/superama.txt
[Michel],       Partages/voice/unirreductibleathee_phrase_01.wav,
                Partages/voice/unirreductibleathee_phrase_01.txt
[Kaël-An],      echantillons/kael_an.wav, echantillons/kael_an.txt
```

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

## Format du texte taggé

- **Attribution de réplique** — en tête de ligne `[Nom]: texte`.
- **Prose / narrateur** — une ligne sans marqueur reprend le locuteur précédent.
- **Tags non-verbaux** — conservés inline (`[sigh]`, `[question-en]`, …).
- `[stop]` — arrête la génération (le reste est ignoré).
- Lignes vides et `#` — ignorées.

---

## Usage

### GUI web (Gradio)

```bash
python -m app.web_app --host 127.0.0.1 --port 7860
# puis ouvrir http://127.0.0.1:7860
```

Onglets : **Éditeur** (texte taggé + montage), **Réglages** (pause, vitesse, taille
de bloc, Whisper, `device`), **Assistant voix** (extraction + transcription d'un
extrait). Options CLI : `--host`, `--port`, `--share`.

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
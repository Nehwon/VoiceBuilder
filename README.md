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
│   ├── text_fr.py           # normalisation des nombres en français
│   ├── adaptive.py          # blocs adaptatifs vérifiés
│   ├── verifier.py          # vérification Whisper
│   ├── multi.py             # pipeline multi-voix
│   ├── modeles.py           # téléchargement/détection du modèle
│   ├── voix.py              # voix.txt
│   ├── tagging.py           # parse du format taggé
│   └── config.py            # chemins + valeurs par défaut
├── app/
│   ├── server.py     # GUI : serveur HTTP local (FastAPI) + API REST/SSE
│   ├── web/          # frontend statique (HTML/CSS/JS + éditeur CodeMirror)
│   └── web_app.py    # GUI web Gradio (alternative)
├── scripts/         # entrypoint (Docker), setup, application des patches
├── patches/cosyvoice/  # patches locaux appliqués au moteur (sous-module)
├── voix/            # voix.txt (+ paires .wav/.txt hors git, voir §Voix)
├── texte/           # documents taggés + <nom>.map (CSV) + archives/
│   ├── brouillons/  # copies de travail (hors git)
│   └── archives/    # projets archivés (hors git)
├── output/          # montages produits
├── vendor/CosyVoice/  # moteur CosyVoice en sous-module git
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
  `numpy`, `soundfile`, `num2words`, `librosa`, `openai-whisper`, `torch` (+
  `torchaudio`, `torchvision`) pour le moteur ; `fastapi`/`uvicorn` pour la GUI
  serveur (référence) et `gradio` pour la GUI web alternative.
- Le moteur **CosyVoice** en **sous-module git** (`vendor/CosyVoice`, voir
  `TODO.md` §Phase 7) avec son venv et le modèle `Fun-CosyVoice3-0.5B`. Les
  chemins sont dans `engine/config.py`.

Pour récupérer le moteur après un clone :

```bash
git submodule update --init --recursive   # clone CosyVoice dans vendor/
./scripts/apply_cosyvoice_patches.sh      # ré-applique les patches locaux
./scripts/setup.sh                        # vérifie venv + modèle
```

### Le modèle CosyVoice3

Le modèle (~9,7 Go) n'est **pas** fourni avec le projet : il est téléchargé au
**premier lancement** depuis l'interface (panneau « 🧠 Modèles », source
ModelScope ou Hugging Face, avec progression) ou **pré-rempli** dans un volume /
dossier. Localement il est rangé dans
`vendor/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B` (réglable via
`COSYVOICE_MODEL_DIR`) ; en Docker il est monté dans le volume `volume-model`
(`/models`). S'il est déjà présent, il est détecté et rien n'est re-téléchargé.

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

> **Hors git** : les fichiers personnels `.wav`/`.txt` et les `.map` sont ignorés
> par `.gitignore` (`voix/*.wav`, `voix/*.txt` hors `voix.txt`) — seul
> `voix.txt` peut rester versionné à titre d'exemple. Les voix s'importent
> depuis l'interface (onglet **Projets** → 🎙️ Voix → 📥 Importer) ou via
> `POST /api/voix/importer` (multipart `wav` + `txt`/`transcription`). La suppression
> se fait depuis le même onglet (`POST /api/voix/supprimer`).

### Où ranger les fichiers .wav / .txt

Le dossier contenant les **fichiers `wav`/`txt`** des voix se configure via la
variable d'environnement `VOICEBUILDER_AUDIO_DIR` (défaut :
`~/Projets/Personnel (Fabrice)/vb-voice` ; en Docker : `/data/voice` via `volume-audio`).

```bash
export VOICEBUILDER_AUDIO_DIR=~/Projets/Personnel\ \(Fabrice\)/vb-voice
python -m tools.gen_multi_voix texte/x.md
```

Les chemins listés dans `voix.txt` sont alors résolus, dans l'ordre, parmi :
`PROJECT_ROOT`, `voix/` (racine du projet), puis `VOICEBUILDER_AUDIO_DIR`
(cf. `config.VOIX_SEARCH_DIRS`).

### Nettoyer une voix (retirer musique / bruit de fond)

Onglet **Projets** → 🎙️ Voix → bouton **« 🧹 Nettoyer »** sur un échantillon :
le fichier passe dans **Demucs** (extraction de la voix seule, la musique et
les autres voix sont retirées) puis **DeepFilterNet** (débruitage /
dé-réverbération). Une modale compare **avant / après** et permet d'**écraser
l'original** ou d'enregistrer une **nouvelle voix** (`<nom>_clean`) — la
transcription `.txt` est recopiée telle quelle.

Les modèles de nettoyage (~180 Mo au total) sont téléchargés au **premier
usage** dans `VOICEBUILDER_ENHANCE_DIR` (défaut : `engine/config.py`,
`enhance_models/` ; en Docker : `/models/enhance_models`, volume
`volume-model`). Demucs passe automatiquement de `cuda fp16` → `cuda fp32` →
`cpu` selon la VRAM disponible.

### Auditer les voix (curation Palier 0)

```bash
python tools/audit_voix.py [--voix NOM] [--sans-whisper]
```

Pour chaque entrée de `voix.txt` : durée (alerte hors 5–30 s), niveau/SNR,
silences dominants, écrêtage, plus **retranscription Whisper du prompt +
diff mot à mot vs `.txt`**. Verdict : `OK` / `à recurer` (txt) /
`à ré-extraire` (wav) / `à nettoyer` (bruit → bouton 🧹 ci-dessus).
`--sans-whisper` = mode rapide sans retranscription.

### Banc A/B de prompts (comparer les segments candidats)

```bash
python tools/bench_prompts.py [--personnage NOM] [--promouvoir]
```

Le paragraphe FR de référence (nombres, date, dialogue, 1 émotion
`<|HAPPY|>`) est synthétisé avec chaque segment candidat du personnage
(variantes `_2`/`_3`, versions `_clean`) : `coverage` Whisper + RTF + WAV
d'écoute dans `output/bench/<personnage>/`. `--promouvoir` fait du gagnant
la référence dans `voix.txt` (sauvegarde `voix.txt.bak`). Même banc dans
l'onglet **🎙️ Voix** (section « Banc A/B », écoute comparative + bouton
de promotion).

### Nettoyage en lot (curation Palier 0)

```bash
python tools/nettoyer_voix.py --tout [--voix NOM] [--promouvoir] [--forcer]
```

Applique le pipeline de nettoyage (Demucs + DeepFilterNet) à chaque voix :
produit `<tige>_clean.wav` (+ `.txt` recopié) et l'entrée `[Nom_clean]`
dans `voix.txt` (idempotent : `--forcer` pour refaire). Comparaison
avant/après (`coverage` Whisper + SNR, écoute des deux WAV côte à côte) ;
avec `--promouvoir`, les gagnants (contenu conservé + SNR non dégradée)
deviennent les références (backup `voix.txt.bak`).

### Kit dataset LoRA (Palier 1)

```bash
python tools/preparer_lora.py --voix NOM --audio long1.wav [long2.wav ...] [--tokens]
```

Depuis de longs enregistrements : segments 5–12 s, transcriptions (Whisper
ou `--text` corrigé), dédup, split train/dev, kaldi + `manifest.json` ;
`--tokens` produit parquet + speech tokens (format CosyVoice). Refuse
< 15 min effectives.

### Entraînement LoRA petit GPU (Palier 1)

```bash
python tools/entrainer_lora.py --dataset dataset/lora/<voix>/manifest.json --vram 12 --steps 300
```

Presets 12/16/24 Go (qLoRA, checkpointing, accumulation, optim 8-bit,
ZeRO-2 en filet) ; n'entraîne que le LLM ; reprise auto, courbe de perte,
registre par voix. D'abord 1 voix test (quelques centaines de steps).
Nécessite `peft` (+ `bitsandbytes` pour qLoRA/8-bit) ; ne pas entraîner
pendant que le serveur infère (12 Go).

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

### Normalisation française

Le texte est automatiquement converti en texte lisible à voix haute
(`engine/text_fr.py`, `num2words` `lang="fr"`) avant la synthèse. Le pipeline
gère les **nombres** (entiers, décimaux, pourcentages, ordinaux), **dates**
(ISO, slash, mois abrégés), **heures** (`14h30`), **abréviations** (`M.`,
`Dr`, `etc.`, `c.-à-d.`, `n°`…), **devises** (`€`, `$`, `£`), **chiffres
romains** (`IV`→4, `XLII`→42) et **ponctuation fine** (`…`, tirets, guillemets
typographiques). Sans cette normalisation, CosyVoice lisait les chiffres en
anglais (`spell_out_number`, désactivé par le patch CosyVoice `0003`).

---

## Usage

### GUI serveur (interface de référence — FastAPI)

```bash
python -m app.server --host 0.0.0.0 --port 8000
# puis ouvrir http://127.0.0.1:8000
```

L'éditeur est **plein écran** : 3 onglets **Éditeur** / **Montage** / **Projets**,
barre de documents réorganisée (sélecteur + Ouvrir / ＋ Nouveau / 📁 Fichier local /
💾 Enregistrer / 📥 Importer / 🗂️ Gérer), boutons personnage en toolbar,
réglages / aide / personnages en modales.

- **Onglet Éditeur** : CodeMirror avec surlignage `[Nom]:`, autocomplétion `Tab`,
  numéros de ligne, brouillon auto-sauvegardé dans `texte/brouillons/`.
- **Onglet Montage** : montage global (lecteur + **timeline cliquable** +
  **file de création visuelle** + journal replié) à gauche, **liste à ascenseur** de lecteurs par bloc à droite (texte + actions
  Régénérer/Diviser/**✕ Retirer**), écoute temps réel. Clic sur une carte ou un
  segment → lecture à partir de ce bloc (bloc en cours surligné) ; poignée ⠿
  pour réordonner les blocs (montage re-créé) ; bouton **⏹ Arrêter** pour
  interrompre proprement une génération (blocs déjà synthétisés conservés ;
  bouton ⏹ aussi sur la page Montage, avec progression ⏳ Bloc i/N ;
  l'arrêt prend effet dès la fin de la synthèse en cours, sans attendre
  la vérification).
  Option **Multi-prompt (×2 GPU)** dans les Réglages : chaque bloc est généré
  avec 2 segments candidats de la voix, le meilleur est gardé (utile sur les
  voix faibles).
  Pendant une génération, le bouton **Regénérer** d'un bloc déjà synthétisé le
  met en file : il est re-synthétisé après le bloc en cours, puis la
  génération globale continue.
  La **dernière génération** de chaque document est conservée
  (`output/.cache-<doc>.json` + WAV, volume Docker) et restaurée à
  l'ouverture — pas besoin de régénérer à chaque session ; bouton
  **🗑 Supprimer la génération** (avec confirmation `yes` + case à cocher)
  pour l'effacer.
  Un rechargement de page pendant une génération se rattache automatiquement
  au job en cours (éditeur, montage et progression restaurés).
- **Onglet Projets** : tableau de gestion des documents (taille, date, .map) avec
  actions **Ouvrir / Renommer / Dupliquer / Archiver / Supprimer**, section **📦 Archives**
  (Restaurer), zone **🎙️ Voix** (pré-écoute, suppression, 📥 Importer un couple
  `wav`+`txt`/transcription). Thème clair/sombre via `🌙`.

> **Projets personnels hors git** : `texte/*.md`/`*.map`/`*.txt` (hors `exemple_demo`)
> et `texte/brouillons/` / `texte/archives/` sont ignorés par `.gitignore` — seul
> `texte/exemple_demo.md` est versionné à titre d'exemple. L'import se fait via
> `📥 Importer` (barre ou onglet Projets, `POST /api/document/importer` multipart) ;
> la gestion complète passe par `GET /api/documents/details` et
> `POST /api/document/{supprimer,archiver,desarchiver,dupliquer,renommer}`.

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
> (`vendor/CosyVoice/venv/bin/python`).

---

## Déploiement en conteneur Docker (GPU)

Le moteur (sous-module `vendor/CosyVoice`) et le GUI FastAPI sont
**conteneurisables avec prise en charge GPU** (NVIDIA `nvidia-container-toolkit`) :
tous les dossiers de données utilisent des **volumes Docker nommés** (pas de bind
mounts hôte).

```bash
docker compose up --build        # serveur sur http://127.0.0.1:8000
```

- Les 5 volumes sont créés automatiquement : `volume-audio`, `volume-model`,
  `volume-texte`, `volume-output`, `volume-tmp`.
- `VOICEBUILDER_AUDIO_DIR=/data/voice` : les voix sont écrites directement dans
  `volume-audio` (writable depuis l'interface).
- `COSYVOICE_MODEL_DIR=/models` (volume `volume-model`) : vide au début,
  rempli par le panneau « 🧠 Modèles » au premier lancement, ou **pré-rempli**
  (si le volume contient déjà le modèle, il est détecté et rien n'est
  re-téléchargé).
- `COSYVOICE_MODEL_SOURCE` : `modelscope` (défaut) ou `huggingface`.

> - **GPU** : image CUDA 13 (torch `cu130`, wheels pip) construite dès le build ;
>   pas de base `nvidia/cuda` (NCCL système incompatible avec torch cu130).
>   `scripts/entrypoint.sh` ne sert plus que de **filet de sécurité** (réinstalle
>   torch/torchaudio/torchvision si l'un des trois manquait).
> - **Dossier des voix** : writable dans le conteneur via `volume-audio` ;
>   plus besoin de dossier hôte pré-rempli.
> - **Modèle CosyVoice3 (~9,7 Go)** : hors image — téléchargé automatiquement
>   la première fois depuis le panneau « 🧠 Modèles » (source ModelScope ou
>   Hugging Face, progression affichée), ou **pré-rempli** dans le volume
>   `volume-model` (détection : rien n'est re-téléchargé).
> - **Versionning** : chaque push sur `main` incrémente automatiquement le numéro
>   de version (M.m.f — Major uniquement sur demande explicite, mineur pour nouvelles
>   fonctionnalités, patch pour corrections). Voir `TODO.md` et le workflow
>   CI/CD `.github/workflows/docker-build.yml`.

Voir `Dockerfile` et `docker-compose.yml` ; les montages couvrent
`volume-audio`, `volume-texte`, `volume-output` et `volume-model` (modèle hors image,
détails `TODO.md` §Phase 7, M15). Les documents/voix personnels restent dans les
volumes et hors git ; un `docker compose down -v` supprime les volumes — prévoir
un export avant.

---

## Ressources

- `docs/UTILISATION.md` — guide d'utilisation complet (CLI, GUI, format de texte
  taggé, **tags non-verbaux / émotions CosyVoice3**).
- `PROJET.md` — brief complet (vision, pipeline, contraintes, étapes).
- `engine/tests` — (à venir) tests unitaires du pipeline.
- Moteur : `CosyVoice3` (voir `vendor/CosyVoice`).
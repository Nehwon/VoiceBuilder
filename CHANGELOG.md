# CHANGELOG — VoiceBuilder

Toutes les modifications notables de ce projet.

Le format suit les principes de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [Unreleased]

### Ajout — Version 0.5.0 (mineur) : nouvelles fonctionnalités
- **Wizard install** (interface web) : étape 1 installer torch/torchvision/torchaudio
  au runtime, étape 2 télécharger modèle CosyVoice3 (ModelScope/Hugging Face,
  progression SSE). Ces composants ne sont plus dans l'image Docker au build.
- **Versionning automatique** : chaque push `main` incrémente M.m.f automatiquement
  (Major sur demande explicite, mineur pour nouvelles fonctions, patch pour corrections).
  Workflow `.github/workflows/docker-build.yml` lit `VERSION`, analyse les fichiers
  modifiés, commit et build l'image Docker avec le bon tag.
- **Volumes Docker nommés** (pas de bind mounts) : `volume-audio`, `volume-model`,
  `volume-texte`, `volume-output`, `volume-tmp` — définis dans `docker-compose.yml`,
  créés automatiquement.
- **Entrée entrypoint** (`scripts/entrypoint.sh`) : installe torch au premier lancement
  si non présent, puis exécute la commande d'origine.
- **GUI** : nouvel onglet "Wizard install" pour guider l'utilisateur première fois.
- **API endpoints** : `GET /api/torch/status`, `POST /api/torch/install`,
  `GET /api/torch/install/{jid}/stream` pour suivre l'installation.
- **Dockerfile** : retrait de torch/torchaudio/torchvision du `RUN pip install` ;
  `ENTRYPOINT ["/app/scripts/entrypoint.sh"]` + `CMD ["python", "-m", "app.server", ...]`.

### Modification — Packaging & infra
- **CosyVoice en sous-module git** : intégré au projet (`vendor/CosyVoice`) au lieu
  d'un clone voisin ; `engine/config.py` pointe vers le sous-module.
- **Conteneur Docker avec GPU allégé** (M15) : `Dockerfile` (base `ubuntu:22.04`
  + Python 3.10, deps `requirements.txt`, moteur CosyVoice, Matcha-TTS) — torch
  CUDA retiré du build, installé au runtime. `docker-compose.yml` (services GUI/CLI,
  5 volumes nommés, GPU via `nvidia-container-toolkit`).
- **Modèles hors image** (Important) : modèle CosyVoice3 n'est pas embarqué —
  téléchargé par l'utilisateur depuis l'interface (panneau "Modèles" ou "Wizard
  install", source ModelScope/Hugging Face, progression SSE) dans le volume
  `volume-model` (inscriptible) ou dossier pré-rempli (`MODEL_DIR`).
- **CI/CD** : workflow GitHub Actions déplacé vers `.github/workflows/docker-build.yml`
  avec versionning automatique ; workflow Gitea vers `.gitea/workflows/docker-build.yml`.
- **GUI** — détection des balises `[Personnage]` du texte (ajoutées au modal
  "Personnages"), validation avant génération : aucun personnage ou personnage
  sans voix → erreur + ouverture modal.
- **Sauvegarde git** : `origin` pousse vers deux dépôts (gitea + GitHub
  `Nehwon/VoiceBuilder`, remote `backup`), conformément à `AGENTS.md`.
- **Modèles hors image** (Important) : le modèle CosyVoice3 n'est plus embarqué
  dans l'image Docker — téléchargé par l'utilisateur depuis l'interface (panneau
  "🧠 Modèles" ou "Wizard install", source ModelScope/Hugging Face, progression SSE)
  dans le volume inscriptible `volume-model` (ou dossier pré-rempli `MODEL_DIR`).
  Si le volume contient déjà le modèle, il est détecté et rien n'est re-téléchargé.
- **GUI** — nouvelle interface wizard install pour le premier lancement.

---

## [0.5.0] - 2026-08-14

### Ajourné — Packaging & infra
- **Versionning** : chaque push `main` incrémente M.m.f automatiquement.
- **Wizard install** : guide utilisateur première utilisation (torch + modèle).
- **Volumes Docker nommés** : remplacement des bind mounts par volumes nommés.
- **Entrée entrypoint** : installation torch au runtime.

---

## [0.4.0] - 2026-08-11

- Initial commit avec GUI FastAPI, CLI, format taggé, GUI Gradio.
- CosyVoice en sous-module, Docker GPU de base.
- Premier déploiement fonctionnel.
  plus attendu dans l'image Docker — téléchargeable au **premier lancement**
  depuis l'interface (« 🧠 Modèles », `engine/modeles.py`, source
  ModelScope/Hugging Face, progression SSE) dans le volume inscriptible
  `cov3-models` ou un dossier pré-rempli (`MODEL_DIR`). Détection automatique
  de présence (`GET /api/modeles`), `COSYVOICE_MODEL_DIR` réglable par env.
- **GUI Montage** — refonte de l'onglet « Montage » : montage global (lecteur +
  log) à gauche et **liste à ascenseur de lecteurs par bloc** à droite (une
  carte audio + texte complet + en-tête personnage/durée/voix + actions
  Régénérer/Diviser), en remplacement du sélecteur unique de bloc.
- **Écoute temps réel** — chaque bloc généré est immédiatement jouable dans
  l'onglet « Montage » sans attendre la fin de la génération complète
  (callback SSE `bloc` avec `wav` + `ajouterBlocTempsReel` côté frontend).
- Objectifs documentés dans `TODO.md` (§Phase 7, M14/M15, backlog cache/
  volumes/import-export), `ROADMAP.md`, `PROJET.md` et `README.md`.

## [0.4.0] — 2026-08-10

### Changement
- **GUI serveur FastAPI (Phase 3, M7)** — `app/server.py` (uvicorn) devient
  l'interface principale : sert le frontend statique (`app/web/`) + une API REST
  JSON, avec génération en tâche de fond et progression `SSE`. Gradio
  (`app/web_app.py`) reste disponible mais n'est plus l'interface de référence.
- **Personnages par document** — le texte porte désormais des balises
  **personnage** (`[Narrateur]:`) ; chaque personnage est associé à une voix via
  une **modal** (tableau Personnage | Voix). Le mapping est sauvegardé **par
  document** dans un fichier **`<nomdutexte>.map`** (CSV `voix,personnage`) posé
  dans `texte/`. La barre d'outils affiche un **bouton par personnage**.
- **Moteur** — `multi.generate(..., personnages=)` résout personnage→voix à la
  génération ; `load_voix`/`_lire_csv_mapping` relisent le `.map`. Balise
  cohérente : les lignes entre deux balises sont lues avec la voix en cours
  (aucune ligne de contenu ignorée).
- **UX frontend** — modales in-app pour Réglages, Aide et Personnages (plus
  aucune `alert()` navigateur) ; notifications en **toast** ; **thème clair par
  défaut** + bascule clair/sombre (choix mémorisé) ; **pied de page fixe** ;
  **lecteur/montage dans l'onglet « Montage »** (actif seulement après une
  génération) ; **éditeur plein cadre** s'arrêtant à 1 em du footer.
- **Gestion des documents** — ouverture d'un **fichier local**, boutons
  **＋ Nouveau** (document vierge) et **💾 Enregistrer dans le projet** (le
  contenu importé devient un document `texte/` avec copie de travail + `.map`).
- **`voix.txt`** — les noms en doublon sont automatiquement numérotés
  (`Nom`, `Nom_2`, `Nom_3`), rendant visibles les variantes d'une même voix.
- Frontend servi avec `Cache-Control: no-store` (pas d'assets obsolètes en cache).

## [0.3.0] — 2026-08-09

### Changement
- **GUI web (Gradio)** — `app/web_app.py` remplace la GUI native : onglets
  Éditeur / Réglages / Assistant voix, génération multi-voix via `engine/`.
- **Suppression** du backend **Go** (`gui/`, prototype Fyne) et de la GUI
  tkinter `app/gui.py` ; l'application web les remplace.
- `requirements.txt` : ajout de `gradio>=4.0`.
- Mise à jour de `README.md`, `PROJET.md` (§5 interface, §6 architecture) et
  `docs/UTILISATION.md` (§GUI web) pour refléter la GUI web.

## [0.2.0] — 2026-08-08

### Ajout
- **M4 — Raffinements UX** dans `app/gui.py` : autocomplétion (`Tab`), insertion de bloc 1-clic, gouttière de lignes, panneau « Réglages » (pause, vitesse, max chars, Whisper, `device`), génération non bloquante + export. `multi.generate` accepte `device`/`fp16` (plombés vers `cosyvoice_engine.load`).
- **Configuration du dossier des fichiers voix** — nouvelle variable d'environnement `VOICEBUILDER_AUDIO_DIR` (défaut `~/Projets/Personnel (Fabrice)/vb-voice`) via `config.VOIX_AUDIO_DIR` ; résolution des wav/txt élargie à `config.VOIX_SEARCH_DIRS`.
- **M3 — Maquette GUI** : `app/gui.py` (éditeur Markdown + surlignage, panneau des voix, génération multi-fil, pause).
- **Documentation** : `docs/UTILISATION.md` (CLI, GUI, format des voix, format taggé et section « Tags non-verbaux / émotions spécifiques à CosyVoice3 ») ; `TODO.md` et `ROADMAP.md` détaillés point par point (M3/M4) ; lien ajouté au `README.md`.
- `README.md`, `TODO.md`, `ROADMAP.md`, `CHANGELOG.md`.
- Dépôt git configuré (`origin` → `ssh://gitea@gitea.lamachere.fr:2222/fabrice/VoiceBuilder.git`, branche `main`) et livrable poussé.

## [0.1.0] — 2026-08-08

### Ajout — Fondations (M0 / M1 / M2)
- **`engine/config.py`** — chemins projet + moteur CosyVoice, valeurs par défaut (blocs, pause, vitesse, Whisper).
- **`engine/voix.py`** — chargement/parsing de `voix.txt` ; `Voice` (`.wav` + `.txt` de référence, prompt système), collection `Voices`.
- **`engine/tagging.py`** — parse du format taggé (`[Nom]:`, ligne nue → locuteur précédent, tags inline, `[stop]`) et `regrouper` (fusion des segments consécutifs d'un même locuteur).
- **`engine/adaptive.py`** — découpage en blocs adaptatifs (max `max_chars`) et régénération récursive d'un bloc incomplet après vérification.
- **`engine/verifier.py`** — transcription Whisper (FR) et couverture des mots attendus (seuil de vérif).
- **`engine/cosyvoice_engine.py`** — wrapper `AutoModel(Fun-CosyVoice3-0.5B)` + `inference_zero_shot`, sortie mono au `sample_rate` du moteur.
- **`engine/multi.py`** — pipeline : parse → regrouper → blocs adaptatifs vérifiés → concat + pauses → export WAV.
- **`tools/gen_multi_voix.py`** — CLI de génération d'un montage (texte + `voix.txt`).
- **`tools/create_voix.py`** — assistant de création de voix (extraction d'un segment, transcription Whisper, mise à jour de `voix.txt`).
- **`requirements.txt`** — dépendances du backend.

### Notes
- Moteur utilisé : **CosyVoice3** (`Fun-CosyVoice3-0.5B`, multilingue) ; venv et chemins du moteur issus de `~/Projets/CosyVoice`.

---

Les versions sont versionnées de façon sémantique (`MAJOR.MINOR.PATCH`) ; `0.x` =
phase initiale avant API stable.
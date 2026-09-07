# TODO — VoiceBuilder

Liste des tâches de développement. État au dernier avancement (voir `CHANGELOG.md`).

Légende :
- `[x]` fait · `[ ]` à faire · `[~]` en cours

---

## Phase 0 — Fondations du moteur (CosyVoice3)

- [x] **M0 — Structurer `engine/`** : portage de la logique validée.
  - [x] `config.py` : chemins projet + moteur, valeurs par défaut (blocs, pause, vitesse, Whisper).
  - [x] `voix.py` — chargement/parsing de `voix.txt` (wav + transcription `.txt`, options par voix).
  - [x] `adaptive.py` — découpage adaptatif en blocs + re-découpage vérifié.
  - [x] `verifier.py` — vérification par transcription Whisper (couverture des mots).
  - [x] `cosyvoice_engine.py` — wrapper `AutoModel(Fun-CosyVoice3-0.5B)`, `inference_zero_shot`, I/O wav.
- [x] **M1 — Pipeline multi-voix + CLI**
  - [x] `tagging.py` — parse du format taggé (`[Nom]:`, prose non attribuée, tags inline, `[stop]`).
  - [x] `multi.py` — parse → regrouper → blocs adaptatifs vérifiés → concat + pauses.
  - [x] `tools/gen_multi_voix.py` — CLI de génération d'un montage.
- [x] **M2 — Assistant de voix**
  - [x] `tools/create_voix.py` — extraction `[start,stop]`, transcription Whisper, écriture `voix/` + `voix.txt`.

---

## Phase 1 — Assistant de voix & fixtures

- [x] M2.1 — Option `--lang` pour Whisper, sortie horodatée (`[0000.00 - 0005.28] …`) en option.
- [x] M2.2 — Limite/alerte si le segment dépasse ~30 s (fidélité du clone).
- [x] M2.3 — Générer un CLI exemple (échantillon de test + `voix.txt` de démo) pour valider M0/M1 de bout en bout.

---

## Phase 2 — Interface graphique (GUI)

> Réalisé via le **GUI serveur FastAPI** (Phase 3/4) et le GUI Gradio (Phase 2.5) :
> l'ancien `app/gui.py` (tkinter) a été supprimé.
- [x] **M3 — GUI** : ouvrir un texte brut (`.md`/`.txt`), éditeur avec surlignage
      des `[Locuteur]:`, panneau des voix (liste + pré-écoute), génération avec
      progression + log par bloc, vérification et export.
- [x] **M4 — Affiner l'UX**
  - [x] **Autocomplétion des noms de voix** — touche `Tab` : complète `[Pré` → `[LeNarrateur]` (insensible à la casse) ; déclenchement uniquement après un `[`.
  - [x] **Insertion d'un bloc `[Nom]:` en un clic** — bouton « Insérer [Nom]: » (reprend la voix sélectionnée dans le panneau).
  - [x] **Numéros de ligne** — gouttière synchronisée avec le défilement de l'éditeur.
  - [x] **Réglages globaux** — panneau « Réglages » : pause, vitesse, max chars/bloc, vérification Whisper, `device` ; plomberie `device`/`fp16` → `multi.generate` → `cosyvoice_engine.load`.
  - [x] **Vérification / export** — génération en fil d'arrière-plan (UI non bloquée), statut + export du `.wav`.

### Documentation d'utilisation
- [x] `docs/UTILISATION.md` : CLI, GUI, voix (`voix.txt`), format de texte taggé.
  - [x] Section « Tags non-verbaux / émotions spécifiques à CosyVoice3 » (point par point : émotions `<|ÉMOTION|>`, sons paralinguistiques `[sigh]`, etc., événements audio, correspondance OmniVoice).
  - [x] `README.md` référence le guide ; `CHANGELOG.md` mis à jour.

---

## Phase 2.5 — GUI web (Gradio) & gestion du dossier des voix

- [x] **M6 — GUI web (Gradio)** (`app/web_app.py`) : éditeur de texte taggé, panneau
      des voix, génération multi-voix, réglages et assistant voix dans le navigateur.
- [x] **M6.1 — Réglage du dossier des voix** : choix du répertoire des fichiers
      `.wav`/`.txt` (`VOICEBUILDER_AUDIO_DIR`) côté UI, avec persistance.
- [x] **M6.2 — Auto-génération de `voix.txt`** : s'il est absent, le générer depuis le
      dossier configuré (une entrée par coupe `.wav` + `.txt`, nom par défaut déduit
      du nom de fichier).
- [x] **M6.3 — Nommage des voix existantes** : dans l'assistant voix, attribuer un
      `[Nom]` personnage aux voix déjà présentes dans le dossier (et non encore
      nommées) et l'écrire dans `voix.txt`.

---

## Phase 3 — GUI sur serveur HTTP local (FastAPI)

Refonte de l'interface web sur un **petit serveur HTTP local** avec un frontend
dédié (au lieu de Gradio) : serveur applicatif + pages statiques servies par ce
même serveur ; nginx/caddy seulement en reverse-proxy optionnel en face.

**Choix retenu : Python + FastAPI (uvicorn)** (proposé comme le meilleur) —
réutilise le venv CosyVoice et le moteur `engine/` en process, peu de dépendances
ajoutées, API REST typée avec génération en tâche de fond ; nginx ou caddy
n'apportent rien de nécessaire en local (pur statique/proxy, pas de logique Python).

- [x] **M7 — Squelette serveur FastAPI** (`app/server.py`) : sert le frontend
      statique (HTML/CSS/JS) + API REST JSON ; `--host`/`--port` en CLI.
- [x] **M7.1 — API voix** : `GET /api/voix` (liste + état), `POST /api/voix` (nommage,
      génération `voix.txt`), `GET /api/voix/<wav>` (pré-écoute).
- [x] **M7.2 — API génération** : `POST /api/generer` (texte taggé + réglages) en
      tâche de fond, progression via `SSE`, récupération du montage.
- [x] **M7.3 — Frontend éditeur** : **CodeMirror** avec surlignage `[Nom]:`,
      autocomplétion des voix (`Tab`), insertion d'un bloc 1-clic, numéros de ligne.
- [x] **M7.4 — Frontend réglages + dossier des voix** : dossier
      `VOICEBUILDER_AUDIO_DIR` réglable + persistance + génération auto de `voix.txt`.
- [x] **M7.5 — Compatibilité** : module venv `uvicorn`, `requirements`
      (+ `fastapi`, `uvicorn`), doc et script de lancement.

---

## Phase 4 — Gestion d'un document de projet (éditeur)

- [x] **M8 — Document de travail & auto-sauvegarde**
  - [x] **M8.1 — Ouvrir** un fichier du dossier projet (`.md`/`.txt`) dans
        l'éditeur ; toute modification fait l'objet d'un **enregistrement
        automatique** d'une **copie de travail** dans `texte/brouillons/` — sans
        jamais modifier le **fichier d'origine** (`POST /api/document/*`).
- [x] **M8.2 — Fichier des voix** :
  - [x] si `voix.txt` est absent, **vérifier que le dossier des voix** est
        configuré (`VOICEBUILDER_AUDIO_DIR`) ;
  - [x] si non configuré : afficher une **bannière d'erreur en haut de page** avec
        un **lien vers « Réglages »**, pour configurer le dossier ;
  - [x] à la configuration du dossier, **générer `voix.txt` dans le dossier du
        projet** ; si **plusieurs fichiers portent le même nom**, les **numéroter**
        (suffixe `_2`, `_3`, …).
- [x] **M8.3 — Gestion des projets (prochaine itération pratique, 2026-09-01)**
  - [x] **Barre de documents réorganisée** : sélecteur + Ouvrir / ＋ Nouveau /
        📁 Fichier local / 💾 Enregistrer / **📥 Importer** / **🗂️ Gérer** (`app/web/index.html:31`).
  - [x] **Onglet « Projets »** (`app/web/index.html:69`, `app/web/app.js:837`) :
        2 colonnes (documents + voix), tableau actifs (taille/date/.map/brouillon,
        `GET /api/documents/details`), actions **Ouvrir / Renommer / Dupliquer /
        Archiver / Supprimer**, section **📦 Archives** (Restaurer),
        voir `app/server.py:788-940`.
  - [x] **Contenus personnels hors git** : `texte/*.md`/`*.map`/`*.txt` (hors
        `exemple_demo`), `texte/brouillons/`, `texte/archives/`, `voix/*.wav`/`*.txt`
        (hors `voix.txt`) ignorés (`.gitignore:1`, `.dockerignore:1`). Import via
        `POST /api/document/importer` (multipart, `app/server.py:900`, limite 5 Mo).
  - [x] **Import/suppression des voix** : zone 🎙️ (liste + pré-écoute + suppression
        + 📥 Importer `wav`+`txt`/`transcription`), `POST /api/voix/importer` +
        `POST /api/voix/supprimer` (`app/server.py:945-1045`, modal `app/web/index.html:180`,
        `python-multipart` dans `requirements.txt`). Testé en conteneur.

---

## Phase 4.5 — Personnages & montage (production éditoriale)

> Le texte se balise par **personnage**, mappé à une voix, et le montage vit dans
> un onglet dédié.
- [x] **M9 — Mapping personnage → voix par document**
  - [x] La balise du texte porte le **personnage** (`[Narrateur]:`), associé à une
        voix via une **modal « Personnages »** (tableau Personnage | Voix).
  - [x] Un **bouton par personnage** dans la barre d'outils insère sa balise.
  - [x] Persistance **par document** dans `texte/<nomdutexte>.map` (**CSV**
        `voix,personnage`), relu à l'ouverture du document.
  - [x] `multi.generate(..., personnages=)` résout personnage→voix à la génération
        ; les lignes sans balise sont lues avec la voix en cours (aucune perte).
- [x] **M10 — Onglet « Montage »** : actif après une génération ; montage
      global (lecteur + log) à gauche et **liste à ascenseur de lecteurs par
      bloc** (une carte audio + texte + actions Régénérer/Diviser) à droite.
- [x] **M10.1 — Écoute temps réel** : chaque bloc généré est immédiatement
      jouable dans l'onglet « Montage » via SSE (callback `bloc`). Le payload
      porte `id`/`voix`/`texte` et l'audio est servi par l'API
      (`/api/generer/{id}/bloc/{bid}/wav`) — lecture possible dès la fin de
      chaque bloc, boutons Régénérer/Diviser opérationnels en direct.

---

## Phase 5 — Qualité & performance

- [x] **M4.x — Benchmark fidélité** (`tools/benchmark_fidelite.py`, `docs/BENCHMARK_FIDELITE.md`) :
      test de `max_chars` (150–1200) et du seuil Whisper (0.60–0.95). Résultat :
      `max_chars=600` (défaut) = meilleur compromis, seuil 0.85 = conservative mais sûr.
- [x] **M5 — Accélération CosyVoice3** (vLLM + TensorRT)
  - [x] **M5.1 — Activer vLLM pour le LLM** : passer `load_vllm=True` dans
        `cosyvoice_engine.load()` (`AutoModel`), activer le `gpu_memory_utilization`,
        mesurer le RTF pur de synthèse (hors vérif) avant/après.
  - [x] **M5.2 — Activer TensorRT pour le Flow (DiT)** : passer `load_trt=True`,
        générer le plan TRT au premier lancement (`convert_onnx_to_trt`),
        mesurer l'impact sur le RTF flow (10 pas Euler).
  - [x] **M5.3 — Benchmark comparatif** : mesurer RTF pur CosyVoice (synthèse
        seule, hors Whisper) pour chaque combinaison : PyTorch seul, +vLLM,
        +TRT, +vLLM+TRT. Résultat : RTF ~0.27 (baseline) vs ~0.27 (vLLM) —
        gain marginal sur textes courts (×1.03). Les options restent utiles pour
        textes longs / batch / haute concurrence. `docs/BENCHMARK_ACCEL.md`.
  - [x] **M5.4 — Intégration** : ajouter des options `--vllm` / `--trt` dans
        `cosyvoice_engine.load()`, `multi.generate()` et le GUI (panneau
        Réglages). Fallback automatique si vLLM/TRT indisponible.
  - [x] **M5.5 — Documentation** : `docs/BENCHMARK_ACCEL.md` (résultats M5.3),
        `PROJET.md` et `CHANGELOG.md` mis à jour.
- [x] **M5.x — Normalisation du texte FR** :
  - [x] **Nombres en français** (`engine/text_fr.py` + `num2words` `lang="fr"`,
        appliqué dans `cosyvoice_engine.synthesize` ; patch CosyVoice `0003`
        désactivant `spell_out_number` anglais) — les chiffres sont lus
        correctement en français à la génération.
  - [x] **Frontend FR complet** : dates (ISO, slash, mois abrégés), heures
        (14h30, 14:30), abréviations (M., Dr, etc., c.-à-d., n°, art.),
        devises (€, $, £, ¥), chiffres romains (IV, XII), ponctuation fine
        (…, —, guillemets typographiques). Tests unitaires (`tests/test_text_fr.py`).

---

## Phase 6 — Assistant voix avancé (extraction, éditeur wav, clonage)

> **M11 / M12 / M13 sont urgents.**

- [x] **M13.0 — Nettoyage des voix (pré-requis qualité)** (2026-09-02) :
      bouton « 🧹 Nettoyer » dans Projets → 🎙️ Voix ; pipeline **Demucs**
      (séparation vocale) puis **DeepFilterNet** (débruitage, CPU), écoute A/B,
      écraser ou enregistrer `<nom>_clean`. `engine/enhance.py`, API
      `/api/voix/nettoyer*` (SSE), modèles dans `/models/enhance_models`
      (`VOICEBUILDER_ENHANCE_DIR`), patch DeepFilterNet `df/io.py`
      (torchaudio ≥ 2.9). Intégré au build (`docker/vb/Dockerfile`).

- [ ] **M11 — Test bout en bout minimal**
  - [ ] Couvrir le scénario : **une phrase par balise, une voix par balise**,
        génération de la voix et **ouverture de l'espace de montage**.
- [ ] **M12 — Espace de montage**
  - [ ] Développer l'**espace de montage** (lecture de l'ensemble, navigation par
        bloc).
- [ ] **M13 — Onglet « Voix »**
  - [ ] **Extraction d'une piste son depuis une vidéo** (nouvel onglet « Voix »).
  - [ ] **Conversion de la piste au bon format `.wav`** (après upload).
  - [ ] **Éditeur de forme d'onde (style Audacity)** pour **extraire une voix
        (10–20 s)** depuis la piste convertie.
  - [ ] **Transcription d'un `.wav`** (extrait complet ou phrase unique) — Whisper.
  - [ ] **Synchroniser la transcription avec l'éditeur wav** pour une sélection
        efficace de l'extrait.
  - [ ] **Enregistrer la voix** sous forme d'un **couple `.wav` / `.txt`** pour le
        clonage (et mise à jour de `voix.txt`).

---

## Phase 7 — Packaging & infra (sous-module CosyVoice + Docker GPU)

> Objectif : intégrer **CosyVoice comme sous-module git du projet** (plus de clone
> voisin dans `~/Projets/CosyVoice`) et fournir un **conteneur Docker avec prise
> en charge GPU** pour déployer le moteur et le GUI FastAPI.

- [x] **M14 — CosyVoice intégré en sous-module git**
  - [x] Ajouter le dépôt CosyVoice comme sous-module du projet (`vendor/CosyVoice`).
  - [x] Pointer `engine/config.py` (`COSYVOICE_ROOT`) vers le sous-module (au lieu
        de `~/Projets/CosyVoice`).
  - [x] Documenter la récupération (`git submodule update --init --recursive` +
        `scripts/apply_cosyvoice_patches.sh`).
- [x] **M15 — Conteneur Docker avec GPU allégé**
  - [x] `Dockerfile` : base `ubuntu:22.04` + Python 3.10, deps (`requirements.txt`),
        moteur CosyVoice (sous-module), Matcha-TTS — **torch, torchvision, torchaudio
        réintégrés au build** (`requirements.txt`) ; `scripts/entrypoint.sh` reste un
        filet de sécurité (réinstallé si l'un des trois manquait).
  - [x] Accès GPU via `--gpus all` / `nvidia-container-toolkit` (device `cuda`).
  - [x] **5 volumes Docker nommés** (pas de bind mounts) : `volume-audio`,
        `volume-model`, `volume-texte`, `volume-output`, `volume-tmp` — définis dans
        `docker-compose.yml`, créé automatiquement au `docker compose up`.
  - [x] `docker-compose.yml` (services : serveur GUI `app.server`, CLI `cli`).
  - [x] **Téléchargement du modèle** : panneau « 🧠 Modèles » (source ModelScope/
        Hugging Face, progression SSE) dans le volume `volume-model` ; un ancien
        « Wizard install » (torch au runtime) a été simplifié car torch est au build.
  - [x] **Versionning automatique** : workflow CI/CD `.gitea/workflows/docker-build.yml`
        avec bump M.m.f automatique à chaque push `main` ; lecture `VERSION`, analyse
        des fichiers modifiés, mise à jour, commit, build image avec tag de version.
        Le CI GitHub (`.github/workflows/`) est désactivé (out of space dû à la taille
        des dépendances torch) ; GitHub ne sert plus que de backup du dépôt.
  - [x] Vérifier une génération complète dans le conteneur (génération multi-voix
        bout en bout validée sur GPU via `nvidia-container-toolkit`).
- [x] **Optimisation du build (images à 3 niveaux + CI fréquentiel)**
  - [x] **base** (`docker/base/Dockerfile`) : Ubuntu à jour + Python + torch/
        torchaudio/torchvision/torchcodec + packages nvidia-* (cu130). Générique,
        réutilisable pour d'autres projets torch/GPU. Compilée ~1×/semaine
        (`.gitea/workflows/base.yml`).
  - [x] **vb** (`docker/vb/Dockerfile`) : FROM base + venv + requirements.txt +
        requirements-lock.txt. Pré-requis spécifiques au projet. Compilée ~1×/jour
        (`.gitea/workflows/vb.yml`).
  - [x] **final** (`Dockerfile`) : FROM vb + code applicatif + patches CosyVoice.
        Compilée à la demande, au push (`.gitea/workflows/docker-build.yml`).
  - [x] **Skip si inchangé** : chaque job calcule un hash du contenu pertinent et
        vérifie via l'API Gitea si le tag `<niveau>-<hash>` existe déjà (scripts
        `scripts/ci/needs_rebuild.sh`) → skip du build si présent.
  - [x] **Purge du registre** : workflow cron hebdomadaire (`.gitea/workflows/purge.yml`)
        qui supprime les versions obsolètes tout en gardant les tags stables
        (latest, main, cu130) et les N récentes (`scripts/ci/purge_registry.sh`).
  - [x] `docker compose build base|vb` construit les niveaux ; `docker compose build`
        construit le final. Les builds quotidiens ne re-téléchargent plus torch.

---

## Backlog / Idées

- [ ] Vérification différée : transcrire le montage final en entier et signaler les pertes par segment.
- [ ] Pré-cache des prompts `wav+txt` par voix.
- [ ] Détection automatique des limites de segment (VAD) pour `create_voix`.
- [ ] Prévoir un warmup au démarrage du docker pour éviter une trop grande latence lors de la première inférence.

### Cache de la dernière génération

> Le logiciel doit **conserver la dernière génération** pour qu'une reprise de
> session ne force pas à régénérer tout le projet (mauvaise expérience).

- [ ] **M16 — Cache de génération par projet** : garder la dernière génération
      disponible, persistée et relue à l'ouverture du projet.
- [ ] Le cache n'est vidé que dans **deux cas** :
  1. l'utilisateur **demande une nouvelle génération** depuis la page d'édition ;
  2. l'utilisateur **supprime le cache du projet** via un bouton en barre de
     tâche, à droite d'« Enregistrer » : **« Supprimer la génération »**, avec un
     **modal de mise en garde** demandant de taper `yes` et de cocher une case
     « Je comprends que je vais tout supprimer ».

### Docker — volumes persistants

- [ ] Dans la définition du **conteneur Docker**, exposer un **volume** (en
      priorité) pour le cache de génération.
- [ ] **Conseiller** à l'utilisateur de mettre en place des volumes pour
      l'ensemble : **système** (modèles), **voix**, **projets** et **cache**.

### Import / export des configurations & volumes

- [ ] Fournir un moyen d'**importer / exporter** les configurations et les
      volumes : soit via **git**, soit en **fichier téléchargé**.
- [ ] Le volume **système** (modèles) n'est pas prioritaire (modèles
      retéléchargeables) ; pour le reste (**voix**, **projets**, **cache**),
      permettre d'ajouter un **dépôt git (GitHub, Gitea, GitLab)** pour une
      **sauvegarde automatique** ou / et un accès "google drive / nextcloud / etc." pour sauvegarder en archives.

### Important 
- [x] **Modèles hors image** : les modèles ne sont plus embarqués dans l'image
      Docker — ils sont **téléchargés par l'utilisateur depuis l'interface** au
      premier lancement (panneau « 🧠 Modèles », source ModelScope/Hugging Face,
      progression SSE) dans le volume `volume-model` (`/models`, inscriptible) ou un
      dossier pré-rempli. Si le volume contient déjà le modèle, il est
      détecté (`engine/modeles.py`, `GET /api/modeles`) et rien n'est
      re-téléchargé. `COSYVOICE_MODEL_DIR` reste réglable par env/Dockerfile.
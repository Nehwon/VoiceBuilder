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
- [x] **M10.2 — Barre d'outils « émotions » dans l'éditeur** : insérer en un clic
      les tokens CosyVoice3 (`docs/UTILISATION.md` §4, `PROJET_FINE.md` palier 0)
      directement dans le texte au curseur — émotions `<|HAPPY|>` / `<|SAD|>` /
      `<|ANGRY|>` / `<|NEUTRAL|>`, sons `[sigh]` / `[laughter]` / `[breath]` / …,
      emphase `<strong>` (entoure la sélection), ambiances
      `<|Laughter|>…<|/Laughter|>` / `<|Applause|>…` / `<|BGM|>…` ; rappel de
      sobriété (1 tag par bloc) dans l'aide.
  - [x] **Barre d'outils émotions** (`app/web/index.html:61-88`,
        `app/web/app.js` §« barre d'outils émotions ») : groupes modulaires
        `groupe-toolbar` (Émotions, Sons + sélecteur « autre… », Emphase,
        Ambiances) insérant les tokens au curseur ; emphase/ambiances autour de
        la sélection ; rappel sobriété ajouté à la modal d'aide.
  - [x] **Raccourcis clavier** : `Alt+1…4` émotions, `Alt+5…7` sons,
        `Alt+8` emphase, `Alt+9` ambiance rires (`extraKeys` CodeMirror, sans
        conflit avec `Tab`), visibles en infobulles et rappelés dans l'aide.
  - [x] **Forme façon GrapesJS (GridStack / Interact.js)** : chaque groupe de la
        barre d'outils (personnages, émotions, insertion `[Nom]:`) est un
        **bloc modulaire déplaçable / réordonnable par glisser-déposer**
        (inspiration GridStack : grille de blocs, Interact.js : gestes
        drag/resize), repliable, masquable ; disposition persistée côté client
        (ex. `localStorage`) et restaurée à l'ouverture.

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

- [x] **M11 — Test bout en bout minimal**
  - [x] Couvrir le scénario : **une phrase par balise, une voix par balise**,
        génération de la voix et **ouverture de l'espace de montage**.
        Tests (`tests/test_e2e_minimal.py`, 21 tests) : parsing, regroupement,
        découpage adaptatif, chargement voix, `multi.generate()` avec moteur
        mocké, callback progress, personnages→voix, bloc_dir, synth_bloc.
- [x] **M12 — Espace de montage** (2026-09-19)
  - [x] Développer l'**espace de montage** (lecture de l'ensemble, navigation par
        bloc) : offsets `start` par bloc (pause uniquement au changement de
        locuteur) dans `/blocs` + événements SSE, timeline cliquable (segments
        par bloc + curseur + chrono), clic carte/segment → lecture à partir du
        bloc, surlignage + défilement auto du bloc en cours, réordonnancement
        par glisser-déposer (`POST …/blocs/reordonner`), suppression en 2 clics
        (`POST …/bloc/{id}/supprimer`), re-concaténation serveur alignée sur la
        règle de pause de la génération.
- [x] **M13 — Onglet « Voix »**
  - [x] **Extraction d'une piste son depuis une vidéo** (nouvel onglet « Voix »).
  - [x] **Conversion de la piste au bon format `.wav`** (après upload).
  - [x] **Éditeur de forme d'onde (style Audacity)** pour **extraire une voix
        (10–20 s)** depuis la piste convertie.
  - [x] **Transcription d'un `.wav`** (extrait complet ou phrase unique) — Whisper.
  - [x] **Synchroniser la transcription avec l'éditeur wav** pour une sélection
        efficace de l'extrait.
  - [x] **Enregistrer la voix** sous forme d'un **couple `.wav` / `.txt`** pour le
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

## Phase 8 — Outillage Palier 0 (curation des voix, `PROJET_FINE.md` §2)

> Le Palier 0 (gratuit, sans entraînement) porte +30–50 % de qualité perçue :
> curation des prompts, nettoyage, transcriptions exactes, multi-prompt, tokens
> sobres, paramètres par voix. M13.0 (nettoyage unitaire) et M10.2 (barre
> d'outils émotions) couvrent déjà une partie ; il manque les outils de
> **diagnostic**, de **comparaison A/B** et de **traitement en lot**.

- [ ] **M17.1 — Audit qualité des voix (`tools/audit_voix.py`)**
  - [ ] Pour chaque entrée de `voix/voix.txt` : durée (alerte hors 5–30 s),
        niveau/SNR, silences dominants, écrêtage ; **retranscription Whisper
        du `.wav` prompt + diff mot à mot vs `.txt`** (mots divergents ou
        manquants = transcription à recurer, `PROJET_FINE.md` §2 point 3).
  - [ ] Rapport par voix : `OK` / `à recurer` (txt) / `à ré-extraire` (wav) /
        `à nettoyer` (bruit/musique → M13.0) ; sortie console + JSON
        (exploitable par la GUI plus tard).
- [ ] **M17.2 — Banc A/B de prompts par personnage**
  - [ ] Générer le **même paragraphe FR de référence** (nombres, dates,
        dialogue, 1 émotion — cf. `PROJET_FINE.md` §3.4) avec **2–3 segments
        candidats** par personnage (ex. variantes `_2`/`_3`, versions
        `_clean`) : `coverage` Whisper + RTF + écoute comparative
        (`PROJET_FINE.md` §2 point 1).
  - [ ] CLI (`tools/bench_prompts.py`) d'abord, puis section GUI (onglet Voix
        ou Montage) ; le gagnant devient la référence dans `voix.txt`.
- [ ] **M17.3 — Nettoyage en lot des 14 voix**
  - [ ] Appliquer le pipeline M13.0 (Demucs + DeepFilterNet) à toutes les voix
        en une commande (`tools/nettoyer_voix.py --tout`), produire les
        `<nom>_clean`, comparer avant/après (`coverage` + écoute) et promouvoir
        les gagnants en référence dans `voix.txt`
        (`PROJET_FINE.md` §2 point 2).
- [ ] **M17.4 — Multi-prompt à la génération**
  - [ ] Permettre **N prompts candidats par voix** (réutiliser les variantes
        `_2`/`_3`/`_clean` existantes comme candidats, sans casser le format
        `voix.txt`) : chaque bloc est généré avec chacun, le meilleur est gardé
        (`coverage` Whisper puis écoute) ; repli sur le prompt unique si 1 seul
        candidat (`PROJET_FINE.md` §2 point 4).

---

## Phase 9 — Palier 1 : LoRA CosyVoice3 sur petit GPU (`PROJET_FINE.md` §3)

> Fine-tuner 1–3 personnages vedettes **sans GPU 24 Go** : entraînement LoRA
> tenant sur **12–16 Go** (qLoRA, checkpointing, accumulation, optim 8-bit,
> freeze partiel, échelle anti-OOM), puis validation aveugle et intégration
> à l'inférence.

- [ ] **M18.1 — Kit dataset LoRA (`tools/preparer_lora.py`)**
  - [ ] Depuis les segments curés du Palier 0 (M17.1–M17.3) : 15–60 min/voix,
        segments 5–12 s (pic VRAM réduit), transcriptions exactes, dédup, split
        val ; sortie au format attendu par `vendor/CosyVoice/tools/` (parquet
        list + tokens) ; refuser < 15 min effectives (gain marginal vs
        zéro-shot, cf. `PROJET_FINE.md` §3.2).
- [ ] **M18.2 — Entraînement LoRA « petit GPU » (`tools/entrainer_lora.py`)**
  - [ ] Presets `--vram 12/16/24` appliquant l'échelle anti-OOM
        (`PROJET_FINE.md` §3.3) : rang, qLoRA 4-bit, gradient checkpointing,
        micro-batch 1 + accumulation, optim 8-bit/paged, freeze Flow, ZeRO-2 /
        offload CPU en filet ; reprise sur checkpoint, logs + courbe de perte.
  - [ ] D'abord 1 voix test (15–30 min, quelques centaines de steps) avant le
        full ; documenter l'étage OOM retenu par voix.
- [ ] **M18.3 — Validation + registre des LoRA**
  - [ ] Protocole `PROJET_FINE.md` §3.4 (paragraphe FR de référence,
        `coverage` ≥ 0.85, RTF, écoute aveugle à 2+ auditeurs) ; ne garder que
        les LoRA gagnants ; registre (poids, config, étage OOM, scores).
- [ ] **M18.4 — Intégration inférence (switch par personnage)**
  - [ ] Chargement dynamique base 0.5B + LoRA du personnage courant (PEFT,
        fusion optionnelle), cache des adaptateurs (alternance rapide des
        personnages), sans régression RTF ; documenter quel LoRA sert quelle
        voix de `voix.txt`.

---

## Phase 10 — Multi-moteurs : workers locaux / distants (`PROJET_FINE.md` §4)

> Ajouter des moteurs spécialisés qualité (**XTTS-v2, puis Fish-Speech v1.5+**)
> **sans remplacer CosyVoice3** : abstraction worker commune, routage par voix,
> **workers installables sur différentes machines pour chaque type de calcul**
> (synthèse GPU, vérif, enhance, audit, entraînement), avec un mode **CPU-only**
> (2 serveurs bi-Xeon 128 Go RAM, sans GPU). Le pipeline (blocs adaptatifs,
> vérif Whisper, montage, GUI) est réutilisé à l'identique.

- [ ] **M19.0 — Bench hors GUI avant toute intégration**
  - [ ] Comparer **XTTS-v2 puis Fish-Speech v1.5+** vs CosyVoice3 curé (Palier 0)
        sur le paragraphe FR de référence (`PROJET_FINE.md` §3.4 : nombres,
        dates, dialogue, 1 émotion) : `coverage` ≥ 0.85, RTF, écoute aveugle ;
        n'intégrer que sur victoire mesurée. Trancher au passage le point
        licence **XTTS-v2 = CPML** (usage commercial restreint) avant d'investir.
  - [ ] Calibrer en même temps le **RTF CPU-only de référence** sur les bi-Xeon
        (par moteur et par tâche) pour dimensionner le mode batch (M19.5).
- [ ] **M19.1 — Abstraction worker moteur + routage par voix**
  - [ ] Interface commune `synthesize(texte, prompt_wav, prompt_text, speed)`
        (même signature que `cosyvoice_engine.synthesize`, injectable comme
        `SynthesizeFn` dans `adaptive.py`) ; wrappers `engine/xtts_engine.py`
        **puis `engine/fishspeech_engine.py`**.
  - [ ] **Rôles de workers par type de calcul** (un rôle = déployable seul sur
        n'importe quelle machine) : `synthese` (CosyVoice3 / XTTS-v2 /
        Fish-Speech), `verify` (Whisper), `enhance` (Demucs + DeepFilterNet),
        `audit` (M17.1), `lora-train` (M18.2) ; chaque worker s'annonce
        (rôle, moteur, VRAM/CPU, version de modèle) au coordinateur.
  - [ ] Colonne `moteur` dans `voix.txt` (défaut `cosyvoice3`, rétrocompatible) ;
        `multi.generate()` dispatche chaque bloc vers le bon worker ; panneau
        « 🧠 Modèles » étendu au téléchargement/détection des modèles par
        moteur et par machine.
- [ ] **M19.2 — Cohérence du montage multi-moteurs**
  - [ ] Resample + alignement de loudness par bloc (sample rates / niveaux
        différents selon moteur), sinon les changements de voix s'entendent ;
        non-régression sur montage témoin.
  - [ ] Adapter `create_voix`/import au format de prompt par moteur (XTTS :
        wav seul 6–30 s sans `.txt` ; Fish-Speech : avec/sans texte de
        référence).
- [ ] **M19.3 — Placement multi-GPU local (1 moteur / GPU)**
  - [ ] Un processus worker par moteur, chacun avec son `CUDA_VISIBLE_DEVICES`
        (ex. CosyVoice → `cuda:0`, XTTS → `cuda:1`) : isolation des OOM,
        redémarrage indépendant, **génération en parallèle** (zéro switch) ;
        repli chargement/déchargement séquentiel sur GPU unique.
- [ ] **M19.4 — Workers distants (autres machines, GPU ou CPU)**
  - [ ] Adressage réseau des workers (`http://machine-b:8001`, token d'auth,
        TLS hors LAN de confiance) ; file de jobs + retries/timeouts, warmup au
        démarrage, **épinglage des versions de modèles** entre machines,
        fan-in SSE vers le GUI ; **presets de déploiement par machine**
        (ex. `gpu-synth`, `cpu-service`, `cpu-batch`, `lora-train`).
- [ ] **M19.5 — Mode CPU-only (2× bi-Xeon 128 Go, sans GPU)**
  - [ ] Preset `cpu-only` : `verify` (Whisper, voire modèle supérieur au
        `small` puisque la RAM le permet), `enhance` (DeepFilterNet léger ;
        Demucs en batch), `audit`, préparation datasets — tous à l'aise sur
        Xeon ; plusieurs workers par serveur (128 Go RAM : modèles + cache).
  - [ ] Synthèse CPU (CosyVoice / XTTS / Fish-Speech) : RTF ≫ 1 assumé —
        **batch de nuit uniquement**, pas d'interactif ; thread pools torch
        réglés (intra/inter-op), quantification/ONNX à évaluer par moteur si
        le RTF batch reste trop lent.
  - [ ] Ordonnancement : la GUI envoie le batch le soir, les Xeon traitent la
        nuit (synthèse + vérif + enhance), résultats prêts au matin ; suivi
        via la file de jobs (M19.4).
- [ ] **M19.6 — Cache applicatif explicite VRAM ↔ RAM (offload maîtrisé)**
  - [ ] Principe repris (pas de swapping transparent subi) : **le programme
        décide ce qui réside en VRAM** — placement explicite des couches
        (GPU/CPU), pool de staging pinned **limité** (8–32 Go sur 128 Go, jamais
        de pinned massif = pression mémoire), transferts async là où le moteur
        les expose, préchargement du prochain worker pendant le calcul courant.
  - [ ] Limite d'applicabilité honnête : CosyVoice3 / XTTS-v2 / Fish-Speech sont
        **denses, pas MoE** — il n'y a pas de granularité « experts » à cacher
        (pas de « 4 experts actifs sur 128 ») ; l'offload utile ici = couches
        statiques vers CPU, quantification, ZeRO-offload (entraînement, M18.2),
        `--gpu-layers` là où supporté. **Pas de réimplémentation maison d'un
        cache d'experts.**
  - [ ] 3 tiers pour la bibliothèque de modèles/LoRA (bi-Xeon 128 Go) : NVMe
        (stockage froid) → RAM mmap (backing store chaud) → VRAM (actif).
  - [ ] Bench décisionnel : RTF offload vs full-GPU par moteur/tâche — si le
        transfert PCIe dépasse le calcul (cas typique des denses en inférence),
        réserver l'offload à l'entraînement/stockage et garder l'inférence
        full-GPU ou CPU-batch (M19.5).

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
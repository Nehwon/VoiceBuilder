# CHANGELOG — VoiceBuilder

Toutes les modifications notables de ce projet.

Le format suit les principes de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [Unreleased]

### Ajout — Cache de génération par projet M16

- **Serveur** (`app/server.py`) : dernière génération persistée par document
  (`output/.cache-<doc>.json` + WAV, volume `volume-output`) à la fin du job
  et à chaque retouche ; `GET /api/cache/{doc}` restaure un job réutilisable
  par tous les endpoints montage ; `DELETE /api/cache/{doc}` efface manifeste
  + fichiers + jobs mémoire. Nouvelle génération → ancien cache effacé.
- **GUI** : relecture automatique à l'ouverture du document (montage + blocs
  restaurés) ; bouton **« 🗑 Supprimer la génération »** à droite
  d'« Enregistrer », modale exigeant de taper `yes` + case à cocher.
- Test d'intégration `TestClient` vert (persistance, relecture, mutations,
  2 cas de vidage).

### Ajout — Régénération empilée pendant la génération (file-regen)

- **Moteur** (`engine/multi.py`) : `generate()` accepte `file_regen` (file
  d'ids de blocs). Après chaque bloc (et après le dernier), la file est
  dépilée : chaque bloc déjà généré est re-synthétisé aussitôt et **remplace**
  l'audio précédent dans le montage (event `progress` avec `regen: True`,
  même `id`) ; ids futurs ignorés, file abandonnée si arrêt demandé.
- **API** (`app/server.py`) : `POST /api/generer/{jid}/bloc/{bid}/regenerer-file`
  (409 si pas en cours, 400 si bloc pas encore généré, déduplication) ;
  `progress` met à jour en place, le stream SSE transmet l'event sans
  décaler les offsets.
- **GUI** (`app/web/`) : le bouton « Regénérer » d'une carte live met le bloc
  en file (« En file… », log 🔁 à la régénération) ; carte, durée, timeline
  et offsets recalculés sans reconstruire la liste. La zone « Log de
  génération » devient une **file de création visuelle** (pastilles par bloc :
  en attente → en cours (pulsation) → terminé, 🔁 si régénération demandée,
  flash à la régénération, barré si abandonné ; journal texte replié en
  dessous).

### Ajout — Espace de montage M12 (timeline, navigation, réordre/suppression)

- **API** (`app/server.py`) : offsets `start` par bloc (pause uniquement au
  changement de locuteur) dans `GET /api/generer/{jid}/blocs` + événements SSE
  `bloc` ; `_reconcat` factorisé (re-concaténation alignée, sans silence
  final) ; `POST …/blocs/reordonner` (`{ids}`, 400 si incohérents) et
  `POST …/bloc/{id}/supprimer` (404 si inconnu).
- **Arrêt propre** : `POST /api/generer/{jid}/arret` + bouton **⏹ Arrêter** —
  le bloc en cours se termine, les blocs partiels sont conservés et écoutables.
- **GUI** (`app/web/`) : **timeline cliquable** (segments par bloc + curseur +
  chrono), clic carte/segment → lecture à partir du bloc, surlignage +
  défilement auto du bloc en cours, réordonnancement par glisser-déposer
  (poignée ⠿), suppression en 2 clics.
- Test d'intégration `TestClient` vert (offsets, réordre, suppression, 400/404).

### Ajout — Audit qualité des voix M17.1 (Palier 0)

- **`tools/audit_voix.py`** : pour chaque entrée de `voix.txt` — durée (alerte
  hors 5–30 s), niveau/SNR, silences dominants, écrêtage ; retranscription
  Whisper (`small`, FR) + diff mot à mot vs `.txt` (horodatages ignorés).
  Options `--voix NOM`, `--sans-whisper`. Verdicts `OK` / `à recurer` /
  `à ré-extraire` / `à nettoyer` (→ M13.0), sortie console.
- Audit réel des 14 voix : 11 OK, 1 à recurer, 2 à ré-extraire (silence ≥ 60 %).

### Ajout — Banc A/B de prompts M17.2 (Palier 0)

- **`engine/bench.py`** : paragraphe FR de référence (nombres, date, dialogue,
  `<|HAPPY|>`), groupement des candidats par personnage (variantes `_2`/`_3`,
  `_clean`), bench (`coverage` Whisper + RTF + WAV d'écoute), promotion du
  gagnant dans `voix.txt` (backup `voix.txt.bak`).
- **`tools/bench_prompts.py`** : CLI (`--personnage`, `--promouvoir`, `--device`,
  WAV dans `output/bench/<personnage>/`).
- **API + GUI** : job bench en tâche de fond (`candidats`/`lancer`/`{jid}`/
  `/wav`/`promouvoir`), section « Banc A/B » dans l'onglet 🎙️ Voix (sélecteur,
  tableau résultats, écoute comparative, bouton de promotion).
- Bench réel Thepromisedneverland : couv 96/91/87 %, gagnant = base.

### Ajout — Nettoyage en lot M17.3 (Palier 0)

- **`tools/nettoyer_voix.py`** (`--tout`/`--voix`, `--promouvoir` opt-in,
  `--forcer`, `--mode`) : pipeline M13.0 par voix → `<nom>_clean` (wav + txt
  + entrée `voix.txt`, idempotent) ; comparaison avant/après (`coverage`
  Whisper + SNR via `audit_voix`) ; promotion des gagnants (contenu conservé
  + SNR non dégradée) via `bench.promouvoir()`.
- Run réel : 14 voix, 8 clean gagnants, 6 originaux conservés (mot perdu
  détecté sur Gmilgram) ; 12 personnages multi-candidats pour M17.2.

### Ajout — Onglet Voix : extraction audio, waveform, transcription (M13)

- **`engine/audio_extract.py`** : module backend pour l'extraction audio depuis
  vidéo (ffmpeg), la génération de données waveform (pics d'amplitude), et le
  découpage de segment en WAV.
- **API** (`app/server.py`) : 6 nouveaux endpoints :
  - `POST /api/voix/extraire-audio` — upload vidéo → piste audio WAV mono 24 kHz.
  - `GET /api/voix/waveform` — pics d'amplitude pour rendu graphique.
  - `GET /api/voix/wav-raw` — sert un fichier WAV brut (WaveSurfer).
  - `POST /api/voix/decouper` — découpe un segment [start, stop].
  - `POST /api/voix/transcrire-segment` — transcription Whisper + horodatages.
  - `POST /api/voix/enregistrer` — enregistre couple wav+txt et met à jour `voix.txt`.
- **Frontend** (`app/web/`) : nouvel onglet « Voix » avec upload vidéo/audio,
  éditeur WaveSurfer.js v7 (régions drag+resize), transcription Whisper éditable,
  formulaire d'enregistrement.
- **Vendor** (`app/web/vendor/`) : WaveSurfer.js 7 + plugins Regions/Timeline.
- **Tests** (`tests/test_audio_extract.py`) : 13 tests. Total : 96 tests (tous passent).

### Ajout — Benchmark de fidélité (M4.x)

- **`tools/benchmark_fidelite.py`** : script automatisé testant systématiquement
  l'impact de `max_chars` (150–1200) et du seuil Whisper (0.60–0.95) sur la
  couverture, le nombre de blocs et le temps de génération.
- **`tools/benchmark_verify.py`** : script dédié au test vérif ON vs OFF.
- **`docs/BENCHMARK_FIDELITE.md`** : rapport détaillé avec recommandations.
  Résultats clés : `max_chars=600` (défaut) = meilleur compromis (4 blocs,
  95.7% couverture, 37 s) ; vérif ON = RTF ×2.4 vs OFF (re-split améliore
  performance ET qualité) ; seuil 0.85 = conservative mais sûr.
- **`engine/config.py`** : commentaires mis à jour avec les résultats du
  benchmark (sweet spot, validation des seuils).

### Ajout — Accélération CosyVoice3 (vLLM + TensorRT, M5)

- **`engine/cosyvoice_engine.py`** : `load()` accepte `load_vllm` et `load_trt`
  (passés à `AutoModel`). Fallback automatique si `vllm` ou `tensorrt` non
  installés (warning + continuation en PyTorch pur).
- **`engine/multi.py`** : `generate()` propage `load_vllm`/`load_trt` vers
  `cosyvoice_engine.load()`.
- **`engine/config.py`** : ajouts `DEFAULT_VLLM = False`, `DEFAULT_TRT = False`.
- **CLI** (`tools/gen_multi_voix.py`) : options `--vllm` et `--trt`.
- **GUI** (`app/web/index.html`) : cases à cocher « vLLM (LLM) » et
  « TensorRT (Flow) » dans le panneau Réglages.
- **API** (`app/server.py`) : `GenererIn` accepte `load_vllm`/`load_trt`,
  transmis à `multi.generate()`.
- **Benchmark M5.3** (`tools/benchmark_accel.py`, `docs/BENCHMARK_ACCEL.md`) :
  RTF ~0.27 (baseline PyTorch) vs ~0.27 (vLLM) vs ~0.27 (TRT) — gain marginal
  sur textes courts (×1.03). vLLM/TRT utiles pour textes longs (> 1000 chars),
  batch ou haute concurrence.

### Ajout — Normalisation française prosodie (M5.x)

- **`engine/text_fr.py`** : pipeline complet de normalisation du texte français
  pour la synthèse TTS, en 7 étapes :
  1. **Dates** : ISO (`2026-09-04`), barre oblique (`04/09/2026`), point
     (`04.09.2026`), mois abrégés (`4 sept. 2026`) → « quatre septembre
     deux mille vingt-six ».
  2. **Heures** : `14h30`, `14:30`, `8h`, `14h30min` → « quatorze heures trente ».
  3. **Abréviations** : 30+ patterns (titres `M.`/`Mme`/`Dr`/`Pr`, académique
     `etc.`/`c.-à-d.`/`p. ex.`, admin `n°`/`art.`/`tél.`, unités `hab.`/`env.`)
     → formes complètes, casse préservée.
  4. **Devises** : `€`/`$`/`£`/`¥` + codes (`EUR`/`USD`/`GBP`/`JPY`/`CHF`/`CAD`/`AUD`)
     → « dix euros », décimales incluses.
  5. **Chiffres romains** : `IV`→4, `XLII`→42, `CMXCIX`→999 (vérification
     stricte, min. 2 caractères, max. 3999).
  6. **Ponctuation** : `…`→`...`, tirets `–`/`—` espacés, guillemets
     typographiques `« »`.
  7. **Nombres** : entiers, décimaux, milliers espacés, pourcentages, ordinaux
     → mots français (`num2words`).
- **Tests** : `tests/test_text_fr.py` — 62 tests unitaires couvrant chaque
  catégorie de normalisation.
- L'API (`cosyvoice_engine.synthesize`) applique `text_fr.normalize()` sur le
  texte et le prompt avant `inference_zero_shot`, sans changer l'interface.

### Ajout — Test bout en bout minimal (M11)

- **`tests/conftest.py`** (nouveau) : fixtures partagées — voix temporaires
  (WAV sinusoïdale + transcription), mock du moteur CosyVoice (`load`/`synthesize`/
  `save`) et de la vérification Whisper, sans GPU requis.
- **`tests/test_e2e_minimal.py`** (nouveau) : 21 tests couvrant le pipeline
  complet :
  - **Parsing** (7 tests) : `parse_texte` + `regrouper` (balises, lignes nues,
    tags inline `[sigh]`, `[stop]`, texte vide, personnage inconnu).
  - **Adaptive** (3 tests) : `split_sentences`, `build_blocks` (court, long).
  - **Voix** (3 tests) : `load_voix` (2 voix, wav+txt, erreur manquante).
  - **multi.generate()** (7 tests) : scénario M11 minimal (2 personnages,
    1 phrase chacun, sortie WAV valide), callback progress, sans sortie,
    personnages→voix (M9), voix introuvable, bloc_dir, verify=False.
  - **synth_bloc** (1 test) : régénération d'un bloc isolé.

### Ajout — Nettoyage des voix (Demucs + DeepFilterNet)

- **Bouton « 🧹 Nettoyer »** dans Projets → 🎙️ Voix (`app/web/app.js`) :
  nettoie un échantillon en arrière-plan puis ouvre une **modale A/B**
  (avant/après) pour **Écraser l'original** ou **Enregistrer une nouvelle voix**
  (`_clean`). La transcription `.txt` reste inchangée.
- **`engine/enhance.py`** (nouveau) : pipeline **Demucs** (htdemucs,
  séparation vocale, retire la musique/les autres voix) puis **DeepFilterNet**
  (`df`, modèle DeepFilterNet3, débruitage/dé-réverbération sur CPU pour ne pas
  concurrencer CosyVoice sur le GPU). Demucs tente **cuda fp16 → cuda fp32 →
  CPU** avec repli automatique en cas d'OOM ; les modèles (~80 Mo + ~100 Mo)
  sont téléchargés au premier usage dans le volume `/models/enhance_models`
  (`VOICEBUILDER_ENHANCE_DIR`, `engine/config.py:ENHANCE_MODEL_DIR`).
- **API** : `POST /api/voix/nettoyer` (job + progression SSE), `/dispo`,
  `GET /api/voix/nettoyer/{id}/wav` (A/B), `POST …/ecraser` et
  `POST …/sauver_clean` (`app/server.py`). Garde-fous : refus si génération ou
  nettoyage déjà en cours (`409`), dépendances absentes → `501`.
- **Build** : `demucs==4.1.0` installé normalement ;
  `deepfilternet==0.5.6` en `--no-deps --ignore-installed` (il exige
  `packaging<24`, incompatible avec l'image) + ses libs runtime
  (`docker/vb/Dockerfile`). **Patch DeepFilterNet** (`scripts/patch_deepfilternet.py` +
  `scripts/setup_enhance.sh`) : remplace `torchaudio.backend.common`
  (supprimé de torchaudio ≥ 2.9) par `soundfile` dans `df/io.py`.

### Ajout — Gestion des projets (documents) + import voix

- **Onglet « Projets »** (`app/web/index.html:69`, `app/web/style.css:312`) : nouveau
  onglet à côté d'Éditeur/Montage, en 2 colonnes (documents + voix). Tableau des
  documents actifs avec **taille / date / .map / brouillon** (`GET /api/documents/details`,
  `app/server.py:788`) et actions **Ouvrir / Renommer / Dupliquer / Archiver / Supprimer**
  (`POST /api/document/{supprimer,archiver,desarchiver,dupliquer,renommer}`, `app/server.py:810-940`).
  Section **📦 Archives** (`texte/archives/`) avec **Restaurer** (`POST /api/document/desarchiver`).
  Barre de documents réorganisée (`#barre-doc`) : sélecteur + Ouvrir / ＋ Nouveau /
  📁 Fichier local / 💾 Enregistrer / **📥 Importer** / **🗂️ Gérer** (vers Projets).
- **Import de documents** : bouton `📥 Importer` (barre + Projets) via
  `POST /api/document/importer` (multipart, `app/server.py:900`, limite 5 Mo, évite
  l'écrasement par suffixe `_2`). Détection auto personnages → modal si voix manquante.
- **Import/suppression des voix** (`app/server.py:945-1045`) : zone 🎙️ Voix dans Projets,
  pré-écoute, suppression (`POST /api/voix/supprimer`), import d'un couple
  `.wav` + `.txt`/transcription (`POST /api/voix/importer`, multipart, `app/web/app.js:930`,
  modal `app/web/index.html:180`). `voix.txt` mis à jour côté serveur.
- **Hors git** : `.gitignore:1` exclut désormais les contenus personnels
  (`texte/*.md`/`*.map`/`*.txt` hors `exemple_demo`, `texte/brouillons/`, `texte/archives/`,
  `voix/*.wav`/`*.mp3`/`*.txt` hors `voix.txt`) ; `.dockerignore:1` aligné. Seul
  `exemple_demo.md`/`voix.txt` restent versionnés. `requirements.txt:12` ajoute
  `python-multipart` pour les uploads.
- **Docs** : `README.md:16` (architecture + §Voix/§Projets), `PROJET.md:1` (§5/§6/§8),
  `ROADMAP.md:1`, `TODO.md:1` mis à jour.

### Correction — Docker (modèle, voix, dépendances)
- **torch/torchaudio/torchvision réintégrés au build** : de retour dans
  `requirements.txt` (image CUDA 13 complète au build) ; `scripts/entrypoint.sh`
  ne sert plus que de **filet de sécurité** (vérifie les 3 imports, sinon réinstalle
  torch `cu130`).
- **Téléchargement du modèle corrigé** (`engine/modeles.py`) : gestion de la
  progression via des barres tqdm sous-classées (fini `progress_callback` et
  `get_lock`), staging dans le volume cible + `shutil.move` (fini
  `Invalid cross-device link`), barre de progression dans le panneau « 🧠 Modèles ».
- **Dossier des voix invalide → repli** : `app/server.py` et `app/web_app.py`
  replient sur le dossier par défaut si le chemin persisté n'existe plus ;
  `voicebuilder_settings.json` est exclu de l'image (`.dockerignore`) et désindexé
  de git (`.gitignore`).

### Correction — Moteur & logs
- **Patch CosyVoice `0002`** : `logging.DEBUG` → `INFO` dans
  `cosyvoice/utils/file_utils.py` — fin du spam de logs numba/SSA dans
  `docker compose logs` (appliqué au build via `apply_cosyvoice_patches.sh`).

### Correction — GUI : blocs écoutables en direct
- **Payload SSE `bloc` complet** (`engine/multi.py`) : chaque bloc porte désormais
  `id`, `voix`, `texte` — les cartes « Blocs générés » s'affichent toutes (plus de
  doublon `data-id="undefined"`) avec le bon en-tête.
- **Audio servi via l'API** (`app/web/app.js`) : le lecteur d'un bloc utilise
  `/api/generer/{id}/bloc/{bid}/wav` au lieu du chemin conteneur — chaque bloc est
  écoutable immédiatement après sa génération, boutons Regénérer/Diviser actifs.
- **Blocs « trop grands » corrigés** (`engine/multi.py`) : un groupe de
  personnage entier (ex. un chapitre d'un seul narrateur) devenait un bloc géant
  (118 s / 5,7 Mo). Chaque **sous-bloc adaptatif** (`adaptive.build_blocks`,
  ≤ `max_chars`, défaut 600) est désormais un bloc à part entière (wav + texte +
  id + progression), avec pause uniquement au changement de personnage.

### Correction — Moteur : robustesse & nombres en français
- **Normalisation française des nombres** (`engine/text_fr.py`, nouveau) : avant
  la synthèse, les nombres du texte et du prompt sont convertis en **mots
  français** (`num2words`, `lang="fr"`) — `600` → « six cents », `7,7` →
  « sept virgule sept », `2 290` → « deux mille deux cent quatre-vingt-dix »,
  `H100` → « H cent », `CO2` → « CO deux », `1er`/`4e` → « premier »/« quatrième »,
  `85 %` → « quatre-vingt-cinq pour cent ». Jusqu'alors `frontend.py` lisait les
  chiffres en **anglais** via la lib `inflect` (`spell_out_number`).
- **Patch CosyVoice `0003`** (`patches/cosyvoice/0003-disable-english-spell-out-number.patch`) :
  désactive `spell_out_number` dans `cosyvoice/cli/frontend.py` — plus aucune
  re-conversion anglaise des chiffres après notre normalisation.
- **`requirements.txt`** : ajout de `num2words>=0.5.12`.
- **Génération concurrente protégée** (`engine/cosyvoice_engine.py`,
  `app/server.py`) : verrou (`threading.Lock`) autour de la construction
  d'`AutoModel` (fini l'erreur « Cannot copy out of meta tensor ») + réponse
  `409` si une génération est déjà en cours.

---

## [0.5.0] - 2026-08-14

### Ajout — Packaging & infra
- **Versionning** : chaque push `main` incrémente M.m.f automatiquement.
- **Wizard install** : guide utilisateur première utilisation (torch + modèle).
- **Volumes Docker nommés** : remplacement des bind mounts par volumes nommés.
- **Entrée entrypoint** : installation torch au runtime.

---

## [0.4.0] - 2026-08-11

- Initial commit avec GUI FastAPI, CLI, format taggé, GUI Gradio.
- CosyVoice en sous-module, Docker GPU de base.
- Premier déploiement fonctionnel.
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
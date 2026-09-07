# ROADMAP — VoiceBuilder

> Feuille de route orientée **objectifs de produit**, du moteur à la GUI.
> L'état détaillé par tâche est dans `TODO.md` ; l'historique des livrables
> dans `CHANGELOG.md`.

---

## Vision (rappel)

Outil local d'**écriture et de production audio multi-voix** : taguer un texte
dans un éditeur Markdown, associer chaque réplique à une voix définie par une paire
`.wav` + `.txt`, puis générer un montage dans lequel chaque personnage parle avec
**son** timbre — sans perte de contenu, avec une tonalité cohérente.

Moteur : **CosyVoice3 (Fun-CosyVoice3-0.5B)** — clonage zéro-shot `wav+txt`,
multilingue, découpage en blocs adaptatifs + vérification automatique (Whisper).

---

## Jalons

### M0 — Refonte du moteur en package
**Objectif** : porter la logique validée dans `~/Projets/CosyVoice` dans un
package `engine/` réutilisable, pilotable par CLI ou GUI.
**Livrable** : `engine/{config, voix, adaptive, verifier, cosyvoice_engine}.py`.
**Statut** : ✔ Terminé.

### M1 — Génération multi-voix (CLI)
**Objectif** : produire un montage depuis `texte/x.md` + `voix/voix.txt` sur le
moteur CosyVoice, sans perte de texte.
**Livrable** : `tools/gen_multi_voix.py`.
**Statut** : ✔ Terminé.

### M2 — Assistant de création de voix
**Objectif** : créer une voix en une commande (extraction d'un segment +
transcription Whisper + mise à jour de `voix.txt`).
**Livrable** : `tools/create_voix.py`.
**Statut** : ✔ Terminé (raffinements M2.1–M2.3 à suivre, voir TODO).

### M3 — Première maquette GUI
**Objectif** : import de texte, éditeur Markdown surlignant les `[Nom]`, panneau
des voix, génération + pré-écoute par bloc.
**Livrable** : `app/gui.py`.
**Statut** : ✔ Terminé.

### M4 — Raffinements UX
**Objectif** : rendre l'édition et la génération confortables (autocomplétion,
réglages, vérification).
**Statut** : ✔ Terminé.

Parcours fonctionnel (point par point) :
- **Autocomplétion** — touche `Tab` dans l'éditeur : `[Pré` → `[LeNarrateur]`
  (préfixe insensible à la casse, une seule voix plausible).
- **Insertion rapide** — bouton « Insérer [Nom]: » ajoute le bloc de la voix
  sélectionnée au panneau droit.
- **Gouttière de lignes** — numéros synchronisés avec le défilement.
- **Réglages** — boîte de dialogue : pause, vitesse, taille max de sous-bloc,
  activation Whisper, `device` (cuda/cpu). `device`/`fp16` sont transmis au
  moteur (`multi.generate` → `cosyvoice_engine.load`).
- **Génération non bloquante** — fil d'arrière-plan + file d'attente, statut et
  boîte de fin, export du montage `.wav`.

Avec la **documentation d'utilisation** (`docs/UTILISATION.md`), dont la partie
**« Tags non-verbaux / émotions spécifiques à CosyVoice3 »** détaillée point par
point.

### M7/M8 — GUI sur serveur HTTP local (FastAPI)
**Objectif** : remplacer l'interface par un petit serveur local (Python+FastAPI)
servant un frontend dédié + une API REST, avec une vraie gestion du document de
projet (auto-sauvegarde d'une copie de travail, bannière si dossier des voix manquant).
**Livrables** : `app/server.py`, `app/web/` (frontend CodeMirror, modales, thème
clair/sombre), endpoints `/api/*` (voix, config, generation SSE, documents).
**Statut** : ✔ Terminé.

### M9/M10 — Personnages & montage (production éditoriale)
**Objectif** : baliser le texte par **personnage** et associer chaque personnage à
une voix, le mapping étant persistant **par document** (fichier `.map`, CSV) ;
monter le résultat dans un **onglet « Montage »** dédié.
**Livrables** : modal « Personnages », bouton par personnage dans la barre
d'outils, `multi.generate(personnages=)`, `app/server.py` (`/api/document/personnages`),
onglet « Montage » (montage global + **liste à ascenseur de lecteurs par bloc**
: une carte audio + texte + actions Régénérer/Diviser).
**Statut** : ✔ Terminé.

### M5 — Performance & normalisation FR
**Objectif** : réduire le temps de génération via vLLM ou TensorRT ; pipeline de
normalisation française pour la prosodie.
**Statut** : ✔ Terminé — vLLM/TensorRT activables (`--vllm`/`--trt`), gains
marginaux sur textes courts mais utiles en batch/concurrence ; **normalisation
FR complète** (`engine/text_fr.py`) : dates, heures, abréviations, devises,
chiffres romains, ponctuation fine, nombres → mots (`num2words`). Tests
unitaires (`tests/test_text_fr.py`, 62 tests).

### M8.3 — Gestion des projets (prochaine itération pratique)
**Objectif** : réorganiser la barre de documents et fournir un onglet dédié pour
gérer les projets en cours (supprimer, archiver/désarchiver, dupliquer, renommer,
importer), hors git (contenus personnels ignorés).
**Livrables** : onglet **« Projets »** (`app/web/index.html:69`, `app/web/app.js:837`),
barre `#barre-doc` réorganisée, API `GET /api/documents/details` +
`POST /api/document/{supprimer,archiver,desarchiver,dupliquer,renommer,importer}`
(`app/server.py:788-940`), `texte/archives/` + `texte/brouillons/` hors git.
**Statut** : ✔ Terminé (2026-09-01) — tableau actifs + archives, modales de confirmation.

### M13.0 — Import des voix (pré-requis création de voix)
**Objectif** : permettre l'import facile des voix (couple `wav` + `txt`/transcription)
avant l'onglet complet de création de voix (extraction vidéo, éditeur onde).
**Livrables** : zone 🎙️ dans l'onglet Projets, `POST /api/voix/importer` (multipart)
+ `POST /api/voix/supprimer` (`app/server.py:945-1045`), modal `app/web/index.html:180`,
`voix/*.wav`/`*.txt` hors git (`.gitignore:22`), `python-multipart` ajouté.
**Statut** : ✔ Terminé (2026-09-01) — pré-écoute, suppression, import testé en conteneur.

### M13 — Onglet Voix (extraction audio, waveform, transcription)
**Objectif** : permettre la création complète d'une voix depuis une vidéo :
upload vidéo → extraction piste audio → éditeur waveform avec sélection de
segment (10–20 s) → transcription Whisper → enregistrement couple wav+txt.
**Livrables** : `engine/audio_extract.py` (extraction ffmpeg, waveform, découpage),
6 endpoints API, onglet « Voix » dans le frontend (upload, WaveSurfer.js v7 avec
régions, transcription, formulaire d'enregistrement), 13 tests unitaires.
**Statut** : ✔ Terminé (2026-09-07) — 96 tests au total.

### M11 — Test bout en bout minimal
**Objectif** : couvrir le scénario de base (1 phrase/balise, 1 voix/balise,
génération audio, montée en montage) sans GPU via mocks du moteur CosyVoice.
**Livrables** : `tests/conftest.py` (fixtures voix temporaires, mock
cosyvoice/verifier) + `tests/test_e2e_minimal.py` (21 tests : parsing,
adaptive, voix, `multi.generate()`, progress callback, personnages→voix,
bloc_dir, synth_bloc).
**Statut** : ✔ Terminé — 83 tests au total (62 text_fr + 21 e2e).

### M14/M15 — Packaging & infra (sous-module CosyVoice + Docker GPU)
**Objectif** : intégrer **CosyVoice comme sous-module git du projet** (`vendor/CosyVoice`,
fini le clone voisin dans `~/Projets/CosyVoice`) et fournir un **conteneur Docker avec
prise en charge GPU** (nvidia-container-toolkit) pour le moteur et le GUI
FastAPI, portable sur toute machine équipée d'un GPU NVIDIA.
**Livrables** : sous-module `vendor/CosyVoice` + `engine/config.py` ajusté ;
`Dockerfile` + `docker-compose.yml` (5 **volumes nommés** : `volume-audio`,
`volume-model`, `volume-texte`, `volume-output`, `volume-tmp`) ; génération
complète validée dans le conteneur.
**Statut** : M14 ✔ terminé · M15 ✔ terminé — image buildée, **génération multi-voix
bout en bout validée dans le conteneur** sur GPU (NVIDIA `nvidia-container-toolkit`,
torch `cu130` au build). **Modèle hors image** : téléchargé au premier lancement
depuis l'interface (panneau « 🧠 Modèles », `engine/modeles.py`, volume `volume-model`
→ `/models`) ou **pré-rempli** dans le volume (détection : rien n'est re-téléchargé).
Tous les dossiers de données utilisent des **volumes Docker nommés** (`volume-audio`,
`volume-model`, `volume-texte`, `volume-output`, `volume-tmp`).

---

## Critères de succès (définition de « done »)

- **0 texte perdu** : la retranscription de l'audio contient intégralement le
  texte d'entrée (vérification automatique).
- **Ruptures de ton minimale** : le nombre de blocs est aussi faible que possible.
- **Identité vocale** : chaque personnage porte un timbre reconnaissable et
  stable.
- **UX fluide** : d'un texte brut à un montage multi-voix complet en quelques clics.
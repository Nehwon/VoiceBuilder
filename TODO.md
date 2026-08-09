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

- [ ] **M3 — Première maquille** (`app/gui.py`).
  - [ ] Import d'un texte brut (`.md`/`.txt`) et création du fichier de voix si absent.
  - [ ] Éditeur Markdown : surlignage des `[Locuteur]:`, tags inline, prose narrateur.
  - [ ] Panneau des voix : liste depuis `voix.txt`, pré-écoute du `.wav`, lancement de `create_voix`.
  - [ ] Bouton génération multi-voix : progression + log par bloc (personnage, durée, nb sous-blocs).
  - [ ] Verdict. : blocs revérifiés / rapprochés, pré-écoute par segment, export.
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

- [ ] **M6 — GUI web (Gradio)** (`app/web_app.py`) : éditeur de texte taggé, panneau
      des voix, génération multi-voix, réglages et assistant voix dans le navigateur.
- [ ] **M6.1 — Réglage du dossier des voix** : choix du répertoire des fichiers
      `.wav`/`.txt` (`VOICEBUILDER_AUDIO_DIR`) côté UI, avec persistance.
- [ ] **M6.2 — Auto-génération de `voix.txt`** : si absent, le générer depuis le
      dossier configuré (une entrée par coupe `.wav` + `.txt`, nom par défaut déduit
      du nom de fichier).
- [ ] **M6.3 — Nommage des voix existantes** : dans l'assistant voix, attribuer un
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

- [ ] **M7 — Squelette serveur FastAPI** (`app/server.py`) : sert le frontend
      statique (HTML/CSS/JS) + API REST JSON ; `--host`/`--port` en CLI.
- [ ] **M7.1 — API voix** : `GET /api/voix` (liste + état), `POST /api/voix` (nommage,
      génération `voix.txt`), `GET /api/voix/<wav>` (pré-écoute).
- [ ] **M7.2 — API génération** : `POST /api/generer` (texte taggé + réglages) en
      tâche de fond, progression via `SSE`/`websocket`, récupération du montage.
- [ ] **M7.3 — Frontend éditeur** : codeMirror/textarea avec surlignage `[Nom]:`,
      autocomplétion des voix, insertion d'un bloc 1-clic, gouttière de lignes.
- [ ] **M7.4 — Frontend réglages + dossier des voix** : parité @M6.1–M6.2 (dossier
      `VOICEBUILDER_AUDIO_DIR` réglable + persistance + génération auto de `voix.txt`).
- [ ] **M7.5 — Compatibilité** : config `server` (module venv `uvicorn`), `requirements`
      (+ `fastapi`, `uvicorn`), doc et script de lancement.
- [ ] (option) Déploiement derrière **nginx/caddy** en reverse proxy — non bloquant.

---

## Phase 4 — Qualité & performance

- [ ] M4.x — Benchmark fidélité : loi variation de `max_chars`, seuil de vérif.
- [ ] M5 — (optionnel) accélération vLLM (~0.9–0.11) ou TensorRT pour la génération.
- [ ] M5.x — Frontend de normalisation (`wetext`/`ttsfrd`) pour améliorer la prosodie FR (sinon `text_frontend=False`).

---

## Backlog / Idées

- [ ] Vérification différée : transcrire le montage final en entier et signaler les pertes par segment.
- [ ] Pré-cache des prompts `wav+txt` par voix.
- [ ] Détection automatique des limites de segment (VAD) pour `create_voix`.
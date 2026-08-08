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

- [ ] M2.1 — Option `--lang` pour Whisper, sortie horodatée (`[0000.00 - 0005.28] …`) en option.
- [ ] M2.2 — Limite/alerte si le segment dépasse ~30 s (fidélité du clone).
- [ ] M2.3 — Générer un CLI exemple (échantillon de test + `voix.txt` de démo) pour valider M0/M1 de bout en bout.

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

## Phase 3 — Qualité & performance

- [ ] M4.x — Benchmark fidélité : loi variation de `max_chars`, seuil de vérif.
- [ ] M5 — (optionnel) accélération vLLM (~0.9–0.11) ou TensorRT pour la génération.
- [ ] M5.x — Frontend de normalisation (`wetext`/`ttsfrd`) pour améliorer la prosodie FR (sinon `text_frontend=False`).

---

## Backlog / Idées

- [ ] Vérification différée : transcrire le montage final en entier et signaler les pertes par segment.
- [ ] Pré-cache des prompts `wav+txt` par voix.
- [ ] Détection automatique des limites de segment (VAD) pour `create_voix`.
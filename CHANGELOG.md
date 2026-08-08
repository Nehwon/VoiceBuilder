# CHANGELOG — VoiceBuilder

Toutes les modifications notables de ce projet.

Le format suit les principes de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [0.2.0] — 2026-08-08

### Ajout
- Documentation produit : `README.md`, `TODO.md`, `ROADMAP.md`, `CHANGELOG.md`.
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
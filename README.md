# 🎙️ VoiceBuilder

![moteur](https://img.shields.io/badge/moteur-OmniVoice-7b5cff)
![audio](https://img.shields.io/badge/audio-24_kHz_natifs-00b894)
![français](https://img.shields.io/badge/fran%C3%A7ais-qualit%C3%A9_9%2F10-blue)
![docker](https://img.shields.io/badge/docker-GHCR-2496ED)
![gpu](https://img.shields.io/badge/gpu-NVIDIA_CUDA-76b900)

Outil local d'**écriture et de production audio multi-voix** : on tague un texte
dans un éditeur Markdown, on associe chaque réplique à une voix (un échantillon
`.wav` + sa transcription `.txt`), et on génère un montage où chaque personnage
parle avec **son** timbre — sans perte de contenu, avec une tonalité cohérente.

> ✅ **Choix fixé (2026-10-07) : moteur unique OmniVoice** (`k2-fsa/OmniVoice`).
> Le bench comparatif (texte court + texte long de 1 563 mots, voix française)
> donne OmniVoice gagnant sur la **qualité du rendu final, particulièrement en
> français** : écoute 9/10 contre 7/10, 4 à 7 × plus rapide, fidélité texte
> égale ou meilleure (détails : `docs/BENCH_MOTEURS.md`). La branche `cosy`
> conserve CosyVoice3 en legacy.

---

## ✨ Fonctionnalités

- 🎭 **Multi-voix** : un personnage = une voix clonée (zéro-shot `wav` + `txt`)
- 🧩 **Blocs adaptatifs vérifiés** : découpe + vérification Whisper, badges de pertes
- ✂️ **Split inline multi-locuteurs** : `[Alice] … [Bob] …` sur une ligne → 2 blocs auto
- ⏸️ **Pauses en filet** : visibles mais discrètes, masquables d'un interrupteur
- 🎵 **BGM** : marqueurs de fond musical, 🧹 **nettoyage voix** (Demucs + DeepFilterNet)
- 🇫🇷 **Normalisation française** : nombres, dates, heures, devises, chiffres romains
- 🔁 **Reprise après rechargement** : la génération en cours se rattache toute seule
- 🐳 **100 % conteneurisé** : image `voicebuilder-omni` (GHCR), volumes nommés

---

## 🚀 Démarrage rapide

```bash
docker compose -f docker-compose.gitea.yml --env-file .env.gitea up -d gui
# → http://127.0.0.1:8000
```

Le modèle OmniVoice (3,3 Go) est téléchargé au premier lancement dans le cache
HuggingFace (`volume-omni-cache`, conservé entre recréations). Les modèles de
nettoyage restent dans `volume-model` (`/models/enhance_models`).

## 🎤 Les voix (`voix/`)

Chaque voix = un couple **`.wav`** (échantillon ~5–30 s, sans musique) +
**`.txt`** (sa transcription exacte), listé dans `voix/voix.txt` :

```
# [NomVoix], wav, txt[, pause_pré][, vitesse]
[Narrateur],  narrateur_phrase_01.wav, narrateur_phrase_01.txt
[Lina],  lina_phrase_01.wav, lina_phrase_01.txt
```

> La 7ᵉ colonne `moteur` historique est **lue sans effet** sur cette branche
> (moteur unique). Les doublons de nom sont numérotés (`Nom`, `Nom_2`, …).

Import / pré-écoute / suppression / 🧹 nettoyage depuis l'onglet **Projets** →
🎙️ **Voix**. Dossier des voix réglable via `VOICEBUILDER_AUDIO_DIR`
(`/data/voice` en Docker).

## 📝 Format du texte taggé

- `[Personnage]: texte` — attribution de réplique (plusieurs par ligne : auto-split)
- Ligne sans balise — lue par la voix en cours (aucune ligne ignorée)
- `[sigh]`, `[laughter]`… — tags non-verbaux conservés inline
- `[stop]` — arrête la génération ; lignes vides et `#` — commentaires

## 🖥️ Interface (FastAPI, référence)

3 onglets **Éditeur** (CodeMirror, brouillon auto) / **Montage** (timeline
cliquable, lecteurs par bloc, ⏹ arrêt propre, ✓ vérification Whisper,
🗑 suppression de génération) / **Projets** (documents, archives, voix).
Thème clair/sombre 🌙.

```bash
python -m tools.gen_multi_voix texte/chapitre.md -o output/montage.wav \
    --pause 0.45 --vitesse 1.0 --max-chars 260
```

## 🌳 Branches

| Branche | Contenu | Statut |
|---|---|---|
| `main` | OmniVoice seul (ex-`omni` fusionnée, PR #2), image `voicebuilder-omni` | 🛠️ courante, 🏷️ v1.0.0 à venir (tag manuel) |
| `cosy` | CosyVoice3 seul | 📼 legacy |

## 📚 Docs

- `docs/UTILISATION.md` — guide complet (CLI, GUI, format taggé)
- `docs/BENCH_MOTEURS.md` — bench décisif OmniVoice vs CosyVoice
- `PROJET_FINE.md` — spec détaillée · `ROADMAP.md` — jalons · `CHANGELOG.md`
- `TODO.md` — tâches (dont resync des variantes depuis `main`)

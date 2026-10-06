# Bench moteurs M19 — XTTS-v2 vs CosyVoice3 (2026-09-25) puis OmniVoice (2026-10-06)

Protocole `PROJET_FINE.md` §3.4 : même **paragraphe FR de référence**
(`engine/bench.py:PARAGRAPHE_REF`, 298 car.), même voix/prompt
(`Thepromisedneverland_clean`), métriques `coverage` Whisper (seuil 0.85)
+ RTF. Outil : `engine/bench_moteurs.py` + `tools/bench_moteurs.py`.

## Résultats 2026-09-25 (RTX 3050 8 Go, hors GUI)

| Moteur | Coverage | RTF | WAV |
|---|---|---|---|
| CosyVoice3 curé (palier 0) | **0,936** | 0,673 | `output/bench_moteurs/moteur-cosyvoice.wav` |
| XTTS-v2 | 0,915 | **0,257** | `output/bench_moteurs/moteur-xtts.wav` |

Les deux étaient **admissibles** (≥ 0.85). (WAV et verdicts de septembre
supprimés le 2026-10-06 : remplacés par le bench OmniVoice ci-dessous.)

## Résultats 2026-10-06 — OmniVoice vs VoiceBuilder/CosyVoice (RTX 4070)

Même protocole §3.4 **sans token** (texte brut, normalisation côté moteur),
voix **Astronogeek** (5,6 s), OmniVoice `0.2.1` (fp16). Verdict :
`output/bench_moteurs/verdict-omni.json`, texte :
`paragraphe-reference.md`.

| Moteur | Coverage | RTF synthèse | Note écoute |
|---|---|---|---|
| OmniVoice | 0,771 | **0,093** (1,8 s / 19,3 s) | **9/10** (clonage parfait, intention) |
| VoiceBuilder/CosyVoice | 0,771 | ~0,673 | 7/10 (robotique) |
| XTTS-v2 (rappel sept.) | — | 0,257 | 6,5/10 |

Égalité métrique parfaite (mêmes 12 mots perdus, tous des nombres → **biais
de transcription Whisper**, inaudibles à l'écoute). OmniVoice **4–7× plus
rapide**, cohabitation VRAM OK avec le serveur (12 Go).

**Texte long** (« Divine Opportunite - 1 », 1 563 mots, `verdict-divine.json`) :
coverage **0,923 vs 0,910** (seuil tenu des deux côtés, manquants = noms
propres et fautes source), RTF **0,094 vs 0,383**.

**Décision M19.1 : OmniVoice intégré comme moteur alternatif**
(`engine/omnivoice_engine.py`, routage par voix, sélecteur Configuration).

## Licences (usage personnel confirmé)

- **XTTS-v2 = CPML** : non-commercial uniquement ; Coqui fermé (01/2024),
  aucune licence commerciale achetable. ToS accepté (`COQUI_TOS_AGREED=1`).
- **Fish-Speech 1.5 = CC-BY-NC-SA-4.0** ; séries S2+ = licence recherche
  (poursuites annoncées). Usage personnel OK.

## Environnement bench

- `.venv-bench` (torch 2.9.1 cu126 + coqui-tts, hors git) ; patchs venv :
  garde `torchcodec` neutralisée (`TTS/__init__.py`), `torchaudio.load`
  → `soundfile` (FFmpeg système = 9, torchcodec exige ≤ 7),
  `isin_mps_friendly` → `torch.isin` (transformers 5.x).
- Baseline CosyVoice via `docker exec -e CUDA_VISIBLE_DEVICES=1
  voicebuilder-gui` (serveur GUI sature la 4070 ; `multi.load` ignore
  le 2e GPU sans cette variable).

## Reste M19.0

- Fish-Speech v1.5+ : bloqué (deps v1.5.1 : `pydantic==2.9.2` incompilable
  sur Python 3.14, `lightning`/`litgpt` requis) → reprendre en conteneur
  Python ≤ 3.12.
- RTF CPU-only bi-Xeon : reporté (demande utilisateur).

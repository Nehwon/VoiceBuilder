# Bench moteurs M19.0 — XTTS-v2 vs CosyVoice3 curé (2026-09-25)

Protocole `PROJET_FINE.md` §3.4 : même **paragraphe FR de référence**
(`engine/bench.py:PARAGRAPHE_REF`, 298 car.), même voix/prompt
(`Thepromisedneverland_clean`), métriques `coverage` Whisper (seuil 0.85)
+ RTF. Outil : `engine/bench_moteurs.py` + `tools/bench_moteurs.py`.

## Résultats (RTX 3050 8 Go, hors GUI)

| Moteur | Coverage | RTF | WAV |
|---|---|---|---|
| CosyVoice3 curé (palier 0) | **0,936** | 0,673 | `output/bench_moteurs/moteur-cosyvoice.wav` |
| XTTS-v2 | 0,915 | **0,257** | `output/bench_moteurs/moteur-xtts.wav` |

Les deux sont **admissibles** (≥ 0.85). XTTS est **×2,6 plus rapide**,
CosyVoice garde +2 pts de fidélité. Décision d'intégration (M19.1) après
**écoute aveugle** (grille §3.4, à faire par l'utilisateur).

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

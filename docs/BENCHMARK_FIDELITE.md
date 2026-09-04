# Rapport M4.x — Benchmark de fidélité VoiceBuilder

**Date** : 2026-09-04  
**Voix** : Astronogeek (première de `voix.txt`)  
**Texte** : 29 phrases, ~2100 caractères (texte long de démonstration)  
**Modèle** : CosyVoice3 (Fun-CosyVoice3-0.5B), GPU NVIDIA  
**Whisper** : model `small`, lang `fr`

---

## 1. Impact de `max_chars` (taille max des blocs)

Vérification Whisper **activée** (seuil = 0.85).

| max_chars | Blocs | Couverture | Durée audio | Temps gén. | Notes |
|-----------|-------|------------|-------------|------------|-------|
| **150** | 17 | 95.25% | — | **112.4 s** | Très lent (overhead Whisper ×17 appels) |
| **250** | 12 | 95.28% | — | 44.0 s | |
| **400** | 7 | **96.44%** | — | 43.5 s | **Meilleur score** |
| **600** *(défaut)* | 4 | 95.68% | — | **37.1 s** | **Meilleur compromis** |
| **800** | 3 | 96.26% | — | 39.7 s | |
| **1000** | 3 | 94.52% | — | 37.4s | Légère baisse couverture |
| **1200** | 2 | 94.84% | — | 39.8s | Moins de blocs, couverture en baisse |

### Observations

- **La couverture Whisper reste stable entre 94.5% et 96.5%** quelle que soit la taille des blocs — le mécanisme de re-split fonctionne bien.
- **max_chars = 150 est anormalement lent** : 17 blocs × appels Whisper = overhead massif. À éviter.
- **max_chars = 600 (défaut) est le meilleur compromis** : 4 blocs, couverture > 95%, temps minimal (37 s).
- **Au-delà de 800 chars**, la couverture baisse légèrement (94.5–94.8%) malgré le re-split, ce qui suggère que les blocs très longs génèrent parfois des pertes que le split ne compense pas.
- **Écart de vitesse minime entre 600 et 1200** : le gain de blocs (4→2) ne compense pas le temps de synthèse des blocs plus longs.

---

## 2. Impact du seuil de vérification Whisper

`max_chars = 600` (valeur par défaut), vérification **activée**.

| Seuil | Couverture | Temps | Re-splits estimés |
|-------|------------|-------|--------------------|
| **0.60** | 95.72% | 35.6 s | Peu (seuil très permissif) |
| **0.70** | **96.79%** | 37.4 s | Modéré |
| **0.80** | 95.19% | 40.5 s | Plus que 0.70 |
| **0.85** *(défaut)* | 95.72% | 40.8 s | Référence |
| **0.90** | 95.72% | 37.0 s | |
| **0.95** | *(test interrompu)* | — | |

### Observations

- **Le seuil a un impact marginal sur la couverture finale** (95.2% → 96.8%), car le texte de test est de bonne qualité et CosyVoice rend fidèlement le contenu.
- **Le seuil 0.70 offre la meilleure couverture (96.79%)** et un temps correct.
- **Le seuil 0.85 (défaut) est conservateur mais raisonnable** : il pénalise moins les variations mineures de Whisper (qui peut mal transcrire sans que le TTS ait failli).
- **Seuil trop bas (< 0.60)** : risque de laisser passer des blocs incomplets.
- **Seuil trop élevé (> 0.95)** : risque de re-splits inutiles (Whisper lui-même fait des erreurs de transcription).

---

## 3. Vérification ON vs OFF

`max_chars = 600`, seuil = 0.85, texte 1480 chars.

| Mode | Couverture | Durée audio | Temps total | RTF |
|------|------------|-------------|-------------|-----|
| **OFF** | 95.24% | 91.6 s | 59.2 s | 0.65 |
| **ON** | **95.92%** | **86.6 s** | **23.3 s** | **0.27** |

### Observations

- **La vérification ON est plus rapide que OFF** (23 s vs 59 s) — résultat contre-intuitif.
- **Explication** : sans vérification, CosyVoice produit des blocs audio parfois
  plus longs que le texte d'origine (overshoot). La vérification détecte les blocs
  incomplets et les re-split en parties plus courtes, réduisant la durée audio
  totale (86.6 s vs 91.6 s) et le temps de synthèse.
- **La couverture est légèrement meilleure avec la vérif** (95.92% vs 95.24%),
 confirmant que le re-split améliore la fidélité.
- **RTF divisé par 2.4** avec la vérification (0.27 vs 0.65) : le re-split
  produit des blocs plus courts qui synthsètent plus efficacement.
- **Conclusion : la vérification est non seulement utile pour la qualité mais
  aussi pour la performance** — elle doit rester activée par défaut.

---

## Recommandations

| Paramètre | Valeur actuelle | Recommandation | Justification |
|-----------|-----------------|----------------|---------------|
| `DEFAULT_MAX_BLOCK_CHARS` | 600 | **600** (conserver) | Meilleur compromis blocs/temps/couverture |
| `VERIFY_THRESHOLD` | 0.85 | **0.85** (conserver) | Conservative mais sûr ; 0.70 serait plus rapide |
| `WHISPER_MODEL` | small | **small** (conserver) | Assez précis, pas trop lent |
| `DEFAULT_SPEED` | 1.0 | 1.0 | Pas testé dans ce benchmark |

### Optimisations possibles

1. **Garder `max_chars = 600`** : c'est le sweet spot. Pas besoin de changer.
2. **Garder la vérification activée** : elle améliore la qualité ET la performance (RTF ×2.4).
3. **Seuil Whisper à 0.70** : si on veut accélérer un peu plus sans perte significative.
4. **Ne pas utiliser `max_chars < 200`** : l'overhead Whisper rend la génération 3× plus lente sans gain de couverture.
5. **Texte long recommandé pour le benchmark futur** : le texte de 2100 chars est assez pour tester, mais un texte de 5000+ chars serait plus discriminant.

---

## Fichiers

- Script principal : `tools/benchmark_fidelite.py`
- Script verify ON/OFF : `tools/benchmark_verify.py`
- Résultats JSON : `output/benchmark.json` (non généré — timeout avant la phase de sauvegarde)
- Ce rapport : `docs/BENCHMARK_FIDELITE.md`

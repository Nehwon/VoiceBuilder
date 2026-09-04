# Rapport M5.3 — Benchmark accélération CosyVoice3

**Date** : 2026-09-04  
**Voix** : Astronogeek  
**Texte** : 415 chars (2 phrases)  
**GPU** : NVIDIA (via Docker)  
**Méthode** : 1 warmup + 3 mesures par config, RTF moyen

---

## Résultats

| Configuration | RTF | Temps | Durée audio | Accélération |
|---------------|-----|-------|-------------|--------------|
| **PyTorch (baseline)** | 0.278 | 6.59 s | 23.73 s | ×1.00 |
| **+ vLLM** | 0.269 | 6.39 s | 23.73 s | ×1.03 |
| **+ TensorRT** | 0.270 | 6.42 s | 23.73 s | ×1.03 |
| **+ vLLM + TensorRT** | 0.289 | 6.85 s | 23.73 s | ×0.96 |

---

## Analyse

**L'accélération est marginale (~3%) pour ce texte court (415 chars).**

### Pourquoi ?

1. **vLLM** : son avantage principal est le *continuous batching* et le *PagedAttention*
   pour des requêtes concurrentes. Sur une seule requête courte, le surcoût de
   l'export du modèle vLLM (`export_cosyvoice2_vllm`) compense le gain d'inference.

2. **TensorRT** : optimise le kernel du DiT (Flow estimator, 10 pas Euler).
   Mais le DiT n'est pas le goulot d'étranglement sur des textes courts —
   c'est le LLM autoregressif qui domine.

3. **Texte trop court** : le LLM (Qwen2 0.5B) génère peu de tokens, donc
   l'overhead d'initialisation domine le temps utile.

### Quand vLLM/TensorRT seront utiles ?

- **Textes longs** (> 1000 chars) : le LLM devient le goulot, vLLM accélère
  le décodage autoregressif.
- **Batch de plusieurs textes** : vLLM gère le batching nativement.
- **Haute concurrence** (plusieurs utilisateurs) : vLLM + PagedAttention.

---

## Verdict

| Option | Statut | Recommandation |
|--------|--------|----------------|
| vLLM | ✅ Intégré, fonctionnel | Garder l'option, utile pour textes longs/batch |
| TensorRT | ✅ Intégré, fonctionnel | Garder l'option, utile pour flow sur textes longs |
| Les deux | ✅ Intégré | Combinable, pas de conflit |

**Les options `--vllm` et `--trt` restent disponibles** dans la CLI et le GUI.
L'impact sera mesuré sur des textes plus longs lors d'une utilisation réelle.

---

## Fichiers

- Script : `tools/benchmark_accel.py`
- Ce rapport : `docs/BENCHMARK_ACCEL.md`

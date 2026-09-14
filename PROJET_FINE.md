# VoiceBuilder — Fine-tune & qualité des voix (PROJET_FINE.md)

> Objectif : améliorer le rendu des voix existantes — **sans tout casser**.
> Ce document part de l'état actuel (zéro-shot pur), explique les leviers
> **sans entraînement**, puis le **fine-tune de CosyVoice3**, puis le
> **changement de moteur**, et recommande un ordre en 3 paliers.
>
> Lien avec le portage GO (`PROJET_GO.md` §7) : aucun de ces moteurs ne tourne
> en GO natif — tous exigent le même sidecar Python/torch. Changer de moteur
> ne simplifie donc pas le portage, il échange un sidecar contre un autre.
> Ordre conseillé : palier 0 pendant le cadrage GO, paliers 1–2 après `1.0-go`.

État au 2026-09-13 : 14 voix en zéro-shot dans `voix/voix.txt` (1 couple
`.wav` 5–30 s + `.txt` par voix : Astronogeek, Gachiakuta,
Thepromisedneverland ×3, Arthurhennes, Christophepauly, Epense, Gmilgram,
Micode, Superama, Sushinihiliste, Sylarticho, Unirreductibleathee). Aucun
entraînement : le timbre vient du seul prompt
(`"You are a helpful assistant.<|endofprompt|>" + texte_du_txt`,
`engine/cosyvoice_engine.py`, `engine/voix.py`). Nettoyage Demucs+DeepFilterNet
(M13.0, `engine/enhance.py`) et normalisation FR (`engine/text_fr.py`) déjà actifs.

---

## 1. Pourquoi le zéro-shot actuel plafonne — et ce que ça implique

En zéro-shot, le modèle n'apprend rien de permanent : à chaque bloc, il
« imite » le prompt wav+txt. Conséquences concrètes :

- **La qualité du prompt fait 80 % du résultat.** Musique de fond, bruit,
  réverb, respirations fortes, débit irrégulier → clone instable, ton qui
  dérive d'un bloc à l'autre (d'où l'importance des blocs longs,
  `max_chars=600`, et du regroupement par locuteur dans `engine/multi.py`).
- **La transcription doit être exacte au mot près.** Un mot faux dans le `.txt`
  décale l'alignement prompt et dégrade tout le bloc. C'est le point le plus
  sous-estimé.
- **L'émotion ne se décrète pas.** Les tokens `<|HAPPY|>/<|SAD|>/…`, `[sigh]`,
  `[laughter]` (`docs/UTILISATION.md` §4) guident la prosodie, mais un timbre
  source neutre + `<|ANGRY|>` sonne faux. Le timbre source doit déjà porter
  l'émotion visée.

D'où la règle : **toujours épuiser le palier 0 (gratuit) avant tout
entraînement.**

---

## 2. Palier 0 — Sans changer de moteur, coût ≈ 0 (à faire d'abord)

1. **Curation des prompts (levier le plus rentable).**
   Viser 10–20 s de parole dense, sans musique ni bruit, débit régulier, sans
   chevauchement d'autres voix. Tester **2–3 segments par personnage** sur le
   même paragraphe de référence et garder le meilleur en écoute A/B. Vos
   `_2`/`_3` (ex. Thepromisedneverland) sont déjà ce banc d'essai : il faut le
   systématiser aux 14 voix.
2. **Nettoyage systématique.** Passer les 14 wav au bouton « 🧹 Nettoyer »
   (Demucs = retire musique/autres voix, DeepFilterNet = débruitage/déréverb),
   comparer avant/après, publier les `<nom>_clean` gagnants comme référence.
   La musique de fond est le poison n°1 du zéro-shot.
3. **Recurer les transcriptions.** Réécouter chaque wav en lisant son `.txt`,
   corriger chaque mot, garder le format horodaté si utile (ignoré au parsing,
   `engine/voix.py`). Un `.txt` faux annule un bon `.wav`.
4. **Multi-prompt (option coûteuse mais simple).** CosyVoice3 n'accepte qu'1
   prompt par appel, mais on peut générer chaque bloc avec 2 prompts et garder
   le meilleur (verif Whisper `coverage` ≥ 0.85 + écoute). Coût ×2 GPU, utile
   sur les voix faibles en attendant un fine-tune.
5. **Tokens avec sobriété.** 1 tag par bloc max (`<|HAPPY|>`, `[sigh]`,
   `<strong>`), forme `<|…|>` préférée (passe le frontend en brut, cf.
   `docs/UTILISATION.md` §4.5). Et choisir un échantillon source déjà émotionné
   si le personnage doit l'être.
6. **Paramètres figés.** Garder `max_chars=600` + seuil 0.85 (benchmarkés,
   `docs/BENCHMARK_FIDELITE.md`), régler le **débit par voix** (colonnes
   `pause_pré`, `vitesse` de `voix.txt`) plutôt que forcer à la synthèse.

Gain typique observé sur ce type de stack : **+30–50 % de qualité perçue pour
0 € d'entraînement.** C'est le seul palier à faire pendant le portage GO.

---

## 3. Palier 1 — Fine-tuner CosyVoice3 (adapter le moteur existant)

### 3.1 Ce que le repo sait déjà faire

`vendor/CosyVoice/tools/` fournit la chaîne SFT officielle (`make_parquet_list`,
`extract_speech_token`, entraînement du LLM + Flow, LoRA ou full). On reste
donc **dans la même stack** : pas de nouveau moteur, pas de nouveau sidecar,
juste un adaptateur par personnage.

### 3.2 Données nécessaires (le vrai coût)

- **15 min à 3 h de parole propre + transcription exacte par personnage
  vedette.** En deçà de ~15 min, le gain vs zéro-shot soigné (palier 0) est
  marginal : ne pas fine-tuner les 14 voix, seulement **1–3 personnages
  principaux** (narrateur + héros).
- Collecte : extraire des passages propres (onglet Voix existant : upload →
  waveform → transcription Whisper → correction manuelle obligatoire), viser
  30–60 min effectifs par voix pour un LoRA sérieux.
- Format : segments 5–20 s + transcriptions exactes (parquet list selon les
  scripts CosyVoice), dédupliquer, équilibrer les émotions si le personnage
  doit les porter.

### 3.3 Matériel, durée, stockage — y compris petit GPU (12 / 16 Go)

Référence : GPU **24 Go VRAM** (3090/4090/A10), quelques heures à 1–2 jours par
voix selon volume et rang LoRA. Mais un LoRA du 0.5B **tient sur 12–16 Go** en
activant les leviers d'économie VRAM :

| Budget VRAM | Config conseillée |
|---|---|
| 24 Go | LoRA r=16–32, bf16, batch confortable, AdamW standard |
| 16 Go | LoRA r=8–16 + gradient checkpointing + micro-batch 1 avec accumulation + optim 8-bit (`bitsandbytes`) ou paged |
| 12 Go | config 16 Go + **qLoRA** (backbone quantifié 4-bit NF4, seuls les adaptateurs s'entraînent) + ZeRO-2/offload CPU si besoin + segments courts |

Autres leviers (cumulables) :
- **Geler le Flow / HiFi-GAN** et n'entraîner que le LLM (ou l'inverse après
  test : valider sur 1 voix où vit le timbre avant de généraliser) — divise les
  gradients et états d'optimiseur à stocker.
- **Raccourcir les segments** (5–12 s au lieu de 5–20 s) : la mémoire
  attention/Flow croît avec la longueur ; tronquer fait baisser le pic VRAM
  sans réduire le volume de données.
- **DeepSpeed ZeRO-2 + offload CPU** : filet de sécurité si OOM malgré le reste
  (plus lent, mais passe quasiment toujours).
- **Valider petit** : 15–30 min de données, 1 voix, quelques centaines de steps
  — si ça OOM sur l'échantillon, ça OOMera sur le full.

**Échelle anti-OOM (ladder, à tester dans l'ordre)** : config 16 Go → si OOM :
+ checkpointing → + accumulation (batch 1) → + optim 8-bit → + qLoRA → +
ZeRO offload → réduire rank/longueur. Chaque étage se teste en < 30 min ;
documenter l'étage retenu par voix (reproductibilité).

- Stockage : **1 LoRA (~10–200 Mo selon rang/quantif) par personnage**, base
  0.5B partagée.
- Durée petit GPU : compter ×1,5 à ×3 vs 24 Go (offload/accumulation
  ralentissent) — une nuit à un week-end par voix.
- Inférence : surcoût VRAM négligeable (base + adaptateur, fusionnable) ;
  switch par personnage = reload partiel à cacher (cf. `TODO.md` M18.4).

### 3.4 Protocole de validation (ne pas s'auto-convaincre)

1. Paragraphe FR de référence fixe (nombres, dates, dialogue, 1 émotion).
2. Générer : zéro-shot curé (palier 0) vs LoRA, même texte, même `max_chars`.
3. Mesures : `coverage` Whisper (doit rester ≥ 0.85), RTF, puis **écoute aveugle**
   (au moins 2 auditeurs, ordre aléatoire).
4. Ne garder le LoRA que s'il gagne en aveugle. Sinon : retour palier 0.

### 3.5 Verdict

Pertinent pour le narrateur + 1–2 héros à fort temps d'antenne. Overkill pour
les 14 voix secondaires → les garder en zéro-shot curé.

---

## 4. Palier 2 — Changer de moteur (seulement si le palier 1 échoue)

### 4.1 Tableau comparatif (FR, clonage, fine-tune)

| Moteur | FR | Clonage | Fine-tune voix | Coût/notes — explication |
|---|---|---|---|---|
| **CosyVoice3 (actuel)** | bon (multilingue + normalisation FR interne) | zéro-shot 5–30 s, très bon | LoRA/SFT officiel, outils inclus | Référence. Changer n'a de sens que sur échec mesuré. |
| **XTTS-v2 (Coqui)** | bon FR, stable | zéro-shot 6–30 s | fine-tune ~10 min–3 h, outillage mature | Alternative n°1 si on veut un fine-tune simple et documenté. Attention licence **CPML (usage commercial restreint)** — vérifier avant toute diffusion. |
| **Fish-Speech v1.5+** | correct FR (en retrait hors fine-tune) | zéro-shot expressif | fine-tune léger efficace, open | À considérer si la priorité est l'expressivité/émotions plutôt que la neutralité. |
| **F5-TTS / E2-TTS** | moyen FR natif (anglais-centré) | zéro-shot naturel | possible mais FR à valider | À bencher sur le paragraphe FR de référence avant toute adoption pour du FR long. |
| **StyleTTS2** | FR via fine-tune uniquement | pas de zéro-shot | 1–3 h/voix, très stable, temps réel | Si l'objectif est 1 voix studio parfaite plutôt que 14 voix vite clonées. |
| **Seed-VC / RVC** (conversion, pas TTS) | langue-agnostique | — | transforme une voix synthétique vers le timbre cible | **Complément, pas remplacement** : TTS neutre + conversion = prosodie et timbre découplés. Utile si le TTS est bon mais le timbre dérive. |
| **Piper / VITS FR** | excellent mais robotique | aucun (voix fixes) | entraînement from scratch (lourd) | Hors sujet pour du multi-voix clonées. |

### 4.2 Comment migrer sans tout casser

- Bencher XTTS-v2 fine-tuné puis Fish-Speech **sur le même paragraphe FR +
  même protocole qu'en §3.4** (+ écoute aveugle), face au meilleur CosyVoice
  (palier 0 ou LoRA).
- Ne migrer que le(s) personnage(s) gagnant(s) : architecture **multi-moteurs
  côté sidecar** (1 moteur par voix). Prévoir dès le portage GO une colonne
  `moteur` future dans `voix.txt` (sans l'activer) pour ne pas avoir à
  re-câbler le serveur plus tard.
- Rappel licence : XTTS-v2 = CPML. Si le projet diffuse commercialement,
  trancher le point juridique avant d'investir en fine-tune XTTS.

---

## 5. Recommandation — l'ordre qui évite de perdre du temps

1. **Palier 0 (cette semaine, gratuit).** Nettoyer les 14 wav, recurer les
   `.txt`, bancher 2–3 prompts/personnage, figer les `<nom>_clean` + vitesses.
2. **Palier 1 (si palier 0 insuffisant, 1–3 voix).** LoRA CosyVoice3 sur
   narrateur + héros (30–60 min de propre chacun, entraînement nuit/week-end,
   A/B aveugle). Reste dans la stack actuelle.
3. **Palier 2 (si échec palier 1).** Bench XTTS-v2 puis Fish-Speech, migration
   multi-moteurs par personnage uniquement sur victoire aveugle.

Et surtout : **palier 0 pendant le cadrage GO, paliers 1–2 après `1.0-go`.**
Mélanger un changement de moteur avec un changement de langage, c'est
s'interdire de savoir ce qui a cassé quand ça casse.

---

## 6. Critères de succès voix

- Chaque voix de référence a un prompt `.wav` propre (ou `_clean`) + `.txt`
  vérifié mot à mot.
- Tout LoRA/moteur alternatif n'est gardé que sur victoire en écoute aveugle +
  `coverage` ≥ 0.85 maintenu.
- Aucune régression des benchmarks existants (`BENCHMARK_FIDELITE.md`,
  `BENCHMARK_ACCEL.md`) : rejouer les mesures à chaque palier.

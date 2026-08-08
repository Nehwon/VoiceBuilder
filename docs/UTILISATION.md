# VoiceBuilder — Guide d'utilisation

Usage complet : CLI, GUI, format de texte taggé, et en particulier le jeu de
**tags non-verbaux / émotions spécifiques à CosyVoice3**.

Prérequis techniques : moteur **CosyVoice3** (`Fun-CosyVoice3-0.5B`) et son venv
(`~/Projets/CosyVoice`) ; chemins dans `engine/config.py`.

---

## 1. En un coup d'œil

1. Créez une **voix** par personnage (paire `.wav` + `.txt`) — §2.
2. Écrivez un **texte taggé** (format §3), en insérant les **tags émotion /
   non-verbaux** CosyVoice3 (§4) directement dans le texte.
3. Lancez la **génération** (CLI §5 ou GUI §6).
4. Récupérez le **montage `.wav`** dans `output/`.

---

## 2. Les voix (`voix/`)

Assistant rapide :

```bash
python -m tools.create_voix SOURCE.wav --nom LeNarrateur --start 12.5 --stop 30
```

Une voix = un **échantillon `.wav`** (~5–30 s, sans musique) + sa **transcription
`.txt`** exacte. Gardez l'échantillon **inférieur à 30 s** (limite de l'extraction
des tokens vocaux, cf. `~/Projets/CosyVoice/cosyvoice/cli/frontend.py`).

Fichier de listage `voix/voix.txt`, une entrée par ligne :

```
# [Nom] wav, txt[, pause_pré][, vitesse][, max_chars]
[LeNarrateur],  Partages/voice/superama.wav, Partages/voice/superama.txt
[Kaël-An],      echantillons/kael_an.wav,     echantillons/kael_an.txt, 0.3, 1.0, 200
```

- **wav**, **txt** : chemins relatifs au projet ou absolus.
- **pause_pré** (s), **vitesse**, **max_chars** : surcharges optionnelles par voix.
- le `.txt` : transcription exacte, au besoin horodatée `[0000.00 - 0005.28] texte`.

Au clonage, le prompt TTS =
`"You are a helpful assistant.<|endofprompt|>" + texte_du_txt`.

#### Choix de l'emplacement des fichiers .wav/.txt

Les fichiers audio et leurs transcriptions peuvent être stockés **en dehors** du
projet. Leur dossier est réglé par la variable d'environnement
`VOICEBUILDER_AUDIO_DIR` (défaut : `~/Partages/voice`) :

```bash
export VOICEBUILDER_AUDIO_DIR=~/Partages/voice
```

Les chemins de `voix.txt` sont résolus dans l'ordre : dossier du projet, `voix/`,
puis ce dossier audio (`config.VOIX_SEARCH_DIRS`). Ex. une ligne simple :

```
[Michel], unirreductibleathee_phrase_01.wav
```

…est retrouvée dans `~/Partages/voice/` si elle s'y trouve.

---

## 3. Format du texte taggé

```
[Narrateur]: Le ciel était gris, ce matin-là.
Il marchait lentement.<|SAD|> La pluie tombait sans bruit.
[Michel]: Ah, te voilà ! [sigh] Il est l'heure.
[Marie]: [laughter] Tu plaisantes, j'espère.
[stop]
```

Règles (`engine/tagging.py`) :
- **`[Nom]:`** en tête de ligne — change de locuteur.
- **Ligne nue** — reprend le locuteur précédent (prose / narrateur) ; erreur sinon.
- **`[Nom]` sans deux-points** — variante acceptée (ligne = le texte).
- Lignes **vides** et **`#…`** — ignorées.
- **`[stop]`** (seul sur une ligne) — arrête la génération.
- Les autres **`[…]`** en cours de ligne — **conservés tels quels** dans l'éditeur
  TTS (voir §4 pour les tokens reconnus).

---

## 4. Tags non-verbaux / émotions spécifiques à CosyVoice3

CosyVoice3 reconnaît des **tokens spéciaux** dans son vocabulaire
(`~/Projets/CosyVoice/cosyvoice/tokenizer/tokenizer.py`). À écrire **bruts, dans
le texte du bloc**.

### 4.1 Émotions — forme `<|ÉMOTION|>` (recommandé)

`<|HAPPY|>` · `<|SAD|>` · `<|ANGRY|>` · `<|NEUTRAL|>`

> Avantage clé : dès qu'un token `<|…|>` est présent, le **front-end est
> contourné** automatiquement (`frontend.py`) et le token est transmis **brut**
> au modèle, sans altération.

```
[Marie]: C'est merveilleux ! <|HAPPY|> On y retourne demain.
```

### 4.2 Sons paralinguistiques

Tokens entre crochets, insérés en ligne dans le texte :

| Token                 | Effet                        |
|-----------------------|------------------------------|
| `[sigh]`              | soupir                       |
| `[laughter]`          | rire                         |
| `[breath]`            | respiration                  |
| `[quick_breath]`      | respiration courte           |
| `[cough]`             | toux                         |
| `[clucking]`          | claquement de langue         |
| `[hissing]`          | sifflante                 |
| `[lipsmack]`          | claquement de lèvres         |
| `[noise]`             | bruit                        |
| `[vocalized-noise]`   | bruit vocalisé               |
| `[accent]`            | accent                       |
| `[mn]`                | grognement / acquiescement   |
| `<strong>…</strong>`  | emphase sur le morceau        |

```
[Michel]: Où étais-tu toute la nuit ? [sigh] Bon, entrons.
[Marie]: <strong>Non</strong>, ce n'est pas ça.
```

### 4.3 Événements audio / ambiance

`<|Laughter|>…<|/Laughter|>` · `<|Applause|>…<|/Applause|>` ·
`<|BGM|>…<|/BGM|>`

```
[LePublic]: <|Applause|> <|/Applause|> Encore ! Encore !
```

### 4.4 Correspondance avec les tags « OmniVoice »

Les anciens tags de commande (`[confirmation-en]`, `[question-en]`, …) ne sont
**pas** des tokens CosyVoice3. À remplacer par les tokens réels de §4, ou à retirer
(l'intonation/spontanéité est déjà portée par le moteur) :

| ancien `[…]`          | recommandation CosyVoice3                 |
|-----------------------|-------------------------------------------|
| `[sigh]`              | garder `[sigh]` (reconnu)                   |
| `[silence]`           | insérer une **pause inter-bloc** (option `pause`), pas de tag |
| `[question-en]`       | retirer (l'intonation interrogative est naturelle)            |
| `[confirmation-en]`   | retirer                                      |
| `<|…|>` libre instruc | écrire l'émotion réelle (§4.1/4.3)           |

### 4.5 Points d'attention

- **Sobriété** : un tag au même endroit par bloc ; l'empilement déstabilise.
- La forme `<|…|>` **garantit** le passage brut ; les tokens `[…/…]` restent
  soumis au front-end (nombre/segmentation) si aucun `<|…|>` n'est présent —
  testez (la vérification §6 vous l'indiquera).
- **La voix clonée doit "porter" l'émotion** : un timbre neutre ne crée pas une
  émotion forte par simple étiquette.

---

## 5. Génération

### CLI (`tools/gen_multi_voix.py`)

```bash
python -m tools.gen_multi_voix texte/chapitre.md \
    -o output/montage.wav \
    --voix voix/voix.txt --pause 0.45 --vitesse 1.0 --max-chars 260
```

Options : `--voix`, `--pause`, `--vitesse`, `--max-chars`, `--no-verify`,
`--texte-dir`. Sans `-o`, sortie `output/<nom-du-fichier>.wav`.

### GUI

```bash
python -m app.gui
```

Éditeur Markdown (surlignage des `[Nom]:`), panneau des voix, bouton **Générer**
(choix du `.wav`), champ `pause`, barre de progression/statut.

---

## 6. Vérification et qualité

- **Vérification automatique** (active par défaut) : chaque bloc, retranscrit
  (Whisper, FR) et **couverture ≥ 85 %** des mots attendus ; sinon re-fente en 2
  puis régénération (`engine/adaptive.py`, `engine/verifier.py`).
- Désactivable via `--no-verify` (CLI) ou le réglage.
- **Zéro perte** : la transcription du WAV final doit refléter intégralement le
  texte d'entrée.

---

## 7. Création de voix (rappel)

```bash
python -m tools.create_voix SOURCE.wav --nom LeNarrateur --start 12.5 --stop 30
```

Extrait `[12.5, 30] s`, transcrit (Whisper), écrit `voix/<slug>.wav` + `.txt`,
ajoute la ligne dans `voix/voix.txt`. Options : `--out`, `--voix`,
`--no-transcribe`.
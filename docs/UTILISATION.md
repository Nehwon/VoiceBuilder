# VoiceBuilder — Guide d'utilisation

Usage complet : CLI, GUI, format de texte taggé, et en particulier le jeu de
**tags non-verbaux / émotions spécifiques à CosyVoice3**.

Prérequis techniques : moteur **CosyVoice3** (`Fun-CosyVoice3-0.5B`) et son venv
(`vendor/CosyVoice/venv`, sous-module git) ; chemins dans `engine/config.py`.
Un **conteneur Docker GPU** est disponible pour un déploiement portable
(cf. `TODO.md` §Phase 7) ; nécessite `nvidia-container-toolkit` sur l'hôte.
Tous les dossiers utilisent désormais des **volumes Docker nommés** (pas de bind mounts hôte) :
- `volume-audio` : fichiers `.wav`/`.txt` des voix (monté en écriture, interface y écrit)
- `volume-model` : modèle CosyVoice3 (~9,7 Go, téléchargé automatiquement au 1er lancement)
- `volume-texte` : fichiers `.md`/`.txt` du projet (solution d'upload interface)
- `volume-output` : générations audio `.wav`
- `volume-tmp` : fichiers temporaires

La variable `AUDIO_SRC_DIR` n'est plus utilisée ; les voix sont remplies directement
puisque les volumes sont writables dans le conteneur.

---

## 1. En un coup d'œil

1. Créez une **voix** par personnage (paire `.wav` + `.txt`) — §2.
2. Écrivez un **texte taggé** (format §3), en insérant les **tags émotion /
   non-verbaux** CosyVoice3 (§4) directement dans le texte.
3. Lancez la **génération** (CLI §5 ou GUI §6).
4. Récupérez le **montage `.wav`** dans `output/`.
5. **Première utilisation** : torch/torchvision/torchaudio (CUDA 13) sont déjà
   dans l'image Docker ; seul le **modèle CosyVoice3** reste à télécharger depuis
   le panneau **« 🧠 Modèles »** (source ModelScope ou Hugging Face, progression
   affichée). Si le volume `volume-model` est pré-rempli, il est détecté et rien
   n'est re-téléchargé.
6. **Versionning** : chaque push sur `main` incrémente automatiquement le numéro
   de version (M.m.f — Major uniquement sur demande explicite, mineur pour nouvelles
   fonctionnalités, patch pour corrections). Le workflow CI/CD met à jour `VERSION`,
   commit et build l'image Docker avec le bon tag.

---

## 2. Les voix (`voix/`)

Assistant rapide :

```bash
python -m tools.create_voix SOURCE.wav --nom LeNarrateur --start 12.5 --stop 30
```

Une voix = un **échantillon `.wav`** (~5–30 s, sans musique) + sa **transcription
`.txt`** exacte. Gardez l'échantillon **inférieur à 30 s** (limite de l'extraction
des tokens vocaux, cf. `vendor/CosyVoice/cosyvoice/cli/frontend.py`).

Fichier de listage `voix/voix.txt`, une entrée par ligne :

```
# [Nom] wav, txt[, pause_pré][, vitesse][, max_chars]
[LeNarrateur],  vb-voice/superama.wav, vb-voice/superama.txt
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
`VOICEBUILDER_AUDIO_DIR` (défaut : `~/Projets/Personnel (Fabrice)/vb-voice`) :

```bash
export VOICEBUILDER_AUDIO_DIR=~/Projets/Personnel\ \(Fabrice\)/vb-voice
```

Les chemins de `voix.txt` sont résolus dans l'ordre : dossier du projet, `voix/`,
puis ce dossier audio (`config.VOIX_SEARCH_DIRS`). Ex. une ligne simple :

```
[Michel], unirreductibleathee_phrase_01.wav
```

…est retrouvée dans `~/Projets/Personnel (Fabrice)/vb-voice/` si elle s'y trouve.

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
(`vendor/CosyVoice/cosyvoice/tokenizer/tokenizer.py`). À écrire **bruts, dans
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

> **Normalisation française** — avant la synthèse, le texte est automatiquement
> converti en texte lisible à voix haute (`engine/text_fr.py`). Le pipeline
> gère :
>
> - **Nombres** : `600` → « six cents », `7,7` → « sept virgule sept »,
>   `2 290` → « deux mille deux cent quatre-vingt-dix », `85 %` →
>   « quatre-vingt-cinq pour cent », `1er`/`4e` → « premier »/« quatrième ».
> - **Dates** : `2026-09-04`/`04/09/2026`/`4 sept. 2026` →
>   « quatre septembre deux mille vingt-six ».
> - **Heures** : `14h30`/`14:30` → « quatorze heures trente ».
> - **Abréviations** : `M.`→« monsieur », `Dr`→« docteur », `etc.`→
>   « et cetera », `c.-à-d.`→« c'est-à-dire », `n°`→« numéro », etc.
> - **Devises** : `10 €`→« dix euros », `10 $`→« dix dollars ».
> - **Chiffres romains** : `IV`→« quatre », `XLII`→« quarante-deux ».
> - **Ponctuation** : `…`→`...`, tirets/guillemets typographiques normalisés.
>
> Vous pouvez donc écrire vos chiffres, dates et abréviations en chiffres
> et sigles : ils seront lus correctement en français à l'écoute.

### CLI (`tools/gen_multi_voix.py`)

```bash
python -m tools.gen_multi_voix texte/chapitre.md \
    -o output/montage.wav \
    --voix voix/voix.txt --pause 0.45 --vitesse 1.0 --max-chars 260
```

Options : `--voix`, `--pause`, `--vitesse`, `--max-chars`, `--no-verify`,
`--texte-dir`. Sans `-o`, sortie `output/<nom-du-fichier>.wav`.

### GUI web (Gradio)

```bash
python -m app.web_app --host 127.0.0.1 --port 7860   # puis ouvrir http://127.0.0.1:7860
```

Onglets **Éditeur** (texte taggé, insertion `[Nom]:`, bouton **Générer**, aperçu du
montage), **Réglages** (pause, vitesse, max chars/bloc, vérification, `device`) et
**Assistant voix** (extraction + transcription Whisper d'un extrait).

### GUI serveur (référence — FastAPI)

```bash
python -m app.server --host 0.0.0.0 --port 8000   # puis ouvrir http://127.0.0.1:8000
```

Éditeur **plein écran** : barre d'outils avec un bouton par personnage, documents
du projet ou **fichier local**, boutons **＋ Nouveau** / **💾 Enregistrer dans le
projet**, réglages / aide / personnages en modales, thème clair/sombre via `🌙`.
Le bouton **« 🧠 Modèles »** gère le téléchargement du modèle CosyVoice3 au
premier lancement (source ModelScope ou Hugging Face, progression affichée) ;
le volume `volume-model` pré-rempli est détecté automatiquement.

L'onglet **Montage** se débloque après une génération et est organisé en deux
colonnes. Chaque bloc y est **écoutable dès la fin de sa génération** (sans
attendre la fin du montage complet) :
- **À gauche** — le **montage global** (lecteur de l'ensemble + bouton
  « 🔄 Re-créer le montage » + durée totale) et le **log de génération**.
- **À droite** — une **liste à ascenseur des blocs générés**. Chaque bloc est une
  carte contenant :
  - le **lecteur audio** du bloc (ajouté en direct, écoutable immédiatement) ;
  - le **texte** complet de la réplique sous le lecteur ;
  - un en-tête `N. Personnage · durée · nb de chars · voix` ;
  - les boutons **Regénérer ce bloc** et **Diviser ce bloc** (re-synthèse d'une
    moitié en cas de perte de contenu à la vérification).

Les actions affectent immédiatement le montage global (« Re-créer » le
réassemble après une modification de blocs).

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
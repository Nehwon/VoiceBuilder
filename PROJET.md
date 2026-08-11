# VoiceBuilder — Brief de projet (PROJET.md)

> Document d'orientation. Ce projet, initialement un **backend** de clonage de voix
> basé sur **OpenVoice v2 + MeloTTS** (`voicebuilder/`, `README.md`), est réorienté
> vers le **moteur CosyVoice3** (validé dans le sous-module `vendor/CosyVoice`) et prend une
> dimension **GUI d'édition multi-voix**. Le backend OpenVoice reste consultable
> comme historique ; le moteur actif est désormais CosyVoice.

---

## 1. Vision

Construire un outil local **d'écriture et de production audio multi-voix** :

> Importer un texte, le tagger confortablement dans un **éditeur Markdown efficace**,
> associer chaque réplique à une **voix** définie dans un fichier de texte (fichier de
> voix), puis **générer un audio** dans lequel chaque personnage parle avec **son**
> timbre — sans perte de contenu, avec une tonalité cohérente d'un segment à l'autre.

Le moteur (CosyVoice3-0.5B) et la logique de génération **ont été validés
expérimentalement** dans le sous-module `vendor/CosyVoice` :
- clonage zéro-shot à partir d'un **`.wav` + sa transcription `.txt`**,
- découpage en **blocs adaptatifs** avec **vérification automatique** pour ne perdre
  **aucune partie** du texte, tout en maximisant la **longueur des blocs** (moins de
  ruptures de ton entre segments).

---

## 2. Données : les voix (`voix/`)

Contrairement à OmniVoice (`voix/*.pt`, embeddings), chaque voix est représentée par
**un couple fichier `.wav` + fichier `.txt`** qui en est la transcription exacte.

- `.wav` — échantillon de référence (la voix à cloner), ~5–30 s, sans musique.
- `.txt` — transcription du contenu parlé ; accepte le format horodaté
  `[0000.00 - 0005.28] texte` (les estampilles sont ignorées au parsing).

Fichier de listage (`voix/voix.txt`), une entrée par ligne :

```
# [NomPersonnage] wav, txt[, pause_pré][, vitesse]
[LeNarrateur], vb-voice/superama.wav, vb-voice/superama.txt
[Michel],      vb-voice/unirreductibleathee_phrase_01.wav,
                       vb-voice/unirreductibleathee_phrase_01.txt
[Kaël-An],     echantillons/kael_an.wav, echantillons/kael_an.txt
[Lambda1],     echantillons/lambda_01.wav, echantillons/lambda_01.txt
```

- Les colonnes optionnelles (pause avant segment, taille de bloc max, vitesse…)
  surchargent les valeurs globales de l'application.
- Chemins relatifs au dossier projet (ou absolus).
- Au clonage, le prompt TTS =
  `"You are a helpful assistant.<|endofprompt|>" + texte_du_txt` (format CosyVoice3).

Un utilitaire `create-voix` extrait un segment `[start, stop]` d'un gros fichier
source, le transcrit via Whisper et range la paire `.wav`/`.txt` dans `voix/`.

---

## 3. Format de texte taggé (édition Markdown)

Hérité des conventions **OmniVoice** (`~/Projets/OmniVoice/texte/chapitre_1.md`) :

- Attribution d'une réplique : en tête de ligne **`[Nom]: texte`**.
- **Prose non attribuée / narrateur** : une ligne sans marqueur reprend le locuteur
  précédent (typiquement `[LeNarrateur]`) ; s'il n'en existe pas encore, erreur.
- **Tags non-verbaux / instructions inline** conservés dans le texte : `[sigh]`,
  `[confirmation-en]`, `[question-en]`… → mappés vers des instructions CosyVoice
  (émotion) ou ignorés selon la pertinence.
- `[stop]` : arrête la génération (le reste est ignoré).
- Lignes vides et commentaires `#` ignorés.

La qualité prosodique est portée par CosyVoice3.

---

## 4. Pipeline de génération multi-voix (logique validée)

Reprend la chaîne éprouvée dans `vendor/CosyVoice` et la rend **multi-voix** :

```
parse_texte(chapter.md, voix)                # -> [(personnage, texte), ...]
   │  [Nom]: change de voix ; ligne nue -> locuteur précédent ;
   │  tags non-verbaux inline conservés
regrouper par locuteur consécutif            # un seul appel TTS par bloc
                                            # (évite l'artefact de tête)
pour chaque bloc (personnage, texte):
   prompt = wav + txt de la voix[personnage]
   découper le bloc en sous-blocs adaptatifs (cible ≈ 260 carnets, réglable)
   pour chaque sous-bloc :
        audio = CosyVoice3.inference_zero_shot(texte, prompt, prompt_wav)
        si vérif activée : transcrire(audio)
           si contenu incomplet -> resplit le sous-bloc en deux, régénérer
   concaténer les sous-blocs du bloc
insérer une pause silencieuse (réglable, ex. 0.45 s) entre blocs
concaténer l'ensemble -> WAV final
```

Paramètres globaux : vitesse, pause inter-segments, `device` (cuda/cpu), `fp16`,
taille de sous-bloc max/min, seuil de vérification (défaut 0.85).

---

## 5. L'interface (GUI web)

Le GUI est une **application web** bâtie sur un **serveur HTTP local FastAPI**
(`app/server.py`), qui sert un frontend dédié (`app/web/`, éditeur CodeMirror) +
une API REST/SSE ; une interface alternative **Gradio** (`app/web_app.py`) reste
disponible. L'édition du texte taggé, le panneau des voix, les réglages et la
génération multi-voix se font dans le navigateur (le backend `engine/` est
appelé côté serveur).

Priorités de l'écran principal :

1. **Import** d'un texte brut (`.md`, `.txt`) et création du fichier de voix si absent.
2. **Éditeur Markdown efficace** :
   - surlignage syntaxique des `[Locuteur]:`, des tags inline, de la prose narrateur ;
   - autocomplétion des noms de voix définis dans `voix.txt` ;
   - insertion d'un bloc `[Nom]:` en un clic ;
   - numéros de ligne, pliage de paragraphes, navigation.
3. **Panneau des voix** : liste issue de `voix.txt`, pré-écoute du `.wav`, ajout via
   l'assistant « create-voix ».
4. **Génération multi-voix** : bouton lançant la pipeline du §4, avec :
   - **progression & log** : voyant par bloc (personnage, durée, nb de sous-blocs) ;
   - **vérification visible** : blocs revérifiés / rapprochés ;
   - **pré-écoute par segment** et **export** du montage final.
5. **Réglages** : vitesse globale, pause, device, fp16 (panneau avancé).

```bash
python -m app.server --host 0.0.0.0 --port 8000   # GUI serveur FastAPI (référence)
# ouvrir http://127.0.0.1:8000
python -m app.web_app --host 127.0.0.1 --port 7860 # GUI web Gradio (alternative)
# ouvrir http://127.0.0.1:7860
```

---

## 6. Architecture cible

```
VoiceBuilder/
├── PROJET.md                  # ce document
├── app/                       # GUI web (voir §5)
│   ├── server.py              #   GUI serveur FastAPI (interface de référence)
│   ├── web/                   #   frontend statique (HTML/CSS/JS + CodeMirror)
│   └── web_app.py             #   GUI web Gradio (alternative)
├── engine/                    # backend — moteur CosyVoice + logique
│   ├── cosyvoice_engine.py    #   wrapper AutoModel (CosyVoice3), zero_shot
│   ├── adaptive.py            #   découpage adaptatif vérifié
│   ├── multi.py               #   pipeline multi-voix (parse, regrouper, concat)
│   ├── voix.py                #   chargement/parsing de voix.txt
│   └── verifier.py            #   vérification par transcription Whisper
├── voix/                      # voix.txt + paires .wav/.txt
├── texte/                     # projets d'écriture taggés
├── output/                    # montages audio produits
├── vendor/CosyVoice/          # moteur CosyVoice en sous-module git
└── tools/
    ├── gen_multi_voix.py      # génération multi-voix (CLI)
    └── create_voix.py         # assistant création de voix (CLI)
```

Backend (CLI) et **GUI web** (serveur FastAPI en référence, Gradio en
alternative) exposés en bibliothèque (`engine/`) pour être pilotés
indifféremment — dans la lignée de l'existant `voicebuilder/`.

---

## 7. Contraintes & risques

- **Vitesse** : CosyVoice3 sans vLLM (chemin torch natif) est lent. Évaluer vLLM
  (~0.9–0.11) ou TensorRT en option pour réduire le temps de génération.
- **Français** : CosyVoice3 (multilingue) est requis ; CosyVoice2 reste trop faible et
  produirait un mauvais français.
- **Frontend de normalisation** : dépend de `wetext`/`ttsfrd` (réseau/token) ; en
  absence, `text_frontend=False` + token `"<|endofprompt|>"` inséré manuellement.
- **Fidélité** : le clonage dépend du `.wav` de référence (max ~30 s), du timbre et de
  la prosodie du locuteur modèle.
- **Intégration du moteur** : CosyVoice est un **sous-module git** du projet
  (`vendor/CosyVoice`), plus un clone voisin, pour une installation reproductible.
- **Portabilité / GPU** : un **conteneur Docker avec accès GPU** (NVIDIA
  `nvidia-container-toolkit`) doit être fourni pour déployer le moteur et le GUI
  FastAPI (cf. `TODO.md` §Phase 7).

---

## 8. Étapes

- [x] **M0** — Structurer `engine/` : portage de la logique validée (bloc adaptatif +
      vérif) en module réutilisable.
- [x] **M1** — `parse_texte` + `regrouper` + `multi.py` : générer un montage multi-voix
      depuis `texte/x.md` + `voix/voix.txt` (CLI `tools/gen_multi_voix.py`).
- [x] **M2** — Assistant « create-voix » (`tools/create_voix.py` : segment +
      transcription Whisper).
- [x] **M2.1–M2.3** — Raffinements de l'assistant : option `--lang`, alerte si le
      segment dépasse ~30 s, CLI/démo de bout en bout.
- [x] **M3** — Interface **GUI web (Gradio)** (`app/web_app.py`) : éditeur Markdown
      avec surlignage des `[Nom]`, panneau des voix, génération et pré-écoute par bloc.
- [x] **M4** — Affiner l'UX : autocomplétion, insertion 1-clic, réglages (pause,
      vitesse, max chars, Whisper, `device`), génération non bloquante + export.
- [ ] **M5** — (optionnel) accélération vLLM / TensorRT pour la génération
- [x] **M14** — CosyVoice intégré en **sous-module git** (`vendor/CosyVoice`), `engine/config.py` ajusté.
- [~] **M15** — **Conteneur Docker avec GPU** (NVIDIA Container Toolkit) : `Dockerfile` + `docker-compose.yml`, moteur + GUI FastAPI (image buildée, pipeline validé ; génération bout-en-bout à confirmer sur hôte avec toolkit).

## 9. Critères de succès

- **0 texte perdu** : la retranscription de l'audio contient intégralement le texte
  d'entrée (vérification automatique).
- **Ruptures de ton minimales** : nombre de blocs aussi faible que possible (blocs les
  plus longs avant apparition d'un drop).
- **Identité vocale** : chaque personnage porte un timbre reconnaissable et stable.
- **UX d'écriture fluide** : d'un texte brut on passe en quelques clics à un montage
  audio multi-voix complet.
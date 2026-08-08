# ROADMAP — VoiceBuilder

> Feuille de route orientée **objectifs de produit**, du moteur à la GUI.
> L'état détaillé par tâche est dans `TODO.md` ; l'historique des livrables
> dans `CHANGELOG.md`.

---

## Vision (rappel)

Outil local d'**écriture et de production audio multi-voix** : taguer un texte
dans un éditeur Markdown, associer chaque réplique à une voix définie par une paire
`.wav` + `.txt`, puis générer un montage dans lequel chaque personnage parle avec
**son** timbre — sans perte de contenu, avec une tonalité cohérente.

Moteur : **CosyVoice3 (Fun-CosyVoice3-0.5B)** — clonage zéro-shot `wav+txt`,
multilingue, découpage en blocs adaptatifs + vérification automatique (Whisper).

---

## Jalons

### M0 — Refonte du moteur en package
**Objectif** : porter la logique validée dans `~/Projets/CosyVoice` dans un
package `engine/` réutilisable, pilotable par CLI ou GUI.
**Livrable** : `engine/{config, voix, adaptive, verifier, cosyvoice_engine}.py`.
**Statut** : ✔ Terminé.

### M1 — Génération multi-voix (CLI)
**Objectif** : produire un montage depuis `texte/x.md` + `voix/voix.txt` sur le
moteur CosyVoice, sans perte de texte.
**Livrable** : `tools/gen_multi_voix.py`.
**Statut** : ✔ Terminé.

### M2 — Assistant de création de voix
**Objectif** : créer une voix en une commande (extraction d'un segment +
transcription Whisper + mise à jour de `voix.txt`).
**Livrable** : `tools/create_voix.py`.
**Statut** : ✔ Terminé (raffinements M2.1–M2.3 à suivre, voir TODO).

### M3 — Première maquille GUI
**Objectif** : import de texte, éditeur Markdown surlignant les `[Nom]`, panneau
des voix, génération + pré-écoute par bloc.
**Livrable** : `app/gui.py`.
**Statut** : planifié.

### M4 — Raffinements UX
**Objectif** : autocomplétion des noms de voix, réglages, vérification en temps
réel, export fluide.
**Statut** : planifié.

### M5 — Performance (optionnel)
**Objectif** : réduire le temps de génération via vLLM ou TensorRT ; frontend de
normalisation (`wetext`/`ttsfrd`) pour la prosodie FR.
**Statut** : exploration.

---

## Critères de succès (définition de « done »)

- **0 texte perdu** : la retranscription de l'audio contient intégralement le
  texte d'entrée (vérification automatique).
- **Ruptures de ton minimale** : le nombre de blocs est aussi faible que possible.
- **Identité vocale** : chaque personnage porte un timbre reconnaissable et
  stable.
- **UX fluide** : d'un texte brut à un montage multi-voix complet en quelques clics.
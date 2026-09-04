#!/usr/bin/env python3
"""Test rapide : vérification Whisper ON vs OFF (max_chars=600)."""
from __future__ import annotations
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import config, adaptive, cosyvoice_engine, verifier

TEXT = """\
Dans cet épisode de démonstration, nous allons explorer les mécanismes \
fondamentaux de la synthèse vocale par clonage. La technologie CosyVoice trois \
utilise un modèle de neural qui apprend à reproduire le timbre et la prosodie \
d'un locuteur à partir d'un simple extrait audio de quelques secondes. C'est un \
domaine en pleine évolution qui promet de révolutionner la façon dont nous \
interagissons avec les machines.

Le principe est le suivant : on fournit un fichier audio de référence accompagné \
de sa transcription textuelle. Le modèle analyse les caractéristiques acoustiques \
de la voix et les associe au contenu linguistique. Ensuite, pour tout nouveau \
texte, il peut générer un audio qui sonne comme le locuteur original, tout en \
prononçant des phrases qu'il n'a jamais entendues.

Ce qui est fascinant, c'est la capacité du modèle à préserver l'identité vocale \
même sur de longs passages. Les défis restent nombreux : gestion des pauses \
naturelles, cohérence émotionnelle, et surtout la fidélité du contenu. On ne \
doit perdre aucun mot, aucune syllabe, dans le processus de synthèse.

La vérification par transcription joue un rôle crucial ici. On utilise Whisper \
pour transcrire l'audio généré et on compare le résultat avec le texte d'origine. \
Si des mots manquent, le bloc est automatiquement resplitté et régénéré. C'est \
ce qu'on appelle le découpage adaptatif, une approche qui garantit la complétude \
du contenu tout en minimisant le nombre de segments audio produits."""


def main():
    from engine.voix import load_voix
    config.ensure_dirs()

    voices = load_voix()
    voice = list(voices)[0]
    print(f"Voix : {voice.name}")

    import re
    clean = re.sub(r"\[[^\]]+\]:\s*", "", TEXT).strip()
    print(f"Texte : {len(clean)} chars")

    print("Chargement modèle...")
    model, sr = cosyvoice_engine.load()

    def synth(t, _pw="", _pt=""):
        return cosyvoice_engine.synthesize(t, str(voice.wav), voice.system_prompt, model, sr)

    for label, do_verify in [("Vérif OFF", False), ("Vérif ON (seuil=0.85)", True)]:
        print(f"\n{'='*50}")
        print(f"  {label}")
        print(f"{'='*50}")
        config.VERIFY_THRESHOLD = 0.85
        t0 = time.time()
        audio = adaptive.synthesize_verified(
            clean, str(voice.wav), voice.system_prompt, synth, sr,
            max_chars=600, verify=do_verify,
        )
        elapsed = time.time() - t0
        dur = len(audio) / sr
        cov = verifier.coverage(clean, audio, sr)
        print(f"  Couverture : {cov:.2%}")
        print(f"  Durée audio : {dur:.1f} s")
        print(f"  Temps total : {elapsed:.1f} s")
        print(f"  RTF : {elapsed/dur:.2f}")

    print("\n✅ Terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

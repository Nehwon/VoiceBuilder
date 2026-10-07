"""Warmup au démarrage : précharge moteur + Whisper pour éviter la latence
de la première inférence (opt-in, ``VOICEBUILDER_WARMUP=1``).

Non bloquant (thread daemon : le serveur répond aussitôt) et best effort
(aucune erreur ne doit empêcher le démarrage). Sans modèle téléchargé ou
sans voix : étape sautée avec un log explicite.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("voicebuilder.warmup")

PHRASE_WARMUP = "Bonjour, le moteur est prêt."


def etapes(model_dir=None) -> dict:
    """Exécute les étapes de warmup de façon synchrone (testable).

    Renvoie ``{etape: True/False}``. Ne lève jamais.
    """
    from . import omnivoice_engine
    from . import verifier
    from .voix import load_voix

    resultat: dict = {}
    try:
        omnivoice_engine.load()
        resultat["modele"] = True
        log.info("Warmup : modèle OmniVoice chargé.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Warmup : modèle non chargé (%s).", exc)
        resultat["modele"] = False
        return resultat
    try:
        voix = load_voix()
        v = voix.get(voix.names()[0])
        model, sr = omnivoice_engine.load()
        omnivoice_engine.synthesize(
            PHRASE_WARMUP, str(v.wav), v.prompt_text, model, sr)
        resultat["synthese"] = True
        log.info("Warmup : micro-synthèse OK.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Warmup : micro-synthèse sautée (%s).", exc)
        resultat["synthese"] = False
    try:
        verifier._load_model()
        resultat["whisper"] = True
        log.info("Warmup : Whisper chargé.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Warmup : Whisper non chargé (%s).", exc)
        resultat["whisper"] = False
    return resultat


def lancer_warmup(model_dir=None) -> threading.Thread:
    """Lance le warmup en tâche de fond (daemon)."""
    th = threading.Thread(target=etapes, kwargs={"model_dir": model_dir},
                          daemon=True, name="warmup")
    th.start()
    log.info("Warmup démarré en tâche de fond.")
    return th

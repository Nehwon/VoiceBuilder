#!/usr/bin/env python3
"""GUI web (Gradio) de VoiceBuilder — éditeur multi-voix CosyVoice3.

Équivalent navigable de ``app/gui.py`` : éditeur de texte taggé, panneau des
voix (``voix.txt``), réglages, génération multi-voix via le backend ``engine``,
et assistant de création d'une voix (``tools.create_voix``) pour l'extraction +
transcription d'un extrait.

Lancement :
    python -m app.web_app [--host 127.0.0.1] [--port 7860] [--share]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import gradio as gr
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, multi
from engine.voix import load_voix
from tools import create_voix

# ---------------------------------------------------------------------------
# État partagé (chargé au démarrage, modifié par les réglages).
# ---------------------------------------------------------------------------

_voix = None     # engine.voix.Voices
_cfg = {
    "pause": config.DEFAULT_PAUSE,
    "speed": config.DEFAULT_SPEED,
    "max_chars": config.DEFAULT_MAX_BLOCK_CHARS,
    "verify": config.VERIFY_ENABLED,
    "device": config.DEFAULT_DEVICE,
}

DEVICES = ["cuda:0", "cpu"]


def recharge_voix() -> str:
    """Recharge ``voix.txt`` dans ``_voix`` et renvoie un résumé affiché."""
    global _voix
    config.ensure_dirs()
    try:
        _voix = load_voix()
        noms = _voix.names()
        return f"✔ **{len(noms)} voix** chargées : {', '.join(noms)}"
    except Exception as exc:  # noqa: BLE001
        _voix = None
        return f"❌ Erreur voix : {exc}"


def _voix_disponibles():
    """Noms des voix actuellement chargées."""
    return _voix.names() if _voix is not None else []


def _blocs() -> list:
    """Paires (affichage, bout « [Nom]: ``) pour le dropdown d'insertion."""
    return [(f"{n} — [{n}]: ", f"[{n}]: ") for n in _voix_disponibles()]


# ---------------------------------------------------------------------------
# Édition

def insere_bloc(choix, texte: str) -> str:
    """Colle le bloc ``[Nom]: `` sélectionné en fin de l'éditeur."""
    if not choix:
        raise gr.Error("Sélectionne une voix dans le panneau.")
    if texte and not texte.endswith("\n"):
        texte += "\n"
    return texte + choix


def reinit_editeur():
    "Renvoie un éditeur vide."
    return ""


# ---------------------------------------------------------------------------
# Génération multi-voix
# ---------------------------------------------------------------------------

def generer(texte: str, progress=gr.Progress()):
    """Génère le montage dans output/ et renvoie (audio, log).

    Gradio exécute déjà l'événement dans sa propre file d'attente, donc l'appel
    bloquant à ``multi.generate`` ne fige pas l'interface.
    """
    if not texte or not texte.strip():
        raise gr.Error("L'éditeur est vide.")
    if _voix is None:
        raise gr.Error("Aucune voix chargée (vérifie `voix/voix.txt`).")

    config.ensure_dirs()
    tmp = Path(tempfile.mkstemp(suffix=".md")[1])
    tmp.write_text(texte, encoding="utf-8")
    sortie = config.OUTPUT_DIR / "montage_web.wav"
    sortie.parent.mkdir(parents=True, exist_ok=True)

    try:
        progress(0.0, desc="Chargement du modèle CosyVoice3…")
        res = multi.generate(
            str(tmp), _voix, out=str(sortie),
            pause=_cfg["pause"],
            speed=_cfg["speed"],
            max_block_chars=_cfg["max_chars"],
            verify=_cfg["verify"],
            device=_cfg["device"],
            fp16=False,
            verbose=True,
        )
        progress(1.0)
    except Exception as exc:  # noqa: BLE001
        raise gr.Error(f"Génération échouée : {exc}")
    finally:
        tmp.unlink(missing_ok=True)

    audio = res["audio"], res["sample_rate"]
    lignes = "\n".join(f"- **{p}** : {c} chars, {d} s" for p, c, d in res["blocs"])
    log = (f"Durée totale : **{res['duration']} s** — {len(res['blocs'])} bloc(s).\n"
           f"Fichier : `{res['out']}`\n\n{lignes}")
    return audio, log


# ---------------------------------------------------------------------------
# Assistant de création d'une voix
# ---------------------------------------------------------------------------

def creer_voix(source, nom, t_start, t_stop, progress=gr.Progress()):
    """Extrait un segment source et le transcrit via Whisper (proposition)."""
    if not source:
        raise gr.Error("Choisis un fichier audio source (wav/flac/mp3…).")
    if not nom:
        raise gr.Error("Donne un nom au personnage.")

    progress(0.2, desc="Extraction du segment…")
    try:
        audio, sr = create_voix.extract_segment(source, float(t_start), float(t_stop))
    except Exception as exc:  # noqa: BLE001
        raise gr.Error(f"Extraction : {exc}")

    progress(0.6, desc="Transcription Whisper (fr)…")
    try:
        from engine import verifier
        texte = verifier.transcribe(np.asarray(audio), int(sr)).strip()
    except Exception as exc:  # noqa: BLE001
        raise gr.Error(f"Transcription : {exc}")

    progress(1.0)
    detail = (f"Segment extrait : **{len(audio) / sr:.2f} s** @ {sr} Hz.\n"
              "⚠️ Cette vue d'essai ne **sauvegarde pas** encore `voix/` : un clic "
              "« ●naire » est à brancher (voir phase M2).")
    return texte, detail


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

def construire():
    with gr.Blocks(title="VoiceBuilder — éditeur multi-voix (CosyVoice3)",
                   theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# 🎙️ VoiceBuilder\n"
            "Éditeur de texte **multi-voix** local (moteur **CosyVoice3**). "
            "Tague `[Personnage]:` puis génère le montage."
        )
        statut = gr.Markdown(recharge_voix())

        with gr.Tab("Éditeur"):
            with gr.Row():
                with gr.Column(scale=3):
                    editeur = gr.Textbox(
                        lines=20, placeholder="[Narrateur]: …\n\n[David]: Salut !",
                        label="Texte taggé", show_copy_button=True,
                    )
                    out_audio = gr.Audio(label="Montage généré", type="numpy")
                    log = gr.Textbox(label="Journal", lines=5, interactive=False)
                with gr.Column(scale=1):
                    insert = gr.Dropdown(choices=_blocs(), label="Voix → bloc")
                    ins_btn = gr.Button("Insérer [Nom]:", variant="primary")
                    gen_btn = gr.Button("Générer", variant="primary")
                    gr.Button("Réinitialiser").click(
                        reinit_editeur, outputs=editeur)

            ins_btn.click(insere_bloc, [insert, editeur], editeur)
            gen_btn.click(generer, editeur, [out_audio, log])

        with gr.Tab("Réglages"):
            pause = gr.Number(value=_cfg["pause"], label="Pause (s)", step=0.05)
            vitesse = gr.Slider(0.6, 1.6, value=_cfg["speed"], step=0.05, label="Vitesse")
            max_t = gr.Number(value=_cfg["max_chars"], label="Max chars/bloc", precision=0)
            verifier = gr.Checkbox(value=_cfg["verify"], label="Vérification Whisper FR")
            device = gr.Dropdown(DEVICES, value=_cfg["device"], label="Device")
            apply = gr.Button("Enregistrer les réglages")

            def sauver(pause, vitesse, max_t, verifier, device):
                _cfg["pause"] = float(pause)
                _cfg["speed"] = float(vitesse)
                _cfg["max_chars"] = int(max_t)
                _cfg["verify"] = bool(verifier)
                _cfg["device"] = str(device)
                gr.Info("Réglages enregistrés ✓")

            apply.click(
                sauver, [pause, vitesse, max_t, verifier, device], None)

        with gr.Tab("Assistant voix"):
            src = gr.File(label="Source (wav/flac/mp3…)",
                          file_types=[".wav", ".flac", ".mp3"])
            nom = gr.Textbox(label="Nom du personnage")
            start_ = gr.Number(value=0, label="Début (s)", step=0.1)
            stop_ = gr.Number(label="Fin (s)", step=0.1, value=np.nan)
            btn = gr.Button("Extraire & transcrire", variant="primary")
            out_txt = gr.Textbox(label="Transcription Whisper", lines=5)
            detail = gr.Markdown()
            btn.click(creer_voix, [src, nom, start_, stop_], [out_txt, detail])

    return demo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GUI web VoiceBuilder (Gradio)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args(argv)

    config.ensure_dirs()
    recharge_voix()               # charge d'emblée les voix au démarrage.

    demo = construire()
    demo.launch(server_name=args.host, server_port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
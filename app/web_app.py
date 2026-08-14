#!/usr/bin/env python3
"""GUI web (Gradio) de VoiceBuilder — éditeur multi-voix CosyVoice3.

Onglets : éditeur de texte taggé, réglages, assistant de voix.

Fonctions propres à la GUI web :
- choix du **dossier des voix** (``VOICEBUILDER_AUDIO_DIR) dans les réglages,
  avec persistance dans ``voicebuilder_settings.json`` ;
- **génération automatique** de ``voix.txt`` depuis ce dossier (couples
  ``.wav`` + ``.txt``) s'il est absent ;
- **nommage** des voix du dossier dans l'assistant voix.

Lancement :
    python -m app.web_app [--host 127.0.0.1] [--port 7860] [--share]
"""
from __future__ import annotations

import argparse
import json
import requests
import sys
import tempfile
import time
from pathlib import Path

import gradio as gr
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, multi, voix
from engine.voix import load_voix

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
_PERSISTANCE = config.PROJECT_ROOT / "voicebuilder_settings.json"


def _charger_persistance() -> dict:
    try:
        return json.loads(_PERSISTANCE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _sauver_persistance(partial: dict) -> None:
    data = _charger_persistance()
    data.update(partial)
    _PERSISTANCE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")


def recharge_voix() -> str:
    """Recharge ``voix.txt`` dans ``_voix`` et renvoie un résumé affiché."""
    global _voix
    config.ensure_dirs()
    try:
        _voix = load_voix()
        noms = _voix.names()
        return f"✔ **{len(noms)}** voix chargées : {', '.join(noms)}"
    except Exception as exc:  # noqa: BLE001
        _voix = None
        return f"❌ Erreur voix : {exc}"


def _voix_disponibles():
    return _voix.names() if _voix is not None else []


def _blocs() -> list:
    """Paires (affichage, valeur) pour le dropdown d'insertion de bloc."""
    return [(f"{n} : [{n}]: ", f"[{n}]: ") for n in _voix_disponibles()]


def bootstrap() -> str:
    """Applique le dossier sauvegardé et génère ``voix.txt`` si absent."""
    data = _charger_persistance()
    if data.get("audio_dir") and Path(data["audio_dir"]).is_dir():
        config.set_audio_dir(data["audio_dir"])
    config.ensure_dirs()
    voix.generer_voix_txt()          # crée voix.txt s'il n'existe pas
    return recharge_voix()


# ---------------------------------------------------------------------------
# Édition
# ---------------------------------------------------------------------------

def insere_bloc(choix, texte: str) -> str:
    if not choix:
        raise gr.Error("Sélectionne une voix dans le panneau.")
    if texte and not texte.endswith("\n"):
        texte += "\n"
    return texte + choix


# ---------------------------------------------------------------------------
# Génération multi-voix
# ---------------------------------------------------------------------------

def generer(texte: str, progress=gr.Progress()):
    """Génère le montage dans output/ et renvoie (audio, log)."""
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
            pause=_cfg["pause"], speed=_cfg["speed"],
            max_block_chars=_cfg["max_chars"],
            verify=_cfg["verify"], device=_cfg["device"],
            fp16=False, verbose=True,
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
# Assistant : nommage des voix déjà présentes dans le dossier
# ---------------------------------------------------------------------------

def tableau_couples() -> list:
    """Lignes ``[nom, fichier.wav, fichier.txt]`` des couples du dossier."""
    return [[voix.default_nom(wav), wav.name, txt.name]
            for wav, txt in voix.collect_couples()]


def enregistrer_noms(table) -> str:
    """Écrit ``voix.txt`` depuis la table éditée, puis recharge les voix."""
    if not table:
        raise gr.Error("Aucune ligne : le dossier des voix est vide.")
    entries = []
    for ligne in table:
        if not ligne or len(ligne) < 3:
            continue
        nom = str(ligne[0]).strip()
        if not nom:
            continue
        entries.append((nom, ligne[1], ligne[2]))
    voix.ecrire_voix_txt(entries)
    return recharge_voix()


# ---------------------------------------------------------------------------
# Création d'une voix (extraction + transcription d'un extrait)
# ---------------------------------------------------------------------------

def creer_voix(source, nom, t_start, t_stop, progress=gr.Progress()):
    if not source:
        raise gr.Error("Choisis un fichier audio source (wav/flac/mp3…).")
    if not nom:
        raise gr.Error("Donne un nom au personnage.")
    from tools import create_voix

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
              "⚠️ Cette vue d'essai ne sauvegarde pas encore le `.wav`/`.txt` "
              "dans le dossier des voix.")
    return texte, detail


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def appliquer_dossier(dossier_dir: str) -> tuple:
    """Change le dossier des voix, le persiste, (re)génère voix.txt."""
    chemin = dossier_dir.strip() or str(config.VOIX_AUDIO_DIR)
    config.set_audio_dir(chemin)
    _sauver_persistance({"audio_dir": str(config.VOIX_AUDIO_DIR)})
    voix.generer_voix_txt()
    return recharge_voix(), _blocs()


def sauver(pause, vitesse, max_t, verifier, device):
    _cfg["pause"] = float(pause)
    _cfg["speed"] = float(vitesse)
    _cfg["max_chars"] = int(max_t)
    _cfg["verify"] = bool(verifier)
    _cfg["device"] = str(device)
    gr.Info("Réglages enregistrés ✓")


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
        statut = gr.Markdown(bootstrap())

        with gr.Tab("Éditeur"):
            with gr.Row():
                with gr.Column(scale=3):
                    editeur = gr.Textbox(
                        lines=20,
                        placeholder="[Narrateur]: …\n\n[David]: Salut !",
                        label="Texte taggé", show_copy_button=True,
                    )
                    out_audio = gr.Audio(label="Montage généré", type="numpy")
                    log = gr.Textbox(label="Journal", lines=5, interactive=False)
                with gr.Column(scale=1):
                    insert = gr.Dropdown(choices=_blocs(), label="Voix → bloc")
                    gr.Button("Insérer [Nom]:").click(
                        insere_bloc, [insert, editeur], editeur)
                    gen_btn = gr.Button("Générer", variant="primary")
                    gen_btn.click(generer, editeur, [out_audio, log])

        with gr.Tab("Réglages"):
            gr.Markdown("### Génération")
            pause = gr.Number(value=_cfg["pause"], label="Pause (s)", step=0.05)
            vitesse = gr.Slider(0.6, 1.6, value=_cfg["speed"], step=0.05,
                                label="Vitesse")
            max_t = gr.Number(value=_cfg["max_chars"], label="Max chars/bloc",
                              precision=0)
            verif = gr.Checkbox(value=_cfg["verify"],
                                label="Vérification Whisper FR")
            device = gr.Dropdown(DEVICES, value=_cfg["device"], label="Device")
            gr.Button("Enregistrer les réglages").click(
                sauver, [pause, vitesse, max_t, verif, device], None)

            gr.Markdown("---\n### Dossier des voix")
            dossier_dir = gr.Textbox(
                label="Dossier des fichiers .wav/.txt",
                value=str(config.VOIX_AUDIO_DIR),
            )
            gr.Button("Appliquer le dossier", variant="primary").click(
                appliquer_dossier, dossier_dir, [statut, insert])
            gr.Markdown("Génère `voix.txt` depuis ce dossier s'il n'existe pas "
                        "(un couple `nom.wav` + `nom.txt` par voix).")

        with gr.Tab("Assistant voix"):
            gr.Markdown("### Nommer les voix déjà dans le dossier")
            table = gr.Dataframe(
                headers=["[] Personnage", "fichier.wav", "fichier.txt"],
                value=tableau_couples(),
                interactive=True, type="array",
            )
            gr.Button("Enregistrer les noms → voix.txt",
                      variant="primary").click(enregistrer_noms, table, statut)

            gr.Markdown("---\n### Créer une voix (extraction + transcription)")
            src = gr.File(label="Source (wav/flac/mp3…)",
                          file_types=[".wav", ".flac", ".mp3"])
            nom = gr.Textbox(label="Nom du personnage")
            start_ = gr.Number(value=0, label="Début (s)", step=0.1)
            stop_ = gr.Number(label="Fin (s)", step=0.1, value=np.nan)
            out_txt = gr.Textbox(label="Transcription Whisper", lines=4)
            gr.Button("Extraire & transcrire",
                      variant="primary").click(
                creer_voix, [src, nom, start_, stop_], out_txt)

    # --- Onglet Wizard installation ---
    with gr.Tab("Wizard install"):

        # Étape 1 : Installer torch
        gr.Markdown("### 1. Installer torch, torchvision, torchaudio")
        torch_status = gr.Textbox(label="Statut torch", interactive=False)
        torch_install_btn = gr.Button("Installer torch", variant="primary")

        def install_torch():
            import requests
            import json
            try:
                r = requests.post("http://127.0.0.1:8000/api/torch/install", timeout=30)
                if r.status_code == 200:
                    jobid = r.json().get("id", "")
                    # Poll for completion
                    for _ in range(30):  # max 30 seconds wait
                        r2 = requests.get(f"http://127.0.0.1:8000/api/torch/status", timeout=1)
                        status = r2.json()
                        if status.get("status") == "installed":
                            return f"✔ torch {status.get('version', 'inconnue')} installé"
                        elif status.get("status") == "error":
                            return f"❌ Erreur : {status.get('error', 'inconnue')}"
                        import time
                        time.sleep(1)
                    return "⏳ En attente d'installation..."
                else:
                    return f"❌ Erreur API: {r.text}"
            except Exception as e:
                return f"❌ Erreur connexion: {e}"

        torch_install_btn.click(
            fn=install_torch,
            outputs=torch_status,
        )

        # Étape 2 : Télécharger les modèles
        gr.Markdown("### 2. Télécharger le modèle CosyVoice3")
        model_source = gr.Dropdown(choices=["modelscope", "huggingface"],
                                   value="modelscope", label="Source")
        model_status = gr.Textbox(label="Statut modèle", interactive=False)
        model_download_btn = gr.Button("Télécharger le modèle", variant="primary")

        def download_model(source):
            import requests
            import json
            try:
                r = requests.post(
                    "http://127.0.0.1:8000/api/modeles/telecharger",
                    json={"source": source},
                    timeout=60
                )
                if r.status_code == 200:
                    jid = r.json().get("id", "")
                    # Poll for completion
                    for _ in range(60):  # max 60 seconds wait
                        r2 = requests.get(f"http://127.0.0.1:8000/api/modeles", timeout=1)
                        modes = r2.json()
                        if modes.get("dossier"):
                            return f"✔ Modèle téléchargé : {modes.get('dossier')}"
                        import time
                        time.sleep(1)
                    return "⏳ Téléchargement en cours..."
                else:
                    return f"❌ Erreur API: {r.text}"
            except Exception as e:
                return f"❌ Erreur connexion: {e}"

        model_download_btn.click(
            fn=lambda src: download_model(src),
            outputs=model_status,
        )

    return demo


def api_torch_install_call():
    """Call the torch install API and return status + job id."""
    import requests
    try:
        r = requests.get("http://127.0.0.1:8000/api/torch/install")
        if r.status_code == 200:
            return json.dumps(r.json())
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    return json.dumps({"status": "unknown"})


def api_modele_telecharger_call(source):
    """Call the model download API."""
    import requests
    try:
        r = requests.post("http://127.0.0.1:8000/api/modeles/telecharger", json={"source": source})
        if r.status_code == 200:
            return json.dumps(r.json())
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    return json.dumps({"status": "unknown"})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GUI web VoiceBuilder (Gradio)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args(argv)

    demo = construire()    # bootstrap() applique le dossier et génère voix.txt
    demo.launch(server_name=args.host, server_port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
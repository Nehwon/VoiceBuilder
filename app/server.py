#!/usr/bin/env python3
"""Serveur HTTP local (FastAPI) du GUI VoiceBuilder — M7.

Sert un frontend statique (``app/web/``) et expose une API REST JSON :

- ``/api/etat``          état courant (dossier des voix, présence de ``voix.txt``).
- ``/api/config``        lecture/écriture (dossier des voix + persistance).
- ``/api/voix``          liste des voix ; ``/api/voix/*`` (nommage, pré-écoute).
- ``/api/generer``       génération en tâche de fond + progression (SSE).
- ``/api/document/*``    ouvrir / enregistrer automatiquement (copie de travail).

Lancement :
    python -m app.server [--host 127.0.0.1] [--port 8000]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import queue
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, multi, voix
from engine.voix import load_voix

# ---------------------------------------------------------------------------
# Réglages persistants (mêmes clés que le GUI Gradio).
# ---------------------------------------------------------------------------

_PERSISTANCE = config.PROJECT_ROOT / "voicebuilder_settings.json"
_BROUILLONS = config.TEXTE_DIR / "brouillons"

app = FastAPI(title="VoiceBuilder", version="0.1.0")


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


def _voix():
    return load_voix()


def _etat() -> dict:
    """État général : dossier des voix, présence de voix.txt, liste des voix."""
    d = _charger_persistance().get("audio_dir") or str(config.VOIX_AUDIO_DIR)
    config.set_audio_dir(d)
    config.ensure_dirs()
    _BROUILLONS.mkdir(parents=True, exist_ok=True)
    fichier_voix = bool(config.VOIX_FILE.exists())
    if fichier_voix:
        try:
            noms = _voix().names()
        except Exception as exc:  # noqa: BLE001
            return {"audio_dir": d, "voix_file": False, "voix": [],
                    "erreur": f"{config.VOIX_FILE.name} invalide : {exc}"}
    else:
        noms = []
    return {"audio_dir": d, "voix_file": fichier_voix, "voix": noms,
            "erreur": None}


def _bootstrap() -> None:
    """Applique le dossier sauvegardé et génère ``voix.txt`` s'il manque."""
    data = _charger_persistance()
    if data.get("audio_dir"):
        chemin = data["audio_dir"]
        if not Path(chemin).is_dir():
            print(f"⚠️  dossier audio {chemin!r} introuvable", file=sys.stderr)
        else:
            config.set_audio_dir(chemin)
    config.ensure_dirs()
    _BROUILLONS.mkdir(parents=True, exist_ok=True)
    voix.generer_voix_txt()      # génère depuis le dossier s'il n'existe pas


# ---------------------------------------------------------------------------
# Modèles API
# ---------------------------------------------------------------------------

class ConfigIn(BaseModel):
    audio_dir: str | None = None


class NommageIn(BaseModel):
    entries: list[list[str]]


class GenererIn(BaseModel):
    texte: str
    pause: float = 0.5
    vitesse: float = 1.0
    max_chars: int = 260
    verify: bool = True
    device: str = "cuda:0"


class DocumentOuvrirIn(BaseModel):
    fichier: str

class DocumentSaveIn(BaseModel):
    fichier: str
    contenu: str


# ---------------------------------------------------------------------------
# API : voix & config
# ---------------------------------------------------------------------------

@app.get("/api/etat")
def api_etat():
    return _etat()


@app.post("/api/config")
def api_config(payload: ConfigIn):
    if payload.audio_dir:
        chemin = payload.audio_dir.strip()
        if not Path(chemin).is_dir():
            raise HTTPException(400, f"Dossier introuvable : {chemin}")
        config.set_audio_dir(chemin)
        _sauver_persistance({"audio_dir": str(config.VOIX_AUDIO_DIR)})
    config.ensure_dirs()
    voix.generer_voix_txt()          # (re)génère si voix.txt absent
    return _etat()


@app.get("/api/voix")
def api_voix():
    try:
        v = _voix()
        return [{"nom": ve.name, "wav": str(ve.wav), "txt": str(ve.txt)}
                for ve in v]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))


@app.get("/api/voix/couples")
def api_couples():
    return [[voix.default_nom(w), w.name, t.name]
            for w, t in voix.collect_couples()]


@app.post("/api/voix/nommer")
def api_nommer(payload: NommageIn):
    voix.ecrire_voix_txt([tuple(e) for e in payload.entries])
    return _etat()


@app.get("/api/voix/wav")
def api_wav(nom: str):
    try:
        v = _voix().get(nom)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, f"Voix inconnue : {nom}")
    if not Path(v.wav).exists():
        raise HTTPException(404, f"Wav absent : {v.wav}")
    return FileResponse(v.wav, media_type="audio/wav")


# ---------------------------------------------------------------------------
# Génération asynchrone (SSE)
# ---------------------------------------------------------------------------

_jobs: dict[int, dict] = {}
_jobid = itertools.count()


@app.post("/api/generer")
def api_generer(payload: GenererIn):
    texte = (payload.texte or "").strip()
    if not texte:
        raise HTTPException(400, "Éditeur vide.")
    try:
        _voix()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Aucune voix chargée : {exc}")

    config.ensure_dirs()
    tmp = Path(tempfile.mkstemp(suffix=".md")[1])
    tmp.write_text(texte, encoding="utf-8")

    jid = next(_jobid)
    sortie = config.OUTPUT_DIR / f"montage_{jid}.wav"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    q: "queue.Queue[tuple]" = queue.Queue()
    job = {"status": "running", "queue": q, "result": None,
           "error": None, "tmp": tmp, "out": sortie}
    _jobs[jid] = job

    def _run():
        try:
            res = multi.generate(
                str(tmp), _voix(), out=str(sortie),
                pause=payload.pause, speed=payload.vitesse,
                max_block_chars=payload.max_chars,
                verify=payload.verify, device=payload.device,
                fp16=False, verbose=False,
                progress=lambda b: q.put(("bloc", b)),
            )
            job["result"] = res
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            job["status"] = "error"
        finally:
            q.put(("fin", None))

    threading.Thread(target=_run, daemon=True).start()
    return {"id": jid, "out": str(sortie)}


@app.get("/api/generer/{jid}/stream")
def api_stream(jid: int):
    job = _jobs.get(jid)
    if not job:
        raise HTTPException(404, "Travail inconnu.")

    def gen():
        yield ": connected\n\n"
        while job["status"] == "running":
            try:
                kind, data = job["queue"].get(timeout=0.5)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if kind == "bloc":
                yield f"event: bloc\ndata: {json.dumps(data)}\n\n"
            elif kind == "done":
                break
        if job["error"]:
            yield f"event: error\ndata: {json.dumps({'error': job['error']})}\n\n"
        elif job["result"]:
            r = job["result"]
            data = json.dumps({
                "duree": r["duration"], "out": r["out"], "blocs": r["blocs"],
            })
            yield f"event: result\ndata: {data}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/generer/{jid}/result")
def api_result(jid: int):
    job = _jobs.get(jid)
    if not job or job["status"] != "done" or not job["result"]:
        raise HTTPException(404, "Résultat indisponible.")
    return FileResponse(job["out"], media_type="audio/wav",
                        filename=Path(job["out"]).name)


# ---------------------------------------------------------------------------
# Document de projet (ouvrir / auto-enregistrement d'une copie de travail)
# ---------------------------------------------------------------------------

def _chemin_projet(fichier: str) -> Path:
    p = (config.TEXTE_DIR / fichier).resolve()
    if not p.is_relative_to(config.TEXTE_DIR.resolve()):
        raise HTTPException(400, "Fichier hors du dossier projet.")
    if not p.exists():
        raise HTTPException(404, f"Fichier introuvable : {fichier}")
    return p


@app.get("/api/documents")
def api_documents():
    config.ensure_dirs()
    fichiers = sorted(
        p.name for p in config.TEXTE_DIR.glob("*")
        if p.suffix in (".md", ".txt") and p.is_file()
    )
    return {"documents": fichiers}


@app.post("/api/document/ouvrir")
def api_ouvrir(payload: DocumentOuvrirIn):
    p = _chemin_projet(payload.fichier)
    _BROUILLONS.mkdir(parents=True, exist_ok=True)
    brouillon = _BROUILLONS / p.name
    contenu = brouillon.read_text(encoding="utf-8") if brouillon.exists() \
        else p.read_text(encoding="utf-8")
    if not brouillon.exists():
        brouillon.write_text(contenu, encoding="utf-8")
    return {"fichier": payload.fichier, "brouillon": brouillon.name,
            "contenu": contenu}


@app.post("/api/document/enregistrer")
def api_enregistrer(payload: DocumentSaveIn):
    _chemin_projet(payload.fichier)              # valide le nom
    _BROUILLONS.mkdir(parents=True, exist_ok=True)
    brouillon = _BROUILLONS / payload.fichier
    brouillon.write_text(payload.contenu, encoding="utf-8")
    return {"enregistre": brouillon.name}


# ---------------------------------------------------------------------------
# Frontend statique & lancement
# ---------------------------------------------------------------------------

_WEB = Path(__file__).resolve().parent / "web"
app.mount("/web", StaticFiles(directory=_WEB), name="web")


@app.get("/")
def home():
    return FileResponse(_WEB / "index.html")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GUI serveur VoiceBuilder (FastAPI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    _bootstrap()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
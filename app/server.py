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
import csv
from pathlib import Path

import shutil
import time

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, cosyvoice_engine, modeles, multi, voix
from engine.voix import load_voix

# ---------------------------------------------------------------------------
# Réglages persistants (mêmes clés que le GUI Gradio).
# ---------------------------------------------------------------------------

_PERSISTANCE = config.PROJECT_ROOT / "voicebuilder_settings.json"
_BROUILLONS = config.TEXTE_DIR / "brouillons"
_ARCHIVES = config.TEXTE_DIR / "archives"

app = FastAPI(title="VoiceBuilder", version="0.1.0")


@app.middleware("http")
async def _frontend_no_store(request, call_next):
    """Empêche le cache navigateur sur le frontend (dev : toujours à jour)."""
    response = await call_next(request)
    if request.url.path.startswith(("/web/", "/")):
        response.headers["Cache-Control"] = "no-store"
    return response


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
    if not Path(d).is_dir():
        # dossier persisté invalide (ex. chemin hôte repris dans l'image) :
        # on revient au défaut (VOICEBUILDER_AUDIO_DIR) au lieu de casser la résolution
        d = str(config.VOIX_AUDIO_DIR)
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
    _ARCHIVES.mkdir(parents=True, exist_ok=True)
    voix.generer_voix_txt()      # génère depuis le dossier s'il n'existe pas


# ---------------------------------------------------------------------------
# Installation torch & modèles API
# ---------------------------------------------------------------------------
import subprocess

_torch_jobs: dict[int, dict] = {}
_torch_jobid = itertools.count()


def _check_torch():
    """Vérifie si torch est importable et renvoie le statut."""
    import importlib
    try:
        import torch
        return {"status": "installed", "version": torch.__version__}
    except ImportError:
        return {"status": "not_installed"}


@app.get("/api/torch/status")
def api_torch_status():
    return _check_torch()


@app.post("/api/torch/install")
def api_torch_install():
    """Installe torch, torchvision, torchaudio si pas déjà installé."""
    global _torch_jobs, _torch_jobid
    if _torch_jobs and any(j["status"] == "running" for j in _torch_jobs.values()):
        raise HTTPException(400, "Une installation torch est déjà en cours.")
    jid = next(_torch_jobid)
    q: "queue.Queue[tuple]" = queue.Queue()
    job = {"status": "running", "queue": q, "error": None, "result": None}
    _torch_jobs[jid] = job

    def _run():
        try:
            import sys
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install",
                 "--extra-index-url", "https://download.pytorch.org/whl/cu130",
                 "torch==2.13.0", "torchaudio==2.11.0", "torchvision==0.28.0"]
            )
            job["result"] = {"version": torch.__version__}
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            job["status"] = "error"
        finally:
            q.put("fin")

    threading.Thread(target=_run, daemon=True).start()
    return {"id": jid}


@app.get("/api/torch/install/{jid}/stream")
def api_torch_install_stream(jid: int):
    job = _torch_jobs.get(jid)
    if not job:
        raise HTTPException(404, "Téléchargement torch inconnu.")

    def gen():
        yield ": connected\n\n"
        while job["status"] == "running":
            try:
                kind, data = job["queue"].get(timeout=0.5)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if kind == "fin":
                break
        if job["error"]:
            yield f"event: error\ndata: {json.dumps({'error': job['error']})}\n\n"
        elif job["result"]:
            r = job["result"]
            yield f"event: result\ndata: {json.dumps(r)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Modèles API
# ---------------------------------------------------------------------------

class ConfigIn(BaseModel):
    audio_dir: str | None = None


class ModeleIn(BaseModel):
    source: str | None = None  # "modelscope" | "huggingface"


class NommageIn(BaseModel):
    entries: list[list[str]]


class GenererIn(BaseModel):
    texte: str
    personnages: dict[str, str] = {}
    pause: float = 0.5
    vitesse: float = 1.0
    max_chars: int = 600
    verify: bool = True
    device: str = "cuda:0"


class PersonnagesSaveIn(BaseModel):
    fichier: str
    personnages: dict[str, str]


class DocumentOuvrirIn(BaseModel):
    fichier: str

class DocumentSaveIn(BaseModel):
    fichier: str
    contenu: str

class DocumentSauverIn(BaseModel):
    fichier: str
    contenu: str


class DocumentActionIn(BaseModel):
    fichier: str


class DocumentRenommerIn(BaseModel):
    fichier: str
    nouveau: str


class DocumentDupliquerIn(BaseModel):
    fichier: str
    nouveau: str | None = None


class VoixSupprimerIn(BaseModel):
    nom: str


class VoixNettoyerIn(BaseModel):
    nom: str
    mode: str | None = "auto"   # auto | cuda_fp16 | cuda_fp32 | cpu


class VoixNettoyerSauverIn(BaseModel):
    nom: str                    # nom de la voix nettoyée à créer (sans crochets)


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


# ---------------------------------------------------------------------------
# Modèle CosyVoice3 (hors image — téléchargé au premier lancement, M15)
# ---------------------------------------------------------------------------

@app.get("/api/modeles")
def api_modeles():
    return modeles.infos()


_model_jobs: dict[int, dict] = {}
_model_jobid = itertools.count()


@app.post("/api/modeles/telecharger")
def api_modele_telecharger(payload: ModeleIn):
    if modeles.modele_present():
        raise HTTPException(400, "Le modèle CosyVoice3 est déjà présent.")
    if _model_jobs and any(j["status"] == "running" for j in _model_jobs.values()):
        raise HTTPException(400, "Un téléchargement est déjà en cours.")
    source = (payload.source or config.MODEL_SOURCE).lower()
    if source not in ("modelscope", "huggingface"):
        raise HTTPException(400, "Source inconnue : modelscope | huggingface")

    jid = next(_model_jobid)
    q: "queue.Queue[tuple]" = queue.Queue()
    job = {"status": "running", "source": source, "queue": q,
           "error": None, "result": None}
    _model_jobs[jid] = job

    def _run():
        def progress(pct, octets):
            q.put(("prog", {"pct": round(pct, 1), "octets": octets}))
        try:
            dest = modeles.telecharger(source=source, progress=progress)
            job["result"] = {"dossier": str(dest)}
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            job["status"] = "error"
        finally:
            q.put(("fin", None))

    threading.Thread(target=_run, daemon=True).start()
    return {"id": jid}


@app.get("/api/modeles/{jid}/stream")
def api_modele_stream(jid: int):
    job = _model_jobs.get(jid)
    if not job:
        raise HTTPException(404, "Téléchargement inconnu.")

    def gen():
        yield ": connected\n\n"
        while job["status"] == "running":
            try:
                kind, data = job["queue"].get(timeout=0.5)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if kind == "prog":
                yield f"event: prog\ndata: {json.dumps(data)}\n\n"
            elif kind == "fin":
                break
        if job["error"]:
            yield f"event: error\ndata: {json.dumps({'error': job['error']})}\n\n"
        elif job["result"]:
            r = job["result"]
            yield f"event: result\ndata: {json.dumps({'dossier': r['dossier']})}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


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
    if any(j["status"] == "running" for j in _jobs.values()):
        raise HTTPException(409, "Une génération est déjà en cours.")
    try:
        _voix()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Aucune voix chargée : {exc}")

    config.ensure_dirs()
    tmp = Path(tempfile.mkstemp(suffix=".md")[1])
    tmp.write_text(texte, encoding="utf-8")

    jid = next(_jobid)
    sortie = config.OUTPUT_DIR / f"montage_{jid}.wav"
    bloc_dir = config.OUTPUT_DIR / f"blocs_{jid}"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    q: "queue.Queue[tuple]" = queue.Queue()
    job = {"status": "running", "queue": q, "result": None,
           "error": None, "tmp": tmp, "out": sortie, "bloc_dir": str(bloc_dir),
           "pause": payload.pause, "vitesse": payload.vitesse,
           "max_chars": payload.max_chars, "verify": payload.verify,
           "device": payload.device, "personnages": payload.personnages}
    _jobs[jid] = job

    def _run():
        job["blocs"] = []
        def progress_wrapper(b):
            if "wav" in b:
                job["blocs"].append(b)
            q.put(("bloc", b))
        try:
            res = multi.generate(
                str(tmp), _voix(), personnages=payload.personnages, out=str(sortie),
                pause=payload.pause, speed=payload.vitesse,
                max_block_chars=payload.max_chars,
                verify=payload.verify, device=payload.device,
                block_dir=str(bloc_dir), fp16=False, verbose=False,
                progress=progress_wrapper,
            )
            job["result"] = res
            job["blocs"] = res.get("blocs", [])
            job["sample_rate"] = res.get("sample_rate")
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
                if "index" in data:
                    yield f"event: bloc\ndata: {json.dumps(data)}\n\n"
            elif kind == "done":
                break
        if job["error"]:
            yield f"event: error\ndata: {json.dumps({'error': job['error']})}\n\n"
        elif job["result"]:
            r = job["result"]
            data = json.dumps({
                "duree": r["duration"], "out": r["out"], "blocs": r.get("blocs", []),
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


def _job_live(jid: int) -> dict:
    """Retourne le job qu'il soit terminé ou encore en cours (écoute temps réel)."""
    job = _jobs.get(jid)
    if not job:
        raise HTTPException(404, "Travail inconnu.")
    return job


def _job_done(jid: int) -> dict:
    job = _jobs.get(jid)
    if not job or job["status"] != "done":
        raise HTTPException(404, "Travail indisponible.")
    return job


@app.get("/api/generer/{jid}/blocs")
def api_blocs(jid: int):
    job = _job_live(jid)
    blocs = job.get("blocs", [])
    res = job.get("result") or {}
    return {"blocs": blocs, "out": job["out"],
            "duree": res.get("duration") if res else None}


@app.get("/api/generer/{jid}/bloc/{bid}/wav")
def api_bloc_wav(jid: int, bid: int):
    job = _job_live(jid)
    bloc = next((b for b in job.get("blocs", []) if b["id"] == bid), None)
    if not bloc or not Path(bloc["wav"]).exists():
        raise HTTPException(404, "Bloc indisponible.")
    return FileResponse(bloc["wav"], media_type="audio/wav",
                        filename=f"bloc_{bid}.wav")


@app.post("/api/generer/{jid}/bloc/{bid}/regenerer")
def api_bloc_regenerer(jid: int, bid: int):
    """Re-synthétise un seul bloc (même personnage/voix règlages du job)."""
    job = _job_done(jid)
    bloc = next((b for b in job.get("blocs", []) if b["id"] == bid), None)
    if not bloc:
        raise HTTPException(404, "Bloc inconnu.")
    try:
        voix = _voix().get(bloc["voix"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Voix « {bloc['voix']} » introuvable : {exc}")
    model, sr = multi.load(device=job["device"], fp16=False)
    audio = multi.synth_bloc(voix, bloc["texte"], model, sr,
                             block_chars=job["max_chars"],
                             speed=job["vitesse"], verify=job["verify"])
    cosyvoice_engine.save(audio, sr, bloc["wav"])
    bloc["duree"] = round(len(audio) / sr, 2)
    return {"bloc": bloc}


_PONC = ".!?"


def _decouper_phrase(texte: str) -> list[str]:
    """Découpe ``texte`` en phrases aux fins de ponctuation (à la fin d'une phrase)."""
    import re
    phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+", texte.strip()) if p.strip()]
    return phrases or [texte.strip()]


def _diviser_bloc(bloc: dict) -> list[dict]:
    """Divise un bloc en deux au milieu d'une phrase ; garde personnage/voix."""
    phrases = _decouper_phrase(bloc["texte"])
    if len(phrases) < 2:
        # pas de vraie coupe de phrase : on coupe au milieu du texte
        mid = max(1, len(bloc["texte"]) // 2)
        a, b = bloc["texte"][:mid].strip(), bloc["texte"][mid:].strip()
        return [dict(bloc, texte=a), dict(bloc, texte=b)]
    mid = len(phrases) // 2
    return [dict(bloc, texte=" ".join(phrases[:mid])),
            dict(bloc, texte=" ".join(phrases[mid:]))]


@app.post("/api/generer/{jid}/bloc/{bid}/diviser")
def api_bloc_diviser(jid: int, bid: int):
    """Divise un bloc en deux (à la fin d'une phrase) et re-synthétise les deux moitiés."""
    job = _job_done(jid)
    blocs = job.get("blocs", [])
    idx = next((i for i, b in enumerate(blocs) if b["id"] == bid), None)
    if idx is None:
        raise HTTPException(404, "Bloc inconnu.")
    original = blocs[idx]
    try:
        voix = _voix().get(original["voix"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Voix « {original['voix']} » introuvable : {exc}")
    model, sr = multi.load(device=job["device"], fp16=False)

    halves = _diviser_bloc(original)
    nextid = max(b["id"] for b in blocs) + 1
    results = []
    for h, suffix in zip(halves, (nextid, nextid + 1)):
        audio = multi.synth_bloc(voix, h["texte"], model, sr,
                                 block_chars=job["max_chars"],
                                 speed=job["vitesse"], verify=job["verify"])
        wav = str(Path(original["wav"]).with_name(f"bloc_{suffix}.wav"))
        cosyvoice_engine.save(audio, sr, wav)
        results.append({"id": suffix, "personnage": original["personnage"],
                        "voix": original["voix"], "texte": h["texte"],
                        "chars": len(h["texte"]), "duree": round(len(audio) / sr, 2),
                        "wav": wav})
    blocs[idx:idx + 1] = results
    return {"blocs": blocs}


@app.post("/api/generer/{jid}/concatener")
def api_concatener(jid: int):
    """Re-monte le montage complet depuis les blocs courants (ordre + pauses)."""
    job = _job_done(jid)
    blocs = job.get("blocs", [])
    if not blocs:
        raise HTTPException(400, "Aucun bloc à concaténer.")
    sr = job.get("sample_rate")
    model, sr = multi.load(device=job["device"], fp16=False)
    pause_n = int(job.get("pause", 0.5) * sr)
    import numpy as _np
    import soundfile as _sf
    parts = []
    for b in blocs:
        data, _ = _sf.read(b["wav"], dtype="float32")
        parts.append(data)
        parts.append(_np.zeros(pause_n, dtype=_np.float32))
    final = _np.concatenate(parts)
    cosyvoice_engine.save(final, sr, job["out"])
    job["result"]["duration"] = round(len(final) / sr, 2)
    return {"duree": job["result"]["duration"], "out": job["out"]}


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


@app.post("/api/document/sauver")
def api_document_sauver(payload: DocumentSauverIn):
    """Enregistre un document dans le projet (créer ou écraser) + copie de travail.

    Permet de sauver dans ``texte/`` un contenu venu d'un fichier local ou d'une
    session neuve, en tant que véritable document de projet.
    """
    nom = payload.fichier.strip()
    if not nom or nom.startswith("."):
        raise HTTPException(400, "Nom de document invalide.")
    p = (config.TEXTE_DIR / nom).resolve()
    if not p.is_relative_to(config.TEXTE_DIR.resolve()):
        raise HTTPException(400, "Fichier hors du dossier projet.")
    if p.suffix not in (".md", ".txt"):
        raise HTTPException(400, "Extension autorisée : .md ou .txt")
    p.write_text(payload.contenu, encoding="utf-8")
    _BROUILLONS.mkdir(parents=True, exist_ok=True)
    brouillon = _BROUILLONS / p.name
    brouillon.write_text(payload.contenu, encoding="utf-8")
    return {"fichier": p.name, "brouillon": brouillon.name}


def _fichier_personnages(fichier: str) -> Path:
    """Chemin du mapping personnage→voix pour un document du projet.

    Le mapping est un fichier ``nomdutexte.map`` (CSV) posé à côté du texte
    dans ``texte/`` — ex. ``texte/exemple_demo.md`` → ``texte/exemple_demo.map``.
    Contenu (CSV, en-tête compris) : ``voix,personnage`` sur deux colonnes.
    """
    _chemin_projet(fichier)                       # valide le nom
    return config.TEXTE_DIR / (Path(fichier).stem + ".map")


def _lire_csv_mapping(p: Path) -> dict:
    """Lit un ``.map`` CSV en dict ``{personnage: voix}`` (tolérant à l'ordre)."""
    mapping: dict[str, str] = {}
    with open(p, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or not rows[0]:
        return mapping
    header = [c.strip().lower() for c in rows[0]]
    try:
        i_pers = header.index("personnage")
        i_voix = header.index("voix")
    except ValueError:
        return mapping
    for row in rows[1:]:
        if len(row) < 2:
            continue
        pers = row[i_pers].strip()
        voix = row[i_voix].strip()
        if pers and voix:
            mapping[pers] = voix
    return mapping


def _ecrire_csv_mapping(p: Path, mapping: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["voix", "personnage"])
        for pers, voix in mapping.items():
            if pers.strip() and voix:
                w.writerow([voix, pers])


@app.get("/api/document/personnages")
def api_personnages_get(fichier: str):
    _chemin_projet(fichier)
    p = _fichier_personnages(fichier)
    personnages = {}
    if p.exists():
        try:
            personnages = _lire_csv_mapping(p)
        except (OSError, csv.Error):
            personnages = {}
    voix = []
    try:
        voix = _voix().names()
    except Exception:  # noqa: BLE001
        voix = []
    return {"fichier": fichier, "personnages": personnages, "voix": voix}


@app.post("/api/document/personnages")
def api_personnages_save(payload: PersonnagesSaveIn):
    p = _fichier_personnages(payload.fichier)
    propre = {k: v for k, v in payload.personnages.items() if k.strip() and v}
    _ecrire_csv_mapping(p, propre)
    return {"fichier": payload.fichier, "personnages": propre}


# ---------------------------------------------------------------------------
# Gestion des documents : suppr., archiver, dupliquer, renommer, importer
# ---------------------------------------------------------------------------

def _valider_nom_document(nom: str) -> str:
    """Nettoie et valide un nom de document (sécurité anti-traversal)."""
    nom = (nom or "").strip().replace("\\", "/").split("/")[-1]
    if not nom or nom.startswith("."):
        raise HTTPException(400, "Nom de document invalide.")
    if ".." in nom or "/" in nom or "\\" in nom:
        raise HTTPException(400, "Nom de document invalide.")
    # normalise l'extension
    if not nom.lower().endswith((".md", ".txt")):
        nom += ".md"
    # caractères autorisés : évite les caractères spéciaux filesystem
    if len(nom) > 120:
        raise HTTPException(400, "Nom trop long (max 120).")
    return nom


def _details_document(p: Path) -> dict:
    """Métadonnées d'un document pour le tableau de gestion."""
    try:
        st = p.stat()
        map_p = config.TEXTE_DIR / (p.stem + ".map")
        brouillon = _BROUILLONS / p.name
        return {
            "fichier": p.name,
            "taille": st.st_size,
            "modifie": int(st.st_mtime),
            "modifie_iso": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            "map": map_p.exists(),
            "brouillon": brouillon.exists(),
            "archived": False,
        }
    except OSError:
        return {"fichier": p.name, "taille": 0, "modifie": 0, "modifie_iso": "", "map": False, "brouillon": False, "archived": False}


def _details_archive(p: Path) -> dict:
    d = _details_document(p)
    d["archived"] = True
    return d


@app.get("/api/documents/details")
def api_documents_details():
    config.ensure_dirs()
    _ARCHIVES.mkdir(parents=True, exist_ok=True)
    actifs = []
    for p in sorted(config.TEXTE_DIR.glob("*")):
        if p.is_file() and p.suffix in (".md", ".txt"):
            actifs.append(_details_document(p))
    archives = []
    if _ARCHIVES.is_dir():
        for p in sorted(_ARCHIVES.glob("*")):
            if p.is_file() and p.suffix in (".md", ".txt"):
                archives.append(_details_archive(p))
    return {"documents": actifs, "archives": archives}


@app.post("/api/document/supprimer")
def api_document_supprimer(payload: DocumentActionIn):
    p = _chemin_projet(payload.fichier)
    # supprime : fichier + .map + brouillon
    try:
        map_p = config.TEXTE_DIR / (p.stem + ".map")
        brouillon = _BROUILLONS / p.name
        arch_map = _ARCHIVES / map_p.name if _ARCHIVES.is_dir() else None
        p.unlink()
        if map_p.exists():
            map_p.unlink()
        if brouillon.exists():
            brouillon.unlink()
        # aussi en archives si doublon
        if arch_map and arch_map.exists():
            pass  # on garde l'archive
    except OSError as exc:
        raise HTTPException(500, f"Suppression échouée : {exc}")
    return {"supprime": payload.fichier}


@app.post("/api/document/archiver")
def api_document_archiver(payload: DocumentActionIn):
    p = _chemin_projet(payload.fichier)
    _ARCHIVES.mkdir(parents=True, exist_ok=True)
    dest = _ARCHIVES / p.name
    if dest.exists():
        raise HTTPException(409, f"Archive déjà existante : {dest.name}")
    try:
        shutil.move(str(p), str(dest))
        # déplace aussi le .map et le brouillon si présents
        map_src = config.TEXTE_DIR / (p.stem + ".map")
        if map_src.exists():
            shutil.move(str(map_src), str(_ARCHIVES / map_src.name))
        brouillon = _BROUILLONS / p.name
        if brouillon.exists():
            shutil.move(str(brouillon), str(_ARCHIVES / brouillon.name))
    except OSError as exc:
        raise HTTPException(500, f"Archivage échoué : {exc}")
    return {"archive": dest.name}


@app.post("/api/document/desarchiver")
def api_document_desarchiver(payload: DocumentActionIn):
    # le fichier est dans archives/
    arch = (_ARCHIVES / payload.fichier).resolve()
    if not arch.is_relative_to(_ARCHIVES.resolve()):
        raise HTTPException(400, "Chemin d'archive invalide.")
    if not arch.exists():
        raise HTTPException(404, f"Archive introuvable : {payload.fichier}")
    dest = (config.TEXTE_DIR / payload.fichier).resolve()
    if not dest.is_relative_to(config.TEXTE_DIR.resolve()):
        raise HTTPException(400, "Destination invalide.")
    if dest.exists():
        raise HTTPException(409, f"Un document du même nom existe déjà : {dest.name}")
    try:
        shutil.move(str(arch), str(dest))
        map_arch = _ARCHIVES / (arch.stem + ".map")
        if map_arch.exists():
            shutil.move(str(map_arch), str(config.TEXTE_DIR / map_arch.name))
        brouillon_arch = _ARCHIVES / arch.name
        # le brouillon a le même nom que le doc ; déjà déplacé si présent en archive
        # si pas, rien à faire
        if brouillon_arch.exists() and brouillon_arch != arch:
            shutil.move(str(brouillon_arch), str(_BROUILLONS / brouillon_arch.name))
    except OSError as exc:
        raise HTTPException(500, f"Désarchivage échoué : {exc}")
    return {"restaure": dest.name}


@app.post("/api/document/dupliquer")
def api_document_dupliquer(payload: DocumentDupliquerIn):
    p = _chemin_projet(payload.fichier)
    nouveau = payload.nouveau.strip() if payload.nouveau else ""
    if not nouveau:
        # génère un nom : stem_copie.md
        base = p.stem + "_copie"
        ext = p.suffix
        nouveau = f"{base}{ext}"
        i = 2
        while (config.TEXTE_DIR / nouveau).exists():
            nouveau = f"{base}_{i}{ext}"
            i += 1
    else:
        nouveau = _valider_nom_document(nouveau)
    dest = (config.TEXTE_DIR / nouveau).resolve()
    if not dest.is_relative_to(config.TEXTE_DIR.resolve()):
        raise HTTPException(400, "Destination invalide.")
    if dest.exists():
        raise HTTPException(409, f"Fichier déjà existant : {dest.name}")
    try:
        shutil.copy(str(p), str(dest))
        map_src = config.TEXTE_DIR / (p.stem + ".map")
        if map_src.exists():
            shutil.copy(str(map_src), str(config.TEXTE_DIR / (dest.stem + ".map")))
    except OSError as exc:
        raise HTTPException(500, f"Duplication échouée : {exc}")
    return {"original": p.name, "copie": dest.name}


@app.post("/api/document/renommer")
def api_document_renommer(payload: DocumentRenommerIn):
    p = _chemin_projet(payload.fichier)
    nouveau = _valider_nom_document(payload.nouveau)
    dest = (config.TEXTE_DIR / nouveau).resolve()
    if not dest.is_relative_to(config.TEXTE_DIR.resolve()):
        raise HTTPException(400, "Destination invalide.")
    if dest.exists():
        raise HTTPException(409, f"Fichier déjà existant : {dest.name}")
    try:
        p.rename(dest)
        map_src = config.TEXTE_DIR / (p.stem + ".map")
        if map_src.exists():
            map_src.rename(config.TEXTE_DIR / (dest.stem + ".map"))
        brouillon = _BROUILLONS / p.name
        if brouillon.exists():
            brouillon.rename(_BROUILLONS / dest.name)
    except OSError as exc:
        raise HTTPException(500, f"Renommage échoué : {exc}")
    return {"ancien": p.name, "nouveau": dest.name}


@app.post("/api/document/importer")
async def api_document_importer(file: UploadFile = File(...)):
    # valide extension et taille
    fname = _valider_nom_document(file.filename or "import.md")
    # évite l'écrasement silencieux : génère un suffixe si existe
    dest = config.TEXTE_DIR / fname
    if dest.exists():
        base = dest.stem
        ext = dest.suffix
        i = 2
        while (config.TEXTE_DIR / f"{base}_{i}{ext}").exists():
            i += 1
        fname = f"{base}_{i}{ext}"
        dest = config.TEXTE_DIR / fname
    try:
        contenu = await file.read()
        # limite 5 Mo de texte
        if len(contenu) > 5 * 1024 * 1024:
            raise HTTPException(400, "Fichier trop volumineux (max 5 Mo).")
        # tente décodage utf-8
        try:
            text = contenu.decode("utf-8")
        except UnicodeDecodeError:
            text = contenu.decode("latin-1")
        dest.write_text(text, encoding="utf-8")
        _BROUILLONS.mkdir(parents=True, exist_ok=True)
        (_BROUILLONS / dest.name).write_text(text, encoding="utf-8")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Import échoué : {exc}")
    return {"fichier": dest.name, "taille": len(contenu)}


# ---------------------------------------------------------------------------
# Gestion des voix : import (wav+txt) et suppression
# ---------------------------------------------------------------------------

@app.post("/api/voix/importer")
async def api_voix_importer(
    wav: UploadFile = File(...),
    txt: UploadFile | None = File(default=None),
    nom: str | None = Form(default=None),
    transcription: str | None = Form(default=None),
):
    """Importe une voix : couple wav (+ txt ou transcription brute).

    - ``wav`` : fichier audio (wav/mp3/flac)
    - ``txt`` : fichier de transcription (optionnel si ``transcription`` fournie)
    - ``nom`` : nom de la voix (défaut = nom du wav)
    - ``transcription`` : texte brut alternatif au fichier txt
    """
    audio_dir = Path(config.VOIX_AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # valide le wav
    wav_name = Path(wav.filename or "voix.wav").name
    if not wav_name.lower().endswith((".wav", ".mp3", ".flac", ".ogg")):
        # on force .wav si extension inconnue
        wav_name = Path(wav_name).stem + ".wav"
    # sécurise le nom fichier (pas de slash)
    wav_name = wav_name.replace("/", "_").replace("\\", "_")
    if not wav_name or wav_name.startswith("."):
        raise HTTPException(400, "Nom de fichier wav invalide.")

    # nom de la voix
    voix_nom = (nom or Path(wav_name).stem).strip()
    # retire caractères interdits pour le nom de voix
    voix_nom = "".join(c for c in voix_nom if c not in "/\\").strip() or Path(wav_name).stem
    if len(voix_nom) > 80:
        raise HTTPException(400, "Nom de voix trop long (max 80).")

    # vérifie doublon dans voix.txt
    try:
        existants = set()
        if config.VOIX_FILE.exists():
            # lecture tolérante
            for raw in config.VOIX_FILE.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if raw.startswith("[") and "]" in raw:
                    existants.add(raw.split("]")[0].lstrip("["))
        if voix_nom in existants:
            raise HTTPException(409, f"Voix déjà existante : {voix_nom}")
    except HTTPException:
        raise
    except Exception:
        pass

    wav_dest = audio_dir / wav_name
    # évite écrasement : suffixe
    if wav_dest.exists():
        stem = wav_dest.stem
        ext = wav_dest.suffix
        i = 2
        while (audio_dir / f"{stem}_{i}{ext}").exists():
            i += 1
        wav_name = f"{stem}_{i}{ext}"
        wav_dest = audio_dir / wav_name

    try:
        data = await wav.read()
        if len(data) > 100 * 1024 * 1024:
            raise HTTPException(400, "Fichier wav trop volumineux (max 100 Mo).")
        if len(data) < 1000:
            raise HTTPException(400, "Fichier wav trop petit ou vide.")
        wav_dest.write_bytes(data)

        # transcription
        txt_content = ""
        if txt is not None and txt.filename:
            raw = await txt.read()
            try:
                txt_content = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                txt_content = raw.decode("latin-1").strip()
        elif transcription:
            txt_content = transcription.strip()

        if not txt_content:
            raise HTTPException(400, "Transcription manquante : fournis un .txt ou un texte.")

        txt_name = Path(wav_name).stem + ".txt"
        txt_dest = audio_dir / txt_name
        txt_dest.write_text(txt_content, encoding="utf-8")

        # met à jour voix.txt
        config.ensure_dirs()
        # génère si absent, sinon append
        if not config.VOIX_FILE.exists():
            voix.generer_voix_txt(dossier=str(audio_dir))
        # si voix_nom pas déjà dans voix.txt, on append
        lignes = []
        if config.VOIX_FILE.exists():
            lignes = config.VOIX_FILE.read_text(encoding="utf-8").splitlines()
        # vérifie si couple déjà listé
        deja = any(wav_name in l for l in lignes)
        if not deja:
            with open(config.VOIX_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{voix_nom}], {wav_name}, {txt_name}\n")

    except HTTPException:
        # nettoie en cas d'échec partiel
        if wav_dest.exists():
            try:
                wav_dest.unlink()
            except OSError:
                pass
        raise
    except Exception as exc:  # noqa: BLE001
        if wav_dest.exists():
            try:
                wav_dest.unlink()
            except OSError:
                pass
        raise HTTPException(500, f"Import voix échoué : {exc}")

    return {"nom": voix_nom, "wav": wav_name, "txt": txt_name}


@app.post("/api/voix/supprimer")
def api_voix_supprimer(payload: VoixSupprimerIn):
    nom = payload.nom.strip()
    if not nom:
        raise HTTPException(400, "Nom de voix invalide.")
    if not config.VOIX_FILE.exists():
        raise HTTPException(404, "Aucun fichier voix.txt.")
    lignes = config.VOIX_FILE.read_text(encoding="utf-8").splitlines()
    nouvelles = []
    trouve = False
    wav_a_suppr = None
    txt_a_suppr = None
    for l in lignes:
        if l.strip().startswith(f"[{nom}]"):
            trouve = True
            # extrait wav/txt pour éventuelle suppression fichier
            parts = [p.strip() for p in l.split(",")]
            if len(parts) >= 2:
                wav_a_suppr = parts[1]
            if len(parts) >= 3:
                txt_a_suppr = parts[2]
            continue
        nouvelles.append(l)
    if not trouve:
        raise HTTPException(404, f"Voix introuvable : {nom}")
    # réécrit voix.txt
    config.VOIX_FILE.write_text("\n".join(nouvelles) + ("\n" if nouvelles else ""), encoding="utf-8")
    # supprime les fichiers audio/txt du dossier audio (optionnel, mais demandé)
    for fname in (wav_a_suppr, txt_a_suppr):
        if not fname:
            continue
        p = Path(config.VOIX_AUDIO_DIR) / Path(fname).name
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    return {"supprime": nom}


# ---------------------------------------------------------------------------
# Nettoyage des voix (Demucs + DeepFilterNet) — job d'arrière-plan + SSE
# ---------------------------------------------------------------------------

# Espace de travail des nettoyages (dans le volume temporaire, sinon /tmp).
_CLEAN_WORK = config.OUTPUT_DIR / ".clean"
_clean_jobs: dict[int, dict] = {}
_clean_jobid = itertools.count()


def _clean_dispo() -> dict:
    """Dépendances de nettoyage installées ? (sans import lourd au boot)."""
    import importlib.util
    demucs = importlib.util.find_spec("demucs") is not None
    df = importlib.util.find_spec("df") is not None and \
        importlib.util.find_spec("libdf") is not None
    return {"dispo": demucs and df, "demucs": demucs,
            "deepfilternet": df,
            "dossier_modeles": str(Path(config.ENHANCE_MODEL_DIR))}


@app.get("/api/voix/nettoyer/dispo")
def api_voix_nettoyer_dispo():
    return _clean_dispo()


@app.post("/api/voix/nettoyer")
def api_voix_nettoyer(payload: VoixNettoyerIn):
    """Lance le nettoyage d'une voix (Demucs vocals → DeepFilterNet)."""
    nom = (payload.nom or "").strip()
    if not nom:
        raise HTTPException(400, "Nom de voix invalide.")
    try:
        v = _voix().get(nom)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Voix inconnue : {nom} ({exc})")
    if not v.wav or not Path(v.wav).exists():
        raise HTTPException(404, f"Fichier wav introuvable : {v.wav}")
    dispo = _clean_dispo()
    if not dispo["dispo"]:
        raise HTTPException(501,
                            "Dépendances de nettoyage absentes (demucs / deepfilternet) — "
                            "l'image doit être reconstruite.")
    if any(j["status"] == "running" for j in _jobs.values()):
        raise HTTPException(409, "Une génération est déjà en cours.")
    if any(j["status"] == "running" for j in _clean_jobs.values()):
        raise HTTPException(409, "Un nettoyage est déjà en cours.")

    config.ensure_dirs()
    _CLEAN_WORK.mkdir(parents=True, exist_ok=True)
    jid = next(_clean_jobid)
    sortie = _CLEAN_WORK / f"clean_{jid}.wav"
    q: "queue.Queue[tuple]" = queue.Queue()
    job = {
        "status": "running", "nom": nom, "queue": q, "wav": str(v.wav),
        "resultat": str(sortie), "mode": payload.mode or "auto",
        "error": None, "result": None, "etape": "initialisation",
    }
    _clean_jobs[jid] = job

    def _run():
        from engine import enhance
        try:
            def progress(etape, pct):
                job["etape"] = etape
                q.put(("prog", {"etape": etape, "pct": pct}))
            res = enhance.nettoyer(job["wav"], sortie, mode=job["mode"],
                                   progress=progress)
            job["result"] = res
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            job["status"] = "error"
        finally:
            q.put(("fin", None))

    threading.Thread(target=_run, daemon=True).start()
    return {"id": jid, "nom": nom}


@app.get("/api/voix/nettoyer/{jid}/stream")
def api_voix_nettoyer_stream(jid: int):
    job = _clean_jobs.get(jid)
    if not job:
        raise HTTPException(404, "Nettoyage inconnu.")

    def gen():
        yield ": connected\n\n"
        while job["status"] == "running":
            try:
                kind, data = job["queue"].get(timeout=0.5)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if kind == "prog":
                yield f"event: prog\ndata: {json.dumps(data)}\n\n"
            elif kind == "fin":
                break
        if job["error"]:
            yield f"event: error\ndata: {json.dumps({'error': job['error']})}\n\n"
        elif job["result"]:
            r = job["result"]
            yield f"event: result\ndata: {json.dumps({'duree': r['duree'], 'mode': r['mode']})}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def _clean_job_done(jid: int) -> dict:
    job = _clean_jobs.get(jid)
    if not job or job["status"] != "done" or not job["result"]:
        raise HTTPException(404, "Nettoyage indisponible ou pas terminé.")
    return job


@app.get("/api/voix/nettoyer/{jid}/wav")
def api_voix_nettoyer_wav(jid: int):
    """Écoute le résultat nettoyé (A/B)."""
    job = _clean_job_done(jid)
    return FileResponse(job["resultat"], media_type="audio/wav",
                        filename=f"{job['nom']}_clean.wav")


@app.post("/api/voix/nettoyer/{jid}/ecraser")
def api_voix_nettoyer_ecraser(jid: int):
    """Remplace le .wav d'origine de la voix par le résultat nettoyé."""
    job = _clean_job_done(jid)
    wav = Path(job["wav"])
    resultat = Path(job["resultat"])
    if not resultat.exists():
        raise HTTPException(404, "Résultat nettoyé introuvable.")
    try:
        shutil.copyfile(str(resultat), str(wav))
    except OSError as exc:
        raise HTTPException(500, f"Écrasement échoué : {exc}")
    return {"ok": True, "nom": job["nom"], "wav": str(wav)}


@app.post("/api/voix/nettoyer/{jid}/sauver_clean")
def api_voix_nettoyer_sauver(jid: int, payload: VoixNettoyerSauverIn):
    """Enregistre le résultat comme nouvelle voix « <nom>_<suffixe> »."""
    job = _clean_job_done(jid)
    base = Path(job["wav"])
    resultat = Path(job["resultat"])
    if not resultat.exists():
        raise HTTPException(404, "Résultat nettoyé introuvable.")
    audio_dir = Path(config.VOIX_AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # nom de la voix cible
    suffixe = (payload.nom or "clean").strip() or "clean"
    suffixe = "".join(c for c in suffixe if c not in "/\\").strip()
    cible_nom = f"{job['nom']}_{suffixe}"

    # évite un doublon dans voix.txt
    existants = set()
    if config.VOIX_FILE.exists():
        for raw in config.VOIX_FILE.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if raw.startswith("[") and "]" in raw:
                existants.add(raw.split("]")[0].lstrip("["))
    if cible_nom in existants:
        raise HTTPException(409, f"Une voix « {cible_nom} » existe déjà.")

    # fichier wav : stem_clean.wav (unique)
    nom_wav = f"{Path(job['wav']).stem}_{suffixe}.wav"
    wav_dest = audio_dir / nom_wav
    i = 2
    while wav_dest.exists():
        wav_dest = audio_dir / f"{Path(job['wav']).stem}_{suffixe}_{i}.wav"
        i += 1
    # transcription copiée à l'identique
    txt_src = Path(base).with_suffix(".txt")
    txt_dest = wav_dest.with_suffix(".txt")
    try:
        shutil.copyfile(str(resultat), str(wav_dest))
        if txt_src.exists():
            shutil.copyfile(str(txt_src), str(txt_dest))
    except OSError as exc:
        raise HTTPException(500, f"Copie échouée : {exc}")

    config.ensure_dirs()
    with open(config.VOIX_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{cible_nom}], {wav_dest.name}, {txt_dest.name}\n")
    return {"ok": True, "nom": cible_nom, "wav": wav_dest.name,
            "txt": txt_dest.name}


@app.get("/api/etat/clean")
def api_clean_etat():
    """État du nettoyage (dépendances) pour la bannière/UI."""
    d = _clean_dispo()
    running = any(j["status"] == "running" for j in _clean_jobs.values())
    return {"nettoyage": d, "running": running}


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
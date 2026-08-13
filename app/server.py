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

import uvicorn
from fastapi import FastAPI, HTTPException
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


def _job_done(jid: int) -> dict:
    job = _jobs.get(jid)
    if not job or job["status"] != "done":
        raise HTTPException(404, "Travail indisponible.")
    return job


@app.get("/api/generer/{jid}/blocs")
def api_blocs(jid: int):
    job = _job_done(jid)
    return {"blocs": job.get("blocs", []), "out": job["out"],
            "duree": job["result"]["duration"]}


@app.get("/api/generer/{jid}/bloc/{bid}/wav")
def api_bloc_wav(jid: int, bid: int):
    job = _job_done(jid)
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
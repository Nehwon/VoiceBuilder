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
import asyncio
import itertools
import json
import os
import queue
import re
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

from engine import bench
from engine import config, cosyvoice_engine, modeles, multi, voix
from engine.voix import load_voix
from engine import audio_extract

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
    # lit musical BGM persisté (ignoré s'il n'existe plus)
    _restaurer_bgm()
    bgm_etat = {"bgm_lit": Path(config.BGM_LIT).name if config.BGM_LIT else None,
                "bgm_volume": config.BGM_VOLUME}
    fichier_voix = bool(config.VOIX_FILE.exists())
    if fichier_voix:
        try:
            noms = _voix().names()
        except Exception as exc:  # noqa: BLE001
            return {"audio_dir": d, "voix_file": False, "voix": [],
                    "erreur": f"{config.VOIX_FILE.name} invalide : {exc}",
                    **bgm_etat}
    else:
        noms = []
    return {"audio_dir": d, "voix_file": fichier_voix, "voix": noms,
            "erreur": None, **bgm_etat}


def _restaurer_bgm() -> None:
    """Re-applique le lit musical + volume persistés (démarrage, /api/etat)."""
    data = _charger_persistance()
    lit = data.get("bgm_lit")
    if lit and Path(lit).exists():
        config.set_bgm(lit, data.get("bgm_volume", config.BGM_VOLUME_DEFAUT))
    else:
        config.set_bgm(None, data.get("bgm_volume", config.BGM_VOLUME_DEFAUT))


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
_torch_jobid = itertools.count(1)


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
    bgm_volume: float | None = None


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
    load_vllm: bool = False
    load_trt: bool = False
    document: str | None = None  # fichier projet (cache M16) ; None = fichier local, pas de cache
    multi_prompt: bool = False  # M17.4 : chaque bloc avec 2 prompts, meilleur gardé (×2 GPU)


class ReordonnerIn(BaseModel):
    ids: list[int]


class BlocTexteIn(BaseModel):
    texte: str


class BenchLancerIn(BaseModel):
    personnage: str
    device: str = "cuda:0"


class BenchPromouvoirIn(BaseModel):
    personnage: str
    candidat: str


class PersonnagesSaveIn(BaseModel):
    fichier: str
    personnages: dict[str, str]


class IncisesIn(BaseModel):
    fichier: str
    mode: str = "auto"            # auto | import_roman | nettoyer_tagge (regex seul)
    keep_action: str = "narration"  # narration | garder | supprimer (regex seul)
    voix_defaut: str = "Narrateur"
    narrateur_je: str | None = None
    moteur: str = "auto"          # auto | llm | regex (auto = LLM si Ollama répond)
    min_repliques: int = 2        # répliques minimum pour créer un personnage
    preuve_incise: bool = True    # exige une incise explicite « dit X » en source
    verif_minuscule: bool = True  # écarte les noms présents en minuscules (noms communs)
    stop_mots: str = ""           # génériques supplémentaires (séparés par des virgules)
    accepter_tous: bool = False   # désactive les filtres anti faux positifs


class IncisesAppliquerIn(BaseModel):
    fichier: str
    contenu: str
    personnages: dict[str, str] = {}  # nouveaux {personnage: voix} à fusionner au .map


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


class VoixDecouperIn(BaseModel):
    fichier: str
    start: float
    stop: float


class VoixTranscrireIn(BaseModel):
    fichier: str
    lang: str | None = None
    start: float | None = None
    stop: float | None = None


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
    if payload.bgm_volume is not None:
        config.set_bgm(config.BGM_LIT, payload.bgm_volume)
        _sauver_persistance({"bgm_volume": config.BGM_VOLUME})
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
_model_jobid = itertools.count(1)


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
_jobid = itertools.count(1)


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
    document = (payload.document or "").strip() or None
    if document:
        # Cas 1 de vidage du cache (M16) : nouvelle génération demandée.
        _cache_effacer(document)
    job = {"status": "running", "queue": q, "result": None,
           "error": None, "tmp": tmp, "out": sortie, "bloc_dir": str(bloc_dir),
           "pause": payload.pause, "vitesse": payload.vitesse,
           "max_chars": payload.max_chars, "verify": payload.verify,
           "device": payload.device, "personnages": payload.personnages,
           "document": document, "multi_prompt": payload.multi_prompt,
           "stop_event": threading.Event(), "stopped": False,
           "file_regen": queue.Queue()}
    _jobs[jid] = job

    def _run():
        job["blocs"] = []
        def progress_wrapper(b):
            if b.get("regen"):
                # régénération en cours de route : mise à jour en place (même id).
                for ex in job["blocs"]:
                    if ex.get("id") == b.get("id"):
                        ex.update({k: b[k] for k in ("duree", "chars", "texte") if k in b})
                        break
            elif "wav" in b:
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
                stop_event=job["stop_event"],
                load_vllm=payload.load_vllm, load_trt=payload.load_trt,
                file_regen=job["file_regen"],
                multi_prompt=job.get("multi_prompt", False),
            )
            job["result"] = res
            job["blocs"] = res.get("blocs", [])
            job["sample_rate"] = res.get("sample_rate")
            job["stopped"] = bool(res.get("stopped"))
            job["status"] = "stopped" if job["stopped"] else "done"
            _cache_ecrire(job)  # M16 : persiste la dernière génération du document
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
        start_cur = 0.0
        pers_prec = None
        pause = float(job.get("pause", 0.0))
        while job["status"] == "running":
            try:
                kind, data = job["queue"].get(timeout=0.5)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if kind == "bloc":
                if "index" in data:
                    if data.get("regen"):
                        # régénération en file : mêmes offsets, pas de décalage.
                        yield f"event: bloc\ndata: {json.dumps(data)}\n\n"
                    else:
                        if pers_prec is not None and data.get("personnage") != pers_prec:
                            start_cur += pause
                        data = dict(data, start=round(start_cur, 3))
                        start_cur += data.get("duree", 0.0)
                        pers_prec = data.get("personnage")
                        yield f"event: bloc\ndata: {json.dumps(data)}\n\n"
            elif kind == "done":
                break
        if job["error"]:
            yield f"event: error\ndata: {json.dumps({'error': job['error']})}\n\n"
        elif job.get("stopped"):
            r = job["result"] or {}
            data = json.dumps({"status": "stopped",
                               "duree": r.get("duration"),
                               "blocs": job.get("blocs", [])})
            yield f"event: stop\ndata: {data}\n\n"
        elif job["result"]:
            r = job["result"]
            data = json.dumps({
                "duree": r["duration"], "out": r["out"], "blocs": r.get("blocs", []),
            })
            yield f"event: result\ndata: {data}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/generer/en-cours")
def api_generer_en_cours():
    """Génération en cours (reprise après rechargement de page).

    Renvoie l'id du job, son document, le texte soumis, le mapping
    personnages et les ids en file de régénération — de quoi se rattacher.
    """
    for jid, job in _jobs.items():
        if job.get("status") == "running":
            texte = None
            try:
                if job.get("tmp") and Path(job["tmp"]).exists():
                    texte = Path(job["tmp"]).read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            fq = job.get("file_regen")
            try:
                en_file = list(fq.queue) if fq is not None else []
            except Exception:  # noqa: BLE001
                en_file = []
            return {"id": jid, "document": job.get("document"),
                    "texte": texte, "personnages": job.get("personnages", {}),
                    "en_file": en_file,
                    "blocs": len(job.get("blocs", []))}
    return {"id": None}


@app.post("/api/generer/{jid}/arret")
def api_generer_arret(jid: int):
    """Demande l'arrêt propre : le bloc en cours se termine, le reste est abandonné.

    Le résultat partiel (blocs déjà générés + WAV montage partiel) reste disponible.
    """
    job = _job_live(jid)
    if job.get("status") != "running":
        raise HTTPException(409, "La génération n'est plus en cours.")
    evt = job.get("stop_event")
    if evt is not None:
        evt.set()
    return {"ok": True, "message": "Arrêt demandé."}


@app.get("/api/generer/{jid}/result")
def api_result(jid: int):
    """Renvoie le WAV complet (génération normale) ou partiel (génération arrêtée)."""
    job = _job_live(jid)
    f = Path(job["out"])
    if not f.exists():
        raise HTTPException(404, "Résultat indisponible.")
    return FileResponse(f, media_type="audio/wav", filename=f.name)


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


def _job_pret(jid: int) -> dict:
    """Job terminé (done) ou arrêté proprement (stopped) — modifiable (réordre, suppression)."""
    job = _job_live(jid)
    if job.get("status") not in ("done", "stopped"):
        raise HTTPException(409, "Génération en cours.")
    return job


def _cache_chemin(document: str) -> Path:
    """Manifeste du cache de génération d'un document (M16, dans output/)."""
    nom = re.sub(r"[/\\]", "_", document).strip() or "document"
    return config.OUTPUT_DIR / f".cache_{nom}.json"


def _cache_lire(document: str) -> dict | None:
    """Manifeste du cache si présent ET complet (tous les WAV existent)."""
    chemin = _cache_chemin(document)
    if not chemin.exists():
        return None
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    fichiers = [data.get("out")] + [b.get("wav") for b in data.get("blocs", [])]
    if not data.get("out") or not all(f and Path(f).exists() for f in fichiers):
        try:
            chemin.unlink()
        except OSError:
            pass
        return None
    return data


def _cache_ecrire(job: dict) -> None:
    """Persiste la dernière génération d'un document (M16, à la fin du job)."""
    document = job.get("document")
    if not document:
        return
    res = job.get("result") or {}
    try:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _cache_chemin(document).write_text(json.dumps({
            "document": document,
            "status": job.get("status"),
            "stopped": bool(job.get("stopped")),
            "sample_rate": job.get("sample_rate"),
            "pause": job.get("pause"), "vitesse": job.get("vitesse"),
            "max_chars": job.get("max_chars"), "verify": job.get("verify"),
            "device": job.get("device"), "personnages": job.get("personnages"),
            "multi_prompt": bool(job.get("multi_prompt")),
            "out": str(job["out"]),
            "bloc_dir": str(job.get("bloc_dir") or ""),
            "blocs": job.get("blocs", []),
            "duration": res.get("duration"),
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass  # le cache ne doit jamais casser une génération


def _cache_effacer(document: str) -> dict:
    """Supprime le cache d'un document : manifeste + WAV + jobs en mémoire."""
    chemin = _cache_chemin(document)
    data = None
    if chemin.exists():
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = None
    fichiers = []
    if data:
        fichiers = [data.get("out")] + [b.get("wav") for b in data.get("blocs", [])]
    for f in fichiers:
        if f:
            try:
                Path(f).unlink(missing_ok=True)
            except OSError:
                pass
    try:
        chemin.unlink(missing_ok=True)
    except OSError:
        pass
    # bloc_dir résiduel (vide après suppression des WAV de blocs)
    bloc_dir = (data or {}).get("bloc_dir")
    try:
        cand = Path(bloc_dir) if bloc_dir else None
        if cand and cand.is_dir() and not any(cand.iterdir()):
            cand.rmdir()
    except OSError:
        pass
    for jid, job in list(_jobs.items()):
        if job.get("document") == document:
            _jobs.pop(jid, None)
    return {"efface": True, "document": document,
            "fichiers": len([f for f in fichiers if f])}


def _offsets_blocs(blocs: list, pause: float) -> list[float]:
    """Début (s) de chaque bloc dans le montage — pause uniquement au changement de locuteur."""
    offsets: list[float] = []
    start = 0.0
    prec = None
    for b in blocs:
        if prec is not None and b.get("personnage") != prec:
            start += float(pause)
        offsets.append(round(start, 3))
        start += b.get("duree", 0.0)
        prec = b.get("personnage")
    return offsets


def _sr_blocs(job: dict) -> int:
    sr = job.get("sample_rate")
    if sr:
        return int(sr)
    import soundfile as _sf
    for b in job.get("blocs", []):
        if b.get("wav") and Path(b["wav"]).exists():
            return int(_sf.info(b["wav"]).samplerate)
    raise HTTPException(400, "Fréquence d'échantillonnage introuvable.")


def _reconcat(job: dict, blocs: list) -> float:
    """Réassemble le montage depuis les blocs (ordre courant, même règle que generate).

    Pause (silence) uniquement au changement de locuteur, aucun silence final.
    Met à jour le WAV ``job["out"]`` et la durée de ``job["result"]``.
    """
    out = Path(job["out"])
    if not blocs:
        if out.exists():
            out.unlink()
        if job.get("result") is None:
            job["result"] = {"duration": 0.0, "blocs": [], "out": str(out)}
        job["result"]["duration"] = 0.0
        return 0.0
    import numpy as _np
    import soundfile as _sf
    sr = _sr_blocs(job)
    pause_n = int(float(job.get("pause", 0.0)) * sr)
    parts = []
    prec = None
    for b in blocs:
        data, _ = _sf.read(b["wav"], dtype="float32")
        if prec is not None and b.get("personnage") != prec:
            parts.append(_np.zeros(pause_n, dtype=_np.float32))
        parts.append(data)
        prec = b.get("personnage")
    final = _np.concatenate(parts)
    cosyvoice_engine.save(final, sr, out)
    duree = round(len(final) / sr, 3)
    if job.get("result") is None:
        job["result"] = {"duration": duree, "blocs": blocs, "out": str(out)}
    job["result"]["duration"] = duree
    return duree


@app.get("/api/generer/{jid}/blocs")
def api_blocs(jid: int):
    job = _job_live(jid)
    blocs = job.get("blocs", [])
    pause = float(job.get("pause", 0.0))
    ofs = _offsets_blocs(blocs, pause)
    res_list = [dict(b, start=o) for b, o in zip(blocs, ofs)]
    res = job.get("result") or {}
    return {"blocs": res_list, "pause": pause, "out": job["out"],
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
    _cache_ecrire(job)  # M16 : le cache suit les retouches
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
    _cache_ecrire(job)  # M16 : le cache suit les retouches
    return {"blocs": blocs}


@app.post("/api/generer/{jid}/concatener")
def api_concatener(jid: int):
    """Re-monte le montage complet depuis les blocs courants (ordre + pauses locuteur)."""
    job = _job_pret(jid)
    blocs = job.get("blocs", [])
    if not blocs:
        raise HTTPException(400, "Aucun bloc à concaténer.")
    duree = _reconcat(job, blocs)
    _cache_ecrire(job)  # M16 : le cache suit les retouches
    return {"duree": duree, "out": job["out"]}


@app.post("/api/generer/{jid}/blocs/reordonner")
def api_blocs_reordonner(jid: int, payload: ReordonnerIn):
    """Réordonne les blocs (rien à re-synthétiser : on réassemble les WAV existants)."""
    job = _job_pret(jid)
    blocs = job.get("blocs", [])
    byid = {b["id"]: b for b in blocs}
    ids = list(payload.ids)
    if len(ids) != len(set(ids)) or set(ids) != set(byid):
        raise HTTPException(400, "La liste des ids ne correspond pas aux blocs.")
    job["blocs"] = [byid[i] for i in ids]
    duree = _reconcat(job, job["blocs"])
    _cache_ecrire(job)  # M16 : le cache suit les retouches
    ofs = _offsets_blocs(job["blocs"], float(job.get("pause", 0.0)))
    out_blocs = [dict(b, start=o) for b, o in zip(job["blocs"], ofs)]
    return {"blocs": out_blocs, "duree": duree}


@app.post("/api/generer/{jid}/bloc/{bid}/supprimer")
def api_bloc_supprimer(jid: int, bid: int):
    """Supprime un bloc du montage (réassemble les WAV restants)."""
    job = _job_pret(jid)
    blocs = job.get("blocs", [])
    restants = [b for b in blocs if b["id"] != bid]
    if len(restants) == len(blocs):
        raise HTTPException(404, "Bloc inconnu.")
    job["blocs"] = restants
    duree = _reconcat(job, restants)  # vide → montant supprimé, durée 0
    _cache_ecrire(job)  # M16 : le cache suit les retouches
    ofs = _offsets_blocs(job["blocs"], float(job.get("pause", 0.0)))
    out_blocs = [dict(b, start=o) for b, o in zip(job["blocs"], ofs)]
    return {"blocs": out_blocs, "duree": duree, "vide": not restants}


@app.post("/api/generer/{jid}/bloc/{bid}/texte")
def api_bloc_texte(jid: int, bid: int, payload: BlocTexteIn):
    """Met à jour le texte d'un bloc (édition depuis la carte) : pris en
    compte par « Régénérer » (l'audio existant est inchangé)."""
    job = _job_pret(jid)
    bloc = next((b for b in job.get("blocs", []) if b["id"] == bid), None)
    if not bloc:
        raise HTTPException(404, "Bloc inconnu.")
    texte = (payload.texte or "").strip()
    if not texte:
        raise HTTPException(400, "Texte de bloc vide.")
    bloc["texte"] = texte
    bloc["chars"] = len(texte)
    _cache_ecrire(job)  # M16 : le cache suit les retouches
    return {"bloc": bloc}


@app.post("/api/generer/{jid}/verifier")
def api_verifier_lancer(jid: int):
    """Vérification différée : transcrit le montage final en entier (Whisper)
    et signale les pertes par segment (tâche de fond, suivi par polling)."""
    from engine import verifier
    job = _job_pret(jid)
    if not job.get("blocs"):
        raise HTTPException(400, "Aucun bloc à vérifier.")
    if not Path(job["out"]).exists():
        raise HTTPException(404, "Montage introuvable.")
    if job.get("verification_running"):
        raise HTTPException(409, "Vérification déjà en cours.")
    job["verification_running"] = True
    job["verification"] = {"status": "running", "lignes": []}

    def _run():
        try:
            import soundfile as _sf
            sr = _sr_blocs(job)
            audio, _ = _sf.read(str(job["out"]), dtype="float32")
            segments = verifier.transcribe_segments(audio, sr)
            pause = float(job.get("pause", 0.0))
            ofs = _offsets_blocs(job["blocs"], pause)
            lignes = []
            for b, start in zip(job["blocs"], ofs):
                fin = start + b.get("duree", 0.0)
                cov = verifier.couverture_bloc(b.get("texte", ""), segments,
                                               start, fin)
                lignes.append({"id": b["id"], "personnage": b.get("personnage"),
                               **cov})
            couv = [l["couverture"] for l in lignes]
            job["verification"] = {
                "status": "done", "lignes": lignes,
                "couverture_moyenne": round(sum(couv) / len(couv), 4) if couv else 0.0,
                "blocs_sous_seuil": sum(
                    1 for l in lignes
                    if l["couverture"] < config.VERIFY_THRESHOLD),
            }
        except Exception as exc:  # noqa: BLE001
            job["verification"] = {"status": "error", "lignes": [],
                                   "error": str(exc)}
        finally:
            job["verification_running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"lance": True}


@app.get("/api/generer/{jid}/verification")
def api_verification_etat(jid: int):
    """État de la vérification différée (polling) + résultats par segment."""
    job = _job_live(jid)
    return job.get("verification") or {"status": "aucune", "lignes": []}


@app.post("/api/generer/{jid}/bloc/{bid}/regenerer-file")
def api_bloc_regenerer_file(jid: int, bid: int):
    """Met un bloc en file de régénération : la génération en cours termine
    son bloc, re-synthétise celui-ci aussitôt (remplacement en place), puis
    continue la génération globale."""
    job = _job_live(jid)
    if job.get("status") != "running":
        raise HTTPException(409, "Aucune génération en cours.")
    termines = len(job.get("blocs", []))
    if bid < 1 or bid > termines:
        raise HTTPException(400, "Bloc pas encore généré — réessaie après sa synthèse.")
    file_regen = job.get("file_regen")
    if file_regen is None:
        raise HTTPException(409, "File de régénération indisponible.")
    if bid in list(file_regen.queue):
        return {"file": True, "message": f"Bloc {bid} déjà en file de régénération."}
    file_regen.put(bid)
    return {"file": True,
            "message": f"Bloc {bid} régénéré après le bloc en cours."}


@app.get("/api/cache/{document}")
def api_cache_lire(document: str):
    """Relit la dernière génération d'un document (M16) : la restaure en
    job mémoire (nouvel id) pour réutiliser tous les endpoints montage."""
    data = _cache_lire(document)
    if not data:
        raise HTTPException(404, "Aucune génération en cache pour ce document.")
    jid = next(_jobid)
    job = {"status": data.get("status", "done"),
           "queue": queue.Queue(), "result": {"duration": data.get("duration"),
                                              "blocs": data.get("blocs", []),
                                              "out": data.get("out")},
           "error": None, "tmp": None, "out": Path(data["out"]),
           "bloc_dir": data.get("bloc_dir") or "",
           "pause": data.get("pause", 0.5), "vitesse": data.get("vitesse", 1.0),
           "max_chars": data.get("max_chars", 600),
           "verify": data.get("verify", True),
           "device": data.get("device", "cuda:0"),
           "personnages": data.get("personnages", {}),
           "document": data.get("document"),
           "sample_rate": data.get("sample_rate"),
           "stopped": bool(data.get("stopped", data.get("status") == "stopped")),
           "stop_event": threading.Event(),
           "file_regen": queue.Queue(),
           "blocs": data.get("blocs", [])}
    _jobs[jid] = job
    return {"id": jid, "document": data.get("document"),
            "status": job["status"], "duree": data.get("duration"),
            "blocs": len(job["blocs"])}


@app.delete("/api/cache/{document}")
def api_cache_supprimer(document: str):
    """Supprime le cache de génération d'un document (M16, cas 2 de vidage)."""
    for job in _jobs.values():
        if job.get("document") == document and job.get("status") == "running":
            raise HTTPException(409, "Génération en cours : arrête-la avant de supprimer son cache.")
    return _cache_effacer(document)


# ---------------------------------------------------------------------------
# Banc A/B de prompts (M17.2) : même paragraphe de référence synthétisé avec
# chaque segment candidat d'un personnage (coverage Whisper + RTF + écoute).
# ---------------------------------------------------------------------------

_bench_jobs: dict[int, dict] = {}
_bench_id = itertools.count(1)


@app.get("/api/bench/candidats")
def api_bench_candidats():
    """Personnages et leurs segments candidats (variantes _2/_3, _clean)."""
    try:
        voix = _voix()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Aucune voix chargée : {exc}")
    groupes = bench.grouper_candidats(voix.names())
    return {"groupes": [{"base": b, "candidats": c} for b, c in groupes.items()]}


@app.post("/api/bench/lancer")
def api_bench_lancer(payload: BenchLancerIn):
    """Lance le bench d'un personnage en tâche de fond (résultat par polling)."""
    base = (payload.personnage or "").strip()
    if not base:
        raise HTTPException(400, "Personnage vide.")
    if any(j["status"] == "running" for j in _bench_jobs.values()):
        raise HTTPException(409, "Un bench est déjà en cours.")
    try:
        voix = _voix()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Aucune voix chargée : {exc}")
    groupes = bench.grouper_candidats(voix.names())
    if base not in groupes:
        raise HTTPException(404, f"Personnage inconnu : {base}")
    candidats = groupes[base]
    if len(candidats) < 2:
        raise HTTPException(400, "Un seul candidat : rien à comparer.")
    jid = next(_bench_id)
    q: "queue.Queue[tuple]" = queue.Queue()
    job = {"status": "running", "queue": q, "result": None, "error": None,
           "personnage": base, "out_dir": str(config.OUTPUT_DIR / "bench" / bench.slug(base))}

    def _run():
        def progress(d):
            q.put(("candidat", d))
        try:
            model, sr = multi.load(device=payload.device, fp16=False)
            res = bench.bench_personnage(base, candidats, voix, model, sr,
                                         job["out_dir"], progress=progress)
            job["result"] = res
            job["status"] = "done"
            q.put(("fin", None))
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            job["status"] = "error"
            q.put(("fin", None))

    _bench_jobs[jid] = job
    threading.Thread(target=_run, daemon=True).start()
    return {"id": jid, "personnage": base, "candidats": candidats}


@app.get("/api/bench/{jid}")
def api_bench_etat(jid: int):
    """État d'un bench (polling) : running + avancement, done + résultat."""
    job = _bench_jobs.get(jid)
    if not job:
        raise HTTPException(404, "Bench inconnu.")
    avancement = []
    while True:
        try:
            kind, data = job["queue"].get_nowait()
        except queue.Empty:
            break
        if kind == "candidat":
            avancement.append(data)
    lignes = (job.get("result") or {}).get("lignes", []) if job.get("result") else []
    return {"status": job["status"], "personnage": job["personnage"],
            "avancement": avancement, "lignes": lignes,
            "gagnant": (job.get("result") or {}).get("gagnant"),
            "error": job.get("error")}


@app.get("/api/bench/{jid}/wav")
def api_bench_wav(jid: int, candidat: str):
    """WAV d'écoute comparative d'un candidat (résultat du bench)."""
    job = _bench_jobs.get(jid)
    if not job or not job.get("result"):
        raise HTTPException(404, "Bench indisponible.")
    for l in job["result"].get("lignes", []):
        if l["candidat"] == candidat and Path(l["wav"]).exists():
            return FileResponse(l["wav"], media_type="audio/wav")
    raise HTTPException(404, f"WAV introuvable pour : {candidat}")


@app.post("/api/bench/promouvoir")
def api_bench_promouvoir(payload: BenchPromouvoirIn):
    """Le gagnant devient la référence du personnage dans voix.txt (backup .bak)."""
    try:
        res = bench.promouvoir(config.VOIX_FILE, payload.personnage.strip(),
                                payload.candidat.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Promotion échouée : {exc}")
    return res


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
# Incises de dialogue (M20) : prévisualisation + application (jamais auto)
# ---------------------------------------------------------------------------

def _contenu_travail(fichier: str) -> str:
    """Contenu de travail d'un document : brouillon s'il existe, sinon l'original."""
    p = _chemin_projet(fichier)
    brouillon = _BROUILLONS / p.name
    if brouillon.exists():
        return brouillon.read_text(encoding="utf-8")
    return p.read_text(encoding="utf-8")


@app.post("/api/document/incises")
def api_incises(payload: IncisesIn):
    """Prévisualise le nettoyage des incises (M20, dry-run : n'écrit rien)."""
    from engine.incises import (
        FiltrePersonnages,
        nettoyer as nettoyer_regex,
        synchroniser_map,
    )
    from engine.incises_llm import nettoyer_llm, ollama_disponible
    if payload.mode not in ("auto", "import_roman", "nettoyer_tagge"):
        raise HTTPException(400, "Mode inconnu : auto | import_roman | nettoyer_tagge")
    if payload.keep_action not in ("narration", "garder", "supprimer"):
        raise HTTPException(400, "keep_action inconnu : narration | garder | supprimer")
    if payload.moteur not in ("auto", "llm", "regex"):
        raise HTTPException(400, "Moteur inconnu : auto | llm | regex")
    _chemin_projet(payload.fichier)
    contenu = _contenu_travail(payload.fichier)
    p = _fichier_personnages(payload.fichier)
    mapping = {}
    if p.exists():
        try:
            mapping = _lire_csv_mapping(p)
        except (OSError, csv.Error):
            mapping = {}
    moteur = payload.moteur
    if moteur == "auto":
        moteur = "llm" if ollama_disponible() else "regex"
    filtre = None
    if not payload.accepter_tous:
        stop_supp = {s.strip().lower()
                     for s in (payload.stop_mots or "").split(",") if s.strip()}
        filtre = FiltrePersonnages(min_repliques=max(1, payload.min_repliques),
                                   preuve_incise=payload.preuve_incise,
                                   verif_minuscule=payload.verif_minuscule,
                                   stop_mots=frozenset(stop_supp))
    try:
        if moteur == "llm":
            res = nettoyer_llm(contenu, mapping=mapping,
                               voix_defaut=payload.voix_defaut or "Narrateur",
                               narrateur_je=(payload.narrateur_je or "").strip() or None,
                               filtre=filtre)
        else:
            res = nettoyer_regex(contenu, mode=payload.mode,
                                 keep_action=payload.keep_action, mapping=mapping,
                                 voix_defaut=payload.voix_defaut or "Narrateur",
                                 narrateur_je=(payload.narrateur_je or "").strip() or None,
                                 filtre=filtre)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    propose = synchroniser_map(mapping, res.nouveaux_personnages,
                               voix_defaut=payload.voix_defaut or "Narrateur")
    return {"fichier": payload.fichier, "texte_nettoye": res.texte,
            "nouveaux_personnages": res.nouveaux_personnages,
            "personnages_rejetes": res.stats.get("personnages_rejetes") or {},
            "mapping_propose": propose, "stats": res.stats, "moteur": moteur}


@app.post("/api/document/incises/appliquer")
def api_incises_appliquer(payload: IncisesAppliquerIn):
    """Applique le nettoyage validé : écrit le brouillon + fusionne le .map."""
    from engine.incises import synchroniser_map
    _chemin_projet(payload.fichier)
    contenu = (payload.contenu or "").strip()
    if not contenu:
        raise HTTPException(400, "Contenu nettoyé vide.")
    _BROUILLONS.mkdir(parents=True, exist_ok=True)
    brouillon = _BROUILLONS / Path(payload.fichier).name
    brouillon.write_text(contenu, encoding="utf-8")
    p = _fichier_personnages(payload.fichier)
    mapping = {}
    if p.exists():
        try:
            mapping = _lire_csv_mapping(p)
        except (OSError, csv.Error):
            mapping = {}
    propre = {k: v for k, v in (payload.personnages or {}).items()
              if k.strip() and v}
    fusion = synchroniser_map(mapping, list(propre.keys()),
                              voix_defaut="Narrateur")
    for k, v in propre.items():
        if v.strip():
            fusion[k] = v.strip()
    _ecrire_csv_mapping(p, fusion)
    return {"fichier": payload.fichier, "brouillon": brouillon.name,
            "personnages": fusion}


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


@app.post("/api/musique/importer")
async def api_musique_importer(fichier: UploadFile = File(...)):
    """Importe le lit musical BGM (wav/mp3/flac/ogg) : devient le lit actif."""
    config.ensure_dirs()
    nom = Path(fichier.filename or "lit.wav").name
    nom = nom.replace("/", "_").replace("\\", "_")
    if not nom or nom.startswith("."):
        raise HTTPException(400, "Nom de fichier invalide.")
    if not nom.lower().endswith((".wav", ".mp3", ".flac", ".ogg")):
        nom = Path(nom).stem + ".wav"
    dest = config.MUSIQUE_DIR / nom
    if dest.exists():
        dest = config.MUSIQUE_DIR / f"{dest.stem}_2{dest.suffix}"
    try:
        data = await fichier.read()
        if len(data) > 100 * 1024 * 1024:
            raise HTTPException(400, "Fichier trop volumineux (max 100 Mo).")
        if len(data) < 1000:
            raise HTTPException(400, "Fichier trop petit ou vide.")
        dest.write_bytes(data)
    except HTTPException:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise HTTPException(500, f"Import du lit musical échoué : {exc}")
    config.set_bgm(dest, config.BGM_VOLUME)
    _sauver_persistance({"bgm_lit": str(dest)})
    return {"lit": nom, "chemin": str(dest), "volume": config.BGM_VOLUME}


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
# Onglet Voix — extraction audio depuis vidéo, waveform, segment, transcription
# ---------------------------------------------------------------------------

_VOIX_WORK = config.OUTPUT_DIR / ".voix_work"
_VOIX_WORK.mkdir(parents=True, exist_ok=True)


@app.post("/api/voix/extraire-audio")
async def api_voix_extraire_audio(fichier: UploadFile = File(...)):
    """Upload d'un fichier vidéo/audio, extraction de la piste son en WAV."""
    nom = (fichier.filename or "upload").replace("/", "_").replace("\\", "_")
    src = _VOIX_WORK / nom
    MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2 Go
    total = 0
    CHUNK = 1024 * 1024  # 1 Mo
    with open(src, "wb") as f:
        while True:
            chunk = await fichier.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SIZE:
                src.unlink(missing_ok=True)
                raise HTTPException(413, "Fichier trop volumineux (max 2 Go)")
            f.write(chunk)

    out_wav = _VOIX_WORK / f"{src.stem}.wav"
    try:
        result = await asyncio.to_thread(audio_extract.extraire_audio, str(src), str(out_wav))
    except Exception as exc:
        raise HTTPException(400, f"Extraction échouée : {exc}")
    return result


@app.get("/api/voix/waveform")
def api_voix_waveform(file: str, points: int = 2000):
    """Renvoie les pics d'amplitude pour le rendu waveform."""
    path = Path(file)
    if not path.is_file():
        raise HTTPException(404, "Fichier introuvable")
    try:
        data = audio_extract.waveform_data(str(path), num_points=points)
    except Exception as exc:
        raise HTTPException(400, f"Erreur waveform : {exc}")
    return {"peaks": data, "num_points": len(data)}


@app.get("/api/voix/wav-raw")
def api_voix_wav_raw(file: str):
    """Sert un fichier WAV brut pour WaveSurfer."""
    path = Path(file)
    if not path.is_file():
        raise HTTPException(404, "Fichier introuvable")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/voix/decouper")
def api_voix_decouper(payload: VoixDecouperIn):
    """Découpe un segment [start, stop] d'un fichier audio."""
    path = Path(payload.fichier)
    if not path.is_file():
        raise HTTPException(404, "Fichier introuvable")
    try:
        result = audio_extract.decouper_segment(
            str(path), payload.start, payload.stop,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result


@app.post("/api/voix/ajuster-vad")
def api_voix_ajuster_vad(payload: VoixDecouperIn):
    """Recale [start, stop] sur la parole (VAD énergie) : début avancé au
    premier span, fin reculée au dernier (vers l'intérieur, tolérance 1 s)."""
    from engine import vad as _vad
    path = Path(payload.fichier)
    if not path.is_file():
        raise HTTPException(404, "Fichier introuvable")
    if payload.stop <= payload.start:
        raise HTTPException(400, "Segment [start, stop] invalide.")
    try:
        import soundfile as _sf
        y, sr = _sf.read(str(path), dtype="float32", always_2d=True)
        spans = _vad.detecter_parole(y.mean(axis=1).astype("float32"), sr)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Détection échouée : {exc}")
    res = _vad.ajuster_segment(spans, payload.start, payload.stop)
    res["segments"] = [[round(s, 2), round(e, 2)] for s, e in spans]
    return res


@app.post("/api/voix/transcrire-segment")
def api_voix_transcrire_segment(payload: VoixTranscrireIn):
    """Transcrit un segment audio (ou la totalité) via Whisper."""
    path = Path(payload.fichier)
    if not path.is_file():
        raise HTTPException(404, "Fichier introuvable")
    import librosa
    import numpy as np
    from engine import verifier
    try:
        audio, sr = librosa.load(str(path), sr=None, mono=True)
        audio = audio.astype(np.float32)
        if payload.start is not None and payload.stop is not None and payload.stop > payload.start:
            i0, i1 = int(payload.start * sr), int(payload.stop * sr)
            i0 = max(0, i0)
            i1 = min(len(audio), i1)
            audio = audio[i0:i1]
        lang = payload.lang or config.WHISPER_LANG
        texte_complet = verifier.transcribe(audio, sr, lang=lang).strip()
        texte_horo = verifier.transcribe_timestamped(audio, sr, lang=lang).strip()
    except Exception as exc:
        raise HTTPException(500, f"Transcription échouée : {exc}")
    return {"texte": texte_complet, "horodates": texte_horo}


@app.post("/api/voix/enregistrer")
async def api_voix_enregistrer(nom: str = Form(...),
                               transcription: str = Form(...),
                               wav: UploadFile = File(...)):
    """Enregistre un couple wav + txt et met à jour voix.txt."""
    import re as _re
    nom = nom.strip()
    if not nom:
        raise HTTPException(400, "Le nom ne peut pas être vide")
    nom = _re.sub(r"[\[\]]", "", nom).strip()
    nom = _re.sub(r"[^A-Za-z0-9À-ÿ _-]", "", nom)[:80]
    if not nom:
        raise HTTPException(400, "Nom invalide")

    existing = load_voix() if config.VOIX_FILE.exists() else None
    if existing and nom in existing:
        raise HTTPException(409, f"La voix « {nom} » existe déjà")

    wav_data = await wav.read()
    wav_name = f"{nom}.wav"
    wav_path = config.VOIX_AUDIO_DIR / wav_name
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    wav_path.write_bytes(wav_data)

    txt_name = f"{nom}.txt"
    txt_path = config.VOIX_AUDIO_DIR / txt_name
    txt_path.write_text(transcription + "\n", encoding="utf-8")

    lignes = []
    if config.VOIX_FILE.exists():
        lignes = [l.strip() for l in config.VOIX_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    lignes.append(f"[{nom}], {wav_name}, {txt_name}")
    config.VOIX_FILE.write_text("\n".join(lignes) + "\n", encoding="utf-8")

    return {"nom": nom, "wav": wav_name, "txt": txt_name}


# ---------------------------------------------------------------------------
# Nettoyage des voix (Demucs + DeepFilterNet) — job d'arrière-plan + SSE
# ---------------------------------------------------------------------------

# Espace de travail des nettoyages (dans le volume temporaire, sinon /tmp).
_CLEAN_WORK = config.OUTPUT_DIR / ".clean"
_clean_jobs: dict[int, dict] = {}
_clean_jobid = itertools.count(1)


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
    if os.environ.get("VOICEBUILDER_WARMUP") == "1":
        # Précharge moteur + Whisper en tâche de fond (première inférence
        # sans latence) ; le serveur répond aussitôt.
        from engine import warmup as _warmup
        _warmup.lancer_warmup()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
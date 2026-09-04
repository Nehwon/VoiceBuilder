/* VoiceBuilder — frontend (M7). Vanilla JS, aucune dépendance. */
"use strict";

const $ = (id) => document.getElementById(id);

let voixNoms = [];
let docCourant = null;      // {fichier, brouillon} — null si fichier local
let cm = null;              // instance CodeMirror
let montageId = null;       // résultat de la dernière génération
let personnages = {};       // { personnage: voix }
let voixDispo = [];         // noms de voix proposés dans le selecteur

// ---------------------------------------------------------------- thème (clair par défaut, sombre optionnel)
function appliquerTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("vb-theme", t);
  $("btn-theme").textContent = t === "dark" ? "☀️" : "🌙";
}
(() => {
  const saved = localStorage.getItem("vb-theme");
  const t = saved ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  appliquerTheme(t);
})();
$("btn-theme").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  appliquerTheme(cur === "dark" ? "light" : "dark");
});

// ---------------------------------------------------------------- navigation par vues
function mountVue(nom) {
  $("vue-edit").hidden = nom !== "edit";
  $("vue-montage").hidden = nom !== "montage";
  $("vue-projets").hidden = nom !== "projets";
  $("tab-edit").classList.toggle("actif", nom === "edit");
  $("tab-montage").classList.toggle("actif", nom === "montage");
  $("tab-projets").classList.toggle("actif", nom === "projets");
  if (nom === "edit" && cm) cm.refresh();
  if (nom === "montage" && montageId) chargerBlocs();
  if (nom === "projets") { chargerDetailsProjets(); chargerVoixListe(); }
}
$("tab-edit").addEventListener("click", () => mountVue("edit"));
$("tab-montage").addEventListener("click", () => mountVue("montage"));
$("tab-projets").addEventListener("click", () => mountVue("projets"));
$("btn-gerer").addEventListener("click", () => mountVue("projets"));

// l'onglet Montage est toujours accessible (le contenu dépend du résultat)
function majMontage() {
  const actif = !!(montageId && cm && cm.getValue().trim());
  $("tab-montage").classList.toggle("actif", $("vue-montage") && !$("vue-montage").hidden);
}

// ---------------------------------------------------------------- notifications (in-app)
function notifier(msg, type) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + (type === "err" ? "erreur" : "ok");
  t.hidden = false;
  clearTimeout(notifier._t);
  notifier._t = setTimeout(() => { t.hidden = true; }, 3500);
}

// ---------------------------------------------------------------- modal d'erreur
const modalErreur = $("modal-erreur");
function afficherErreur(msg) {
  $("erreur-msg").textContent = msg || "Erreur inconnue.";
  ouvrirModal(modalErreur);
}
$("btn-erreur-fermer").addEventListener("click", () => fermerModal(modalErreur));

// ---------------------------------------------------------------- progression
const $progBar = $("progression-remplie");
function majProgression(index, total, personnage, duree) {
  const pct = total > 0 ? Math.round((index / total) * 100) : 0;
  $progBar.style.width = pct + "%";
  $("progression-compteur").textContent = `${pct}%`;
  $("progression-label").textContent =
    personnage ? `Bloc ${index}/${total} — ${personnage}${duree ? ` · ${duree} s` : ""}` : "Génération en cours…";
}
function demarrerProgression() {
  $("progression").hidden = false;
  $progBar.style.width = "0%";
  $("progression-compteur").textContent = "0%";
  $("progression-label").textContent = "Lancement de la génération…";
}
function terminerProgression() {
  $("progression").hidden = true;
  $progBar.style.width = "0%";
}

// ---------------------------------------------------------------- modals
function ouvrirModal(el) { el.hidden = false; document.body.classList.add("modal-open"); }
function fermerModal(el) { el.hidden = true; document.body.classList.remove("modal-open"); }
const modalReglages = $("modal-reglages");
const modalAide = $("modal-aide");
const modalPerso = $("modal-personnages");
const modalNom = $("modal-nom");

$("btn-reglages").addEventListener("click", () => ouvrirModal(modalReglages));
$("btn-modal-fermer").addEventListener("click", () => fermerModal(modalReglages));
$("btn-aide").addEventListener("click", () => ouvrirModal(modalAide));
$("btn-aide-fermer").addEventListener("click", () => fermerModal(modalAide));

const modalModeles = $("modal-modeles");
$("btn-modeles").addEventListener("click", () => { chargerModele(); ouvrirModal(modalModeles); });
$("btn-modele-fermer").addEventListener("click", () => fermerModal(modalModeles));
$("btn-modele-telecharger").addEventListener("click", telechargerModele);
modalModeles.addEventListener("click", (e) => { if (e.target === modalModeles) fermerModal(modalModeles); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!modalNom.hidden) { annulerNom(); return; }
    if (!modalModeles.hidden) { fermerModal(modalModeles); return; }
    if (!$("modal-nettoyage").hidden) { fermerModal($("modal-nettoyage")); return; }
    if (!$("modal-confirm").hidden) { fermerModal($("modal-confirm")); if (_confirmResolve) { _confirmResolve(false); _confirmResolve = null; } return; }
    if (!$("modal-voix-import").hidden) { fermerModal($("modal-voix-import")); return; }
    [modalReglages, modalAide, modalPerso, modalErreur].forEach((m) => { if (!m.hidden) fermerModal(m); });
  }
});

// ---------------------------------------------------------------- nom de document (modal promesse)
let _resolveNom = null;
function demanderNom(titre, defaut) {
  $("nom-titre").textContent = titre;
  $("nom-input").value = defaut || "";
  ouvrirModal(modalNom);
  setTimeout(() => $("nom-input").focus(), 0);
  return new Promise((res) => { _resolveNom = res; });
}
function annulerNom() {
  fermerModal(modalNom);
  if (_resolveNom) { _resolveNom(null); _resolveNom = null; }
}
$("btn-nom-ok").addEventListener("click", () => {
  const val = $("nom-input").value.trim();
  fermerModal(modalNom);
  if (_resolveNom) { _resolveNom(val || null); _resolveNom = null; }
});
$("btn-nom-annuler").addEventListener("click", annulerNom);
modalNom.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); $("btn-nom-ok").click(); }
});

// ---------------------------------------------------------------- éditeur
function initEditeur() {
  cm = CodeMirror($("zone-editeur"), {
    mode: "tagged",
    lineNumbers: true,
    lineWrapping: true,
    placeholder: "[Narrateur]: …",
    extraKeys: { Tab: completer },
  });
  cm.on("change", () => { autoEnregistrer(); majMontage(); majBoutonGenerer(); });
}

// ---------------------------------------------------------------- autocomplétion (Tab)
function completer() {
  const { line, ch } = cm.getCursor();
  const ligne = cm.getLine(line).slice(0, ch);
  const idx = ligne.lastIndexOf("[");
  if (idx < 0 || ligne.indexOf("]", idx) < ch) return;
  const prefixe = ligne.slice(idx + 1).toLowerCase();
  const nom = Object.keys(personnages)
    .find((n) => n.toLowerCase().startsWith(prefixe));
  if (nom) {
    cm.replaceRange(nom.slice(prefixe.length), { line, ch }, { line, ch });
    cm.focus();
  }
}

// ---------------------------------------------------------------- autosave (documents serveur uniquement)
function autoEnregistrer() {
  if (!docCourant) return;
  clearTimeout(autoEnregistrer._t);
  autoEnregistrer._t = setTimeout(async () => {
    try {
      await fetch("/api/document/enregistrer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fichier: docCourant.fichier, contenu: cm.getValue() }),
      });
      $("doc-statut").textContent = "✔ sauvegardé";
    } catch { $("doc-statut").textContent = "⚠ échec sauvegarde"; }
  }, 600);
}

// ---------------------------------------------------------------- documents serveur
async function chargerDocuments() {
  const r = await fetch("/api/documents");
  const { documents } = await r.json();
  const sel = $("sel-doc");
  sel.innerHTML = "";
  for (const d of documents) {
    const o = document.createElement("option");
    o.value = d; o.textContent = d;
    sel.appendChild(o);
  }
}

async function chargerPersonnagesDoc(fichier) {
  const r = await fetch(`/api/document/personnages?fichier=${encodeURIComponent(fichier)}`);
  if (!r.ok) return;
  const d = await r.json();
  personnages = d.personnages || {};
  voixDispo = d.voix || [];
  majBoutonsPerso();
}

function persisterPersonnages() {
  if (!docCourant) return;                    // fichier local : mémorisé en session
  fetch("/api/document/personnages", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fichier: docCourant.fichier, personnages }),
  });
}

$("btn-ouvrir").addEventListener("click", async () => {
  const choix = $("sel-doc").value;
  if (!choix) { notifier("Aucun document sélectionné.", "err"); return; }
  const r = await fetch("/api/document/ouvrir", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fichier: choix }),
  });
  const d = await r.json();
  docCourant = { fichier: d.fichier, brouillon: d.brouillon };
  cm.setValue(d.contenu ?? "");
  majMontage();
  await chargerPersonnagesDoc(d.fichier);
  $("doc-statut").textContent = `brouillon : ${d.brouillon} (source non modifiée)`;
  mountVue("edit");
  notifier(`Document « ${d.fichier} » ouvert.`, "ok");
});

// ---------------------------------------------------------------- ouverture d'un fichier local
$("btn-fichier").addEventListener("click", () => $("file-local").click());
$("file-local").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = () => {
    docCourant = null;                       // pas d'auto-sauvegarde serveur
    personnages = {};                        // mapping en session uniquement
    voixDispo = [];
    cm.setValue(reader.result);
    majMontage();
    majBoutonsPerso();
    $("doc-statut").textContent = `local : ${f.name}`;
    mountVue("edit");
    notifier(`« ${f.name} » chargé depuis l'ordinateur.`, "ok");
  };
  reader.readAsText(f);
  e.target.value = "";
});

// ---------------------------------------------------------------- persistance projet (Nouveau / Enregistrer)
function normaliserNom(nom) {
  nom = nom.replace(/[/\\]/g, "_").trim();
  if (nom && !/\.[a-z0-9]+$/i.test(nom)) nom += ".md";
  return nom;
}
function selectDoc(fichier) { $("sel-doc").value = fichier; }
async function sauverDocumentProjet(fichier, contenu) {
  const r = await fetch("/api/document/sauver", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fichier, contenu }),
  });
  if (!r.ok) { notifier((await r.json()).detail, "err"); return null; }
  return await r.json();
}

$("btn-nouveau").addEventListener("click", async () => {
  const nom = normaliserNom((await demanderNom("Nouveau document", "histoire.md")) || "");
  if (!nom) return;
  const d = await sauverDocumentProjet(nom, "");
  if (!d) return;
  cm.setValue("");
  docCourant = { fichier: d.fichier, brouillon: d.brouillon };
  personnages = {}; voixDispo = [];
  majBoutonsPerso(); majMontage();
  await chargerDocuments();
  selectDoc(d.fichier);
  $("doc-statut").textContent = `nouveau : ${d.fichier}`;
  mountVue("edit");
  notifier(`Nouveau document « ${d.fichier} » créé.`, "ok");
});

$("btn-sauver").addEventListener("click", async () => {
  const contenu = cm.getValue();
  const mapping = personnages;                       // mapping courant (session)
  let fichier = docCourant ? docCourant.fichier : null;
  if (!fichier) {
    const nom = normaliserNom((await demanderNom("Enregistrer dans le projet", "document.md")) || "");
    if (!nom) return;
    fichier = nom;
  }
  const d = await sauverDocumentProjet(fichier, contenu);
  if (!d) return;
  docCourant = { fichier: d.fichier, brouillon: d.brouillon };
  personnages = mapping;
  majBoutonsPerso(); majMontage();
  persisterPersonnages();                            // mapping → fichier .map du doc
  await chargerDocuments();
  selectDoc(d.fichier);
  $("doc-statut").textContent = `enregistré dans le projet : ${d.fichier}`;
  mountVue("edit");
  notifier(`« ${d.fichier} » enregistré dans le projet.`, "ok");
});

// ---------------------------------------------------------------- voix (dispo pour le selecteur)
async function chargerVoix() {
  const r = await fetch("/api/voix");
  if (!r.ok) { voixNoms = []; voixDispo = []; return; }
  voixNoms = await r.json();
  voixDispo = voixNoms.map((v) => v.nom);
}

// ---------------------------------------------------------------- boutons personnages (barre d'outils)
function majBoutonsPerso() {
  const box = $("perso-boutons");
  box.innerHTML = "";
  for (const pers in personnages) {
    const b = document.createElement("button");
    b.textContent = pers;
    b.title = `Insérer la balise [${pers}]: (voix : ${personnages[pers] || "—"})`;
    b.onclick = () => {
      const ins = `[${pers}]: `;
      const sel = cm.getSelection();
      const pos = cm.getCursor();
      if (!sel) {
        cm.replaceRange(ins, pos);
      } else {
        const { from, to } = cm.listSelections()[0];
        cm.replaceRange(ins + sel, from, to);
      }
      cm.focus();
    };
    box.appendChild(b);
  }
}

// ---------------------------------------------------------------- modal personnages
// Tags non-verbaux CosyVoice3 : jamais traités comme des personnages.
const TAGS_NON_VERBAUX = new Set([
  "sigh", "laughter", "breath", "quick_breath", "cough", "clucking",
  "hissing", "lipsmack", "noise", "vocalized-noise", "accent", "mn", "stop",
]);

function detecterPersonnagesTexte(texte) {
  const trouves = [];
  for (const ligne of (texte || "").split("\n")) {
    const m = ligne.match(/^\s*\[([^\]]+)\]/);
    if (!m) continue;
    const nom = m[1].trim();
    if (!nom || TAGS_NON_VERBAUX.has(nom.toLowerCase())) continue;
    if (!trouves.includes(nom)) trouves.push(nom);
  }
  return trouves;
}

function ouvrirPerso() {
  if (!voixDispo.length) {
    notifier("Aucune voix disponible : vérifie le dossier des voix (Réglages).", "err");
    return;
  }
  remplirLignesPerso();
  ouvrirModal(modalPerso);
}
$("btn-personnages").addEventListener("click", ouvrirPerso);

function remplirLignesPerso() {
  const tbody = $("perso-lignes");
  tbody.innerHTML = "";
  // personnages du texte + ceux déjà affectés (union, sans doublon)
  const duTexte = detecterPersonnagesTexte(cm ? cm.getValue() : "");
  const noms = duTexte.slice();
  for (const n of Object.keys(personnages)) if (!noms.includes(n)) noms.push(n);
  if (!noms.length) noms.push("");
  for (const pers of noms) {
    ajouterLignePerso(pers, personnages[pers] || "");
  }
}

function ajouterLignePerso(nom, voix) {
  const tr = document.createElement("tr");

  const tdNom = document.createElement("td");
  const inputNom = document.createElement("input");
  inputNom.type = "text";
  inputNom.value = nom;
  inputNom.placeholder = "ex. Narrateur";
  tdNom.appendChild(inputNom);

  const tdVoix = document.createElement("td");
  const select = document.createElement("select");
  const vide = document.createElement("option");
  vide.value = ""; vide.textContent = "— choisir —";
  select.appendChild(vide);
  for (const v of voixDispo) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    select.appendChild(o);
  }
  select.value = voix;
  tdVoix.appendChild(select);

  const tdDel = document.createElement("td");
  const del = document.createElement("button");
  del.textContent = "✕";
  del.className = "del-row";
  del.title = "Supprimer ce personnage";
  del.onclick = () => tr.remove();
  tdDel.appendChild(del);

  tr.appendChild(tdNom); tr.appendChild(tdVoix); tr.appendChild(tdDel);
  $("perso-lignes").appendChild(tr);
}

$("btn-perso-ajouter").addEventListener("click", () => ajouterLignePerso("", ""));
$("btn-perso-save").addEventListener("click", () => {
  const nouveau = {};
  const rows = $("perso-lignes").querySelectorAll("tr");
  for (const tr of rows) {
    const nom = tr.querySelector("input").value.trim();
    const voix = tr.querySelector("select").value;
    if (nom && voix) nouveau[nom] = voix;
  }
  personnages = nouveau;
  majBoutonsPerso();
  persisterPersonnages();
  fermerModal(modalPerso);
  notifier(`${Object.keys(nouveau).length} personnage(s) enregistré(s).`, "ok");
});
$("btn-perso-fermer").addEventListener("click", () => {
  remplirLignesPerso();      // annule les saisies non enregistrées
  fermerModal(modalPerso);
});

// ---------------------------------------------------------------- réglages
$("btn-dir").addEventListener("click", async () => {
  const r = await fetch("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_dir: $("audio-dir").value }),
  });
  if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
  await chargerVoix();
  await chargerEtat();
  notifier("Dossier des voix appliqué.", "ok");
});
$("btn-save").addEventListener("click", () =>
  notifier("Réglages utilisés côté serveur à la génération.", "ok"));

// ---------------------------------------------------------------- génération
async function sauvegarderAvantGeneration() {
  if (!docCourant) return;                 // fichier local : rien à écrire côté serveur
  const contenu = cm.getValue();
  await fetch("/api/document/enregistrer", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fichier: docCourant.fichier, contenu }),
  });
  persisterPersonnages();                  // mapping → fichier .map du doc
}

let generationActive = false;
let contenuGenere = null;   // contenu éditeur au moment de la génération

function majBoutonGenerer() {
  const peutRegenerer = !generationActive && contenuGenere !== null &&
    contenuGenere !== cm.getValue();
  if (generationActive) {
    setGenererEtat(false, "Génération en cours…");
  } else if (contenuGenere === null) {
    setGenererEtat(true, "Générer");
  } else if (peutRegenerer) {
    setGenererEtat(true, "Générer");
  } else {
    setGenererEtat(false, "Généré");
  }
}

function setGenererEtat(actif, libelle) {
  $("generer").disabled = !actif;
  $("generer").textContent = libelle;
  $("generer").classList.toggle("en-cours", !actif);
}

$("generer").addEventListener("click", async () => {
  if (generationActive) return;
  generationActive = true;
  contenuGenere = null;
  majBoutonGenerer();
  $("log").textContent = "Lancement…\n";
  $("montage").src = "";
  demarrerProgression();
  const terminer = () => {
    generationActive = false;
    majBoutonGenerer();
    terminerProgression();
  };
  const persosTexte = detecterPersonnagesTexte(cm.getValue());
  const sansVoix = persosTexte.filter((p) => !personnages[p]);
  if (!persosTexte.length || sansVoix.length) {
    terminer();
    const message = !persosTexte.length
      ? "Aucun personnage détecté dans le texte. Ajoute des balises [Personnage]: puis affecte une voix à chacun."
      : "Personnage(s) sans voix définie : " + sansVoix.join(", ") + ". Affecte une voix dans la liste des personnages.";
    $("log").textContent += `\n❌ ${message}\n`;
    notifier(message, "err");
    afficherErreur(message);
    remplirLignesPerso();
    ouvrirModal(modalPerso);
    return;
  }
  try {
    await sauvegarderAvantGeneration();
  } catch {
    terminer();
    notifier("Échec de la sauvegarde avant génération.", "err");
    afficherErreur("Échec de la sauvegarde avant génération.");
    return;
  }
  const r = await fetch("/api/generer", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      texte: cm.getValue(),
      personnages,
      pause: parseFloat($("pause").value),
      vitesse: parseFloat($("vitesse").value),
      max_chars: parseInt($("maxchars").value, 10),
      verify: $("verify").checked,
      device: $("device").value,
      load_vllm: $("load-vllm").checked,
      load_trt: $("load-trt").checked,
    }),
  });
  if (!r.ok) {
    let m = "Erreur lors du lancement de la génération.";
    try { m = (await r.json()).detail || m; } catch { /* corps non JSON */ }
    $("log").textContent += `\n❌ ${m}\n`;
    notifier(m, "err");
    afficherErreur(m);
    terminer();
    return;
  }
  const { id } = await r.json();
  montageId = id;

  const ev = new EventSource(`/api/generer/${id}/stream`);
  let fini = false;
  const fin = () => {
    if (fini) return;
    fini = true;
    ev.close();
    contenuGenere = cm.getValue();
    generationActive = false;
    majBoutonGenerer();
    terminerProgression();
  };
  ev.addEventListener("bloc", (e) => {
    const b = JSON.parse(e.data);
    $("log").textContent +=
      `[${b.index}/${b.total}] ${b.personnage} (${b.chars} chars) — ${b.duree} s\n`;
    majProgression(b.index, b.total, b.personnage, b.duree);
    if (b.wav) {
      ajouterBlocTempsReel(b);
    }
  });
  ev.addEventListener("result", (e) => {
    const res = JSON.parse(e.data);
    $("log").textContent +=
      `\nTerminé : ${res.duree} s, ${res.blocs.length} blocs.\n`;
    $("montage").src = `/api/generer/${id}/result`;
    montageId = id;
    majMontage();
    mountVue("montage");
  });
  ev.addEventListener("error", (e) => {
    if (e.data) {
      const d = JSON.parse(e.data).error;
      $("log").textContent += `\n❌ ${d}\n`;
      notifier(d, "err");
      afficherErreur(d);
    }
  });
  ev.addEventListener("end", fin);
});

// ---------------------------------------------------------------- montage : blocs
let montageBlocs = [];

async function chargerBlocs() {
  if (!montageId) return;
  try {
    const r = await fetch(`/api/generer/${montageId}/blocs`);
    if (!r.ok) { notifier("Impossible de charger les blocs.", "err"); return; }
    const d = await r.json();
    montageBlocs = d.blocs || [];
    const duree = d.duree != null ? `${d.duree} s` : "…";
    $("montage-info").textContent = `Durée totale : ${duree} · ${montageBlocs.length} bloc(s)`;
    remplirListeBlocs();
  } catch { notifier("Erreur au chargement des blocs.", "err"); }
}

// Une carte par bloc : audio + texte + infos + boutons.
function remplirListeBlocs() {
  const box = $("liste-blocs");
  box.innerHTML = "";
  if (!montageBlocs.length) {
    box.innerHTML = '<p class="liste-vide">Aucun bloc (génère d\u2019abord un montage).</p>';
    return;
  }
  montageBlocs.forEach((b, i) => {
    const carte = document.createElement("article");
    carte.className = "bloc-carte";
    carte.dataset.id = b.id;

    const tete = document.createElement("div");
    tete.className = "bloc-carte-tete";
    const titre = document.createElement("strong");
    titre.textContent = `${i + 1}. ${b.personnage}`;
    const dur = document.createElement("span");
    dur.className = "bloc-carte-duree";
    dur.textContent = `${b.duree} s · ${b.chars} chars · ${b.voix || "—"}`;
    tete.append(titre, dur);

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = `/api/generer/${montageId}/bloc/${b.id}/wav`;

    const texte = document.createElement("p");
    texte.className = "bloc-carte-texte";
    texte.textContent = b.texte || "—";

    const actions = document.createElement("div");
    actions.className = "bloc-carte-actions";
    const btnRegen = document.createElement("button");
    btnRegen.textContent = "Regénérer ce bloc";
    btnRegen.onclick = () => actionBloc(b.id, "regenerer", btnRegen);
    const btnDiv = document.createElement("button");
    btnDiv.textContent = "Diviser ce bloc";
    btnDiv.onclick = () => actionBloc(b.id, "diviser", btnDiv);
    actions.append(btnRegen, btnDiv);

    carte.append(tete, audio, texte, actions);
    box.appendChild(carte);
  });
}

// ---------------------------------------------------------------- écoute temps réel : ajoute un bloc au fur et à mesure
function ajouterBlocTempsReel(b) {
  const box = $("liste-blocs");
  // si c'est le premier bloc, vider le message "Aucun bloc"
  if (box.querySelector(".liste-vide")) {
    box.innerHTML = "";
  }
  // éviter les doublons si l'événement arrive deux fois
  if (box.querySelector(`[data-id="${b.id}"]`)) return;

  const i = (montageBlocs.length) + 1;
  const carte = document.createElement("article");
  carte.className = "bloc-carte";
  carte.dataset.id = b.id;

  const tete = document.createElement("div");
  tete.className = "bloc-carte-tete";
  const titre = document.createElement("strong");
  titre.textContent = `${i}. ${b.personnage}`;
  const dur = document.createElement("span");
  dur.className = "bloc-carte-duree";
  dur.textContent = `${b.duree} s · ${b.chars} chars · ${b.voix || "—"}`;
  tete.append(titre, dur);

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = b.wav
    ? `/api/generer/${montageId}/bloc/${b.id}/wav`
    : "";

  const texte = document.createElement("p");
  texte.className = "bloc-carte-texte";
  texte.textContent = b.texte || "—";

  const actions = document.createElement("div");
  actions.className = "bloc-carte-actions";
  const btnRegen = document.createElement("button");
  btnRegen.textContent = "Regénérer ce bloc";
  btnRegen.onclick = () => actionBloc(b.id, "regenerer", btnRegen);
  const btnDiv = document.createElement("button");
  btnDiv.textContent = "Diviser ce bloc";
  btnDiv.onclick = () => actionBloc(b.id, "diviser", btnDiv);
  actions.append(btnRegen, btnDiv);

  carte.append(tete, audio, texte, actions);
  box.appendChild(carte);

  // mémoriser pour le futur rechargement / concaténation
  montageBlocs.push(b);
}

async function actionBloc(bid, action, btn) {
  if (btn) btn.disabled = true;
  const msg = action === "regenerer" ? "Bloc régénéré." : "Bloc divisé en deux.";
  try {
    const r = await fetch(`/api/generer/${montageId}/bloc/${bid}/${action}`, { method: "POST" });
    if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
    await chargerBlocs();
    notifier(msg, "ok");
  } catch { notifier("Action bloc échouée.", "err"); }
  finally { if (btn) btn.disabled = false; }
}

$("btn-concat").addEventListener("click", async () => {
  $("btn-concat").disabled = true;
  try {
    const r = await fetch(`/api/generer/${montageId}/concatener`, { method: "POST" });
    if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
    const d = await r.json();
    $("montage").src = `/api/generer/${montageId}/result`;
    $("montage-info").textContent = `Durée totale : ${d.duree} s · ${montageBlocs.length} bloc(s)`;
    notifier("Montage re-créé.", "ok");
  } catch { notifier("Concatenation échouée.", "err"); }
  finally { $("btn-concat").disabled = false; }
});

// ---------------------------------------------------------------- modèle CosyVoice3
let modelePresent = null;          // true | false | null (inconnu)
function afficherStatutModele(m) {
  const el = $("modele-statut");
  const fmt = (n) => (n >= 1e9 ? (n / 1e9).toFixed(1) + " Go" : (n >= 1e6 ? (n / 1e6).toFixed(0) + " Mo" : n + " o"));
  $("modele-manquants").textContent = (m.manquants && m.manquants.length ? m.manquants.join("\n") : "— aucun —");
  modelePresent = !!m.present;
  if (m.present) {
    el.className = "modele-statut ok";
    el.innerHTML = "✔ Modèle présent dans <code>" + m.dossier + "</code>.";
    $("btn-modele-telecharger").disabled = true;
  } else {
    el.className = "modele-statut missing";
    const partiel = m.octets > 0 ? ` · ${fmt(m.octets)} déjà présents` : "";
    el.innerHTML = `⚠ Modèle absent (${fmt(m.total)} attendus${partiel}).<br/>
      Source : <code>${m.source}</code> · <code>${m.id}</code>`;
    $("btn-modele-telecharger").disabled = false;
  }
  $("modele-source").value = m.source || "modelscope";
  majBanniere();
}

async function chargerModele() {
  try {
    const r = await fetch("/api/modeles");
    if (!r.ok) { afficherStatutModele({ present: false, manquants: [], octets: 0, total: 0, source: "modelscope", id: "", dossier: "?" }); return; }
    afficherStatutModele(await r.json());
  } catch { notifier("Impossible de lire l'état du modèle.", "err"); }
}

function setModeleProgression(label, pct) {
  $("modele-progress").hidden = false;
  $("modele-progress-label").textContent = label;
  $("modele-progress-compteur").textContent = (pct >= 0 ? Math.round(pct) + "%" : "");
  $("modele-progress-remplie").style.width = (pct >= 0 ? pct : 0) + "%";
  $("btn-modele-telecharger").disabled = true;
}

async function telechargerModele() {
  if (generationActive) { notifier("Attends la fin de la génération.", "err"); return; }
  const source = $("modele-source").value;
  const r = await fetch("/api/modeles/telecharger", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source }),
  });
  if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
  const { id } = await r.json();

  setModeleProgression("Téléchargement du modèle…", 0);
  const ev = new EventSource(`/api/modeles/${id}/stream`);
  let fini = false;
  const fin = () => {
    if (fini) return;
    fini = true;
    ev.close();
    $("modele-progress").hidden = true;
    chargerModele();
  };
  ev.addEventListener("prog", (e) => {
    const d = JSON.parse(e.data);
    setModeleProgression("Téléchargement du modèle…", d.pct);
  });
  ev.addEventListener("result", () => {
    notifier("Modèle CosyVoice3 téléchargé.", "ok");
    $("modele-progress-label").textContent = "Téléchargement terminé.";
    $("modele-progress-compteur").textContent = "100%";
    $("modele-progress-remplie").style.width = "100%";
  });
  ev.addEventListener("error", (e) => {
    if (e.data) {
      const d = JSON.parse(e.data).error;
      $("modele-progress-label").textContent = "Échec du téléchargement.";
      notifier(d, "err");
      afficherErreur(d);
    }
  });
  ev.addEventListener("end", fin);
}

// ---------------------------------------------------------------- état (dossier des voix)
async function chargerEtat() {
  const etat = await (await fetch("/api/etat")).json();
  $("audio-dir").value = etat.audio_dir;
  let msg = null;
  if (!etat.voix_file && etat.erreur) msg = { texte: etat.erreur, lien: "→ Régler le dossier des voix" };
  else if (!etat.voix_file) msg = { texte: "Aucun fichier de voix : configure le dossier des voix.", lien: "→ Régler le dossier des voix" };
  banniereVoix = msg;
  majBanniere();
}

// ---------------------------------------------------------------- bannière (voix → modèle, priorité absolue au modèle)
let banniereVoix = null;   // {texte, lien} | null
function majBanniere() {
  // le modèle est un prérequis : sa bannière prime toujours
  if (modelePresent === false) {
    if ($("banniere").dataset.perso !== "modele") {
      $("banniere").dataset.perso = "modele";
      $("banniere-msg").textContent =
        "Le modèle CosyVoice3 n'est pas encore téléchargé — télécharge-le depuis 🧠 Modèles (premier lancement).";
      $("banniere-lien").textContent = "→ Télécharger le modèle (~11 Go)";
      $("banniere-lien").hidden = false;
    }
    $("banniere-lien").onclick = (e) => { e.preventDefault(); ouvrirModal(modalModeles); };
    $("banniere").hidden = false;
    return;
  }
  $("banniere").dataset.perso = "";
  if (banniereVoix) {
    $("banniere-msg").textContent = banniereVoix.texte;
    $("banniere-lien").textContent = banniereVoix.lien || "→ Régler le dossier des voix";
    $("banniere-lien").hidden = false;
    $("banniere-lien").onclick = (e) => { e.preventDefault(); ouvrirModal(modalReglages); };
    $("banniere").hidden = false;
  } else {
    $("banniere").hidden = true;
  }
}

// ---------------------------------------------------------------- confirmation générique
const modalConfirm = $("modal-confirm");
let _confirmResolve = null;
function demanderConfirmation(titre, msg) {
  $("confirm-titre").textContent = titre;
  $("confirm-msg").textContent = msg;
  ouvrirModal(modalConfirm);
  return new Promise((res) => { _confirmResolve = res; });
}
$("btn-confirm-annuler").addEventListener("click", () => { fermerModal(modalConfirm); if (_confirmResolve) { _confirmResolve(false); _confirmResolve = null; } });
$("btn-confirm-ok").addEventListener("click", () => { fermerModal(modalConfirm); if (_confirmResolve) { _confirmResolve(true); _confirmResolve = null; } });
modalConfirm.addEventListener("click", (e) => { if (e.target === modalConfirm) { fermerModal(modalConfirm); if (_confirmResolve) { _confirmResolve(false); _confirmResolve = null; } } });

// ---------------------------------------------------------------- projets : détails + actions
async function chargerDetailsProjets() {
  try {
    const r = await fetch("/api/documents/details");
    if (!r.ok) throw new Error("details failed");
    const d = await r.json();
    renderProjets(d.documents || [], $("projets-liste"), false);
    renderProjets(d.archives || [], $("archives-liste"), true);
    $("archives-count").textContent = (d.archives || []).length;
  } catch { notifier("Impossible de charger les projets.", "err"); }
}

function fmtTaille(o) {
  if (o < 1024) return o + " o";
  if (o < 1024 * 1024) return (o / 1024).toFixed(1) + " Ko";
  return (o / (1024 * 1024)).toFixed(1) + " Mo";
}

function renderProjets(list, container, archived) {
  container.innerHTML = "";
  if (!list.length) {
    container.innerHTML = `<p class="liste-vide">${archived ? "Aucune archive." : "Aucun projet. Crée ou importe un document."}</p>`;
    return;
  }
  for (const doc of list) {
    const carte = document.createElement("div");
    carte.className = "projet-carte";
    const info = document.createElement("div");
    info.className = "projet-carte-info";
    const nom = document.createElement("div");
    nom.className = "projet-carte-nom";
    nom.textContent = doc.fichier;
    const meta = document.createElement("div");
    meta.className = "projet-carte-meta";
    meta.textContent = `${fmtTaille(doc.taille)} · ${doc.modifie_iso || ""}${doc.map ? " · .map" : ""}${doc.brouillon ? " · brouillon" : ""}`;
    info.append(nom, meta);
    const acts = document.createElement("div");
    acts.className = "projet-carte-actions";
    if (!archived) {
      const bOuvrir = document.createElement("button");
      bOuvrir.textContent = "Ouvrir";
      bOuvrir.onclick = async () => {
        // reproduit le flux Ouvrir de la barre-doc
        const r = await fetch("/api/document/ouvrir", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fichier: doc.fichier }) });
        if (!r.ok) { notifier("Ouverture échouée.", "err"); return; }
        const d = await r.json();
        docCourant = { fichier: d.fichier, brouillon: d.brouillon };
        cm.setValue(d.contenu ?? "");
        await chargerPersonnagesDoc(d.fichier);
        $("doc-statut").textContent = `brouillon : ${d.brouillon}`;
        await chargerDocuments();
        selectDoc(d.fichier);
        mountVue("edit");
        notifier(`« ${d.fichier} » ouvert.`, "ok");
      };
      const bRenommer = document.createElement("button");
      bRenommer.textContent = "Renommer";
      bRenommer.onclick = async () => {
        const nouveau = await demanderNom("Renommer le document", doc.fichier);
        if (!nouveau || nouveau === doc.fichier) return;
        const r = await fetch("/api/document/renommer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fichier: doc.fichier, nouveau }) });
        if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
        notifier("Document renommé.", "ok");
        await chargerDocuments();
        await chargerDetailsProjets();
      };
      const bDupliquer = document.createElement("button");
      bDupliquer.textContent = "Dupliquer";
      bDupliquer.onclick = async () => {
        const r = await fetch("/api/document/dupliquer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fichier: doc.fichier }) });
        if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
        const d = await r.json();
        notifier(`Copie créée : ${d.copie}`, "ok");
        await chargerDocuments();
        await chargerDetailsProjets();
      };
      const bArchiver = document.createElement("button");
      bArchiver.textContent = "Archiver";
      bArchiver.onclick = async () => {
        const ok = await demanderConfirmation("Archiver", `Archiver « ${doc.fichier} » ? Il sera déplacé dans texte/archives/ et retiré de la liste active.`);
        if (!ok) return;
        const r = await fetch("/api/document/archiver", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fichier: doc.fichier }) });
        if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
        notifier("Document archivé.", "ok");
        await chargerDocuments();
        await chargerDetailsProjets();
      };
      const bSuppr = document.createElement("button");
      bSuppr.textContent = "Supprimer";
      bSuppr.className = "danger";
      bSuppr.onclick = async () => {
        const ok = await demanderConfirmation("Supprimer", `Supprimer définitivement « ${doc.fichier} » ? Cette action est irréversible (fichier + .map + brouillon seront effacés).`);
        if (!ok) return;
        const r = await fetch("/api/document/supprimer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fichier: doc.fichier }) });
        if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
        if (docCourant && docCourant.fichier === doc.fichier) { docCourant = null; cm.setValue(""); $("doc-statut").textContent = ""; }
        notifier("Document supprimé.", "ok");
        await chargerDocuments();
        await chargerDetailsProjets();
      };
      acts.append(bOuvrir, bRenommer, bDupliquer, bArchiver, bSuppr);
    } else {
      const bRestaurer = document.createElement("button");
      bRestaurer.textContent = "Restaurer";
      bRestaurer.onclick = async () => {
        const r = await fetch("/api/document/desarchiver", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fichier: doc.fichier }) });
        if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
        notifier("Document restauré.", "ok");
        await chargerDocuments();
        await chargerDetailsProjets();
      };
      const bSuppr = document.createElement("button");
      bSuppr.textContent = "Supprimer";
      bSuppr.className = "danger";
      bSuppr.onclick = async () => {
        const ok = await demanderConfirmation("Supprimer l'archive", `Supprimer l'archive « ${doc.fichier} » ?`);
        if (!ok) return;
        // suppression directe dans archives via fetch DELETE-like (on utilise archiver path)
        // on supprime le fichier archive manuellement côté serveur : on le restaure puis supprime, plus simple : delete via API supprimer sur archive path non supporté, on fait un fetch custom
        // fallback : on supprime via un appel direct au fichier archive côté serveur (on tente supprimer via un endpoint archive)
        // Pour l'instant, on informe que la suppression d'archive se fait après restauration
        notifier("Restaure d'abord l'archive puis supprime-la depuis les projets actifs.", "err");
      };
      acts.append(bRestaurer, bSuppr);
    }
    carte.append(info, acts);
    container.appendChild(carte);
  }
}

// import document (barre + onglet projets)
async function importerDocument(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/document/importer", { method: "POST", body: fd });
  if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
  const d = await r.json();
  notifier(`Document importé : ${d.fichier}`, "ok");
  await chargerDocuments();
  await chargerDetailsProjets();
  selectDoc(d.fichier);
}

$("btn-import-doc").addEventListener("click", () => $("file-import-doc").click());
$("file-import-doc").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) importerDocument(f); e.target.value = ""; });
$("btn-projets-import").addEventListener("click", () => $("file-projets-import").click());
$("file-projets-import").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) importerDocument(f); e.target.value = ""; });
$("btn-projets-nouveau").addEventListener("click", () => $("btn-nouveau").click());
$("btn-projets-rafraichir").addEventListener("click", chargerDetailsProjets);

// ---------------------------------------------------------------- voix : liste + import / suppression
async function chargerVoixListe() {
  try {
    const r = await fetch("/api/voix");
    if (!r.ok) { $("voix-liste").innerHTML = '<p class="liste-vide">Aucune voix (vérifie le dossier des voix).</p>'; return; }
    const voix = await r.json();
    renderVoix(voix);
  } catch { $("voix-liste").innerHTML = '<p class="liste-vide">Erreur chargement voix.</p>'; }
}
function renderVoix(list) {
  const box = $("voix-liste");
  box.innerHTML = "";
  if (!list.length) { box.innerHTML = '<p class="liste-vide">Aucune voix. Importe un couple .wav + .txt.</p>'; return; }
  for (const v of list) {
    const carte = document.createElement("div");
    carte.className = "voix-carte";
    carte.dataset.nom = v.nom;
    const info = document.createElement("div");
    const nom = document.createElement("div");
    nom.className = "voix-carte-nom";
    nom.textContent = v.nom;
    const meta = document.createElement("div");
    meta.className = "voix-carte-meta";
    meta.textContent = `${v.wav.split("/").pop()} · ${v.txt.split("/").pop()}`;
    info.append(nom, meta);
    const acts = document.createElement("div");
    acts.className = "projet-carte-actions";
    const bPlay = document.createElement("button");
    bPlay.textContent = "▶ Écouter";
    bPlay.onclick = () => {
      const a = new Audio(`/api/voix/wav?nom=${encodeURIComponent(v.nom)}`);
      a.play().catch(() => notifier("Lecture impossible.", "err"));
    };
    const bClean = document.createElement("button");
    bClean.textContent = "🧹 Nettoyer";
    bClean.title = "Retirer musique/bruit de fond (Demucs + DeepFilterNet)";
    bClean.onclick = () => nettoyerVoix(v.nom, bClean);
    const bDel = document.createElement("button");
    bDel.textContent = "Supprimer";
    bDel.className = "danger";
    bDel.onclick = async () => {
      const ok = await demanderConfirmation("Supprimer la voix", `Supprimer la voix « ${v.nom} » ? Le .wav/.txt et l'entrée dans voix.txt seront effacés.`);
      if (!ok) return;
      const r = await fetch("/api/voix/supprimer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nom: v.nom }) });
      if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
      notifier("Voix supprimée.", "ok");
      await chargerVoix();
      await chargerVoixListe();
      await chargerEtat();
    };
    acts.append(bPlay, bClean, bDel);
    carte.append(info, acts);
    box.appendChild(carte);
  }
}
$("btn-voix-rafraichir").addEventListener("click", async () => { await chargerVoix(); await chargerVoixListe(); });

// import voix : modal + fichiers
const modalVoixImport = $("modal-voix-import");
let _voixWavFile = null;
let _voixTxtFile = null;
$("btn-voix-import").addEventListener("click", () => { _voixWavFile = null; _voixTxtFile = null; $("voix-import-nom").value = ""; $("voix-import-txt").value = ""; $("voix-import-wav-name").value = ""; ouvrirModal(modalVoixImport); });
$("btn-voix-import-annuler").addEventListener("click", () => fermerModal(modalVoixImport));
$("btn-voix-choisir-wav").addEventListener("click", () => $("file-voix-wav").click());
$("file-voix-wav").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  _voixWavFile = f;
  $("voix-import-wav-name").value = f.name;
  if (!$("voix-import-nom").value) $("voix-import-nom").value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  e.target.value = "";
});
$("btn-voix-choisir-txt").addEventListener("click", () => $("file-voix-txt").click());
$("file-voix-txt").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  _voixTxtFile = f;
  const reader = new FileReader();
  reader.onload = () => { $("voix-import-txt").value = reader.result; };
  reader.readAsText(f);
  e.target.value = "";
});
$("btn-voix-import-ok").addEventListener("click", async () => {
  if (!_voixWavFile) { notifier("Choisis un fichier .wav.", "err"); return; }
  const transcription = $("voix-import-txt").value.trim();
  if (!_voixTxtFile && !transcription) { notifier("Fournis une transcription (.txt ou saisie).", "err"); return; }
  const fd = new FormData();
  fd.append("wav", _voixWavFile);
  if (_voixTxtFile) fd.append("txt", _voixTxtFile);
  if (transcription) fd.append("transcription", transcription);
  const nom = $("voix-import-nom").value.trim();
  if (nom) fd.append("nom", nom);
  $("btn-voix-import-ok").disabled = true;
  try {
    const r = await fetch("/api/voix/importer", { method: "POST", body: fd });
    if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
    const d = await r.json();
    notifier(`Voix « ${d.nom} » importée.`, "ok");
    fermerModal(modalVoixImport);
    await chargerVoix();
    await chargerVoixListe();
    await chargerEtat();
  } catch { notifier("Import voix échoué.", "err"); }
  finally { $("btn-voix-import-ok").disabled = false; }
});
modalVoixImport.addEventListener("click", (e) => { if (e.target === modalVoixImport) fermerModal(modalVoixImport); });

// ---------------------------------------------------------------- nettoyage des voix (Demucs + DeepFilterNet)
const modalClean = $("modal-nettoyage");
let cleanJobNom = null;      // nom de la voix en cours de nettoyage
let cleanJobId = null;       // id du job terminé (lecture A/B)

function voixCarte(nom) {
  return document.querySelector(`#voix-liste .voix-carte[data-nom="${CSS.escape(nom)}"]`);
}

// Lance le nettoyage d'une voix et suit la progression (SSE).
async function nettoyerVoix(nom, btn) {
  if (!btn) btn = voixCarte(nom)?.querySelector("button:not(.danger)");
  btn.disabled = true;
  btn.textContent = "🧹 Nettoyage…";
  try {
    const r = await fetch("/api/voix/nettoyer", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nom, mode: "auto" }),
    });
    if (!r.ok) {
      let m = "Nettoyage impossible.";
      try { m = (await r.json()).detail || m; } catch { /* non JSON */ }
      throw new Error(m);
    }
    const { id } = await r.json();

    const ev = new EventSource(`/api/voix/nettoyer/${id}/stream`);
    const fin = () => {
      ev.close();
      btn.disabled = false;
      btn.textContent = "🧹 Nettoyer";
    };
    ev.addEventListener("prog", (e) => {
      const d = JSON.parse(e.data);
      btn.textContent = d.etape ? `🧹 ${d.etape}` : "🧹 Nettoyage…";
    });
    ev.addEventListener("result", () => {
      cleanJobNom = nom;
      cleanJobId = id;
      ouvrirModal(modalClean);
      modalClean.querySelector(".clean-nom").textContent = nom;
      modalClean.querySelector("audio.clean-original").src =
        `/api/voix/wav?nom=${encodeURIComponent(nom)}&v=${Date.now()}`;
      const a = modalClean.querySelector("audio.clean-result");
      a.src = `/api/voix/nettoyer/${id}/wav?v=${Date.now()}`;
      $("nettoyer-nouveau-nom").value = nom + "_clean";
    });
    ev.addEventListener("error", (e) => {
      if (e.data) {
        const m = JSON.parse(e.data).error;
        notifier(m, "err");
        afficherErreur(m);
      }
    });
    ev.addEventListener("end", fin);
  } catch (e) {
    notifier(e.message, "err");
    afficherErreur(e.message);
    btn.disabled = false;
    btn.textContent = "🧹 Nettoyer";
  }
}

$("btn-nettoyer-annuler").addEventListener("click", () => {
  fermerModal(modalClean);
  const a = modalClean.querySelector("audio.clean-result");
  a.removeAttribute("src");
  cleanJobId = null;
});

// Écraser l'original par le résultat nettoyé.
$("btn-nettoyer-ecraser").addEventListener("click", async () => {
  if (cleanJobId == null) return;
  const ok = await demanderConfirmation("Écraser la voix",
    `Remplacer le .wav d'origine de « ${cleanJobNom} » par la version nettoyée ? L'original sera perdu.`);
  if (!ok) return;
  const btn = $("btn-nettoyer-ecraser");
  btn.disabled = true;
  try {
    const r = await fetch(`/api/voix/nettoyer/${cleanJobId}/ecraser`, { method: "POST" });
    if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
    notifier(`Voix « ${cleanJobNom} » remplacée par sa version nettoyée.`, "ok");
    fermerModal(modalClean);
    await chargerVoix();
    await chargerVoixListe();
    await chargerEtat();
  } finally { btn.disabled = false; }
});

// Enregistrer comme nouvelle voix « <nom>_<suffixe> ».
$("btn-nettoyer-sauver").addEventListener("click", async () => {
  if (cleanJobId == null) return;
  const nom = $("nettoyer-nouveau-nom").value.trim();
  if (!nom) { notifier("Indique un nom pour la nouvelle voix.", "err"); return; }
  const btn = $("btn-nettoyer-sauver");
  btn.disabled = true;
  try {
    const r = await fetch(`/api/voix/nettoyer/${cleanJobId}/sauver_clean`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nom }),
    });
    if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
    const d = await r.json();
    notifier(`Nouvelle voix « ${d.nom} » enregistrée.`, "ok");
    fermerModal(modalClean);
    await chargerVoix();
    await chargerVoixListe();
    await chargerEtat();
  } finally { btn.disabled = false; }
});
modalClean.addEventListener("click", (e) => { if (e.target === modalClean) { fermerModal(modalClean); } });

// ---------------------------------------------------------------- init
(async function init() {
  initEditeur();
  majMontage();
  majBoutonsPerso();
  await chargerDocuments();
  await chargerEtat();
  await chargerVoix();
  await chargerModele();
})();
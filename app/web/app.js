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
  $("tab-edit").classList.toggle("actif", nom === "edit");
  $("tab-montage").classList.toggle("actif", nom === "montage");
  if (nom === "edit" && cm) cm.refresh();
  if (nom === "montage" && montageId) chargerBlocs();
}
$("tab-edit").addEventListener("click", () => mountVue("edit"));
$("tab-montage").addEventListener("click", () => mountVue("montage"));

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

[modalReglages, modalAide, modalPerso, modalNom, modalErreur].forEach((m) =>
  m.addEventListener("click", (e) => { if (e.target === m) fermerModal(m); }));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!modalNom.hidden) { annulerNom(); return; }
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
    $("montage-info").textContent = `Durée totale : ${d.duree} s · ${montageBlocs.length} bloc(s)`;
    remplirSelBlocs();
    majPanelBloc();
  } catch { notifier("Erreur au chargement des blocs.", "err"); }
}

function remplirSelBlocs() {
  const sel = $("sel-bloc");
  const courant = sel.value;
  sel.innerHTML = "";
  montageBlocs.forEach((b, i) => {
    const o = document.createElement("option");
    o.value = b.id;
    o.textContent = `${i + 1}. ${b.personnage} — ${b.duree} s (${b.chars} chars)`;
    sel.appendChild(o);
  });
  if ([...sel.options].find((o) => o.value === courant)) sel.value = courant;
  else sel.selectedIndex = 0;
}

function blocCourant() {
  const id = parseInt($("sel-bloc").value, 10);
  return montageBlocs.find((b) => b.id === id) || null;
}

function majPanelBloc() {
  const b = blocCourant();
  if (!b) {
    $("bloc-panel").hidden = true;
    return;
  }
  $("bloc-panel").hidden = false;
  $("bloc-audio").src = `/api/generer/${montageId}/bloc/${b.id}/wav`;
  const extra = b.texte ? `\n« ${b.texte.slice(0, 90)}${b.texte.length > 90 ? "…" : ""} »` : "";
  $("bloc-detail").textContent =
    `Personnage : ${b.personnage} · voix : ${b.voix} · ${b.duree} s${extra}`;
}

$("sel-bloc").addEventListener("change", majPanelBloc);

async function actionBloc(url, msg) {
  const b = blocCourant();
  if (!b) return;
  $("btn-bloc-regenerer").disabled = true;
  $("btn-bloc-diviser").disabled = true;
  try {
    const r = await fetch(url, { method: "POST" });
    if (!r.ok) { notifier((await r.json()).detail, "err"); return; }
    await chargerBlocs();
    if (msg) notifier(msg, "ok");
  } catch { notifier("Action bloc échouée.", "err"); }
  finally {
    $("btn-bloc-regenerer").disabled = false;
    $("btn-bloc-diviser").disabled = false;
  }
}

$("btn-bloc-regenerer").addEventListener("click", () =>
  actionBloc(`/api/generer/${montageId}/bloc/${blockId()}/regenerer`, "Bloc régénéré."));
$("btn-bloc-diviser").addEventListener("click", () =>
  actionBloc(`/api/generer/${montageId}/bloc/${blockId()}/diviser`, "Bloc divisé en deux."));

function blockId() {
  const b = blocCourant();
  return b ? b.id : "";
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

// ---------------------------------------------------------------- état (dossier des voix)
async function chargerEtat() {
  const etat = await (await fetch("/api/etat")).json();
  $("audio-dir").value = etat.audio_dir;
  if (!etat.voix_file && etat.erreur) {
    afficherBanniere(etat.erreur, true);
  } else if (!etat.voix_file) {
    afficherBanniere("Aucun fichier de voix : configure le dossier des voix.", true);
  } else {
    masquerBanniere();
  }
}

// ---------------------------------------------------------------- bannière
function afficherBanniere(msg, avecLien) {
  $("banniere-msg").textContent = msg;
  $("banniere-lien").hidden = !avecLien;
  $("banniere").hidden = false;
}
function masquerBanniere() { $("banniere").hidden = true; }
$("banniere-lien").addEventListener("click", (e) => {
  e.preventDefault();
  ouvrirModal(modalReglages);
});

// ---------------------------------------------------------------- init
(async function init() {
  initEditeur();
  majMontage();
  majBoutonsPerso();
  await chargerDocuments();
  await chargerEtat();
  await chargerVoix();
})();
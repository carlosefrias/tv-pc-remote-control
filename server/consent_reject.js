// Finds the button of a cookie / consent notice that REFUSES cookies (never one
// that accepts) in this document, including open shadow roots (Usercentrics...).
// Returns {el, label} for the server to click, or null. Run via Marionette; the
// server also runs it inside consent iframes (Sourcepoint...). See fullscreen.py.

// Refusing labels, best first (PT / EN / DE / FR).
var REFUSE = [
  /^(alle\s+)?ablehnen$/i, /^(reject|decline|refuse|deny)(\s+all)?$/i, /^(rejeitar|recusar)(\s+tudo)?$/i,
  /^(tout\s+)?refuser(\s+tout)?$/i, /^disagree$/i, /^nicht\s+zustimmen$/i, /^zustimmung\s+verweigern$/i,
  /continuar\s+sem\s+aceitar/i, /continue\s+without\s+(accepting|agreeing)/i, /continuer\s+sans\s+accepter/i,
  /(weiter|fortfahren)\s+ohne\s+(einwilligung|zustimmung|auswahl)/i, /ohne\s+(einwilligung|zustimmung|auswahl)\s+(weiter|fortfahren)/i,
  /^n[aã]o\s+aceitar$/i, /^do\s+not\s+accept$/i
];
// "Only necessary cookies" refuses the optional ones, even when the label also
// says "accept" ("Nur notwendige akzeptieren", "Accept only essential").
var NECESSARY_ONLY = /(nur|only|apenas|s[oó])\s+(die\s+|os\s+)?(notwendig|erforderlich|essenziell|necess|essential|essenc)|(necessary|essential)\s+(cookies\s+)?only/i;
// Anything that looks like accepting / settings is never clicked.
var ACCEPTS = /accept|akzeptier|aceit|zustimm|einverstanden|agree|allow|erlaub|permitir|concordo|got it|verstanden|ok\b/i;
var NEGATED = /without|sem\s|ohne|n[aã]o\s|nicht|do not|disagree|verweigern|sans/i;
var SETTINGS = /einstellung|setting|option|configur|personali|anpassen|details|preferen|defini[cç]|op[cç][oõ]es|gerir|manage|mehr|more|learn|saiba/i;

function label(el) {
  return ((el.innerText || el.textContent || el.value || '') + '').replace(/\s+/g, ' ').trim() ||
         (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
}
function visible(el) {
  var r = el.getBoundingClientRect(), s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity !== 0;
}
function roots(root, out) {  // document + every open shadow root inside it
  out.push(root);
  Array.prototype.forEach.call(root.querySelectorAll('*'), function (el) { if (el.shadowRoot) roots(el.shadowRoot, out); });
  return out;
}

var best = null;
roots(document, []).forEach(function (root) {
  Array.prototype.forEach.call(root.querySelectorAll(
    'button,a,[role=button],input[type=button],input[type=submit],[class*="btn" i],[class*="button" i]'), function (el) {
    var text = label(el);
    if (!text || text.length > 60 || !visible(el) || SETTINGS.test(text)) return;
    var rank = -1;
    if (NECESSARY_ONLY.test(text)) rank = REFUSE.length;          // after explicit "reject"
    else if (ACCEPTS.test(text) && !NEGATED.test(text)) return;   // accepting: never
    else for (var i = 0; i < REFUSE.length; i++) if (REFUSE[i].test(text)) { rank = i; break; }
    if (rank >= 0 && (!best || rank < best.rank)) best = { el: el, label: text, rank: rank };
  });
});
return best ? { el: best.el, label: best.label } : null;

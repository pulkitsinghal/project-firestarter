/**
 * <version-changelog> — the build stamp in the corner, made useful.
 *
 * Every project ends up printing a version somewhere. This turns that dead text
 * into the answer to three questions a reader actually has: what am I looking at,
 * what changed, and can I go back to the one that worked.
 *
 * Design constraints, learned the hard way:
 *   - No dependencies and no build step. It has to run inside a Claude artifact
 *     (strict CSP, no external hosts), a static page on Cloudflare Pages, and an
 *     app shell, without changing shape.
 *   - Shadow DOM. Host stylesheets vary wildly across projects; the panel must not
 *     inherit them, and must not leak into them.
 *   - It never performs a rollback itself. It navigates, or it emits an event and
 *     lets the host decide. A component that can silently revert someone's data is
 *     a component that will eventually revert someone's data.
 *
 * Usage:
 *   <version-changelog src="changelog.json"></version-changelog>
 *   <version-changelog>{ ...inline manifest... }</version-changelog>
 *
 * Manifest shape: see common/docs/VERSION_CHANGELOG.md and changelog.schema.json.
 */

const TEMPLATE = document.createElement("template");
TEMPLATE.innerHTML = `
<style>
  :host {
    --vc-ink: var(--changelog-ink, #1a1f1e);
    --vc-ink-2: var(--changelog-ink-2, #5d6b68);
    --vc-ink-3: var(--changelog-ink-3, #8a9693);
    --vc-surface: var(--changelog-surface, #ffffff);
    --vc-rule: var(--changelog-rule, #dde4e2);
    --vc-accent: var(--changelog-accent, #0d6a62);
    --vc-disabled: var(--changelog-disabled, #a5adab);
    --vc-mono: var(--changelog-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    --vc-sans: var(--changelog-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
    display: inline-block;
    position: relative;
    font-family: var(--vc-sans);
  }
  @media (prefers-color-scheme: dark) {
    :host(:not([theme="light"])) {
      --vc-ink: var(--changelog-ink, #e6edeb);
      --vc-ink-2: var(--changelog-ink-2, #a3b0ad);
      --vc-ink-3: var(--changelog-ink-3, #7d8a87);
      --vc-surface: var(--changelog-surface, #161d1c);
      --vc-rule: var(--changelog-rule, #2a3533);
      --vc-accent: var(--changelog-accent, #57c2b2);
      --vc-disabled: var(--changelog-disabled, #55605e);
    }
  }
  :host([theme="dark"]) {
    --vc-ink: #e6edeb; --vc-ink-2: #a3b0ad; --vc-ink-3: #7d8a87;
    --vc-surface: #161d1c; --vc-rule: #2a3533; --vc-accent: #57c2b2;
    --vc-disabled: #55605e;
  }

  .stamp {
    font-family: var(--vc-mono);
    font-size: .72rem;
    letter-spacing: .06em;
    color: var(--vc-ink-3);
    background: none;
    border: 0;
    border-bottom: 1px dotted currentColor;
    padding: 0 0 1px;
    cursor: pointer;
    line-height: 1.4;
  }
  .stamp:hover, .stamp:focus-visible { color: var(--vc-accent); }
  .stamp:focus-visible { outline: 2px solid var(--vc-accent); outline-offset: 3px; }

  .panel {
    position: absolute;
    bottom: calc(100% + .5rem);
    left: 0;
    z-index: 40;
    width: min(26rem, calc(100vw - 2rem));
    max-height: min(24rem, 70vh);
    overflow-y: auto;
    overscroll-behavior: contain;
    background: var(--vc-surface);
    border: 1px solid var(--vc-rule);
    border-radius: 6px;
    box-shadow: 0 10px 30px rgba(0,0,0,.18);
    padding: .25rem 0;
  }
  :host([drop="down"]) .panel { bottom: auto; top: calc(100% + .5rem); }

  /* Placement. inline (default) sits wherever the host puts it; the rest pin
     themselves so a page can carry the stamp without reserving layout for it. */
  :host([placement="float"]),
  :host([placement="header"]),
  :host([placement="footer"]),
  :host([placement="side"]) { position: fixed; z-index: 60; }

  :host([placement="float"]) { bottom: 1.25rem; right: 1.25rem; }
  :host([placement="float"][corner="bottom-left"])  { right: auto; left: 1.25rem; }
  :host([placement="float"][corner="top-right"])    { bottom: auto; top: 1.25rem; }
  :host([placement="float"][corner="top-left"])     { bottom: auto; top: 1.25rem; right: auto; left: 1.25rem; }
  :host([placement="float"]) .stamp {
    background: var(--vc-surface);
    border: 1px solid var(--vc-rule);
    border-bottom-color: var(--vc-rule);
    border-radius: 999px;
    padding: .45rem .85rem;
    box-shadow: 0 4px 14px rgba(0,0,0,.16);
    color: var(--vc-ink-2);
  }
  :host([placement="float"]) .stamp:hover { color: var(--vc-accent); border-color: var(--vc-accent); }

  :host([placement="header"]) { top: .6rem; right: 1rem; }
  :host([placement="footer"]) { bottom: .6rem; right: 1rem; }
  :host([placement="side"])   { top: 50%; right: 0; transform: translateY(-50%); }
  :host([placement="side"]) .stamp {
    writing-mode: vertical-rl;
    background: var(--vc-surface);
    border: 1px solid var(--vc-rule);
    border-radius: 6px 0 0 6px;
    padding: .8rem .4rem;
  }

  /* A pinned stamp near the bottom must open upward, near the top downward. */
  :host([placement="header"]) .panel { bottom: auto; top: calc(100% + .5rem); }
  :host([placement="float"][corner^="top"]) .panel { bottom: auto; top: calc(100% + .5rem); }
  /* Right-pinned placements would overflow the viewport if the panel grew rightward. */
  :host([placement="float"]) .panel,
  :host([placement="header"]) .panel,
  :host([placement="footer"]) .panel { left: auto; right: 0; }
  :host([placement="side"]) .panel { right: calc(100% + .5rem); top: 50%; bottom: auto; transform: translateY(-50%); }

  @media (prefers-reduced-motion: reduce) { .stamp, .ch, .rel-top { transition: none; } }
  .panel[hidden] { display: none; }

  .head {
    display: flex; justify-content: space-between; align-items: baseline; gap: 1rem;
    padding: .6rem .85rem; border-bottom: 1px solid var(--vc-rule);
  }
  .head b { font-size: .8rem; color: var(--vc-ink); font-weight: 600; }
  .head span { font-family: var(--vc-mono); font-size: .66rem; color: var(--vc-ink-3); }

  .rel { border-bottom: 1px solid var(--vc-rule); }
  .rel:last-child { border-bottom: 0; }
  .rel-top {
    width: 100%; display: grid; grid-template-columns: 1fr auto; gap: .5rem;
    align-items: baseline; padding: .55rem .85rem; background: none; border: 0;
    text-align: left; cursor: pointer; color: var(--vc-ink); font-family: inherit;
  }
  .rel-top:hover { background: color-mix(in srgb, var(--vc-accent) 7%, transparent); }
  .rel-top:focus-visible { outline: 2px solid var(--vc-accent); outline-offset: -2px; }
  .rel-title { font-size: .82rem; font-weight: 500; }
  .rel-meta { font-family: var(--vc-mono); font-size: .66rem; color: var(--vc-ink-3); white-space: nowrap; }
  .current .rel-title::after {
    content: "current"; margin-left: .45rem; font-family: var(--vc-mono);
    font-size: .6rem; letter-spacing: .08em; text-transform: uppercase;
    color: var(--vc-accent); border: 1px solid currentColor; border-radius: 2px; padding: 0 .25rem;
  }
  .body { padding: 0 .85rem .7rem; }
  .body[hidden] { display: none; }
  .body ul { margin: 0 0 .55rem; padding-left: 1.05rem; }
  .body li { font-size: .78rem; line-height: 1.5; color: var(--vc-ink-2); margin: .15rem 0; }

  .roll {
    font-family: var(--vc-mono); font-size: .68rem; letter-spacing: .04em;
    padding: .3rem .6rem; border-radius: 3px; cursor: pointer;
    border: 1px solid var(--vc-accent); color: var(--vc-accent); background: none;
  }
  .roll:hover { background: color-mix(in srgb, var(--vc-accent) 12%, transparent); }
  .roll:focus-visible { outline: 2px solid var(--vc-accent); outline-offset: 2px; }
  .roll[disabled] {
    border-color: var(--vc-disabled); color: var(--vc-disabled);
    cursor: not-allowed; background: none;
  }
  .why { font-size: .7rem; color: var(--vc-ink-3); margin-top: .35rem; line-height: 1.45; }
  .err { padding: .7rem .85rem; font-size: .78rem; color: var(--vc-ink-2); }
</style>

<button class="stamp" part="stamp" aria-haspopup="dialog" aria-expanded="false"></button>
<div class="panel" part="panel" role="dialog" aria-label="Version history" hidden></div>
`;

class VersionChangelog extends HTMLElement {
  static get observedAttributes() { return ["src", "current", "placement", "corner"]; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" }).appendChild(TEMPLATE.content.cloneNode(true));
    this._stamp = this.shadowRoot.querySelector(".stamp");
    this._panel = this.shadowRoot.querySelector(".panel");
    this._open = false;
    this._data = null;
    this._onDocClick = (e) => { if (!this.contains(e.target) && e.target !== this) this.close(); };
    this._onKey = (e) => { if (e.key === "Escape" && this._open) { this.close(); this._stamp.focus(); } };
  }

  connectedCallback() {
    this._stamp.addEventListener("click", () => this.toggle());
    this._load();
  }

  disconnectedCallback() {
    document.removeEventListener("click", this._onDocClick, true);
    document.removeEventListener("keydown", this._onKey);
  }

  attributeChangedCallback(name, prev, next) {
    if (prev !== next && this.isConnected) this._load();
  }

  async _load() {
    const src = this.getAttribute("src");
    try {
      if (src) {
        const res = await fetch(src, { cache: "no-cache" });
        if (!res.ok) throw new Error(`${res.status} fetching ${src}`);
        this._data = await res.json();
      } else {
        const inline = this.textContent.trim();
        if (!inline) throw new Error("no src attribute and no inline manifest");
        this._data = JSON.parse(inline);
      }
      this._render();
    } catch (err) {
      this._data = null;
      this._stamp.textContent = "version unavailable";
      this._panel.innerHTML = `<p class="err">Could not load the version history: ${escapeHtml(err.message)}</p>`;
    }
  }

  get _current() {
    const pinned = this.getAttribute("current");
    const releases = (this._data && this._data.releases) || [];
    return releases.find((r) => r.id === pinned) || releases[0] || null;
  }

  _render() {
    const cur = this._current;
    const releases = (this._data && this._data.releases) || [];
    if (!cur) {
      this._stamp.textContent = "no versions";
      return;
    }
    const floating = this.getAttribute("placement") === "float";
    const short = this._data.floatLabel || "What's new";
    this._stamp.textContent = floating
      ? short
      : (this._data.stampLabel
          ? interpolate(this._data.stampLabel, cur)
          : `build ${cur.id}${cur.runtime ? " · " + cur.runtime : ""}`);
    this._stamp.title = "What changed, and how to go back";

    const head = `<div class="head"><b>${escapeHtml(this._data.title || "Version history")}</b>` +
      `<span>${releases.length} release${releases.length === 1 ? "" : "s"}</span></div>`;

    this._panel.innerHTML = head + releases.map((r, i) => {
      const isCur = r.id === cur.id;
      const bodyId = `vc-body-${i}`;
      const notes = (r.highlights || []).map((h) => `<li>${escapeHtml(h)}</li>`).join("");
      const roll = this._rollbackMarkup(r, isCur);
      return `
        <div class="rel ${isCur ? "current" : ""}">
          <button class="rel-top" aria-expanded="${isCur}" aria-controls="${bodyId}">
            <span class="rel-title">${escapeHtml(r.title || r.id)}</span>
            <span class="rel-meta">${escapeHtml(r.date || "")} ${escapeHtml(r.id)}</span>
          </button>
          <div class="body" id="${bodyId}" ${isCur ? "" : "hidden"}>
            ${notes ? `<ul>${notes}</ul>` : ""}
            ${roll}
          </div>
        </div>`;
    }).join("");

    this._panel.querySelectorAll(".rel-top").forEach((btn) => {
      btn.addEventListener("click", () => {
        const body = this.shadowRoot.getElementById(btn.getAttribute("aria-controls"));
        const nowHidden = !body.hasAttribute("hidden");
        body.toggleAttribute("hidden", nowHidden);
        btn.setAttribute("aria-expanded", String(!nowHidden));
      });
    });
    this._panel.querySelectorAll(".roll:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => this._rollback(btn.dataset.id));
    });
  }

  _rollbackMarkup(release, isCurrent) {
    if (isCurrent) return `<p class="why">You are viewing this version.</p>`;
    const rb = release.rollback || {};
    if (rb.available) {
      return `<button class="roll" data-id="${escapeHtml(release.id)}">Open this version</button>`;
    }
    const why = rb.reason || "This version cannot be restored from here.";
    return `<button class="roll" disabled title="${escapeHtml(why)}">Open this version</button>` +
           `<p class="why">${escapeHtml(why)}</p>`;
  }

  /**
   * Navigate, or hand off. Never mutate. A host that wants to do something
   * cleverer (restore a snapshot, warn about unsaved work) listens for the event
   * and calls preventDefault().
   */
  _rollback(id) {
    const release = (this._data.releases || []).find((r) => r.id === id);
    if (!release) return;
    const evt = new CustomEvent("changelog:rollback", {
      detail: { release }, bubbles: true, composed: true, cancelable: true,
    });
    const proceed = this.dispatchEvent(evt);
    if (proceed && release.rollback && release.rollback.url) {
      window.open(release.rollback.url, this.getAttribute("target") || "_self");
    }
  }

  toggle() { this._open ? this.close() : this.open(); }

  open() {
    this._open = true;
    this._panel.hidden = false;
    this._stamp.setAttribute("aria-expanded", "true");
    // capture phase: a host that stops propagation on its own clicks should not
    // trap the panel open forever
    document.addEventListener("click", this._onDocClick, true);
    document.addEventListener("keydown", this._onKey);
  }

  close() {
    this._open = false;
    this._panel.hidden = true;
    this._stamp.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", this._onDocClick, true);
    document.removeEventListener("keydown", this._onKey);
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function interpolate(tpl, release) {
  return String(tpl).replace(/\{(\w+)\}/g, (_, k) => escapeHtml(release[k] ?? ""));
}

if (!customElements.get("version-changelog")) {
  customElements.define("version-changelog", VersionChangelog);
}

export { VersionChangelog };

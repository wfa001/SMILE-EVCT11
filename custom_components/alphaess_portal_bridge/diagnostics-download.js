const cardName = "alphaess-diagnostics-download";

// Wait for HA's custom element registry before registering a global extra module.
customElements.whenDefined("home-assistant").then(() => {
  if (customElements.get(cardName)) return;

  customElements.define(cardName, class extends HTMLElement {
    constructor() {
      super();
      const root = this.attachShadow({ mode: "open" });
      root.innerHTML = `
        <style>
          ha-card { padding: 12px 16px; text-align: center; }
          button { font: inherit; color: var(--primary-color); background: transparent;
                   border: 0; padding: 10px; cursor: pointer; }
          button:disabled { color: var(--disabled-text-color); cursor: default; }
          ha-icon { --mdc-icon-size: 20px; margin-right: 5px; }
          p { margin: 0; color: var(--secondary-text-color); }
          a { color: var(--primary-color); }
        </style>
        <ha-card>
          <button type="button" disabled>
            <ha-icon icon="mdi:download"></ha-icon>Diagnose als ZIP herunterladen
          </button>
          <p role="status"></p>
          <a hidden>ZIP erneut speichern</a>
        </ha-card>`;
      this.button = root.querySelector("button");
      this.status = root.querySelector("p");
      this.link = root.querySelector("a");
      this.button.addEventListener("click", () => this.download());
    }

    setConfig(config) {
      this.path = config.path;
    }

    set hass(hass) {
      this.client = hass;
      this.button.disabled = Boolean(this.busy) || !hass.user?.is_admin;
      if (!hass.user?.is_admin && !this.busy) {
        this.status.textContent = "Diagnose-Download nur für Administratoren.";
      }
    }

    getCardSize() {
      return 2;
    }

    clearLink() {
      if (this.link.hasAttribute("href")) {
        URL.revokeObjectURL(this.link.href);
        this.link.removeAttribute("href");
        this.link.hidden = true;
      }
    }

    disconnectedCallback() {
      this.clearLink();
    }

    async download() {
      if (this.busy || !this.client?.user?.is_admin) return;
      this.clearLink();
      this.busy = true;
      this.button.disabled = true;
      this.status.textContent = "Diagnose-ZIP wird erstellt …";
      try {
        const { path } = await this.client.callWS({
          type: "auth/sign_path",
          path: this.path,
        });
        const response = await fetch(path);
        if (response.status === 409) {
          this.status.textContent = "Ein Diagnose-Export läuft bereits. Bitte versuche es gleich erneut.";
          return;
        }
        if (!response.ok || response.headers.get("Content-Type") !== "application/zip") {
          throw new Error("ZIP unavailable");
        }
        this.status.textContent = "Diagnose-ZIP wird übertragen …";
        const blob = await response.blob();
        if (!this.isConnected) return;
        const disposition = response.headers.get("Content-Disposition") || "";
        this.link.download = /filename="([^"]+)"/.exec(disposition)?.[1] || "alphaess-wallbox-diagnose.zip";
        this.link.href = URL.createObjectURL(blob);
        this.link.hidden = false;
        this.link.click();
        this.status.textContent = "Diagnose-ZIP ist bereit.";
      } catch {
        this.status.textContent = "Diagnose-ZIP konnte nicht heruntergeladen werden. Bitte versuche es erneut.";
      } finally {
        this.busy = false;
        this.button.disabled = !this.client?.user?.is_admin;
      }
    }
  });
});

import { bytes, count, progress, ago, serviceURL } from "./format.mjs";

const $ = (id) => document.getElementById(id);
const names = {
  jellyfin: "Jellyfin",
  seerr: "Seerr",
  radarr: "Radarr",
  sonarr: "Sonarr",
  prowlarr: "Prowlarr",
  qbittorrent: "qBittorrent",
  gluetun: "Gluetun",
  dispatcharr: "Dispatcharr",
};
const marks = {
  jellyfin: "Jf",
  seerr: "Se",
  radarr: "Ra",
  sonarr: "So",
  prowlarr: "Pr",
  qbittorrent: "qB",
  gluetun: "Gl",
  dispatcharr: "Di",
};
const routes = {
  overview: "Overview",
  connections: "Connections",
  storage: "Storage",
  setup: "Setup",
  settings: "Panel settings",
};
const state = {
  csrf: "",
  needsSetup: false,
  authenticated: false,
  connections: [],
  overview: null,
  selected: "jellyfin",
  route: "",
  plan: null,
  busy: false,
  folder: "/data",
  folderInput: null,
  profilesLoaded: false,
  setupDefaultsApplied: false,
};
let toastTimer;

// All upstream and user-provided strings go through textContent, never HTML.
function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined)
      node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined)
      node.append(child instanceof Node ? child : String(child));
  }
  return node;
}
function icon(name, small = false) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("class", `icon${small ? " small" : ""}`);
  node.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  node.append(use);
  return node;
}
function mark(id) {
  return el(
    "span",
    { class: "app-mark", "data-app": id, "aria-hidden": "true" },
    marks[id],
  );
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 4500);
}
function message(id, text, type = "info") {
  const node = $(id);
  node.className = `message ${type}`;
  node.textContent = text;
  node.hidden = !text;
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    options.long ? 180000 : 60000,
  );
  try {
    const response = await fetch(`/api${path}`, {
      method: options.method || "GET",
      credentials: "same-origin",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": state.csrf,
      },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const result = await response.json();
    if (response.status === 401) {
      state.authenticated = false;
      await initialize();
      throw new Error("Your session ended. Sign in again.");
    }
    if (!response.ok)
      throw new Error(
        result.error || "The request could not finish. Try again.",
      );
    return result;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error(
        "The request timed out. Check the apps, then refresh status before retrying.",
      );
    if (error instanceof SyntaxError)
      throw new Error(
        "The panel returned an unexpected response. Check its container or reverse proxy and try again.",
      );
    if (error instanceof TypeError)
      throw new Error(
        "Cannot reach the control panel. Check that its container is running.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
async function busy(button, working, action) {
  const previous = button.textContent;
  button.disabled = true;
  button.textContent = working;
  try {
    return await action();
  } finally {
    button.textContent = previous;
    button.disabled = false;
  }
}
function connection(id) {
  return state.connections.find((item) => item.id === id);
}
function snapshot(id) {
  return state.overview?.services.find((item) => item.id === id);
}
function appURL(id) {
  const config = connection(id);
  return config ? serviceURL(config, location.href) : "#connections";
}
function openLink(id, label = "Open app") {
  return el(
    "a",
    {
      class: "text-link",
      href: appURL(id),
      target: "_blank",
      rel: "noopener",
      "aria-label": `${label}: ${names[id]}`,
    },
    label,
    icon("external", true),
  );
}
function statusBadge(item) {
  const status = item?.status || "unlinked";
  const label =
    {
      online: "Connected",
      unavailable: "Needs attention",
      unlinked: "Not linked",
      disabled: "Off",
    }[status] || "Unknown";
  return el("span", { class: "service-status", "data-status": status }, label);
}
function goConnection(id) {
  state.selected = id;
  if (state.route !== "connections") location.hash = "connections";
  else {
    renderConnections();
    renderEditor();
  }
}
function empty(title, description, action) {
  return el(
    "div",
    { class: "empty-state" },
    el("strong", {}, title),
    el("p", {}, description),
    action,
  );
}
function updateLastChecked() {
  if (state.overview?.checked_at) {
    $("last-checked").textContent =
      `Checked ${ago(state.overview.checked_at).toLowerCase()}`;
  }
}
function renderOverview() {
  const data = state.overview;
  if (!data) return;
  if (!state.setupDefaultsApplied) {
    $("setup-form").elements.downloads.checked = Boolean(
      data.downloads_enabled,
    );
    state.setupDefaultsApplied = true;
  }
  const linked = state.connections.filter((item) => item.configured).length;
  const online = data.services.filter(
    (item) => item.status === "online",
  ).length;
  $("connection-count").textContent = linked ? String(linked) : "";
  $("online-count").textContent = `${online} connected`;
  updateLastChecked();
  $("onboarding").hidden = linked >= 5;
  if (linked < 5) {
    $("onboarding").replaceChildren(
      el(
        "div",
        {},
        el(
          "h2",
          {},
          linked
            ? "Keep setting up your stack"
            : "Start by connecting your apps",
        ),
        el(
          "p",
          {},
          linked
            ? `${linked} of ${state.connections.length} apps linked. Downloads and VPN are optional.`
            : "Connect the installed apps, choose your folders, then review the links between them.",
        ),
      ),
      el(
        "a",
        { class: "button", href: "#connections" },
        linked ? "Manage connections" : "Connect your apps",
        icon("chevron", true),
      ),
    );
  }
  const library = snapshot("jellyfin");
  const metrics = library?.metrics || {};
  const stats = [
    ["Movies", metrics.movies, "Jellyfin library"],
    ["TV shows", metrics.series, "Jellyfin library"],
    ["Episodes", metrics.episodes, "Jellyfin library"],
    ["Playing now", metrics.streams, "Jellyfin sessions"],
  ];
  $("library-stats").replaceChildren(
    ...stats.map(([label, value, source]) =>
      el(
        "div",
        { class: "stat" },
        el("span", { class: "stat-label" }, label),
        el("strong", { class: "stat-value" }, count(value)),
        el(
          "span",
          { class: "stat-source" },
          value == null
            ? library?.status === "unlinked"
              ? "Connect Jellyfin to see"
              : "Data unavailable"
            : source,
        ),
      ),
    ),
  );
  $("service-list").replaceChildren(
    ...state.connections.map((config) => {
      const item = snapshot(config.id);
      let detail = config.role;
      if (item?.status === "online") {
        if (config.id === "prowlarr" && item.metrics.indexers != null)
          detail = `${count(item.metrics.indexers)} indexers · ${count(item.metrics.applications)} app connections`;
        if (config.id === "radarr" || config.id === "sonarr")
          detail =
            item.metrics.queue != null
              ? `${count(item.metrics.queue)} in queue`
              : config.role;
        if (config.id === "seerr" && item.metrics.pending != null)
          detail = `${count(item.metrics.pending)} requests awaiting approval`;
      }
      const row = el(
        "div",
        { class: "service-row" },
        mark(config.id),
        el(
          "div",
          { class: "service-name" },
          el("strong", {}, config.name),
          el("small", {}, detail),
        ),
        statusBadge(item),
      );
      const actions = el("div", { class: "row-action" });
      if (!config.configured || item?.status === "unavailable") {
        actions.append(
          el(
            "button",
            { class: "row-connect", onclick: () => goConnection(config.id) },
            config.configured ? "Fix" : "Connect",
          ),
        );
      }
      if (config.browser !== false) actions.append(
        el(
          "a",
          {
            class: "icon-button",
            href: appURL(config.id),
            target: "_blank",
            rel: "noopener",
            "aria-label": `Open ${config.name}`,
            title: `Open ${config.name}`,
          },
          icon("external", true),
        ),
      );
      row.append(actions);
      return row;
    }),
  );
  const qbit = snapshot("qbittorrent");
  const downloads = qbit?.downloads || [];
  if (qbit?.status === "online" && !qbit.metrics_error) {
    $("download-summary").textContent =
      `Down ${bytes(qbit.metrics.download_speed)}/s · Up ${bytes(qbit.metrics.upload_speed)}/s`;
    $("download-list").replaceChildren(
      ...(downloads.length
        ? downloads.map((item) => {
            const amount = progress(item.progress);
            const bar = el("progress", {
              max: "1",
              value: String(amount),
              "aria-label": `${item.name}: ${Math.round(amount * 100)} percent`,
            });
            const eta =
              typeof item.eta === "number" && item.eta > 0 && item.eta < 8640000
                ? `${Math.ceil(item.eta / 60)} min remaining`
                : "Estimating time";
            return el(
              "div",
              { class: "transfer" },
              el(
                "div",
                { class: "transfer-head" },
                el("strong", { title: item.name }, item.name),
                el("span", {}, `${Math.round(amount * 100)}%`),
              ),
              bar,
              el(
                "div",
                { class: "transfer-foot" },
                el("span", {}, `${bytes(item.speed)}/s`),
                el("span", {}, eta),
              ),
            );
          })
        : [
            empty(
              "No active downloads",
              "qBittorrent is connected. Active downloads appear here.",
              openLink("qbittorrent", "Open qBittorrent"),
            ),
          ]),
    );
  } else {
    $("download-summary").textContent = "Activity from qBittorrent.";
    $("download-list").replaceChildren(
      empty(
        qbit?.status === "unlinked"
          ? "Downloads are optional"
          : "Download activity unavailable",
        qbit?.metrics_error ||
          (qbit?.status === "unlinked"
            ? "Connect qBittorrent to see transfer speeds and active downloads."
            : qbit?.message || "Check the connection and try again."),
        el(
          "button",
          { class: "row-connect", onclick: () => goConnection("qbittorrent") },
          "Manage download connection",
        ),
      ),
    );
  }
  renderDisk($("storage-summary"), data.storage, true);
  $("activity-list").replaceChildren(
    ...(data.events.length
      ? data.events.slice(0, 5).map((event) =>
          el(
            "div",
            { class: "activity-item" },
            el("span", {
              class: `activity-dot ${event.kind}`,
              "aria-hidden": "true",
            }),
            el(
              "div",
              {},
              el("p", {}, event.message),
              el(
                "time",
                {
                  datetime: event.time,
                  title: new Date(event.time).toLocaleString(),
                },
                ago(event.time),
              ),
            ),
          ),
        )
      : [
          empty(
            "Nothing changed yet",
            "Connections and setup changes made here will appear in this log.",
          ),
        ]),
  );
  const health = [];
  for (const item of data.services) {
    if (item.status === "unavailable")
      health.push({ id: item.id, message: item.message });
    if (item.metrics_error)
      health.push({ id: item.id, message: item.metrics_error });
    for (const issue of item.health || [])
      health.push({ id: item.id, message: issue.message });
  }
  $("health-panel").hidden = !health.length;
  $("health-list").replaceChildren(
    ...health
      .slice(0, 10)
      .map((item) =>
        el(
          "div",
          { class: "health-item" },
          icon("alert"),
          el(
            "div",
            {},
            el("strong", {}, names[item.id]),
            el("p", {}, item.message),
          ),
        ),
      ),
  );
  $("setup-jellyfin").href = appURL("jellyfin");
  $("setup-seerr").href = appURL("seerr");
}
function diskMeter(disk) {
  return el("meter", {
    class: "disk-meter",
    min: "0",
    max: String(disk.total || 1),
    value: String(disk.used),
    low: String(disk.total * 0.8),
    high: String(disk.total * 0.95),
    optimum: "0",
    "aria-label": `${bytes(disk.used)} used out of ${bytes(disk.total)}`,
  });
}
function renderDisk(node, storage, compact = false) {
  const children = [];
  if (storage.disk) {
    const disk = storage.disk;
    children.push(
      el(
        "div",
        { class: "storage-value" },
        bytes(disk.free),
        el("small", {}, "free"),
      ),
      el(
        "p",
        { class: "storage-caption" },
        `${bytes(disk.total)} total on the data filesystem`,
      ),
      diskMeter(disk),
      el(
        "p",
        { class: "storage-caption" },
        `${bytes(disk.used)} used across this filesystem`,
      ),
    );
  } else
    children.push(
      el("p", { class: "subtle" }, storage.error || "Storage is unavailable."),
    );
  if (compact)
    children.push(
      el(
        "div",
        { class: "storage-locations" },
        ...Object.entries(storage.locations).map(([kind, item]) =>
          el(
            "div",
            {},
            el("span", {}, kind === "movies" ? "Movies" : "TV shows"),
            el("code", {}, item.path),
          ),
        ),
      ),
    );
  node.replaceChildren(...children);
}
function renderConnections() {
  $("connection-list").replaceChildren(
    ...state.connections.map((config) =>
      el(
        "button",
        {
          class: "connection-option",
          type: "button",
          "aria-pressed": String(state.selected === config.id),
          onclick: () => {
            state.selected = config.id;
            renderConnections();
            renderEditor();
          },
        },
        mark(config.id),
        el(
          "div",
          {},
          el("strong", {}, config.name),
          statusBadge(snapshot(config.id)),
        ),
        icon("chevron"),
      ),
    ),
  );
}
function renderEditor() {
  const config = connection(state.selected);
  if (!config) return;
  $("connection-title").textContent = config.name;
  $("connection-description").textContent = config.role;
  $("connection-mark").textContent = marks[config.id];
  $("connection-mark").dataset.app = config.id;
  $("connection-open").href = appURL(config.id);
  $("connection-open").hidden = config.browser === false;
  $("service-url").value = config.url;
  $("public-url").value = config.public_url;
  $("key-fields").hidden = config.id === "qbittorrent" || config.auth === "none";
  $("qbit-fields").hidden = config.id !== "qbittorrent";
  $("key-source").querySelector("[value=local]").disabled = ![
    "radarr",
    "sonarr",
    "prowlarr",
    "seerr",
  ].includes(config.id);
  $("key-source").value = config.key_source;
  $("api-key").value = "";
  $("api-key").placeholder =
    config.has_key && config.key_source === "manual"
      ? "Saved; leave blank to keep"
      : "Paste the app’s API key";
  $("qbit-username").value = config.username;
  $("qbit-password").value = "";
  $("qbit-password").placeholder = config.has_password
    ? "Saved; leave blank to keep"
    : "Your permanent Web UI password";
  $("key-help").textContent =
    config.id === "jellyfin"
      ? "Jellyfin → Dashboard → API Keys → create a key for Media Stack."
      : config.id === "seerr"
        ? "Seerr → Settings → General → API Key. Finish its first-time setup first."
        : `${config.name} → Settings → General → Security → API Key.`;
  $("disconnect").hidden = !config.configured;
  $("save-connection").textContent = config.configured
    ? "Save connection"
    : "Save and connect";
  const item = snapshot(config.id);
  message(
    "connection-result",
    item?.status === "unavailable" ? item.message : "",
    "warning",
  );
  updateKeyFields();
}
function updateKeyFields() {
  const local = $("key-source").value === "local";
  $("manual-key-field").hidden = local;
  $("local-key-help").hidden = !local;
}
function connectionPayload() {
  return {
    url: $("service-url").value.trim(),
    public_url: $("public-url").value.trim(),
    key_source: $("key-source").value,
    api_key: $("api-key").value.trim(),
    username: $("qbit-username").value.trim(),
    password: $("qbit-password").value,
  };
}
async function refresh() {
  if (!state.authenticated || state.busy) return;
  state.busy = true;
  $("refresh").disabled = true;
  try {
    const data = await api("/overview");
    state.overview = data;
    state.connections = data.connections;
    renderOverview();
    if (state.route === "connections") renderConnections();
    message("global-error", "");
  } catch (error) {
    if (state.authenticated)
      message(
        "global-error",
        `${error.message} Previously loaded stats may be out of date.`,
        "error",
      );
  } finally {
    state.busy = false;
    $("refresh").disabled = false;
  }
}
async function renderStorage() {
  const data = await api("/storage");
  $("host-data-path").textContent =
    data.host_path || "Defined by DATA_DIR in .env";
  renderDisk($("disk-detail"), data);
  for (const [kind, item] of Object.entries(data.locations)) {
    $(`${kind}-path`).value = item.path;
    $(`${kind}-path-status`).textContent =
      `${item.exists ? "Folder exists" : "Will be created during setup"}${item.writable ? " · Writable by the panel" : " · Check write permissions"}`;
  }
}
async function loadProfiles() {
  if (state.profilesLoaded) return;
  const data = await api("/setup/profiles");
  const errors = [];
  for (const kind of ["radarr", "sonarr"]) {
    const node = $(`${kind}-profile`);
    const previous = node.value;
    node.replaceChildren(
      el("option", { value: "" }, "Choose a profile"),
      ...data[kind].profiles.map((profile) =>
        el("option", { value: String(profile.id) }, profile.name),
      ),
    );
    node.value = previous;
    if (data[kind].error) errors.push(`${names[kind]}: ${data[kind].error}`);
  }
  $("profile-help").textContent = errors.length
    ? errors.join(" ")
    : "Profiles come from Radarr and Sonarr. Choose what fits your devices and storage.";
  state.profilesLoaded = !errors.length;
}
function currentRoute() {
  const value = location.hash.slice(1);
  return Object.hasOwn(routes, value) ? value : "overview";
}
async function navigate() {
  if (!state.authenticated) return;
  const previousRoute = state.route;
  state.route = currentRoute();
  document.querySelectorAll(".view").forEach((view) => {
    view.hidden = view.id !== `view-${state.route}`;
  });
  document.querySelectorAll("[data-route]").forEach((link) => {
    if (link.dataset.route === state.route)
      link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("page-name").textContent = routes[state.route];
  document.title = `${routes[state.route]} · Media Stack`;
  updateLastChecked();
  if (state.route !== previousRoute) {
    window.scrollTo({ top: 0, behavior: "instant" });
    $("main").focus({ preventScroll: true });
  }
  try {
    if (state.route === "connections") {
      renderConnections();
      renderEditor();
    }
    if (state.route === "storage") await renderStorage();
    if (state.route === "setup" && $("setup-form").elements.requests.checked)
      await loadProfiles();
  } catch (error) {
    message("global-error", error.message, "error");
  }
}
async function initialize() {
  try {
    const result = await api("/session");
    state.csrf = result.csrf;
    state.needsSetup = result.needs_setup;
    state.authenticated = result.authenticated;
    $("auth-screen").hidden = state.authenticated;
    $("shell").hidden = !state.authenticated;
    if (!state.authenticated) {
      $("auth-form").hidden = false;
      $("auth-title").textContent = state.needsSetup
        ? "Set up your control panel"
        : "Welcome back";
      $("auth-description").textContent = state.needsSetup
        ? "Choose an administrator username and password to manage your apps and library settings."
        : "Sign in to manage your Media Stack.";
      $("confirm-password-field").hidden = !state.needsSetup;
      $("auth-confirm").required = state.needsSetup;
      $("auth-password").autocomplete = state.needsSetup
        ? "new-password"
        : "current-password";
      $("auth-submit").textContent = state.needsSetup
        ? "Create administrator account"
        : "Sign in";
      return;
    }
    $("server-name").textContent = location.hostname;
    state.connections = (await api("/connections")).services;
    await navigate();
    await refresh();
  } catch (error) {
    message("auth-error", error.message, "error");
    $("auth-title").textContent = "Control panel unavailable";
  }
}
$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (
    state.needsSetup &&
    $("auth-password").value !== $("auth-confirm").value
  ) {
    message("auth-error", "The two passwords do not match.", "error");
    return;
  }
  await busy(
    $("auth-submit"),
    state.needsSetup ? "Creating account…" : "Signing in…",
    async () => {
      try {
        const result = await api(
          state.needsSetup ? "/auth/setup" : "/auth/login",
          {
            method: "POST",
            body: {
              username: $("auth-username").value.trim(),
              password: $("auth-password").value,
            },
          },
        );
        state.csrf = result.csrf;
        $("auth-form").reset();
        message("auth-error", "");
        await initialize();
      } catch (error) {
        message("auth-error", error.message, "error");
      }
    },
  );
});
$("refresh").addEventListener("click", refresh);
$("key-source").addEventListener("change", updateKeyFields);
$("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const service = state.selected;
  await busy($("save-connection"), "Verifying and saving…", async () => {
    try {
      await api(`/connections/${service}`, {
        method: "POST",
        body: connectionPayload(),
      });
      state.profilesLoaded = false;
      state.connections = (await api("/connections")).services;
      if (state.selected === service) {
        renderConnections();
        renderEditor();
        message(
          "connection-result",
          `${names[service]} is connected.`,
          "success",
        );
      }
      toast(`${names[service]} connected`);
      await refresh();
    } catch (error) {
      message("connection-result", error.message, "error");
    }
  });
});
$("test-connection").addEventListener("click", async () => {
  if (!$("connection-form").reportValidity()) return;
  await busy($("test-connection"), "Testing…", async () => {
    try {
      const result = await api(`/connections/${state.selected}/test`, {
        method: "POST",
        body: connectionPayload(),
      });
      message(
        "connection-result",
        `Connected to version ${result.version}. Save to use these settings in the panel.`,
        "success",
      );
    } catch (error) {
      message("connection-result", error.message, "error");
    }
  });
});
$("discover").addEventListener("click", async () => {
  await busy($("discover"), "Checking local apps…", async () => {
    try {
      const data = await api("/connections/discover", {
        method: "POST",
        body: {},
      });
      const node = $("discovery-results");
      node.className = "message info";
      node.hidden = false;
      node.replaceChildren(
        el("strong", {}, "Local connection results"),
        el(
          "ul",
          {},
          ...data.results.map((item) =>
            el("li", {}, `${names[item.id]}: ${item.message}`),
          ),
        ),
      );
      state.connections = (await api("/connections")).services;
      state.profilesLoaded = false;
      renderConnections();
      renderEditor();
      await refresh();
    } catch (error) {
      message("discovery-results", error.message, "error");
    }
  });
});
$("disconnect").addEventListener("click", () =>
  $("disconnect-dialog").showModal(),
);
$("confirm-disconnect").addEventListener("click", async () => {
  await busy($("confirm-disconnect"), "Disconnecting…", async () => {
    try {
      const service = state.selected;
      await api(`/connections/${service}`, { method: "DELETE" });
      $("disconnect-dialog").close();
      state.connections = (await api("/connections")).services;
      state.profilesLoaded = false;
      renderConnections();
      renderEditor();
      toast(`${names[service]} disconnected from the panel`);
      await refresh();
    } catch (error) {
      $("disconnect-dialog").close();
      message("connection-result", error.message, "error");
    }
  });
});
$("locations-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await busy(event.submitter, "Saving…", async () => {
    try {
      const result = await api("/storage/locations", {
        method: "POST",
        body: {
          movies: $("movies-path").value.trim(),
          tv: $("tv-path").value.trim(),
        },
      });
      message("locations-result", result.message, "success");
      await renderStorage();
    } catch (error) {
      message("locations-result", error.message, "error");
    }
  });
});
$("check-storage").addEventListener("click", async () => {
  await busy($("check-storage"), "Checking…", async () => {
    try {
      const result = await api("/storage/check", { method: "POST", body: {} });
      $("storage-check-result").replaceChildren(
        ...result.results.map((item) =>
          el(
            "div",
            { class: "check-result", "data-ok": String(item.hardlinks) },
            el(
              "strong",
              {},
              item.kind === "movies" ? "Movie imports" : "TV imports",
            ),
            el("code", {}, item.path),
            el("p", {}, item.message),
          ),
        ),
      );
    } catch (error) {
      $("storage-check-result").replaceChildren(
        el("p", { class: "message error" }, error.message),
      );
    }
  });
});
async function browseFolder(path) {
  $("folder-list").replaceChildren(
    el("p", { class: "loading-note" }, "Reading folders…"),
  );
  $("choose-folder").disabled = true;
  message("browser-error", "");
  try {
    const result = await api(
      `/storage/browse?path=${encodeURIComponent(path)}`,
    );
    state.folder = result.path;
    $("browser-path").textContent = result.path;
    $("folder-up").disabled = result.path === "/data";
    $("choose-folder").disabled = result.path === "/data";
    $("folder-list").replaceChildren(
      ...(result.folders.length
        ? result.folders.map((name) =>
            el(
              "button",
              {
                class: "folder-option",
                type: "button",
                onclick: () =>
                  browseFolder(`${result.path.replace(/\/$/, "")}/${name}`),
              },
              icon("folder"),
              name,
              icon("chevron", true),
            ),
          )
        : [
            empty(
              "No subfolders",
              "You can use this folder or enter a new subfolder path in the location field.",
            ),
          ]),
    );
    if (result.truncated)
      message(
        "browser-error",
        "Showing the first 200 folders. Enter a more specific path in the location field.",
        "warning",
      );
  } catch (error) {
    message("browser-error", error.message, "error");
    $("folder-list").replaceChildren();
  }
}
document.querySelectorAll(".browse-folder").forEach((button) =>
  button.addEventListener("click", () => {
    state.folderInput = button.dataset.input;
    $("folder-dialog").showModal();
    browseFolder("/data");
  }),
);
$("folder-up").addEventListener("click", () => {
  const parent = state.folder.split("/").slice(0, -1).join("/") || "/data";
  browseFolder(parent.startsWith("/data") ? parent : "/data");
});
$("choose-folder").addEventListener("click", () => {
  $(state.folderInput).value = state.folder;
  $("folder-dialog").close();
  $(state.folderInput).focus();
});
document
  .querySelectorAll(".close-dialog")
  .forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
$("setup-form").elements.requests.addEventListener("change", async (event) => {
  $("profile-fields").hidden = !event.target.checked;
  if (event.target.checked) {
    try {
      await loadProfiles();
    } catch (error) {
      message("setup-result", error.message, "error");
    }
  }
});
$("setup-form").addEventListener("change", () => {
  state.plan = null;
  $("apply-setup").disabled = true;
  if (!$("setup-review").hidden)
    $("review-warning").textContent =
      "Choices changed. Review again before applying.";
});
function renderPlan(steps) {
  const labels = {
    create: "New",
    exists: "Already set",
    blocked: "Needs attention",
    done: "Configured",
    kept: "Kept",
    failed: "Failed",
    skipped: "Skipped",
  };
  $("review-steps").replaceChildren(
    ...steps.map((step) =>
      el(
        "div",
        { class: "review-step" },
        el("div", {}, el("strong", {}, step.label), el("p", {}, step.detail)),
        el(
          "span",
          { class: "review-badge", "data-status": step.status },
          labels[step.status] || step.status,
        ),
      ),
    ),
  );
}
$("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const options = {};
  for (const key of [
    "folders",
    "libraries",
    "downloads",
    "indexers",
    "requests",
  ])
    options[key] = $("setup-form").elements[key].checked;
  for (const name of ["radarr", "sonarr"])
    options[`${name}_profile`] =
      $(`${name}-profile`).value === ""
        ? null
        : Number($(`${name}-profile`).value);
  await busy($("review-setup"), "Checking settings…", async () => {
    try {
      const plan = await api("/setup/preview", {
        method: "POST",
        body: options,
        long: true,
      });
      state.plan = plan;
      renderPlan(plan.steps);
      $("setup-review").hidden = false;
      $("review-title").textContent = "Review changes";
      const ready = plan.steps.filter(
        (step) => step.status === "create",
      ).length;
      const blocked = plan.steps.filter(
        (step) => step.status === "blocked",
      ).length;
      $("review-description").textContent =
        `${ready} new settings. Existing settings will be kept.`;
      $("review-warning").textContent = blocked
        ? `${blocked} tasks need attention and will be skipped. Ready tasks can still be applied.`
        : "No files will be moved or deleted.";
      $("apply-setup").textContent = ready
        ? `Apply ${ready} new settings`
        : "No new settings to apply";
      $("apply-setup").disabled = !plan.can_apply;
      message("setup-result", "");
      $("setup-review").scrollIntoView({ block: "start", behavior: "instant" });
    } catch (error) {
      message("setup-result", error.message, "error");
    }
  });
});
$("apply-setup").addEventListener("click", async () => {
  if (!state.plan) return;
  const plan = state.plan;
  state.plan = null;
  await busy($("apply-setup"), "Applying settings…", async () => {
    $("review-setup").disabled = true;
    try {
      const result = await api("/setup/apply", {
        method: "POST",
        body: { token: plan.token },
        long: true,
      });
      renderPlan(result.steps);
      $("review-title").textContent = "Setup results";
      $("review-description").textContent = result.complete
        ? "All reviewed settings are configured."
        : "Some tasks still need attention. Check the results below.";
      $("review-warning").textContent =
        "To retry, review changes again. Existing settings will be detected.";
      message(
        "setup-result",
        result.complete
          ? "Setup is complete. You can now add indexers and try a request."
          : "Completed settings were saved. Fix the blocked or failed tasks, then review again.",
        result.complete ? "success" : "warning",
      );
      await refresh();
    } catch (error) {
      message(
        "setup-result",
        `${error.message} Some changes may have completed. Review again to check the current settings.`,
        "error",
      );
    } finally {
      $("review-setup").disabled = false;
    }
  });
  $("apply-setup").disabled = true;
});
$("logout").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST", body: {} });
    state.overview = null;
    state.plan = null;
    state.profilesLoaded = false;
    await initialize();
  } catch (error) {
    toast(error.message);
  }
});
$("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("new-password").value !== $("new-password-confirm").value) {
    message("password-result", "The new passwords do not match.", "error");
    return;
  }
  await busy(event.submitter, "Updating…", async () => {
    try {
      const result = await api("/auth/password", {
        method: "POST",
        body: {
          current: $("current-password").value,
          password: $("new-password").value,
        },
      });
      state.csrf = result.csrf;
      $("password-form").reset();
      message(
        "password-result",
        "Password updated. Other panel sessions have been signed out.",
        "success",
      );
    } catch (error) {
      message("password-result", error.message, "error");
    }
  });
});
window.addEventListener("hashchange", () => {
  navigate();
});
document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  $("main").focus();
});
setInterval(() => {
  if (state.authenticated) updateLastChecked();
  if (!document.hidden && state.route === "overview") refresh();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.route === "overview") refresh();
});
initialize();

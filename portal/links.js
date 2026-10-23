// Use the address the visitor opened, including hostnames and IPv6 literals.
for (const link of document.querySelectorAll("[data-port]")) {
  const url = new URL(window.location.href);
  url.protocol = "http:";
  url.port = link.dataset.port;
  url.pathname = "/";
  url.search = "";
  url.hash = "";
  link.href = url.href;
}
const server = document.getElementById("server");
if (server) server.textContent = window.location.hostname;

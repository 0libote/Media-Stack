export function bytes(value, digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
    return "—";
  if (value === 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: index ? digits : 0 }).format(value / 1024 ** index)} ${units[index]}`;
}
export function count(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? new Intl.NumberFormat().format(value)
    : "—";
}
export function progress(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : 0;
}
export function ago(value) {
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (!Number.isFinite(seconds)) return "Not checked yet";
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return new Date(value).toLocaleDateString();
}
export function serviceURL(connection, currentURL) {
  if (connection.public_url) {
    const url = new URL(connection.public_url);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      throw new Error("Invalid app address");
    return url.href;
  }
  const url = new URL(currentURL);
  url.protocol = "http:";
  url.username = "";
  url.password = "";
  url.port = String(connection.port);
  url.pathname = "/";
  url.search = "";
  url.hash = "";
  return url.href;
}

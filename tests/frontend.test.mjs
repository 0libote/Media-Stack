import test from "node:test";
import assert from "node:assert/strict";
import { bytes, count, progress, serviceURL } from "../portal/format.mjs";

test("unknown metrics stay unknown and real zero stays zero", () => {
  assert.equal(bytes(null), "—");
  assert.equal(bytes(undefined), "—");
  assert.equal(bytes(NaN), "—");
  assert.equal(bytes(-1), "—");
  assert.equal(bytes(0), "0 B");
  assert.equal(count(null), "—");
  assert.equal(count(0), "0");
  assert.equal(bytes(1024), "1 KiB");
});
test("download progress is bounded", () => {
  assert.equal(progress(NaN), 0);
  assert.equal(progress(-2), 0);
  assert.equal(progress(2), 1);
  assert.equal(progress(0.42), 0.42);
});
test("app links use the current hostname and drop panel paths and fragments", () => {
  assert.equal(
    serviceURL({ port: 8096 }, "http://server.local:8088/#overview"),
    "http://server.local:8096/",
  );
  assert.equal(
    serviceURL({ port: 5055 }, "http://[::1]:8088/panel?secret=value#storage"),
    "http://[::1]:5055/",
  );
  assert.equal(
    serviceURL(
      { port: 7878, public_url: "https://media.example/radarr" },
      "http://server:8088",
    ),
    "https://media.example/radarr",
  );
  assert.throws(() =>
    serviceURL({ public_url: "javascript:alert(1)" }, "http://server"),
  );
  assert.throws(() =>
    serviceURL(
      { public_url: "https://user:pass@media.example" },
      "http://server",
    ),
  );
});

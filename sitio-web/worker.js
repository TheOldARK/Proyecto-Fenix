const TARGETS = new Set([
  "windows_directa",
  "windows_store",
  "macos_arm64",
  "macos_x64",
  "linux",
]);

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

async function registrarClic(request, env) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }

  const url = new URL(request.url);
  if (request.headers.get("origin") !== url.origin) {
    return jsonResponse({ error: "invalid_origin" }, 403);
  }
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("text/plain")) {
    return jsonResponse({ error: "unsupported_media_type" }, 415);
  }

  let body;
  try {
    const text = await request.text();
    if (new TextEncoder().encode(text).byteLength > 1024) {
      return jsonResponse({ error: "payload_too_large" }, 413);
    }
    body = JSON.parse(text);
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }

  if (
    !body || typeof body !== "object" || Array.isArray(body) ||
    Object.keys(body).length !== 1 || typeof body.target !== "string" ||
    !TARGETS.has(body.target)
  ) {
    return jsonResponse({ error: "invalid_payload" }, 400);
  }
  if (!env.FENIX_ANALYTICS) {
    return jsonResponse({ error: "analytics_unavailable" }, 503);
  }

  env.FENIX_ANALYTICS.writeDataPoint({
    blobs: [body.target],
    doubles: [1],
    indexes: [body.target],
  });
  return new Response(null, {
    status: 204,
    headers: { "cache-control": "no-store" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/download-click") {
      return registrarClic(request, env);
    }
    return env.ASSETS.fetch(request);
  },
};

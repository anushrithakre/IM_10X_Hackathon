const BACKEND_BASE_URL = process.env.BACKEND_API_BASE_URL || "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function proxy(request: Request, context: RouteContext) {
  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const backendUrl = new URL(`/api/${path.join("/")}`, BACKEND_BASE_URL);
  backendUrl.search = incomingUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  headers.set("x-tracefix-origin", incomingUrl.origin);

  try {
    const response = await fetchBackend(request, backendUrl, headers);

    const location = response.headers.get("location");
    if (location && response.status >= 300 && response.status < 400) {
      return new Response(null, {
        status: response.status,
        headers: { location }
      });
    }

    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json"
      }
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown proxy error";
    return Response.json(
      {
        detail:
          `QA + RCA backend is not reachable at ${BACKEND_BASE_URL} for ${backendUrl.pathname}. ` +
          `Start FastAPI there or set BACKEND_API_BASE_URL. ${message}`
      },
      { status: 502 }
    );
  }
}

async function fetchBackend(request: Request, backendUrl: URL, headers: Headers) {
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.text();
  try {
    return await fetch(backendUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual"
    });
  } catch {
    await new Promise((resolve) => setTimeout(resolve, 250));
    return fetch(backendUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual"
    });
  }
}

export async function GET(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function POST(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function PATCH(request: Request, context: RouteContext) {
  return proxy(request, context);
}

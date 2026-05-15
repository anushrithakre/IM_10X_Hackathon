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

  try {
    const response = await fetch(backendUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
      cache: "no-store"
    });

    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json"
      }
    });
  } catch {
    return Response.json(
      {
        detail:
          "TraceFix backend is not reachable. Start FastAPI on http://127.0.0.1:8000 or set BACKEND_API_BASE_URL."
      },
      { status: 502 }
    );
  }
}

export async function GET(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export async function POST(request: Request, context: RouteContext) {
  return proxy(request, context);
}

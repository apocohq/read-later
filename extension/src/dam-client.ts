import { isSecureHost, type Settings } from "./contract.js";

/**
 * Minimal client for the DAM api-server's tRPC surface, using an API key.
 * Plain JSON on the wire (the router has no transformer). The agent is woken
 * by the server on upload, so a cold call can take a while.
 */
export class DamClient {
  constructor(private readonly host: string, private readonly apiKey: string) {
    if (!isSecureHost(host)) throw new Error("the DAM host must be https (or loopback); refusing to send the API key in the clear");
  }

  private base = () => `${this.host.replace(/\/+$/, "")}/api/trpc`;

  private async call<T>(procedure: string, input: unknown, method: "GET" | "POST", timeoutMs: number): Promise<T> {
    const url =
      method === "GET" && input !== undefined
        ? `${this.base()}/${procedure}?input=${encodeURIComponent(JSON.stringify(input))}`
        : `${this.base()}/${procedure}`;
    const res = await fetch(url, {
      method,
      headers: { authorization: `Bearer ${this.apiKey}`, "content-type": "application/json" },
      body: method === "POST" ? JSON.stringify(input) : undefined,
      signal: AbortSignal.timeout(timeoutMs),
    });
    const body = (await res.json().catch(() => ({}))) as {
      result?: { data: T };
      error?: { message?: string; data?: { code?: string } };
      message?: string;
    };
    if (!res.ok || body.error) {
      const detail = body.error?.message ?? body.message ?? `${res.status} ${res.statusText}`;
      throw new Error(`DAM ${procedure} failed: ${detail}`);
    }
    return body.result!.data;
  }

  listAgents(): Promise<Array<{ id: string; name: string }>> {
    return this.call("agents.list", undefined, "GET", 20_000);
  }

  uploadFile(input: { agentId: string; path: string; content: string; contentType: string }): Promise<{ mtimeMs: number }> {
    return this.call(
      "files.upload",
      {
        agentId: input.agentId,
        path: input.path,
        contentBase64: toBase64(input.content),
        contentType: input.contentType,
        overwrite: false,
      },
      "POST",
      180_000,
    );
  }
}

export const fromSettings = (s: Settings) => new DamClient(s.host, s.apiKey);

function toBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

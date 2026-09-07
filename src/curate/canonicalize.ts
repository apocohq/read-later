const TRACKING_PARAMS = /^(utm_|fbclid|gclid|mc_|ref$|source$|si$)/i;

/** Deterministic URL normalization. Same article, same key. */
export function canonicalizeUrl(input: string): string {
  const url = new URL(input);
  url.hash = "";
  url.hostname = url.hostname.toLowerCase().replace(/^www\./, "");
  for (const key of [...url.searchParams.keys()]) {
    if (TRACKING_PARAMS.test(key)) url.searchParams.delete(key);
  }
  url.searchParams.sort();
  if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, "");
  return url.toString();
}

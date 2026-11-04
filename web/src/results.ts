import type { Headline } from "./types";

let pending: Promise<Headline | null> | null = null;

export const headline = () =>
  (pending ??= fetch(`${import.meta.env.BASE_URL}results/headline.json`, { cache: "no-cache" })
    .then((r) => (r.ok ? (r.json() as Promise<Headline>) : null))
    .catch(() => null));

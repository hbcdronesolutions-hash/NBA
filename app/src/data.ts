import { useEffect, useState } from "react";
import type { Game, PropsData, RecordData, Ratings, Side, Today } from "./types";

const cache = new Map<string, Promise<unknown>>();

function load<T>(name: string): Promise<T> {
  if (!cache.has(name)) {
    cache.set(
      name,
      fetch(`./data/${name}.json`, { cache: "no-cache" }).then((r) => {
        if (!r.ok) throw new Error(`${name}: ${r.status}`);
        return r.json();
      }),
    );
  }
  return cache.get(name) as Promise<T>;
}

function useData<T>(name: string): { data: T | null; error: boolean } {
  const [state, setState] = useState<{ data: T | null; error: boolean }>({ data: null, error: false });
  useEffect(() => {
    let live = true;
    load<T>(name)
      .then((data) => live && setState({ data, error: false }))
      .catch(() => live && setState({ data: null, error: true }));
    return () => {
      live = false;
    };
  }, [name]);
  return state;
}

export const useToday = () => useData<Today>("today");
export const useRatings = () => useData<Ratings>("ratings");
export const useRecord = () => useData<RecordData>("record");
export const useProps = () => useData<PropsData>("props");

/** Équipe pronostiquée et sa probabilité. */
export function pick(g: Game): { side: Side; abbr: string; p: number } {
  return g.p_home >= 0.5
    ? { side: "home", abbr: g.home, p: g.p_home }
    : { side: "away", abbr: g.away, p: 1 - g.p_home };
}

export function badge(p: number): { label: string; tone: "top" | "good" | "ok" } | null {
  if (p >= 0.75) return { label: "Très sûr", tone: "top" };
  if (p >= 0.7) return { label: "Sûr", tone: "good" };
  if (p >= 0.65) return { label: "Correct", tone: "ok" };
  return null;
}

export const comboMinOdds = (probs: number[]) =>
  Math.ceil(((1.05 / probs.reduce((a, b) => a * b, 1)) * 100) - 1e-9) / 100;

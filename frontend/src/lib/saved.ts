import type { SavedAnswer } from "../types";

const KEY = "charaka_saved_answers";

export function loadSaved(): SavedAnswer[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function persistSaved(list: SavedAnswer[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    // storage full/unavailable — non-fatal
  }
}

export function addSaved(item: SavedAnswer): SavedAnswer[] {
  const list = loadSaved().filter((s) => s.id !== item.id);
  const next = [item, ...list];
  persistSaved(next);
  return next;
}

export function removeSaved(id: string): SavedAnswer[] {
  const next = loadSaved().filter((s) => s.id !== id);
  persistSaved(next);
  return next;
}
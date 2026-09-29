import "@testing-library/jest-dom/vitest";

/**
 * A real in-memory `localStorage`.
 *
 * WHY this is needed rather than relying on jsdom: Node 22+ ships its own experimental
 * `localStorage` global, and on Node 25 it shadows jsdom's implementation while being disabled —
 * `window.localStorage` is present but is a hollow object with no `getItem`/`setItem`/`clear`
 * (it also emits "`--localstorage-file` was provided without a valid path"). Any test touching
 * storage fails with "clear is not a function", which reads like a bug in the code under test
 * rather than an environment artefact.
 *
 * Defined on `window` so both `window.localStorage` and the bare `localStorage` binding resolve
 * to it inside jsdom.
 */
class MemoryStorage implements Storage {
  #entries = new Map<string, string>();

  get length(): number {
    return this.#entries.size;
  }

  clear(): void {
    this.#entries.clear();
  }

  getItem(key: string): string | null {
    return this.#entries.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.#entries.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.#entries.delete(key);
  }

  setItem(key: string, value: string): void {
    this.#entries.set(key, String(value));
  }
}

Object.defineProperty(window, "localStorage", {
  configurable: true,
  writable: true,
  value: new MemoryStorage(),
});

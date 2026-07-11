// ---------------------------------------------------------------------------
// M41 — Obsidian command-palette catalog (plugin side)
//
// Obsidian commands can only be *executed* here in the renderer (the Python service
// can't reach `app.commands`). So the plugin enumerates the whole palette — core + every
// installed community plugin — and pushes it to the service, which keeps an awareness copy
// the model can search. When the user asks Loremaster to do something a plugin provides,
// the model proposes `command:run <id>`; on approval we execute it via executeCommandById.
//
// `app.commands` / `app.plugins` are undocumented-but-stable Obsidian internals. Everything
// here is defensively guarded so a future API change degrades to "no catalog", never a crash.
// ---------------------------------------------------------------------------

import type { App } from "obsidian";

export interface PaletteCommand {
    id: string;
    name: string;
    source: string;   // "core" or the community-plugin id the command belongs to
}

export interface CatalogPayload {
    commands: PaletteCommand[];
    plugins: string[];   // display names of the community plugins contributing commands
    plugin_descriptions: Record<string, string>;  // name → manifest description (what it's for)
    hash: string;        // stable hash of the id-set — cheap drift detection
}

/** Enumerate every command currently in the palette. */
export function listPaletteCommands(app: App): PaletteCommand[] {
    const anyApp = app as unknown as {
        commands?: { commands?: Record<string, { name?: string }> };
        plugins?: { enabledPlugins?: Set<string> };
    };
    const table = anyApp?.commands?.commands ?? {};
    const enabled: Set<string> = anyApp?.plugins?.enabledPlugins ?? new Set<string>();
    const out: PaletteCommand[] = [];
    for (const id of Object.keys(table)) {
        if (!id) continue;
        // Plugin command ids are "<pluginId>:<slug>"; core ids use namespaces like
        // "editor:" / "app:" / "workspace:" (not plugins) or have no colon at all.
        const prefix = id.includes(":") ? id.split(":", 1)[0] : "";
        const source = prefix && enabled.has(prefix) ? prefix : "core";
        out.push({ id, name: String(table[id]?.name ?? id), source });
    }
    return out;
}

/** Cheap, stable 32-bit hash of the sorted id-set — changes exactly when the set changes. */
export function catalogHash(cmds: PaletteCommand[]): string {
    const ids = cmds.map((c) => c.id).sort().join("\n");
    let h = 0;
    for (let i = 0; i < ids.length; i++) h = (Math.imul(h, 31) + ids.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
}

/** Build the full payload to push to the service (commands + plugin display names + hash). */
export function buildCatalog(app: App): CatalogPayload {
    const anyApp = app as unknown as {
        plugins?: {
            enabledPlugins?: Set<string>;
            manifests?: Record<string, { name?: string; description?: string }>;
        };
    };
    const cmds = listPaletteCommands(app);
    const manifests = anyApp?.plugins?.manifests ?? {};
    const enabled: Set<string> = anyApp?.plugins?.enabledPlugins ?? new Set<string>();
    const names = new Set<string>();
    const descriptions: Record<string, string> = {};
    for (const c of cmds) {
        if (c.source !== "core" && enabled.has(c.source)) {
            const name = manifests[c.source]?.name ?? c.source;
            names.add(name);
            const desc = manifests[c.source]?.description;
            if (desc) descriptions[name] = desc;   // the "what this plugin does" text Obsidian has
        }
    }
    return { commands: cmds, plugins: [...names].sort(), plugin_descriptions: descriptions, hash: catalogHash(cmds) };
}

/** Execute a palette command by id. Returns true if it ran, false if unavailable/blocked. */
export function executeCommand(app: App, id: string): boolean {
    const anyApp = app as unknown as {
        commands?: { executeCommandById?: (id: string) => boolean };
    };
    try {
        return !!anyApp?.commands?.executeCommandById?.(id);
    } catch {
        return false;
    }
}

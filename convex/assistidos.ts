import { query, mutation } from "./_generated/server";
import { v } from "convex/values";

function nowStr(): string {
  // Formato compativel com o legado: "YYYY-MM-DD HH:MM:SS" (UTC)
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

// Insert-or-ignore por (filme_id, user_id).
export const add = mutation({
  args: {
    filme_id: v.string(),
    user_id: v.string(),
    username: v.optional(v.string()),
    display_name: v.optional(v.string()),
    avatar: v.optional(v.string()),
    source: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("usuarios_assistidos")
      .withIndex("by_filme_and_user", (q) =>
        q.eq("filme_id", args.filme_id).eq("user_id", args.user_id),
      )
      .first();
    if (existing) return { inserted: false, updated: false };
    await ctx.db.insert("usuarios_assistidos", {
      filme_id: args.filme_id,
      user_id: args.user_id,
      username: args.username,
      display_name: args.display_name,
      avatar: args.avatar,
      source: args.source,
      data_assistido: nowStr(),
    });
    return { inserted: true, updated: false };
  },
});

/** Atualiza perfil ou insere registro de quem assistiu. */
export const upsert = mutation({
  args: {
    filme_id: v.string(),
    user_id: v.string(),
    username: v.optional(v.string()),
    display_name: v.optional(v.string()),
    avatar: v.optional(v.string()),
    source: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("usuarios_assistidos")
      .withIndex("by_filme_and_user", (q) =>
        q.eq("filme_id", args.filme_id).eq("user_id", args.user_id),
      )
      .first();
    const data = {
      username: args.username,
      display_name: args.display_name,
      avatar: args.avatar,
      source: args.source,
    };
    if (existing) {
      // Registro já existe: preserva data_assistido e source (ex.: manual antes do evento).
      const patch: Record<string, unknown> = {};
      if (args.username) patch.username = args.username;
      if (args.display_name) patch.display_name = args.display_name;
      if (args.avatar) patch.avatar = args.avatar;
      if (Object.keys(patch).length) {
        await ctx.db.patch(existing._id, patch);
        return { inserted: false, updated: true };
      }
      return { inserted: false, updated: false };
    }
    await ctx.db.insert("usuarios_assistidos", {
      filme_id: args.filme_id,
      user_id: args.user_id,
      username: args.username,
      display_name: args.display_name,
      avatar: args.avatar,
      source: args.source,
      data_assistido: nowStr(),
    });
    return { inserted: true, updated: false };
  },
});

export const existsByFilmeUser = query({
  args: { filme_id: v.string(), user_id: v.string() },
  handler: async (ctx, args) => {
    const row = await ctx.db
      .query("usuarios_assistidos")
      .withIndex("by_filme_and_user", (q) =>
        q.eq("filme_id", args.filme_id).eq("user_id", args.user_id),
      )
      .first();
    return !!row;
  },
});

export const removeByFilmeUser = mutation({
  args: { filme_id: v.string(), user_id: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("usuarios_assistidos")
      .withIndex("by_filme_and_user", (q) =>
        q.eq("filme_id", args.filme_id).eq("user_id", args.user_id),
      )
      .collect();
    for (const r of rows) await ctx.db.delete(r._id);
    return rows.length;
  },
});

export const listByFilme = query({
  args: { filme_id: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("usuarios_assistidos")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .collect();
    rows.sort((a, b) =>
      (a.data_assistido || "").localeCompare(b.data_assistido || ""),
    );
    return rows.map((r) => ({
      user_id: r.user_id,
      username: r.username ?? "",
      display_name: r.display_name ?? "",
      avatar: r.avatar ?? null,
      source: r.source,
      data_assistido: r.data_assistido,
    }));
  },
});

export const distinctFilmeIds = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("usuarios_assistidos").collect();
    const ids = new Set<string>();
    for (const r of rows) ids.add(r.filme_id);
    return Array.from(ids);
  },
});

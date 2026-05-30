import { query, mutation } from "./_generated/server";
import { v } from "convex/values";

// Funcoes publicas: o cliente Python (bot/site) chama via CONVEX_URL.
// Sem auth de usuario final (backend confiavel) — dados de baixa sensibilidade.

function norm(s: string): string {
  return (s || "").trim().toLowerCase();
}

export const getByFilme = query({
  args: { filme_id: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .first();
  },
});

export const getTituloByFilme = query({
  args: { filme_id: v.string() },
  handler: async (ctx, args) => {
    const row = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .first();
    return row ? row.titulo : null;
  },
});

export const listByStatus = query({
  args: { status: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("listas")
      .withIndex("by_status", (q) => q.eq("status", args.status))
      .order("desc")
      .collect();
    return rows;
  },
});

export const listByStatusPaginated = query({
  args: { status: v.string(), limit: v.number(), offset: v.number() },
  handler: async (ctx, args) => {
    const all = await ctx.db
      .query("listas")
      .withIndex("by_status", (q) => q.eq("status", args.status))
      .order("desc")
      .collect();
    const total = all.length;
    const rows = all.slice(args.offset, args.offset + args.limit);
    return { rows, total };
  },
});

// Busca por titulo (substring), opcionalmente filtrando por status.
export const searchByTitulo = query({
  args: {
    titulo: v.string(),
    status: v.optional(v.string()),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const needle = norm(args.titulo);
    let rows;
    if (args.status) {
      rows = await ctx.db
        .query("listas")
        .withIndex("by_status", (q) => q.eq("status", args.status as string))
        .order("desc")
        .collect();
    } else {
      rows = await ctx.db.query("listas").order("desc").collect();
    }
    const matched = rows.filter((r) => norm(r.titulo).includes(needle));
    const limit = args.limit ?? 50;
    return matched.slice(0, limit);
  },
});

export const listWatchlistFilmes = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db
      .query("listas")
      .withIndex("by_status", (q) => q.eq("status", "watchlist"))
      .order("desc")
      .collect();
    return rows.map((r) => ({ filme_id: r.filme_id, titulo: r.titulo }));
  },
});

export const distinctFilmeIds = query({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("listas").collect();
    const ids = new Set<string>();
    for (const r of rows) ids.add(r.filme_id);
    return Array.from(ids);
  },
});

export const filmeIdsByStatus = query({
  args: { status: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("listas")
      .withIndex("by_status", (q) => q.eq("status", args.status))
      .collect();
    return rows.map((r) => r.filme_id);
  },
});

export const addFilme = mutation({
  args: {
    user_id: v.string(),
    filme_id: v.string(),
    titulo: v.string(),
    status: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .first();
    if (existing) {
      return { inserted: false, status: existing.status };
    }
    await ctx.db.insert("listas", {
      user_id: args.user_id,
      filme_id: args.filme_id,
      titulo: args.titulo,
      status: args.status,
    });
    return { inserted: true, status: args.status };
  },
});

export const setStatus = mutation({
  args: { filme_id: v.string(), status: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .collect();
    for (const r of rows) {
      await ctx.db.patch(r._id, { status: args.status });
    }
    return rows.length;
  },
});

// Update-or-insert do status (usado por /visto e toggle do site).
export const marcarAssistido = mutation({
  args: {
    user_id: v.string(),
    filme_id: v.string(),
    titulo: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .first();
    if (existing) {
      await ctx.db.patch(existing._id, { status: "assistido" });
      return { inserted: false };
    }
    await ctx.db.insert("listas", {
      user_id: args.user_id,
      filme_id: args.filme_id,
      titulo: args.titulo,
      status: "assistido",
    });
    return { inserted: true };
  },
});

// Coloca filme na fila: se existe assistido -> volta pra watchlist; se novo -> insere.
export const adicionarFila = mutation({
  args: {
    user_id: v.string(),
    filme_id: v.string(),
    titulo: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .first();
    if (existing) {
      if (existing.status === "watchlist") {
        return { in_fila: true, already: true };
      }
      await ctx.db.patch(existing._id, { status: "watchlist" });
      return { in_fila: true, already: false };
    }
    await ctx.db.insert("listas", {
      user_id: args.user_id,
      filme_id: args.filme_id,
      titulo: args.titulo,
      status: "watchlist",
    });
    return { in_fila: true, already: false };
  },
});

export const removeByFilme = mutation({
  args: { filme_id: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .collect();
    for (const r of rows) await ctx.db.delete(r._id);
    return rows.length;
  },
});

export const removeByFilmeAndStatus = mutation({
  args: { filme_id: v.string(), status: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("listas")
      .withIndex("by_filme", (q) => q.eq("filme_id", args.filme_id))
      .collect();
    let n = 0;
    for (const r of rows) {
      if (r.status === args.status) {
        await ctx.db.delete(r._id);
        n++;
      }
    }
    return n;
  },
});

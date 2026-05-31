import { query, mutation, QueryCtx } from "./_generated/server";
import { v } from "convex/values";
import { Doc } from "./_generated/dataModel";

// Funcoes publicas: o cliente Python (bot/site) chama via CONVEX_URL.
// Sem auth de usuario final (backend confiavel) — dados de baixa sensibilidade.

function norm(s: string): string {
  return (s || "").trim().toLowerCase();
}

function nowStr(): string {
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

/** Ordena watchlist por adição recente; assistidos por data em que foram vistos. */
async function sortListasRows(
  ctx: QueryCtx,
  rows: Doc<"listas">[],
  status: string,
): Promise<Doc<"listas">[]> {
  if (status !== "assistido") {
    return [...rows].sort((a, b) => b._creationTime - a._creationTime);
  }

  // Fallback para registros legados sem assistido_em: usa a data mais recente
  // em usuarios_assistidos para aquele filme.
  const assistidosUsers = await ctx.db.query("usuarios_assistidos").collect();
  const maxByFilme = new Map<string, string>();
  for (const u of assistidosUsers) {
    const d = u.data_assistido || "";
    const cur = maxByFilme.get(u.filme_id);
    if (!cur || d > cur) maxByFilme.set(u.filme_id, d);
  }

  return [...rows].sort((a, b) => {
    const ta = a.assistido_em || maxByFilme.get(a.filme_id) || "";
    const tb = b.assistido_em || maxByFilme.get(b.filme_id) || "";
    const cmp = tb.localeCompare(ta);
    if (cmp !== 0) return cmp;
    return b._creationTime - a._creationTime;
  });
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
      .collect();
    return sortListasRows(ctx, rows, args.status);
  },
});

export const listByStatusPaginated = query({
  args: { status: v.string(), limit: v.number(), offset: v.number() },
  handler: async (ctx, args) => {
    const all = await sortListasRows(
      ctx,
      await ctx.db
        .query("listas")
        .withIndex("by_status", (q) => q.eq("status", args.status))
        .collect(),
      args.status,
    );
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
      rows = await sortListasRows(
        ctx,
        await ctx.db
          .query("listas")
          .withIndex("by_status", (q) => q.eq("status", args.status as string))
          .collect(),
        args.status as string,
      );
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
    const patch: { status: string; assistido_em?: string } = {
      status: args.status,
    };
    if (args.status === "assistido") {
      patch.assistido_em = nowStr();
    }
    for (const r of rows) {
      if (args.status === "watchlist") {
        await ctx.db.patch(r._id, { status: args.status, assistido_em: undefined });
      } else {
        await ctx.db.patch(r._id, patch);
      }
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
      await ctx.db.patch(existing._id, {
        status: "assistido",
        assistido_em: nowStr(),
      });
      return { inserted: false };
    }
    await ctx.db.insert("listas", {
      user_id: args.user_id,
      filme_id: args.filme_id,
      titulo: args.titulo,
      status: "assistido",
      assistido_em: nowStr(),
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
      await ctx.db.patch(existing._id, {
        status: "watchlist",
        assistido_em: undefined,
      });
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

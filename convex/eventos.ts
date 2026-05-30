import { query, mutation } from "./_generated/server";
import { v } from "convex/values";

function norm(s: string): string {
  return (s || "").trim().toLowerCase();
}

const ATIVOS = ["agendado", "ativo"];

export const create = mutation({
  args: {
    discord_event_id: v.string(),
    filme_id: v.string(),
    titulo: v.string(),
    data_evento: v.string(),
    canal_id: v.optional(v.string()),
    guild_id: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("eventos")
      .withIndex("by_discord_event", (q) =>
        q.eq("discord_event_id", args.discord_event_id),
      )
      .first();
    if (existing) return { inserted: false };
    await ctx.db.insert("eventos", {
      discord_event_id: args.discord_event_id,
      filme_id: args.filme_id,
      titulo: args.titulo,
      data_evento: args.data_evento,
      canal_id: args.canal_id,
      guild_id: args.guild_id,
      status: "agendado",
      canal_temporario: 0,
    });
    return { inserted: true };
  },
});

export const getByDiscordEvent = query({
  args: { discord_event_id: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("eventos")
      .withIndex("by_discord_event", (q) =>
        q.eq("discord_event_id", args.discord_event_id),
      )
      .first();
  },
});

export const getAtivoByTitulo = query({
  args: { titulo: v.string() },
  handler: async (ctx, args) => {
    const needle = norm(args.titulo);
    const rows = await ctx.db.query("eventos").order("desc").collect();
    for (const r of rows) {
      if (ATIVOS.includes(r.status) && norm(r.titulo).includes(needle)) {
        return r;
      }
    }
    return null;
  },
});

export const getAtivoByCanal = query({
  args: { canal_id: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("eventos")
      .withIndex("by_canal", (q) => q.eq("canal_id", args.canal_id))
      .collect();
    for (const r of rows) {
      if (ATIVOS.includes(r.status)) return r;
    }
    return null;
  },
});

export const listAtivos = query({
  args: { titulo: v.optional(v.string()), limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const rows = await ctx.db.query("eventos").order("desc").collect();
    let ativos = rows.filter((r) => ATIVOS.includes(r.status));
    if (args.titulo) {
      const needle = norm(args.titulo);
      ativos = ativos.filter((r) => norm(r.titulo).includes(needle));
    }
    const limit = args.limit ?? 8;
    return ativos
      .slice(0, limit)
      .map((r) => ({ titulo: r.titulo, data_evento: r.data_evento }));
  },
});

export const setStatusByDiscordEvent = mutation({
  args: { discord_event_id: v.string(), status: v.string() },
  handler: async (ctx, args) => {
    const row = await ctx.db
      .query("eventos")
      .withIndex("by_discord_event", (q) =>
        q.eq("discord_event_id", args.discord_event_id),
      )
      .first();
    if (!row) return false;
    await ctx.db.patch(row._id, { status: args.status });
    return true;
  },
});

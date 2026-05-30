import { query, mutation } from "./_generated/server";
import { v } from "convex/values";

// Upsert por (discord_event_id, user_id). Atualiza apenas as flags enviadas.
export const upsert = mutation({
  args: {
    discord_event_id: v.string(),
    user_id: v.string(),
    username: v.optional(v.string()),
    interessado: v.optional(v.number()),
    entrou_canal: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("evento_participantes")
      .withIndex("by_evento_and_user", (q) =>
        q.eq("discord_event_id", args.discord_event_id).eq("user_id", args.user_id),
      )
      .first();

    if (existing) {
      const patch: Record<string, unknown> = {};
      if (args.username !== undefined) patch.username = args.username;
      if (args.interessado !== undefined) patch.interessado = args.interessado;
      if (args.entrou_canal !== undefined) patch.entrou_canal = args.entrou_canal;
      await ctx.db.patch(existing._id, patch);
      return existing._id;
    }

    return await ctx.db.insert("evento_participantes", {
      discord_event_id: args.discord_event_id,
      user_id: args.user_id,
      username: args.username,
      interessado: args.interessado ?? 0,
      entrou_canal: args.entrou_canal ?? 0,
    });
  },
});

export const listEntrouByEvento = query({
  args: { discord_event_id: v.string() },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("evento_participantes")
      .withIndex("by_evento", (q) =>
        q.eq("discord_event_id", args.discord_event_id),
      )
      .collect();
    return rows
      .filter((r) => r.entrou_canal === 1)
      .map((r) => ({ user_id: r.user_id, username: r.username ?? "" }));
  },
});
